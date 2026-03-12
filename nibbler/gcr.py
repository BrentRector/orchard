"""
GCR (Group Code Recording) encoding/decoding for Apple II disks.

Supports both 6-and-2 (DOS 3.3, 16-sector) and 5-and-3 (13-sector) formats.
Provides sector finding with configurable address/data prologs.

Overview
--------
Apple II floppy disks store data using GCR encoding, which maps raw data
bytes into "disk nibbles" — byte values that satisfy the Disk II controller's
hardware constraints (high bit set, no more than one consecutive pair of
zero bits). Two GCR schemes exist:

  - **6-and-2**: Used by DOS 3.3 and ProDOS (16-sector disks). Each data byte
    is split into a 6-bit "primary" part and a 2-bit "auxiliary" part.
    The aux bits from groups of 3 bytes are packed into single 6-bit values.
    All 6-bit values are then encoded into valid disk nibbles via ENCODE_62.
    342 encoded nibbles represent 256 data bytes.

  - **5-and-3**: Used by DOS 3.2 and the Apple II 13-sector ROM (P5A ROM).
    Each data byte is split into a 5-bit "primary" (top) part and a 3-bit
    "secondary" (thr) part. The 5-bit values are encoded into valid disk
    nibbles via ENCODE_53. 411 encoded nibbles represent 256 data bytes.

Address fields on all Apple II disks use **4-and-4** encoding, where each
data byte is split across two disk bytes, each carrying 4 data bits.

Usage
-----
    from nibbler.gcr import find_sectors_62, find_sectors_53

    # Decode all 6-and-2 sectors from a nibble stream:
    sectors = find_sectors_62(nibbles)
    for sec_num, sector_data in sectors.items():
        print(sector_data)  # SectorData(vol=254, trk=0, sec=0, cksum=OK)

    # Decode all 5-and-3 sectors from a nibble stream:
    sectors = find_sectors_53(nibbles)

    # Auto-detect non-standard address prologs (copy protection):
    prologs = auto_detect_address_prologs(nibbles)
    sectors = find_sectors_62(nibbles, addr_prolog=prologs[0])

Expected Output
---------------
Each find_sectors_* function returns a dict mapping physical sector numbers
(0-15 for 6-and-2, 0-12 for 5-and-3) to SectorData objects, each containing
256 decoded data bytes plus checksum validation status.
"""


# ── 6-and-2 GCR tables ──────────────────────────────────────────────

# ENCODE_62: Maps 6-bit values (0x00..0x3F) to valid disk nibbles (0x96..0xFF).
# These are the 64 byte values that satisfy the Disk II hardware constraints:
# high bit set, and no more than one consecutive pair of zero bits. This is the
# same table stored in the DOS 3.3 / ProDOS RWTS (Read/Write Track/Sector) code.
ENCODE_62 = [
    0x96, 0x97, 0x9A, 0x9B, 0x9D, 0x9E, 0x9F, 0xA6,
    0xA7, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF, 0xB2, 0xB3,
    0xB4, 0xB5, 0xB6, 0xB7, 0xB9, 0xBA, 0xBB, 0xBC,
    0xBD, 0xBE, 0xBF, 0xCB, 0xCD, 0xCE, 0xCF, 0xD3,
    0xD6, 0xD7, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE,
    0xDF, 0xE5, 0xE6, 0xE7, 0xE9, 0xEA, 0xEB, 0xEC,
    0xED, 0xEE, 0xEF, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6,
    0xF7, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF,
]

# DECODE_62: Reverse lookup — maps a disk nibble back to its 6-bit value.
# Built by inverting ENCODE_62. Only valid GCR nibbles have entries.
DECODE_62 = {v: i for i, v in enumerate(ENCODE_62)}

# ── 5-and-3 GCR tables ──────────────────────────────────────────────

# ENCODE_53: Maps 5-bit values (0x00..0x1F) to valid disk nibbles (0xAB..0xFF).
# These are the 32 byte values used by the Apple II 13-sector ROM (P5A).
# The constraint is stricter than 6-and-2: only 32 values qualify because each
# nibble must encode 5 data bits while maintaining the Disk II's self-clocking
# requirements. The value 0xD5 is excluded because it is reserved as the first
# byte of sector prologs (address and data field markers).
ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]

# DECODE_53: Reverse lookup — maps a 5-and-3 disk nibble back to its 5-bit value.
# Built by inverting ENCODE_53. Only valid 5-and-3 GCR nibbles have entries.
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def build_53_gcr_table():
    """Build the 5-and-3 GCR decode table as the Apple II boot ROM does.

    This replicates the algorithm from the P5A (13-sector) boot ROM at $C600.
    The ROM builds this table at runtime rather than storing it, to save ROM space.

    The algorithm tests each candidate byte value y ($AB..$FF) to see if it
    satisfies the Disk II's self-clocking constraint:

      1. Shift y right by 1 bit (clearing the high bit).
      2. OR the result with the original y.
      3. If the result is $FF, then y has no adjacent zero-bit pairs and is
         a valid GCR nibble.
      4. Skip $D5, which is reserved as the sector prolog marker byte.

    Valid nibbles are assigned sequential decode values starting at 0.

    Returns:
        A 256-entry list where table[nibble] gives the decoded 5-bit value.
        Entries for invalid nibbles are 0.
    """
    table = [0] * 256
    x = 0  # Sequential index assigned to each valid nibble
    for y in range(0xAB, 0x100):
        a = y
        zp3c = a  # Save original value (mirrors the ROM's zero-page temp at $3C)
        # Shift right by 1: tests whether adjacent bits overlap sufficiently
        a = (a >> 1) & 0x7F
        # OR with original: if result is $FF, every bit position has at least
        # one '1' between the original and its shifted copy — meaning no
        # adjacent pair of zero bits exists in the original value.
        a = a | zp3c
        if a != 0xFF:
            continue  # Adjacent zero-bit pair found — not a valid GCR nibble
        if y == 0xD5:
            continue  # Reserved as prolog marker; cannot be used for data
        table[y] = x
        x += 1
    return table


# ── Sector interleave tables ────────────────────────────────────────

# DOS33_INTERLEAVE: Maps physical sector numbers (index) to logical sector
# numbers (value) as used by DOS 3.3. The non-sequential ordering exists because
# the Apple II's CPU needs time to process each sector before reading the next.
# By spacing logical sectors around the track, the disk doesn't have to make
# a full extra revolution to read the next logical sector.
DOS33_INTERLEAVE = [0x0, 0x7, 0xE, 0x6, 0xD, 0x5, 0xC, 0x4,
                    0xB, 0x3, 0xA, 0x2, 0x9, 0x1, 0x8, 0xF]

# PRODOS_INTERLEAVE: Maps physical sector numbers to logical sector numbers
# as used by ProDOS. ProDOS uses a different interleave pattern than DOS 3.3
# because its block-based I/O reads two sectors at a time (512-byte blocks),
# resulting in a different optimal spacing.
PRODOS_INTERLEAVE = [0x0, 0x8, 0x1, 0x9, 0x2, 0xA, 0x3, 0xB,
                     0x4, 0xC, 0x5, 0xD, 0x6, 0xE, 0x7, 0xF]


# ── Utility functions ───────────────────────────────────────────────

def decode_44(b1, b2):
    """Decode a 4-and-4 encoded byte pair (used in address fields).

    In 4-and-4 encoding, one data byte is spread across two disk bytes:
      - b1 carries the even bits (bits 7,5,3,1) in its positions 7,6,5,4,3,2,1,0
        with odd bit positions set to 1.
      - b2 carries the odd bits (bits 6,4,2,0) in its positions 7,6,5,4,3,2,1,0
        with odd bit positions set to 1.

    The formula works as follows:
      1. (b1 << 1) shifts b1's data bits into the even positions (7,5,3,1).
      2. | 0x01 ensures bit 0 is set (so the AND doesn't clear b2's bit 0).
      3. & b2 combines: b2's odd-position bits pass through, while b1's
         even-position bits are masked into place.

    This reconstructs the original 8-bit value from the two halves.

    Example:
        Original byte 0xFE (volume 254):
        b1 = 0xFF (even bits of 0xFE, with odd positions set to 1)
        b2 = 0xFE (odd bits of 0xFE, with odd positions set to 1)
        decode_44(0xFF, 0xFE) -> (0xFF << 1 | 1) & 0xFE = 0xFF & 0xFE = 0xFE

    Args:
        b1: First disk byte (carries even data bits).
        b2: Second disk byte (carries odd data bits).

    Returns:
        The decoded 8-bit data byte.
    """
    return ((b1 << 1) | 0x01) & b2


# ── Sector data classes ─────────────────────────────────────────────

class SectorData:
    """Holds decoded sector information: metadata and the 256 data bytes.

    Attributes:
        volume: Disk volume number (0-254).
        track: Track number (0-34 for standard disks).
        sector: Physical sector number (0-15 for 6-and-2, 0-12 for 5-and-3).
        data: The 256 decoded data bytes.
        addr_checksum_ok: True if the address field checksum passed, None if
            not checked.
        data_checksum_ok: True if the data field checksum passed, None if
            not checked.
    """

    def __init__(self, volume, track, sector, data,
                 addr_checksum_ok=None, data_checksum_ok=None):
        self.volume = volume
        self.track = track
        self.sector = sector
        self.data = data  # 256 bytes
        self.addr_checksum_ok = addr_checksum_ok
        self.data_checksum_ok = data_checksum_ok

    def __repr__(self):
        ck = ''
        if self.data_checksum_ok is not None:
            ck = f', cksum={"OK" if self.data_checksum_ok else "BAD"}'
        return (f"SectorData(vol={self.volume}, trk={self.track}, "
                f"sec={self.sector}{ck})")


# ── 6-and-2 sector decoding ─────────────────────────────────────────

def decode_sector_62(nibbles, data_start):
    """Decode 6-and-2 encoded sector data starting at data_start.

    This implements the same algorithm as the Apple II DOS 3.3 RWTS (Read/Write
    Track/Sector) routine, which decodes 342 GCR-encoded nibbles back into
    256 data bytes.

    Encoding layout (342 nibbles + 1 checksum nibble):
      - Nibbles 0-85 (86 "auxiliary" nibbles): Each carries a 6-bit value
        containing the low 2 bits for 3 data bytes. 86 aux nibbles * 3 bits
        each = 258 pairs of bits, covering all 256 data bytes (with 2 spare).
        These are stored in REVERSE order on disk (aux[85] first, aux[0] last).
      - Nibbles 86-341 (256 "primary" nibbles): Each carries the upper 6 bits
        of one data byte, in forward order.

    Decode proceeds in 3 phases:

    Phase 1 (XOR chain - aux bytes, reversed):
      The 86 aux nibbles are XOR-chained and stored into aux_buf in reverse
      order. The XOR chain means each nibble on disk is XOR'd with the running
      accumulator; this spreads errors and provides checksum coverage.

    Phase 2 (XOR chain - primary bytes, forward):
      The 256 primary nibbles continue the same XOR chain into pri_buf.
      After all 342 nibbles, the XOR accumulator should equal the checksum
      nibble (nibble 342).

    Phase 3 (post-decode with destructive LSR/ROL):
      Reassembles the original 256 bytes by combining each primary byte's
      upper 6 bits with 2 bits from the corresponding aux byte.
      The variable 'x' indexes into aux_buf, starting at 0x56 (86) and
      wrapping at 0x55 (85). For each data byte y (0-255):
        - x decrements, wrapping from -1 to 0x55 (85) — so byte 0 uses
          aux[85], byte 1 uses aux[84], ..., byte 85 uses aux[0], byte 86
          uses aux[85] again (second pass), and so on.
        - Two LSR operations on aux_buf[x] shift out the low 2 bits
          (destructively — the aux byte is modified in place).
        - Two ROL operations on the primary byte shift those 2 bits in
          as the new low bits.

    Magic numbers explained:
      - 342: Total encoded nibbles (86 aux + 256 primary).
      - 86 (0x56): Number of auxiliary nibbles. ceil(256*2/6) = 86 nibbles
        are needed to carry 2 extra bits per data byte in 6-bit chunks.
      - 0x56: Decimal 86, the initial aux index (one past end of aux_buf).
      - 0x55: Decimal 85, the wrap-around value (last valid aux index).
      - 256: Number of primary nibbles (one per output data byte).

    Args:
        nibbles: List/array of raw disk nibbles.
        data_start: Index of the first data nibble (after the D5 AA AD prolog).

    Returns:
        (data, checksum_ok): A tuple of the 256 decoded bytes and a boolean
        indicating whether the XOR checksum passed. Returns (None, False)
        if the nibble stream is too short or contains invalid nibbles.
    """
    idx = data_start

    # Read and GCR-decode all 342 data nibbles into 6-bit values
    encoded = []
    for i in range(342):
        if idx + i >= len(nibbles):
            return None, False
        nib = nibbles[idx + i]
        if nib not in DECODE_62:
            return None, False
        encoded.append(DECODE_62[nib])

    # Read and decode the checksum nibble (nibble #343, immediately after data)
    ck_idx = idx + 342
    if ck_idx >= len(nibbles) or nibbles[ck_idx] not in DECODE_62:
        return None, False
    checksum_byte = DECODE_62[nibbles[ck_idx]]

    # Phase 1 & 2: XOR-chain decode
    # The XOR chain links all 342 nibbles: each decoded value on disk is the
    # XOR of the actual value with the running accumulator. This provides
    # error detection (the final accumulator must match the checksum nibble).
    aux_buf = [0] * 86       # 86 auxiliary 6-bit values
    xor_acc = 0
    # Phase 1: Aux nibbles — stored reversed on disk, so we fill aux_buf
    # from index 85 down to 0 as we read nibbles 0 through 85.
    for k in range(86):
        xor_acc ^= encoded[k]
        aux_buf[85 - k] = xor_acc

    pri_buf = [0] * 256       # 256 primary 6-bit values
    # Phase 2: Primary nibbles — stored in forward order.
    for k in range(256):
        xor_acc ^= encoded[86 + k]
        pri_buf[k] = xor_acc

    # Verify checksum: final XOR accumulator should equal the checksum nibble
    checksum_ok = (xor_acc == checksum_byte)

    # Phase 3: Post-decode with destructive LSR/ROL
    # Recombine upper 6 bits (from pri_buf) with lower 2 bits (from aux_buf)
    # to reconstruct each original 8-bit data byte.
    result = bytearray(256)
    x = 0x56  # aux index starts at 86 (one past end), decremented before use
    for y in range(256):
        x -= 1
        if x < 0:
            x = 0x55  # Wrap to 85 — cycles through aux_buf 3 times (256/86 ~ 3)
        a = pri_buf[y]
        # Extract bit 0 from aux, shift aux right (destructive LSR)
        carry = aux_buf[x] & 1
        aux_buf[x] >>= 1
        # Shift primary left and insert the aux bit as new bit 0 (ROL)
        a = ((a << 1) | carry) & 0xFF
        # Repeat for the second aux bit
        carry2 = aux_buf[x] & 1
        aux_buf[x] >>= 1
        a = ((a << 1) | carry2) & 0xFF
        result[y] = a

    return bytes(result), checksum_ok


def decode_sector_53(nibbles, data_start):
    """Decode one 5-and-3 encoded sector using the P5A ROM algorithm.

    The 5-and-3 encoding scheme (used by the 13-sector Apple II ROM) splits
    each data byte into a 5-bit "top" (primary) part and a 3-bit "thr"
    (secondary/three-bit) part. Five data bytes are grouped together:

      - Group structure: Each group of 5 data bytes (A, B, C, D, E) produces:
        * 5 top nibbles: one per data byte, carrying bits 7-3.
        * 3 thr nibbles: carrying the low 3 bits of A, B, and C directly.
          The low bits of D and E are packed across two of these thr nibbles.

    With 51 groups of 5 bytes = 255 bytes, plus 1 extra byte, we get 256 bytes.

    Encoding layout (411 nibbles + 1 checksum nibble):
      - Nibbles 0-153 (154 "secondary" nibbles): Carry 3-bit values for the
        low bits of each group. Stored in REVERSE order on disk.
      - Nibbles 154-409 (256 "primary" nibbles): Carry 5-bit values for the
        upper bits of each data byte, in forward order.

    Magic numbers explained:
      - GRP = 51: Group size — 51 groups of 5 bytes = 255 data bytes,
        plus 1 extra byte = 256 total.
      - 411: Total encoded nibbles (154 secondary + 256 primary + 1 checksum).
        This is why find_sectors_53 requires 411 valid nibbles.
      - 154: Number of secondary (thr) nibbles. 51 groups * 3 thr nibbles each
        = 153, plus 1 extra = 154.
      - 256: Number of primary (top) nibbles (one per data byte).

    Reconstruction algorithm:
      For each group index i (counting down from 50 to 0), 5 output bytes
      are produced by combining top[group*51 + i] with thr[group*51 + i]:
        * Byte A: top[0*51+i] << 3 | (thr[0*51+i] >> 2) & 7
        * Byte B: top[1*51+i] << 3 | (thr[1*51+i] >> 2) & 7
        * Byte C: top[2*51+i] << 3 | (thr[2*51+i] >> 2) & 7
        * Byte D: top[3*51+i] << 3 | mixed bits from thr bit 1 of A,B,C
        * Byte E: top[4*51+i] << 3 | mixed bits from thr bit 0 of A,B,C
      The final (256th) byte uses top[5*51] and thr[3*51].

    Args:
        nibbles: List/array of raw disk nibbles.
        data_start: Index of the first data nibble (after the D5 AA AD prolog).

    Returns:
        (data, checksum_ok): A tuple of the 256 decoded bytes and a boolean
        indicating whether the XOR checksum passed. Returns (None, False)
        if the nibble stream is too short or contains invalid nibbles.
    """
    GRP = 51  # Group size: 51 groups * 5 bytes/group = 255 bytes (+1 = 256)

    # Translate 411 disk nibbles into 5-bit decoded values via DECODE_53
    translated = []
    for i in range(411):
        if data_start + i >= len(nibbles):
            return None, False
        nib = nibbles[data_start + i]
        if nib not in DECODE_53:
            return None, False
        translated.append(DECODE_53[nib])

    # XOR chain decode: each value on disk is XOR'd with its predecessor.
    # This is the same error-detection scheme as 6-and-2 encoding.
    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    # The final XOR accumulator should match the 411th nibble (checksum)
    checksum_ok = (prev == translated[410])

    # Split decoded stream into secondary (thr) and primary (top) buffers.
    # decoded[0..153] = secondary nibbles, stored reversed on disk so we
    # un-reverse them here. decoded[154..409] = primary nibbles in order.
    thr = [decoded[153 - j] for j in range(154)]  # Reverse the secondary buffer
    top = [decoded[154 + j] for j in range(256)]   # Primary buffer, forward order

    # Reconstruct 256 data bytes from groups of 5
    output = bytearray()
    for i in range(GRP - 1, -1, -1):  # Count down from 50 to 0
        # Safely index into thr, which has 154 entries (3 full groups + 1 extra)
        s0 = thr[0 * GRP + i] if (0 * GRP + i) < 154 else 0
        s1 = thr[1 * GRP + i] if (1 * GRP + i) < 154 else 0
        s2 = thr[2 * GRP + i] if (2 * GRP + i) < 154 else 0

        # Byte A: top 5 bits from top[0*51+i], low 3 bits from thr[0*51+i] >> 2
        output.append(((top[0 * GRP + i] << 3) | ((s0 >> 2) & 7)) & 0xFF)
        # Byte B: top 5 bits from top[1*51+i], low 3 bits from thr[1*51+i] >> 2
        output.append(((top[1 * GRP + i] << 3) | ((s1 >> 2) & 7)) & 0xFF)
        # Byte C: top 5 bits from top[2*51+i], low 3 bits from thr[2*51+i] >> 2
        output.append(((top[2 * GRP + i] << 3) | ((s2 >> 2) & 7)) & 0xFF)

        # Byte D: top 5 bits from top[3*51+i], low 3 bits assembled from
        # bit 1 of each secondary value s0, s1, s2 (cross-group packing)
        d_low = ((s0 & 2) << 1) | (s1 & 2) | ((s2 & 2) >> 1)
        output.append(((top[3 * GRP + i] << 3) | (d_low & 7)) & 0xFF)

        # Byte E: top 5 bits from top[4*51+i], low 3 bits assembled from
        # bit 0 of each secondary value s0, s1, s2 (cross-group packing)
        e_low = ((s0 & 1) << 2) | ((s1 & 1) << 1) | (s2 & 1)
        output.append(((top[4 * GRP + i] << 3) | (e_low & 7)) & 0xFF)

    # Final (256th) byte: the leftover from the 51st position
    final_top = top[5 * GRP] if 5 * GRP < 256 else 0
    final_thr = thr[3 * GRP] if 3 * GRP < 154 else 0
    output.append(((final_top << 3) | (final_thr & 7)) & 0xFF)

    return bytes(output[:256]), checksum_ok


# ── Sector finding ───────────────────────────────────────────────────

def _match_prolog(nib, i, prolog):
    """Check if nibbles at position i match the prolog pattern.

    None values in prolog act as wildcards and match any nibble value.
    This allows matching prologs where copy protection has altered one
    or more of the standard bytes.

    Example:
        # Standard DOS 3.3 address prolog: D5 AA 96
        _match_prolog(nibbles, 100, (0xD5, 0xAA, 0x96))  # exact match

        # Match any first byte, require AA 96 for bytes 2 and 3:
        _match_prolog(nibbles, 100, (None, 0xAA, 0x96))   # wildcard first byte

    Args:
        nib: List/array of nibble values.
        i: Starting index to check in nib.
        prolog: Tuple of byte values (or None for wildcard) to match.

    Returns:
        True if all non-None prolog bytes match the nibbles at position i.
    """
    for k, p in enumerate(prolog):
        if p is not None and nib[i + k] != p:
            return False
    return True


def find_sectors_62(nibbles, addr_prolog=(0xD5, 0xAA, 0x96),
                    data_prolog=(0xD5, 0xAA, 0xAD)):
    """Find and decode all 6-and-2 sectors in a nibble stream.

    Search algorithm:
      1. Scan the nibble stream for the 3-byte address field prolog.
      2. When found, decode the 4-and-4 encoded address field (volume, track,
         sector, checksum — 8 bytes = 4 data values).
      3. Validate the address checksum (vol XOR trk XOR sec XOR chk == 0).
      4. Search forward (up to 100 nibbles) for the data field prolog.
      5. Decode the 342+1 data nibbles using decode_sector_62().
      6. Skip duplicate sector numbers (first valid decode wins).

    The search_limit is set to half the nibble stream length + 1000. This is
    because bit-doubled tracks contain two copies of the data; searching only
    slightly past the halfway point avoids decoding duplicates while ensuring
    we don't miss sectors near the track boundary.

    Args:
        nibbles: List of nibbles (should be from a bit-doubled track for
            reliable reads — bit-doubling duplicates the track data to handle
            the case where a sector straddles the track boundary).
        addr_prolog: 3-byte address field prolog sequence. Use None for any
            byte position to match any value (for copy-protected disks).
        data_prolog: 3-byte data field prolog sequence. Use None for wildcards.

    Returns:
        dict mapping physical sector numbers (int) to SectorData objects.
    """
    nib = nibbles
    # Limit search to avoid re-decoding in the bit-doubled second copy.
    # The +1000 margin ensures sectors near the wraparound point are found.
    search_limit = len(nibbles) // 2 + 1000 if len(nibbles) > 8000 else len(nibbles)
    sectors = {}

    i = 0
    while i < search_limit - 20:
        # Search for address field prolog
        if not _match_prolog(nib, i, addr_prolog):
            i += 1
            continue

        idx = i + 3  # Skip past the 3-byte prolog
        if idx + 8 > len(nib):
            break

        # Decode address field: 4 values in 4-and-4 encoding (8 bytes total)
        volume = decode_44(nib[idx], nib[idx + 1])
        track = decode_44(nib[idx + 2], nib[idx + 3])
        sector = decode_44(nib[idx + 4], nib[idx + 5])
        cksum = decode_44(nib[idx + 6], nib[idx + 7])
        # Address checksum: XOR of all 4 decoded values should be 0
        addr_ok = (volume ^ track ^ sector ^ cksum) == 0
        idx += 8

        # Skip if we already decoded this sector number (first occurrence wins)
        if sector in sectors:
            i = idx
            continue

        # Find data field prolog within 100 nibbles after the address field.
        # The gap contains the address epilog (DE AA EB) and sync bytes.
        # We need at least 350 nibbles remaining for the data field (342 data
        # + checksum + epilog).
        found_data = False
        for j in range(idx, min(idx + 100, len(nib) - 350)):
            if _match_prolog(nib, j, data_prolog):
                data, ck_ok = decode_sector_62(nib, j + 3)
                if data is not None:
                    sectors[sector] = SectorData(
                        volume=volume, track=track, sector=sector,
                        data=data, addr_checksum_ok=addr_ok,
                        data_checksum_ok=ck_ok)
                # Skip past the data field (3 prolog + 342 data + 1 checksum)
                i = j + 346
                found_data = True
                break

        if not found_data:
            i = idx

    return sectors


def find_sectors_53(nibbles, addr_prolog=(0xD5, 0xAA, 0xB5),
                    data_prolog=(0xD5, 0xAA, 0xAD)):
    """Find and decode all 5-and-3 sectors in a nibble stream.

    Search algorithm:
      1. Scan the nibble stream for the 3-byte address field prolog.
         The default third byte is $B5, which identifies the 13-sector format
         (vs. $96 for 16-sector).
      2. Decode the 4-and-4 encoded address field (same format as 6-and-2).
      3. Search forward (up to 80 nibbles) for the data field prolog.
      4. Validate that at least 410 of the next 411 nibbles are valid 5-and-3
         GCR values (a pre-check to avoid wasting time on garbage data).
      5. Decode the 411+1 data nibbles using decode_sector_53().

    Why 411 encoded nibbles: 5-and-3 encoding produces 154 secondary +
    256 primary + 1 checksum = 411 data nibbles per sector (vs. 342+1 for
    6-and-2). The larger count is because each nibble only carries 5 data
    bits instead of 6.

    Args:
        nibbles: List of nibbles (should be from a bit-doubled track).
        addr_prolog: 3-byte address field prolog sequence (None = any byte).
        data_prolog: 3-byte data field prolog sequence (None = any byte).

    Returns:
        dict mapping physical sector numbers (int) to SectorData objects.
    """
    nib = nibbles
    # Limit search to avoid re-decoding in the bit-doubled second copy
    search_limit = len(nibbles) // 2 + 1000 if len(nibbles) > 8000 else len(nibbles)
    valid_53 = set(ENCODE_53)  # Set of valid 5-and-3 nibble byte values
    sectors = {}

    i = 0
    while i < search_limit:
        if i + 2 >= len(nib):
            break
        if not _match_prolog(nib, i, addr_prolog):
            i += 1
            continue

        idx = i + 3  # Skip past the 3-byte prolog
        if idx + 8 >= len(nib):
            break

        # Decode address field (same 4-and-4 format as 6-and-2)
        volume = decode_44(nib[idx], nib[idx + 1])
        track = decode_44(nib[idx + 2], nib[idx + 3])
        sector = decode_44(nib[idx + 4], nib[idx + 5])
        cksum = decode_44(nib[idx + 6], nib[idx + 7])
        addr_ok = (volume ^ track ^ sector ^ cksum) == 0

        if sector in sectors:
            i = idx + 8
            continue

        # Find data field prolog within 80 nibbles after the address field
        found_data = False
        for j in range(idx + 8, min(idx + 80, len(nib) - 2)):
            if j + 2 >= len(nib):
                break
            if _match_prolog(nib, j, data_prolog):
                didx = j + 3
                # Pre-validate: count how many of the 411 nibbles are valid
                # 5-and-3 GCR values. Require at least 410 valid (allowing 1
                # marginal nibble) to avoid attempting decode on random data.
                valid_count = sum(1 for k in range(411)
                                  if didx + k < len(nib) and nib[didx + k] in valid_53)
                if valid_count >= 410:
                    data, ck_ok = decode_sector_53(nib, didx)
                    if data is not None:
                        sectors[sector] = SectorData(
                            volume=volume, track=track, sector=sector,
                            data=data, addr_checksum_ok=addr_ok,
                            data_checksum_ok=ck_ok)
                # Skip past the data field (3 prolog + 411 data + 1 checksum)
                i = j + 415
                found_data = True
                break

        if not found_data:
            i = idx + 8

    return sectors


def auto_detect_address_prologs(nibbles):
    """Auto-detect address field prolog patterns in a nibble stream.

    Many copy-protected Apple II disks use non-standard address field prologs
    (e.g., $DE $AA $96 instead of the standard $D5 $AA $96) to prevent
    standard DOS from reading the disk. This function detects the actual
    prolog bytes by looking for the structural signature of an address field,
    regardless of what the specific prolog bytes are.

    Detection strategy (structural pattern matching):
      Rather than looking for known prolog bytes, this function scans for the
      structural pattern that ALL address fields must have:

      1. A 3-byte prolog where:
         - Byte 1 (filter: >= $96): Must have the high bit set and be a
           plausible disk marker. Values below $96 are excluded because they
           cannot appear as disk nibbles (the Disk II hardware requires the
           high bit set and limits zero-bit runs).
         - Byte 2: Any value (copy protection commonly changes this byte).
         - Byte 3 (filter: $96 or $B5): Must be the format identifier — $96
           for 6-and-2 (16-sector) or $B5 for 5-and-3 (13-sector). Copy
           protection never changes this byte because it tells the RWTS which
           decode algorithm to use.

      2. Followed by 8 bytes of valid 4-and-4 data (all with high bit set).
         4-and-4 encoding always produces bytes >= $80, so this is a strong
         structural constraint.

      3. Followed (within 80 nibbles) by a $D5 $AA $AD data field prolog.
         This is the strongest filter: a genuine address field is always
         followed by its data field. False positives (random byte sequences
         that happen to look like an address field) almost never have a valid
         data prolog at the right distance.

    Note: Address checksums are NOT required to pass, because some copy
    protection schemes deliberately use invalid checksums as an anti-copy
    signature.

    Deduplication: Results are deduplicated by (volume, track, sector) to
    avoid counting the same physical sector twice in a bit-doubled stream.

    Args:
        nibbles: List of nibbles (should be from a bit-doubled track).

    Returns:
        List of unique (byte1, byte2, byte3) prolog tuples found, sorted by
        frequency (most common first). Typically returns a single-element list
        for standard disks, or multiple elements if different tracks use
        different prologs.
    """
    search_limit = len(nibbles) // 2 + 1000 if len(nibbles) > 8000 else len(nibbles)
    prolog_counts = {}  # (b1, b2, b3) -> count
    seen_sectors = set()  # (vol, trk, sec) to deduplicate bit-doubled matches

    i = 0
    while i < search_limit - 11:
        b0 = nibbles[i]
        # Filter 1: First byte must be >= $96 (valid disk nibble range).
        # This eliminates most random bytes while accepting all known prolog
        # first bytes (standard $D5, plus non-standard values like $DE).
        if b0 < 0x96:
            i += 1
            continue

        # Filter 2: Third byte must be a format identifier.
        # $96 = 6-and-2 (16-sector), $B5 = 5-and-3 (13-sector).
        # These are never altered by copy protection because changing them
        # would break the sector decode algorithm selection in the RWTS.
        b2 = nibbles[i + 2]
        if b2 != 0x96 and b2 != 0xB5:
            i += 1
            continue

        # Filter 3: All 8 address data bytes (4 pairs of 4-and-4 encoding)
        # must have their high bit set. This is a fundamental property of
        # 4-and-4 encoding and eliminates many false positives.
        idx = i + 3
        if idx + 8 > len(nibbles):
            break

        if not all(nibbles[idx + k] & 0x80 for k in range(8)):
            i += 1
            continue

        # Filter 4 (strongest): Require a D5 AA AD data prolog within 80
        # nibbles. The gap between address and data fields contains the
        # address epilog ($DE $AA $EB) and sync bytes (~15-30 nibbles).
        # 80 nibbles is generous enough to handle all known disk formats.
        data_end = idx + 8
        if data_end + 80 > len(nibbles):
            break
        found_data_prolog = False
        for j in range(data_end, min(data_end + 80, len(nibbles) - 2)):
            if (nibbles[j] == 0xD5 and nibbles[j + 1] == 0xAA
                    and nibbles[j + 2] == 0xAD):
                found_data_prolog = True
                break
        if not found_data_prolog:
            i += 1
            continue

        # Decode the sector identity for deduplication.
        # Note: we do NOT validate the address checksum here, because some
        # copy protection schemes deliberately write bad checksums.
        volume = decode_44(nibbles[idx], nibbles[idx + 1])
        track = decode_44(nibbles[idx + 2], nibbles[idx + 3])
        sector = decode_44(nibbles[idx + 4], nibbles[idx + 5])

        # Deduplicate: bit-doubled tracks produce two copies of each sector.
        # Only count each physical sector once.
        key = (volume, track, sector)
        if key in seen_sectors:
            i += 1
            continue
        seen_sectors.add(key)

        prolog = (nibbles[i], nibbles[i + 1], nibbles[i + 2])
        prolog_counts[prolog] = prolog_counts.get(prolog, 0) + 1
        i = data_end  # Skip past this address field

    # Sort by frequency (most common first) — the most-seen prolog is most
    # likely the standard one for this disk.
    return sorted(prolog_counts.keys(), key=lambda p: prolog_counts[p], reverse=True)


def scan_address_fields(nibbles):
    """Scan a nibble stream for all address fields, returning detailed info.

    This function uses the same structural validation as auto_detect_address_prologs()
    to find address fields regardless of their prolog bytes. It is useful for
    diagnosing disk formats, inspecting copy protection schemes, and verifying
    that all sectors on a track are present and readable.

    Validation approach:
      1. First byte >= $96 (valid disk nibble).
      2. Third byte is $96 (6-and-2) or $B5 (5-and-3) — the format identifier.
      3. All 8 address data bytes have high bit set (required by 4-and-4 encoding).
      4. A $D5 $AA $AD data prolog follows within 80 nibbles (structural proof
         that this is a real address field, not a coincidental byte pattern).

    Results are deduplicated by (volume, track, sector), so each physical sector
    appears at most once even in bit-doubled nibble streams.

    Args:
        nibbles: List of nibbles (should be from a bit-doubled track).

    Returns:
        List of dicts, each containing:
          - 'position': byte offset in the nibble stream
          - 'prolog': (byte1, byte2, byte3) tuple
          - 'volume': decoded volume number
          - 'track': decoded track number
          - 'sector': decoded sector number
          - 'checksum_byte': raw decoded checksum value
          - 'checksum_ok': True if vol ^ trk ^ sec ^ chk == 0
    """
    nib = nibbles
    search_limit = len(nibbles) // 2 + 1000 if len(nibbles) > 8000 else len(nibbles)
    results = []
    seen = set()  # (volume, track, sector) — one entry per physical sector

    i = 0
    while i < search_limit - 12:
        b0 = nib[i]
        # First byte must be >= $96 (minimum valid disk nibble value)
        if b0 < 0x96:
            i += 1
            continue

        # Third byte must be a format identifier ($96 or $B5)
        third = nib[i + 2]
        if third != 0x96 and third != 0xB5:
            i += 1
            continue

        idx = i + 3
        if idx + 8 > len(nib):
            break

        # Validate 4-and-4 encoding: all 8 bytes must have high bit set
        if not all(nib[idx + k] & 0x80 for k in range(8)):
            i += 1
            continue

        # Require D5 AA AD data prolog within 80 nibbles after address data
        data_end = idx + 8
        if data_end + 80 > len(nib):
            break
        found_data_prolog = False
        for j in range(data_end, min(data_end + 80, len(nib) - 2)):
            if nib[j] == 0xD5 and nib[j + 1] == 0xAA and nib[j + 2] == 0xAD:
                found_data_prolog = True
                break
        if not found_data_prolog:
            i += 1
            continue

        # Decode the 4 address field values
        volume = decode_44(nib[idx], nib[idx + 1])
        track = decode_44(nib[idx + 2], nib[idx + 3])
        sector = decode_44(nib[idx + 4], nib[idx + 5])
        cksum = decode_44(nib[idx + 6], nib[idx + 7])
        addr_ok = (volume ^ track ^ sector ^ cksum) == 0

        prolog = (nib[i], nib[i + 1], third)
        key = (volume, track, sector)
        # Deduplicate by sector identity (bit-doubling produces duplicates)
        if key in seen:
            i += 1
            continue
        seen.add(key)

        results.append({
            'position': i,
            'prolog': prolog,
            'volume': volume,
            'track': track,
            'sector': sector,
            'checksum_byte': cksum,
            'checksum_ok': addr_ok,
        })

        i = data_end  # Skip past the address field data

    return results

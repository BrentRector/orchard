"""
GCR (Group Code Recording) encoding/decoding for Apple II disks.

Supports both 6-and-2 (DOS 3.3, 16-sector) and 5-and-3 (13-sector) formats.
Provides sector finding with configurable address/data prologs.
"""


# ── 6-and-2 GCR tables ──────────────────────────────────────────────

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

DECODE_62 = {v: i for i, v in enumerate(ENCODE_62)}

# ── 5-and-3 GCR tables ──────────────────────────────────────────────

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]

DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def build_53_gcr_table():
    """Build the 5-and-3 GCR decode table as the Apple II boot ROM does.

    Returns a 256-entry list mapping nibble values to decoded values.
    Only entries for valid 5-and-3 nibbles ($AB-$FF range) are non-zero.
    """
    table = [0] * 256
    x = 0
    for y in range(0xAB, 0x100):
        a = y
        zp3c = a
        a = (a >> 1) & 0x7F
        a = a | zp3c
        if a != 0xFF:
            continue
        if y == 0xD5:
            continue
        table[y] = x
        x += 1
    return table


# ── Sector interleave tables ────────────────────────────────────────

DOS33_INTERLEAVE = [0x0, 0x7, 0xE, 0x6, 0xD, 0x5, 0xC, 0x4,
                    0xB, 0x3, 0xA, 0x2, 0x9, 0x1, 0x8, 0xF]

PRODOS_INTERLEAVE = [0x0, 0x8, 0x1, 0x9, 0x2, 0xA, 0x3, 0xB,
                     0x4, 0xC, 0x5, 0xD, 0x6, 0xE, 0x7, 0xF]


# ── Utility functions ───────────────────────────────────────────────

def decode_44(b1, b2):
    """Decode a 4-and-4 encoded byte pair (used in address fields)."""
    return ((b1 << 1) | 0x01) & b2


# ── Sector data classes ─────────────────────────────────────────────

class SectorData:
    """Holds decoded sector information."""

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

    Uses the ROM-exact algorithm with reversed aux buffer and
    destructive LSR/ROL post-decode.

    Returns (256-byte data, checksum_ok) or (None, False) on error.
    """
    idx = data_start

    # Read 342 encoded bytes
    encoded = []
    for i in range(342):
        if idx + i >= len(nibbles):
            return None, False
        nib = nibbles[idx + i]
        if nib not in DECODE_62:
            return None, False
        encoded.append(DECODE_62[nib])

    # Checksum byte
    ck_idx = idx + 342
    if ck_idx >= len(nibbles) or nibbles[ck_idx] not in DECODE_62:
        return None, False
    checksum_byte = DECODE_62[nibbles[ck_idx]]

    # XOR-decode: phase 1 (aux, reversed) + phase 2 (primary)
    aux_buf = [0] * 86
    xor_acc = 0
    for k in range(86):
        xor_acc ^= encoded[k]
        aux_buf[85 - k] = xor_acc

    pri_buf = [0] * 256
    for k in range(256):
        xor_acc ^= encoded[86 + k]
        pri_buf[k] = xor_acc

    checksum_ok = (xor_acc == checksum_byte)

    # Phase 3: Post-decode with destructive LSR/ROL
    result = bytearray(256)
    x = 0x56  # aux index starts at 86
    for y in range(256):
        x -= 1
        if x < 0:
            x = 0x55  # reset to 85
        a = pri_buf[y]
        carry = aux_buf[x] & 1
        aux_buf[x] >>= 1
        a = ((a << 1) | carry) & 0xFF
        carry2 = aux_buf[x] & 1
        aux_buf[x] >>= 1
        a = ((a << 1) | carry2) & 0xFF
        result[y] = a

    return bytes(result), checksum_ok


def decode_sector_53(nibbles, data_start):
    """Decode one 5-and-3 encoded sector using the P5A ROM algorithm.

    nibbles: list of nibbles
    data_start: index of first data nibble (after D5 AA AD prolog)

    Returns (256-byte data, checksum_ok) or (None, False) on error.
    """
    GRP = 51

    # Translate 411 nibbles
    translated = []
    for i in range(411):
        if data_start + i >= len(nibbles):
            return None, False
        nib = nibbles[data_start + i]
        if nib not in DECODE_53:
            return None, False
        translated.append(DECODE_53[nib])

    # XOR chain decode
    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    checksum_ok = (prev == translated[410])

    # decoded[0..153] = secondary (thr), stored reversed on disk
    # decoded[154..409] = primary (top)
    thr = [decoded[153 - j] for j in range(154)]
    top = [decoded[154 + j] for j in range(256)]

    # Reconstruct 256 bytes
    output = bytearray()
    for i in range(GRP - 1, -1, -1):
        s0 = thr[0 * GRP + i] if (0 * GRP + i) < 154 else 0
        s1 = thr[1 * GRP + i] if (1 * GRP + i) < 154 else 0
        s2 = thr[2 * GRP + i] if (2 * GRP + i) < 154 else 0

        output.append(((top[0 * GRP + i] << 3) | ((s0 >> 2) & 7)) & 0xFF)
        output.append(((top[1 * GRP + i] << 3) | ((s1 >> 2) & 7)) & 0xFF)
        output.append(((top[2 * GRP + i] << 3) | ((s2 >> 2) & 7)) & 0xFF)

        d_low = ((s0 & 2) << 1) | (s1 & 2) | ((s2 & 2) >> 1)
        output.append(((top[3 * GRP + i] << 3) | (d_low & 7)) & 0xFF)

        e_low = ((s0 & 1) << 2) | ((s1 & 1) << 1) | (s2 & 1)
        output.append(((top[4 * GRP + i] << 3) | (e_low & 7)) & 0xFF)

    final_top = top[5 * GRP] if 5 * GRP < 256 else 0
    final_thr = thr[3 * GRP] if 3 * GRP < 154 else 0
    output.append(((final_top << 3) | (final_thr & 7)) & 0xFF)

    return bytes(output[:256]), checksum_ok


# ── Sector finding ───────────────────────────────────────────────────

def _match_prolog(nib, i, prolog):
    """Check if nibbles at position i match the prolog pattern.
    None values in prolog match any nibble."""
    for k, p in enumerate(prolog):
        if p is not None and nib[i + k] != p:
            return False
    return True


def find_sectors_62(nibbles, addr_prolog=(0xD5, 0xAA, 0x96),
                    data_prolog=(0xD5, 0xAA, 0xAD)):
    """Find and decode all 6-and-2 sectors in a nibble stream.

    Args:
        nibbles: list of nibbles (should be from bit-doubled track)
        addr_prolog: 3-byte address field prolog sequence (None = any byte)
        data_prolog: 3-byte data field prolog sequence (None = any byte)

    Returns: dict of sector_number -> SectorData
    """
    nib = nibbles
    search_limit = len(nibbles) // 2 + 1000 if len(nibbles) > 8000 else len(nibbles)
    sectors = {}

    i = 0
    while i < search_limit - 20:
        # Search for address field prolog
        if not _match_prolog(nib, i, addr_prolog):
            i += 1
            continue

        idx = i + 3
        if idx + 8 > len(nib):
            break

        # Decode address field (4-and-4 encoded)
        volume = decode_44(nib[idx], nib[idx + 1])
        track = decode_44(nib[idx + 2], nib[idx + 3])
        sector = decode_44(nib[idx + 4], nib[idx + 5])
        cksum = decode_44(nib[idx + 6], nib[idx + 7])
        addr_ok = (volume ^ track ^ sector ^ cksum) == 0
        idx += 8

        if sector in sectors:
            i = idx
            continue

        # Find data field prolog
        found_data = False
        for j in range(idx, min(idx + 100, len(nib) - 350)):
            if _match_prolog(nib, j, data_prolog):
                data, ck_ok = decode_sector_62(nib, j + 3)
                if data is not None:
                    sectors[sector] = SectorData(
                        volume=volume, track=track, sector=sector,
                        data=data, addr_checksum_ok=addr_ok,
                        data_checksum_ok=ck_ok)
                i = j + 346
                found_data = True
                break

        if not found_data:
            i = idx

    return sectors


def find_sectors_53(nibbles, addr_prolog=(0xD5, 0xAA, 0xB5),
                    data_prolog=(0xD5, 0xAA, 0xAD)):
    """Find and decode all 5-and-3 sectors in a nibble stream.

    Args:
        nibbles: list of nibbles (should be from bit-doubled track)
        addr_prolog: 3-byte address field prolog sequence (None = any byte)
        data_prolog: 3-byte data field prolog sequence (None = any byte)

    Returns: dict of sector_number -> SectorData
    """
    nib = nibbles
    search_limit = len(nibbles) // 2 + 1000 if len(nibbles) > 8000 else len(nibbles)
    valid_53 = set(ENCODE_53)
    sectors = {}

    i = 0
    while i < search_limit:
        if i + 2 >= len(nib):
            break
        if not _match_prolog(nib, i, addr_prolog):
            i += 1
            continue

        idx = i + 3
        if idx + 8 >= len(nib):
            break

        # Decode address field
        volume = decode_44(nib[idx], nib[idx + 1])
        track = decode_44(nib[idx + 2], nib[idx + 3])
        sector = decode_44(nib[idx + 4], nib[idx + 5])
        cksum = decode_44(nib[idx + 6], nib[idx + 7])
        addr_ok = (volume ^ track ^ sector ^ cksum) == 0

        if sector in sectors:
            i = idx + 8
            continue

        # Find data field prolog
        found_data = False
        for j in range(idx + 8, min(idx + 80, len(nib) - 2)):
            if j + 2 >= len(nib):
                break
            if _match_prolog(nib, j, data_prolog):
                didx = j + 3
                # Validate that we have enough valid 5-and-3 nibbles
                valid_count = sum(1 for k in range(411)
                                  if didx + k < len(nib) and nib[didx + k] in valid_53)
                if valid_count >= 410:
                    data, ck_ok = decode_sector_53(nib, didx)
                    if data is not None:
                        sectors[sector] = SectorData(
                            volume=volume, track=track, sector=sector,
                            data=data, addr_checksum_ok=addr_ok,
                            data_checksum_ok=ck_ok)
                i = j + 415
                found_data = True
                break

        if not found_data:
            i = idx + 8

    return sectors


def scan_address_fields(nibbles, prolog_first_bytes=(0xD5, 0xDE)):
    """Scan nibble stream for unique address fields with various prolog patterns.

    Deduplicates by (prolog, volume, track, sector) so that each physical
    address field is counted only once even in a bit-doubled nibble stream.

    Returns list of dicts with address field info (volume, track, sector,
    checksum, prolog bytes, position). Useful for detecting non-standard
    address field markers.
    """
    nib = nibbles
    search_limit = len(nibbles) // 2 + 1000 if len(nibbles) > 8000 else len(nibbles)
    results = []
    seen = set()  # (volume, track, sector) — one per physical sector

    for i in range(search_limit - 12):
        if nib[i] not in prolog_first_bytes:
            continue
        if nib[i + 1] != 0xAA:
            continue
        # Third byte can vary — accept any valid nibble except $AD and $EB
        # ($AD is the data field third byte, $EB is the epilog third byte)
        third = nib[i + 2]
        if third < 0x90 or third == 0xAD or third == 0xEB:
            continue

        idx = i + 3
        if idx + 8 > len(nib):
            break

        # Validate 4-and-4 encoding: all 8 bytes must have high bit set
        if not all(nib[idx + k] & 0x80 for k in range(8)):
            continue

        volume = decode_44(nib[idx], nib[idx + 1])
        track = decode_44(nib[idx + 2], nib[idx + 3])
        sector = decode_44(nib[idx + 4], nib[idx + 5])
        cksum = decode_44(nib[idx + 6], nib[idx + 7])
        addr_ok = (volume ^ track ^ sector ^ cksum) == 0

        prolog = (nib[i], nib[i + 1], third)
        key = (volume, track, sector)
        if key in seen:
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

    return results

#!/usr/bin/env python3
"""
Decode Apple Panic WOZ disk using 5-and-3 encoding (13-sector format).
The disk uses D5 AA B5 address fields and 5-and-3 data encoding,
NOT the 6-and-2 encoding used by 16-sector disks.
"""
import struct
import hashlib

# 5-and-3 translation table (32 entries, mapping 0-31 to valid disk nibbles)
ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def read_woz2(path):
    with open(path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tracks = {}
    for i in range(160):
        offset = 256 + i * 8
        sb = struct.unpack_from('<H', data, offset)[0]
        bc = struct.unpack_from('<H', data, offset + 2)[0]
        bits = struct.unpack_from('<I', data, offset + 4)[0]
        if sb == 0 and bc == 0:
            continue
        tracks[i] = {'bit_count': bits, 'data': data[sb * 512:sb * 512 + bc * 512]}
    return tracks, tmap


def to_nibbles(track_data, bit_count):
    bits = []
    for b in track_data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
            if len(bits) >= bit_count:
                break
        if len(bits) >= bit_count:
            break
    nibbles = []
    current = 0
    for b in bits:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles


def decode_44(b1, b2):
    return ((b1 << 1) | 0x01) & b2


def decode_53_sector(nibbles, idx):
    """Decode 5-and-3 sector data starting at nibble index idx.

    5-and-3 format: 410 data nibbles + 1 checksum nibble
    - nibbles 0-153: secondary buffer (packed 3-bit values)
    - nibbles 154-409: primary buffer (5-bit values, one per byte)

    Returns (256-byte data, checksum_ok) or (None, False).
    """
    if idx + 411 > len(nibbles):
        return None, False

    # Step 1: Translate all 411 nibbles through inverse table
    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DECODE_53:
            return None, False
        translated.append(DECODE_53[nib])

    # Step 2: XOR-chain decode
    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    # Checksum: the running XOR should equal the checksum nibble
    cksum_val = translated[410]
    cksum_ok = (prev == cksum_val)

    # Step 3: Reconstruct 256 bytes
    # Primary buffer: decoded[154..409] = upper 5 bits of each byte
    # Secondary buffer: decoded[0..153] = packed lower 3 bits
    #
    # The P5A ROM packing (Beneath Apple DOS style):
    # For each group of 5 bytes (bytes i*5 through i*5+4):
    #   Their 3 lower bits b0..b4 are packed into 3 five-bit values:
    #   Try multiple packing orders to find the correct one.

    result = bytearray(256)

    # Packing scheme attempt 1: Standard "Beneath Apple DOS" ordering
    # Secondary nibbles are stored in reverse order
    # decoded[0] corresponds to the LAST group's data
    for i in range(256):
        upper5 = decoded[154 + i] & 0x1F
        result[i] = upper5 << 3  # placeholder, add lower3 below

    # Now decode the secondary (3-bit) values
    # The P5A ROM stores the 3-bit portions in a specific way.
    # Let's try the most common packing:
    #
    # For byte i (0-255):
    #   group = i / 5  (0-50, with group 51 for byte 255)
    #   position = i % 5  (0-4)
    #   The 3 nibbles for this group are at decoded[group*3], [group*3+1], [group*3+2]
    #
    # However, the exact bit packing within the 3 nibbles varies.
    # Let me try the most common Apple II 5-and-3 reconstruction.
    #
    # From the P5A ROM analysis:
    # The secondary buffer stores values in groups of 3 nibbles per 5 bytes.
    # Each group of 3 five-bit values (15 bits total) encodes 5 three-bit values.
    #
    # Packing (MSB first):
    #   nibble[0]: b4[2] b4[1] b4[0] b3[2] b3[1]
    #   nibble[1]: b3[0] b2[2] b2[1] b2[0] b1[2]
    #   nibble[2]: b1[1] b1[0] b0[2] b0[1] b0[0]
    #
    # Where b0..b4 are the 3-bit lower portions of bytes 0..4 in the group.

    for group in range(51):
        n0 = decoded[group * 3]     & 0x1F
        n1 = decoded[group * 3 + 1] & 0x1F
        n2 = decoded[group * 3 + 2] & 0x1F

        # Combine into 15 bits
        combined = (n0 << 10) | (n1 << 5) | n2

        # Extract 5 three-bit values
        b4 = (combined >> 12) & 7
        b3 = (combined >> 9) & 7
        b2 = (combined >> 6) & 7
        b1 = (combined >> 3) & 7
        b0 = combined & 7

        base = group * 5
        if base + 0 < 256: result[base + 0] |= b0
        if base + 1 < 256: result[base + 1] |= b1
        if base + 2 < 256: result[base + 2] |= b2
        if base + 3 < 256: result[base + 3] |= b3
        if base + 4 < 256: result[base + 4] |= b4

    # Handle byte 255 (group 51, only 1 byte)
    if 51 * 3 < 154:
        n0 = decoded[51 * 3] & 0x1F
        b0 = n0 & 7
        result[255] |= b0

    return bytes(result), cksum_ok


def decode_53_sector_v2(nibbles, idx):
    """Alternative packing order - reversed byte order within groups."""
    if idx + 411 > len(nibbles):
        return None, False

    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DECODE_53:
            return None, False
        translated.append(DECODE_53[nib])

    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    cksum_val = translated[410]
    cksum_ok = (prev == cksum_val)

    result = bytearray(256)
    for i in range(256):
        upper5 = decoded[154 + i] & 0x1F
        result[i] = upper5 << 3

    # Try reversed group order (P5A ROM reads buffer backwards)
    for group in range(51):
        # P5A ROM secondary buffer is stored in reverse
        sec_base = 153 - group * 3
        n2 = decoded[sec_base]     & 0x1F  # reversed order
        n1 = decoded[sec_base - 1] & 0x1F
        n0 = decoded[sec_base - 2] & 0x1F

        combined = (n0 << 10) | (n1 << 5) | n2

        b4 = (combined >> 12) & 7
        b3 = (combined >> 9) & 7
        b2 = (combined >> 6) & 7
        b1 = (combined >> 3) & 7
        b0 = combined & 7

        base = group * 5
        if base + 0 < 256: result[base + 0] |= b0
        if base + 1 < 256: result[base + 1] |= b1
        if base + 2 < 256: result[base + 2] |= b2
        if base + 3 < 256: result[base + 3] |= b3
        if base + 4 < 256: result[base + 4] |= b4

    # Handle last byte
    n0 = decoded[0] & 0x1F
    result[255] |= (n0 & 7)

    return bytes(result), cksum_ok


def decode_53_sector_v3(nibbles, idx):
    """P5A ROM style: secondary buffer at indices [0..153], read in specific order.

    Based on actual P5A ROM disassembly:
    - Buffer is filled from disk in order 0..409
    - XOR decode applied
    - Primary (5-bit upper) values at indices 154-409
    - Secondary (3-bit lower) values packed in indices 0-153
    - Secondary index mapping: for byte I, the 3-bit value is at
      secondary index = (255 - I) for some ROMs, or just I/5*3 + offset
    """
    if idx + 411 > len(nibbles):
        return None, False

    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DECODE_53:
            return None, False
        translated.append(DECODE_53[nib])

    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    cksum_val = translated[410]
    cksum_ok = (prev == cksum_val)

    result = bytearray(256)

    # Primary: byte i upper 5 bits = decoded[154 + i]
    for i in range(256):
        result[i] = (decoded[154 + i] & 0x1F) << 3

    # Secondary: each 3 five-bit values encode 5 three-bit values
    # Try: bytes are stored in reverse order (255 down to 0)
    # and secondary buffer is read from end to start
    for i in range(256):
        # Map byte i to secondary buffer position
        # Groups of 5 bytes: group = (255 - i) // 5
        # Position within group: pos = (255 - i) % 5
        rev_i = 255 - i
        group = rev_i // 5
        pos = rev_i % 5

        sec_idx = group * 3
        if sec_idx + 2 >= 154:
            # Last partial group
            n0 = decoded[sec_idx] & 0x1F if sec_idx < 154 else 0
            lower3 = n0 & 7
        else:
            n0 = decoded[sec_idx] & 0x1F
            n1 = decoded[sec_idx + 1] & 0x1F
            n2 = decoded[sec_idx + 2] & 0x1F
            combined = (n0 << 10) | (n1 << 5) | n2

            if pos == 0:
                lower3 = combined & 7
            elif pos == 1:
                lower3 = (combined >> 3) & 7
            elif pos == 2:
                lower3 = (combined >> 6) & 7
            elif pos == 3:
                lower3 = (combined >> 9) & 7
            else:
                lower3 = (combined >> 12) & 7

        result[i] |= lower3

    return bytes(result), cksum_ok


def decode_53_raw(nibbles, idx):
    """Just do translate + XOR decode, return raw 5-bit values for analysis."""
    if idx + 411 > len(nibbles):
        return None

    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DECODE_53:
            return None
        translated.append(DECODE_53[nib])

    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    cksum_val = translated[410]
    cksum_ok = (prev == cksum_val)

    return decoded, cksum_ok, cksum_val, prev


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    tracks, tmap = read_woz2(woz_path)

    print("=" * 70)
    print("5-AND-3 DECODE OF APPLE PANIC WOZ")
    print("=" * 70)

    all_sectors = {}  # (track, sector) -> data

    for track_num in range(14):
        qt = track_num * 4
        tidx = tmap[qt]
        if tidx == 0xFF or tidx not in tracks:
            continue

        t = tracks[tidx]
        nibbles = to_nibbles(t['data'], t['bit_count'])
        nib2 = nibbles + nibbles[:1000]

        # Find D5 AA B5 address fields (or D5 xx B5 for tracks 1-5)
        addr_fields = []
        for i in range(len(nibbles)):
            if nib2[i] == 0xD5 and i + 2 < len(nib2) and nib2[i + 2] == 0xB5:
                idx = i + 3
                if idx + 8 < len(nib2):
                    vol = decode_44(nib2[idx], nib2[idx + 1])
                    trk = decode_44(nib2[idx + 2], nib2[idx + 3])
                    sec = decode_44(nib2[idx + 4], nib2[idx + 5])
                    addr_fields.append((i, vol, trk, sec))

        # Find D5 AA AD data fields
        data_positions = []
        for i in range(len(nibbles) + 500):
            if nib2[i] == 0xD5 and nib2[i + 1] == 0xAA and nib2[i + 2] == 0xAD:
                data_positions.append(i)

        print(f"\nTrack {track_num}: {len(addr_fields)} address fields, "
              f"{len(data_positions)} data fields")

        # Match address fields to data fields
        for dpos in data_positions:
            # Find nearest preceding address field
            best_addr = None
            for apos, vol, trk, sec in addr_fields:
                if apos < dpos and dpos - apos < 80:
                    best_addr = (vol, trk, sec, apos)

            if not best_addr:
                continue

            vol, trk, sec, apos = best_addr
            didx = dpos + 3

            # Check how many nibbles are 5-and-3 valid
            valid_53 = 0
            for j in range(500):
                if nib2[didx + j] in DECODE_53:
                    valid_53 += 1
                else:
                    break

            # Skip the one 6-and-2 sector on track 0 (the dummy boot sector)
            if valid_53 < 410:
                print(f"  S{sec:2d}: skipping (only {valid_53} valid 5&3 nibbles - "
                      f"6&2 encoded dummy)")
                continue

            # Try 5-and-3 raw decode first
            raw = decode_53_raw(nib2, didx)
            if raw:
                decoded, cksum_ok, cksum_val, prev = raw

                # Try all 3 reconstruction methods
                for version, func in [("v1", decode_53_sector),
                                       ("v2", decode_53_sector_v2),
                                       ("v3", decode_53_sector_v3)]:
                    result, ckok = func(nib2, didx)
                    if result:
                        first8 = ' '.join(f'{b:02X}' for b in result[:8])
                        all_sectors[(track_num, sec, version)] = result
                        if sec <= 1 or track_num == 0:
                            print(f"  S{sec:2d} ({version}): {first8}... "
                                  f"ck={'OK' if ckok else 'BAD'}")

                # Also show raw decoded values for sector 0
                if sec == 0 and track_num == 0:
                    print(f"  Raw 5-bit values [0:20]: "
                          f"{[f'{v:02X}' for v in decoded[:20]]}")
                    print(f"  Raw 5-bit values [154:174]: "
                          f"{[f'{v:02X}' for v in decoded[154:174]]}")
                    print(f"  Checksum: prev=${prev:02X} expected=${cksum_val:02X} "
                          f"{'OK' if cksum_ok else 'BAD'}")

    # Check which version produces the best boot sector
    print("\n" + "=" * 70)
    print("BOOT SECTOR ANALYSIS")
    print("=" * 70)

    for version in ["v1", "v2", "v3"]:
        key = (0, 0, version)
        if key in all_sectors:
            boot = all_sectors[key]
            print(f"\n=== Version {version}: byte0=${boot[0]:02X} ===")
            print("Hex dump:")
            for row in range(16):
                off = row * 16
                h = ' '.join(f'{boot[off + c]:02X}' for c in range(16))
                print(f"  ${0x0800 + off:04X}: {h}")

    # Compare with cracked version to look for matches
    print("\n" + "=" * 70)
    print("PATTERN SEARCH")
    print("=" * 70)

    cracked = open("E:/Apple/ApplePanic_runtime.bin", 'rb').read()

    for version in ["v1", "v2", "v3"]:
        print(f"\n--- Version {version} ---")
        # Concatenate all sectors for this version in order
        all_data = bytearray()
        for track_num in range(14):
            for sec in range(13):
                key = (track_num, sec, version)
                if key in all_sectors:
                    all_data.extend(all_sectors[key])

        print(f"Total decoded: {len(all_data)} bytes")

        # Search for known game patterns
        patterns = {
            "JMP $7465": bytes([0x4C, 0x65, 0x74]),
            "LDA $C050": bytes([0xAD, 0x50, 0xC0]),
            "LDA $C057": bytes([0xAD, 0x57, 0xC0]),
            "STA $C054": bytes([0x8D, 0x54, 0xC0]),
        }
        for name, pat in patterns.items():
            for i in range(len(all_data) - len(pat)):
                if all_data[i:i + len(pat)] == pat:
                    print(f"  FOUND: {name} at offset ${i:04X}")
                    break

        # Try longer patterns from cracked version
        if len(cracked) > 0x7000:
            for start in [0x7000, 0x7465, 0x6000]:
                pat = cracked[start:start + 8]
                for i in range(len(all_data) - 8):
                    if all_data[i:i + 8] == pat:
                        print(f"  FOUND: cracked[${start:04X}] at offset ${i:04X}")
                        break

        # Check sector-level matches
        matches = 0
        for off in range(0, len(all_data) - 256, 256):
            sector = all_data[off:off + 256]
            for game_start in range(0, len(cracked) - 256, 256):
                if cracked[game_start:game_start + 256] == sector:
                    matches += 1
                    if matches <= 5:
                        print(f"  EXACT SECTOR MATCH: woz[${off:04X}] = "
                              f"cracked[${game_start:04X}]")
        if matches > 5:
            print(f"  ... {matches} total sector matches")


if __name__ == '__main__':
    main()

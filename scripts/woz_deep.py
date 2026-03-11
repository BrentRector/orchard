#!/usr/bin/env python3
"""
Deep analysis of Apple Panic copy protection scheme.
Examines boot code, nibble patterns, and encryption.
"""
import struct

# 6-and-2 tables
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


def read_woz2(path):
    with open(path, 'rb') as f:
        data = f.read()
    tmap = data[88:88+160]
    tracks = {}
    for i in range(160):
        offset = 256 + i * 8
        sb = struct.unpack_from('<H', data, offset)[0]
        bc = struct.unpack_from('<H', data, offset + 2)[0]
        bits = struct.unpack_from('<I', data, offset + 4)[0]
        if sb == 0 and bc == 0:
            continue
        tracks[i] = {'bit_count': bits, 'data': data[sb*512:sb*512 + bc*512]}
    return tracks, tmap


def to_nibbles(track_data, bit_count):
    bits = []
    for b in track_data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
            if len(bits) >= bit_count:
                return bits
    nibbles = []
    current = 0
    for b in bits:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles


def to_nibbles_v2(track_data, bit_count):
    """Convert track data to nibbles."""
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


def find_all(nibbles, pattern):
    results = []
    for i in range(len(nibbles) - len(pattern) + 1):
        if all(nibbles[i+j] == pattern[j] for j in range(len(pattern))):
            results.append(i)
    return results


def decode_44(b1, b2):
    return ((b1 << 1) | 0x01) & b2


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    tracks, tmap = read_woz2(woz_path)

    print("=" * 70)
    print("APPLE PANIC COPY PROTECTION ANALYSIS")
    print("=" * 70)

    # === 1. Disk structure overview ===
    print("\n1. DISK STRUCTURE")
    print("-" * 40)
    track_count = 0
    for t in range(35):
        tidx = tmap[t * 4]
        if tidx != 0xFF:
            track_count += 1
    print(f"   Tracks used: {track_count} (standard DOS 3.3 = 35)")
    print(f"   Boot format: Custom (WOZ INFO byte 38 = 3)")

    # === 2. Per-track analysis ===
    print("\n2. PER-TRACK ANALYSIS")
    print("-" * 40)

    for track_num in range(14):
        tidx = tmap[track_num * 4]
        if tidx == 0xFF or tidx not in tracks:
            continue
        t = tracks[tidx]
        nibbles = to_nibbles_v2(t['data'], t['bit_count'])
        nib2 = nibbles + nibbles[:500]

        # Find prologues
        std_addr = find_all(nib2[:len(nibbles)+100], [0xD5, 0xAA, 0x96])
        data_fields = find_all(nib2[:len(nibbles)+100], [0xD5, 0xAA, 0xAD])
        alt_b5 = find_all(nib2[:len(nibbles)+100], [0xD5, 0xAA, 0xB5])

        # Find ALL D5 xx B5 patterns (non-standard address prologues)
        custom_addr = []
        for i in range(len(nibbles)):
            if (nib2[i] == 0xD5 and i+2 < len(nib2) and nib2[i+2] == 0xB5
                and nib2[i+1] not in (0xAA,)):
                custom_addr.append((i, nib2[i+1]))

        # Find sync byte patterns (FF sequences or specific patterns)
        # Check what appears BETWEEN sectors
        sync_patterns = []
        for dp in data_fields[:3]:
            # Look backwards from data prologue to find sync bytes
            sync_start = max(0, dp - 60)
            sync = nibbles[sync_start:dp]
            # Find the non-sync part (before the sync)
            sync_patterns.append(sync)

        addr_type = "STANDARD (D5 AA 96)" if std_addr else f"CUSTOM (D5 {custom_addr[0][1]:02X} B5)" if custom_addr else "NONE"

        # Decode custom address field
        addr_info = ""
        if custom_addr:
            pos, mid_byte = custom_addr[0]
            idx = pos + 3
            # Custom address: D5 xx B5 FF FE vol1 vol2 trk1 trk2 sec1 sec2 ... DE AA
            # Try 4-and-4 decode of what follows
            if idx + 10 < len(nib2):
                post = nib2[idx:idx+12]
                # Try decoding as 4-and-4
                vals = []
                for j in range(0, min(8, len(post)), 2):
                    try:
                        v = decode_44(post[j], post[j+1])
                        vals.append(v)
                    except:
                        vals.append(-1)
                addr_info = f" decoded: {[f'${v:02X}' if v>=0 else '??' for v in vals]}"

        print(f"   Track {track_num:2d}: data={len(data_fields):2d} addr={addr_type}{addr_info}")

        # Show address field structure for first occurrence
        if custom_addr and track_num <= 5:
            pos, mid = custom_addr[0]
            # Show 15 nibbles after D5 xx B5
            idx = pos
            chunk = nib2[idx:idx+20]
            hex_str = ' '.join(f'{n:02X}' for n in chunk)
            print(f"            Address field: {hex_str}")

            # Also show what's between address epilogue and data prologue
            # Find the data prologue that follows this address
            for dp in data_fields:
                if dp > pos + 10:
                    between = nib2[pos:dp+3]
                    hex_str = ' '.join(f'{n:02X}' for n in between[:40])
                    print(f"            Addr to data: {hex_str}...")
                    break

    # === 3. Boot sector analysis ===
    print("\n3. BOOT SECTOR ANALYSIS")
    print("-" * 40)

    tidx = tmap[0]
    t = tracks[tidx]
    nibbles = to_nibbles_v2(t['data'], t['bit_count'])
    nib2 = nibbles + nibbles[:500]

    # Find T0S0 data field
    data_pos = find_all(nib2, [0xD5, 0xAA, 0xAD])
    if data_pos:
        idx = data_pos[0] + 3
        # Decode the sector
        encoded = []
        valid = True
        for i in range(342):
            nib = nib2[idx + i]
            if nib in DECODE_62:
                encoded.append(DECODE_62[nib])
            else:
                valid = False
                break

        if valid:
            # XOR decode
            decoded = [0] * 342
            prev = 0
            for i in range(342):
                decoded[i] = encoded[i] ^ prev
                prev = decoded[i]
            cksum = DECODE_62.get(nib2[idx+342], -1)

            # Reconstruct
            result = bytearray(256)
            for i in range(256):
                upper = decoded[86 + i] << 2
                aux_idx = 85 - (i % 86)
                shift = (i // 86) * 2
                lower = (decoded[aux_idx] >> shift) & 0x03
                result[i] = (upper | lower) & 0xFF

            print(f"   Boot sector T0S0 decoded ({256} bytes), cksum={'OK' if prev==cksum else 'BAD'}")
            print(f"   First byte (sector count): ${result[0]:02X}")
            print(f"   Boot entry at $0801:")

            # Better disassembly using knowledge of X = slot*16 ($60 for slot 6)
            # The boot code accesses $C0nC, $C0nD, $C0nE with n = slot
            for i in range(0, 128, 1):
                b = result[i+1] if i+1 < 256 else 0
                print(f"   ${0x0801+i:04X}: {result[i+1]:02X}", end="")
                if i < 254:
                    print(f" {result[i+2]:02X}" if i+2 < 256 else "", end="")
                print()
                if i > 60:
                    break

            # Show the boot sector as a hex dump
            print(f"\n   Boot sector hex dump:")
            for row in range(16):
                offset = row * 16
                hex_str = ' '.join(f'{result[offset+c]:02X}' for c in range(16))
                ascii_str = ''.join(chr(result[offset+c]) if 32 <= result[offset+c] < 127 else '.' for c in range(16))
                print(f"   ${0x0800+offset:04X}: {hex_str}  {ascii_str}")

    # === 4. Nibble-level sync analysis ===
    print("\n4. SYNC BYTE / GAP ANALYSIS")
    print("-" * 40)

    for track_num in [0, 1, 6]:
        tidx = tmap[track_num * 4]
        if tidx == 0xFF or tidx not in tracks:
            continue
        t = tracks[tidx]
        nibbles = to_nibbles_v2(t['data'], t['bit_count'])

        # Categorize nibble types
        from collections import Counter
        nib_counts = Counter(nibbles)
        sync_nibs = sum(v for k, v in nib_counts.items() if k == 0xFF)
        total = len(nibbles)
        print(f"   Track {track_num}: {total} nibbles, {sync_nibs} sync ($FF)")
        print(f"   Top nibbles: {[(f'${k:02X}', v) for k, v in nib_counts.most_common(8)]}")

    # === 5. Address field format comparison ===
    print("\n5. ADDRESS FIELD FORMAT")
    print("-" * 40)

    # Each track uses a different second byte in D5 xx B5
    addr_bytes = {}
    for track_num in range(14):
        tidx = tmap[track_num * 4]
        if tidx == 0xFF or tidx not in tracks:
            continue
        t = tracks[tidx]
        nibbles = to_nibbles_v2(t['data'], t['bit_count'])
        nib2 = nibbles + nibbles[:500]

        for i in range(len(nibbles)):
            if (nib2[i] == 0xD5 and i+2 < len(nib2) and nib2[i+2] == 0xB5):
                mid = nib2[i+1]
                if track_num not in addr_bytes:
                    addr_bytes[track_num] = mid

    print(f"   Address prologue second byte per track:")
    for t, b in sorted(addr_bytes.items()):
        if b == 0xAA:
            note = "(standard + B5)"
        else:
            note = f"(custom)"
        print(f"   Track {t:2d}: D5 {b:02X} B5 {note}")

    # === 6. Data encoding verification ===
    print("\n6. DATA ENCODING ANALYSIS")
    print("-" * 40)

    # Check if the 6-and-2 encoded nibbles use the standard translation table
    # by checking that ALL nibbles in data fields are valid 6-and-2 values
    for track_num in [0, 1, 6, 13]:
        tidx = tmap[track_num * 4]
        if tidx == 0xFF or tidx not in tracks:
            continue
        t = tracks[tidx]
        nibbles = to_nibbles_v2(t['data'], t['bit_count'])
        nib2 = nibbles + nibbles[:500]
        data_positions = find_all(nib2[:len(nibbles)+100], [0xD5, 0xAA, 0xAD])

        all_valid = 0
        total_checked = 0
        invalid_nibs = Counter()

        for dp in data_positions[:13]:
            idx = dp + 3
            for i in range(343):  # 342 data + 1 checksum
                if idx + i < len(nib2):
                    total_checked += 1
                    if nib2[idx + i] in DECODE_62:
                        all_valid += 1
                    else:
                        invalid_nibs[nib2[idx + i]] += 1

        if total_checked > 0:
            pct = all_valid * 100 / total_checked
            print(f"   Track {track_num:2d}: {all_valid}/{total_checked} valid 6-and-2 nibbles ({pct:.1f}%)")
            if invalid_nibs:
                top_invalid = invalid_nibs.most_common(5)
                print(f"            Invalid nibbles: {[(f'${k:02X}', v) for k, v in top_invalid]}")

    # === 7. Epilogue analysis ===
    print("\n7. EPILOGUE FORMAT")
    print("-" * 40)

    for track_num in [0, 1, 6]:
        tidx = tmap[track_num * 4]
        if tidx == 0xFF or tidx not in tracks:
            continue
        t = tracks[tidx]
        nibbles = to_nibbles_v2(t['data'], t['bit_count'])
        nib2 = nibbles + nibbles[:500]
        data_positions = find_all(nib2[:len(nibbles)+100], [0xD5, 0xAA, 0xAD])

        if data_positions:
            dp = data_positions[0]
            idx = dp + 3 + 343  # After data + checksum
            if idx + 5 < len(nib2):
                epilogue = nib2[idx:idx+5]
                hex_str = ' '.join(f'{n:02X}' for n in epilogue)
                standard = "YES" if epilogue[:3] == [0xDE, 0xAA, 0xEB] else "NO"
                print(f"   Track {track_num:2d} data epilogue: {hex_str} (standard DE AA EB: {standard})")

    # === 8. Sector ordering ===
    print("\n8. SECTOR ORDERING")
    print("-" * 40)
    print("   Standard DOS 3.3 uses 16 sectors per track with D5 AA 96 address fields")
    print("   containing volume, track, sector, and checksum bytes in 4-and-4 encoding.")
    print()
    print("   Apple Panic uses:")
    print("   - 13 sectors per track (non-standard)")
    print("   - Custom address field: D5 xx B5 (xx varies by track)")
    print("   - Standard data field: D5 AA AD")
    print("   - Sectors appear in sequential order within each track")
    print("   - No sector interleave needed (sectors are physically sequential)")


if __name__ == '__main__':
    main()

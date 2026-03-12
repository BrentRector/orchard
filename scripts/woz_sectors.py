#!/usr/bin/env python3
"""
Decode ALL address fields from the Apple Panic WOZ disk to determine sector ordering.

Parses both standard (D5 AA 96) and custom (D5 xx B5) address prologues across
all 14 tracks, pairs each address field with its following D5 AA AD data field,
and decodes 6-and-2 sector data. Builds an ordered image using sector numbers
from address fields (tracks 0-5) or sequential order (tracks 6-13). Searches
the resulting image for known game code patterns, including XOR $24 variants.

Usage:
    python woz_sectors.py

    Default paths (override by editing APPLE_PANIC / OUTPUT_DIR):
        woz_path - apple-panic/Apple Panic - Disk 1, Side A.woz
        out_path - apple-panic/output/ApplePanic_original_ordered.bin
        Also reads apple-panic/ApplePanic_runtime.bin for pattern comparison

Output:
    Per-track sector ordering with address field details (volume, track, sector),
    checksum status, first-8-byte previews. Writes an ordered binary image and
    prints game pattern search results.
"""
import os
import struct
import hashlib
from pathlib import Path

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
    """Parse a WOZ2 file and return (tracks dict, tmap bytes)."""
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
    """Convert raw track bytes into a list of disk nibbles (high-bit-set bytes)."""
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
    """Decode a 4-and-4 encoded byte pair (used in address field headers)."""
    return ((b1 << 1) | 0x01) & b2


def find_all(nibbles, pattern):
    """Return indices of all exact occurrences of pattern in the nibble stream."""
    results = []
    for i in range(len(nibbles) - len(pattern) + 1):
        if all(nibbles[i+j] == pattern[j] for j in range(len(pattern))):
            results.append(i)
    return results


def decode_62_sector(nibbles, idx):
    """Decode 6-and-2 sector at nibble index idx."""
    if idx + 343 > len(nibbles):
        return None
    encoded = []
    for i in range(342):
        nib = nibbles[idx + i]
        if nib not in DECODE_62:
            return None
        encoded.append(DECODE_62[nib])
    cksum_nib = nibbles[idx + 342]
    if cksum_nib not in DECODE_62:
        return None
    cksum_val = DECODE_62[cksum_nib]

    # XOR decode
    decoded = [0] * 342
    prev = 0
    for i in range(342):
        decoded[i] = encoded[i] ^ prev
        prev = decoded[i]

    cksum_ok = (prev == cksum_val)

    # Reconstruct 256 bytes
    result = bytearray(256)
    for i in range(256):
        upper = decoded[86 + i] << 2
        aux_idx = 85 - (i % 86)
        shift = (i // 86) * 2
        lower = (decoded[aux_idx] >> shift) & 0x03
        result[i] = (upper | lower) & 0xFF

    return bytes(result), cksum_ok


def main():
    """Analyze sector ordering, build an ordered image, and search for game patterns."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    OUTPUT_DIR = APPLE_PANIC / "output"
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    tracks, tmap = read_woz2(woz_path)

    print("=" * 70)
    print("SECTOR ORDERING ANALYSIS")
    print("=" * 70)

    # For each track, find ALL address fields and decode sector numbers
    # Then pair each address with its following data field

    all_track_sectors = {}  # track -> [(sector_num, data_bytes), ...]

    for track_num in range(14):
        tidx = tmap[track_num * 4]
        if tidx == 0xFF or tidx not in tracks:
            continue
        t = tracks[tidx]
        nibbles = to_nibbles(t['data'], t['bit_count'])
        nib2 = nibbles + nibbles[:1000]  # wrap-around

        # Find ALL D5 xx B5 address fields (for tracks 1+)
        # and D5 AA 96 for track 0
        addr_fields = []

        if track_num == 0:
            # Standard D5 AA 96 address
            for i in range(len(nibbles)):
                if (nib2[i] == 0xD5 and nib2[i+1] == 0xAA and nib2[i+2] == 0x96):
                    idx = i + 3
                    vol = decode_44(nib2[idx], nib2[idx+1])
                    trk = decode_44(nib2[idx+2], nib2[idx+3])
                    sec = decode_44(nib2[idx+4], nib2[idx+5])
                    cksum = decode_44(nib2[idx+6], nib2[idx+7])
                    addr_fields.append((i, vol, trk, sec))

            # Also check for D5 AA B5 (track 0 has both!)
            for i in range(len(nibbles)):
                if (nib2[i] == 0xD5 and nib2[i+1] == 0xAA and nib2[i+2] == 0xB5):
                    idx = i + 3
                    if idx + 8 < len(nib2):
                        vol = decode_44(nib2[idx], nib2[idx+1])
                        trk = decode_44(nib2[idx+2], nib2[idx+3])
                        sec = decode_44(nib2[idx+4], nib2[idx+5])
                        cksum = decode_44(nib2[idx+6], nib2[idx+7])
                        addr_fields.append((i, vol, trk, sec))
        else:
            # Custom D5 xx B5 address
            for i in range(len(nibbles)):
                if (nib2[i] == 0xD5 and i+2 < len(nib2) and nib2[i+2] == 0xB5):
                    idx = i + 3
                    if idx + 8 < len(nib2):
                        vol = decode_44(nib2[idx], nib2[idx+1])
                        trk = decode_44(nib2[idx+2], nib2[idx+3])
                        sec = decode_44(nib2[idx+4], nib2[idx+5])
                        cksum = decode_44(nib2[idx+6], nib2[idx+7])
                        addr_fields.append((i, vol, trk, sec))

        # Sort by position
        addr_fields.sort(key=lambda x: x[0])

        # Find all data fields
        data_positions = find_all(nib2[:len(nibbles)+500], [0xD5, 0xAA, 0xAD])

        # Match each address field to its nearest following data field
        sector_data = {}  # sector_num -> data_bytes

        # For each data field, find the preceding address field
        data_order = []  # ordered list of (sector_num, data_bytes)

        for di, dpos in enumerate(data_positions):
            # Find the address field that precedes this data field
            best_addr = None
            for ai, (apos, vol, trk, sec) in enumerate(addr_fields):
                if apos < dpos and dpos - apos < 100:  # within 100 nibbles
                    best_addr = (vol, trk, sec)

            # Decode data
            result = decode_62_sector(nib2, dpos + 3)
            if result is None:
                continue
            sector_bytes, cksum_ok = result

            if best_addr:
                vol, trk, sec = best_addr
                data_order.append((sec, sector_bytes, cksum_ok, vol, trk))
            else:
                # No address field - tracks 6+ have no address markers
                # Assume sequential ordering
                data_order.append((di, sector_bytes, cksum_ok, 0, track_num))

        all_track_sectors[track_num] = data_order

        # Print sector ordering
        sec_nums = [s[0] for s in data_order]
        has_addr = any(s[3] != 0 for s in data_order)  # vol != 0 means we found an address
        if has_addr:
            print(f"Track {track_num:2d}: sectors = {sec_nums}")
            for sec, sdata, ckok, vol, trk in data_order:
                first8 = ' '.join(f'{b:02X}' for b in sdata[:8])
                print(f"  Sector {sec:2d} (V={vol:3d} T={trk:2d}): {first8}... cksum={'OK' if ckok else 'BAD'}")
        else:
            print(f"Track {track_num:2d}: {len(data_order)} sectors (no address fields, sequential order)")
            for i, (sec, sdata, ckok, vol, trk) in enumerate(data_order):
                first8 = ' '.join(f'{b:02X}' for b in sdata[:8])
                print(f"  Seq {i:2d}: {first8}... cksum={'OK' if ckok else 'BAD'}")

    # === Now try to build a properly ordered image ===
    print("\n" + "=" * 70)
    print("BUILDING ORDERED IMAGE")
    print("=" * 70)

    # For tracks with address fields (0-5), use sector number from address
    # For tracks without (6-13), use sequential order
    ordered_data = bytearray()

    for track_num in range(14):
        if track_num not in all_track_sectors:
            continue
        sectors = all_track_sectors[track_num]

        # Create ordered by sector number
        by_sector = {}
        for sec, sdata, ckok, vol, trk in sectors:
            if sec not in by_sector:
                by_sector[sec] = sdata

        # For tracks 0-5, output in sector order
        has_addr = any(s[3] != 0 for s in sectors)
        if has_addr:
            max_sec = max(by_sector.keys()) if by_sector else 12
            for s in range(max_sec + 1):
                if s in by_sector:
                    ordered_data.extend(by_sector[s])
                else:
                    ordered_data.extend(bytes(256))  # missing sector
        else:
            # Sequential order
            for sec, sdata, ckok, vol, trk in sectors:
                ordered_data.extend(sdata)

    # Save ordered image
    os.makedirs(str(OUTPUT_DIR), exist_ok=True)
    out_path = str(OUTPUT_DIR / "ApplePanic_original_ordered.bin")
    with open(out_path, 'wb') as f:
        f.write(ordered_data)
    print(f"\nOrdered image: {out_path} ({len(ordered_data)} bytes)")
    print(f"MD5: {hashlib.md5(ordered_data).hexdigest()}")

    # Search for game patterns in ordered data
    with open(str(APPLE_PANIC / "ApplePanic_runtime.bin"), 'rb') as f:
        cracked = f.read()

    print(f"\n=== Searching for game patterns in ordered data ===")
    patterns = {
        "JMP $7465": bytes([0x4C, 0x65, 0x74]),
        "Font 0E11": bytes([0x00, 0x0E, 0x11, 0x11, 0x11, 0x11, 0x0E, 0x00]),
        "LDA $C050": bytes([0xAD, 0x50, 0xC0]),
        "LDA $C057": bytes([0xAD, 0x57, 0xC0]),
    }
    for name, pat in patterns.items():
        for i in range(len(ordered_data) - len(pat)):
            if ordered_data[i:i+len(pat)] == pat:
                print(f"  Found {name} at offset ${i:04X}")

    # Try XOR $24 on the ordered data
    print(f"\n=== Trying XOR $24 on ordered data ===")
    xored_24 = bytes(b ^ 0x24 for b in ordered_data)
    for name, pat in patterns.items():
        for i in range(len(xored_24) - len(pat)):
            if xored_24[i:i+len(pat)] == pat:
                print(f"  Found {name} (XOR $24) at offset ${i:04X}")


if __name__ == '__main__':
    main()

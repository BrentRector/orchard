#!/usr/bin/env python3
"""
Decode copy-protected Apple Panic WOZ2 disk.
Custom format: 14 tracks, 13 sectors per track, non-standard address prologues.
"""
import struct
import hashlib

# 6-and-2 decode table
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
DECODE_62 = {}
for i, v in enumerate(ENCODE_62):
    DECODE_62[v] = i


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
        tracks[i] = {
            'bit_count': bits,
            'data': data[sb*512:sb*512 + bc*512],
        }
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


def find_all(nibbles, pattern):
    results = []
    for i in range(len(nibbles) - len(pattern) + 1):
        if all(nibbles[i+j] == pattern[j] for j in range(len(pattern))):
            results.append(i)
    return results


def decode_62_sector(nibbles, idx):
    """Decode 6-and-2 sector data at nibble index. Returns (256-byte data, next_idx) or (None, idx)."""
    if idx + 343 > len(nibbles):
        return (None, idx, False)

    # Read 342 encoded nibbles + 1 checksum
    encoded = []
    for i in range(342):
        nib = nibbles[idx + i]
        if nib not in DECODE_62:
            return (None, idx, False)
        encoded.append(DECODE_62[nib])
    cksum_nib = nibbles[idx + 342]
    if cksum_nib not in DECODE_62:
        return (None, idx, False)
    cksum_val = DECODE_62[cksum_nib]

    # XOR-decode
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

    return (bytes(result), idx + 343, cksum_ok)


def decode_44(b1, b2):
    return ((b1 << 1) | 0x01) & b2


def analyze_address_patterns(nibbles, data_positions):
    """Look at what precedes each D5 AA AD data prologue to find address markers."""
    for i, dpos in enumerate(data_positions[:3]):
        # Show 40 nibbles before data prologue
        start = max(0, dpos - 40)
        chunk = nibbles[start:dpos+3]
        hex_str = ' '.join(f'{n:02X}' for n in chunk)
        print(f"  Before data field {i}: ...{hex_str}")


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    tracks, tmap = read_woz2(woz_path)

    all_sectors = {}  # (track, sector) -> data

    for track_num in range(14):
        qt = track_num * 4
        tidx = tmap[qt]
        if tidx == 0xFF or tidx not in tracks:
            continue

        t = tracks[tidx]
        nibbles = to_nibbles(t['data'], t['bit_count'])
        # Double for wrap-around
        nib2 = nibbles + nibbles

        # Find all D5 AA AD data prologues
        data_positions = find_all(nib2[:len(nibbles)+500], [0xD5, 0xAA, 0xAD])

        print(f"\nTrack {track_num}: {len(data_positions)} data fields")

        # For track 0, also check standard address fields
        if track_num == 0:
            addr_positions = find_all(nib2[:len(nibbles)+500], [0xD5, 0xAA, 0x96])
            print(f"  Standard address fields: {len(addr_positions)}")
            for ap in addr_positions:
                idx = ap + 3
                vol = decode_44(nib2[idx], nib2[idx+1])
                trk = decode_44(nib2[idx+2], nib2[idx+3])
                sec = decode_44(nib2[idx+4], nib2[idx+5])
                print(f"  Addr: vol={vol} trk={trk} sec={sec}")

        # Try to find address info by looking at what's between sectors
        # Look for D5 xx B5 patterns (non-standard address prologues)
        alt_addr = []
        for i in range(len(nibbles)):
            if nib2[i] == 0xD5 and i + 2 < len(nib2):
                if nib2[i+2] == 0xB5 and nib2[i+1] != 0xAA:
                    alt_addr.append((i, nib2[i+1]))
        if alt_addr:
            print(f"  Alt address prologues (D5 xx B5): {len(alt_addr)}")
            for pos, mid in alt_addr[:3]:
                # Try to decode address info after the prologue
                idx = pos + 3
                if idx + 10 < len(nib2):
                    # Show bytes after prologue
                    post = nib2[idx:idx+12]
                    hex_str = ' '.join(f'{n:02X}' for n in post)
                    print(f"    D5 {mid:02X} B5 + {hex_str}")

        # Decode each data sector
        decoded_count = 0
        for sec_idx, dpos in enumerate(data_positions):
            sector_data, next_idx, cksum_ok = decode_62_sector(nib2, dpos + 3)
            if sector_data:
                all_sectors[(track_num, sec_idx)] = sector_data
                decoded_count += 1
                if sec_idx < 3:
                    first_16 = ' '.join(f'{b:02X}' for b in sector_data[:16])
                    print(f"  Sector {sec_idx}: {first_16}... cksum={'OK' if cksum_ok else 'BAD'}")
            else:
                if sec_idx < 3:
                    print(f"  Sector {sec_idx}: DECODE FAILED")

        print(f"  Decoded: {decoded_count}/{len(data_positions)}")

    # Summary
    total_bytes = len(all_sectors) * 256
    print(f"\n=== Summary ===")
    print(f"Total sectors decoded: {len(all_sectors)}")
    print(f"Total bytes: {total_bytes}")

    # Dump all decoded data sequentially
    if all_sectors:
        # Order by track, then sector
        raw_data = bytearray()
        for track_num in range(14):
            track_sectors = [(t, s) for (t, s) in all_sectors if t == track_num]
            track_sectors.sort(key=lambda x: x[1])
            for t, s in track_sectors:
                raw_data.extend(all_sectors[(t, s)])

        out_path = "E:/Apple/ApplePanic_original_raw.bin"
        with open(out_path, 'wb') as f:
            f.write(raw_data)
        print(f"Raw sequential dump: {out_path} ({len(raw_data)} bytes)")

        # Also save individual tracks for analysis
        for track_num in range(14):
            track_data = bytearray()
            track_sectors = sorted([(t, s) for (t, s) in all_sectors if t == track_num],
                                  key=lambda x: x[1])
            for t, s in track_sectors:
                track_data.extend(all_sectors[(t, s)])
            if track_data:
                print(f"  Track {track_num}: {len(track_data)} bytes, "
                      f"MD5={hashlib.md5(track_data).hexdigest()[:12]}")

        # Look for known signatures in the data
        print(f"\n=== Searching for game signatures ===")
        # Look for "APPLE PANIC" text or known game code patterns
        for i in range(len(raw_data) - 3):
            # JMP $7465 (the game entry point we know about)
            if raw_data[i:i+3] == bytes([0x4C, 0x65, 0x74]):
                print(f"  Found JMP $7465 at offset ${i:04X}")
            # "APPLE" in ASCII
            if raw_data[i:i+5] == b'APPLE':
                print(f"  Found 'APPLE' at offset ${i:04X}")
            # "PANIC" in ASCII
            if raw_data[i:i+5] == b'PANIC':
                print(f"  Found 'PANIC' at offset ${i:04X}")

        # Check for high-ASCII text
        for i in range(len(raw_data) - 5):
            text = bytes(b & 0x7F for b in raw_data[i:i+11])
            if text == b'APPLE PANIC':
                print(f"  Found 'APPLE PANIC' (high ASCII) at offset ${i:04X}")


if __name__ == '__main__':
    main()

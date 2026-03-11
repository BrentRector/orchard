#!/usr/bin/env python3
"""
Analyze raw nibble data from WOZ2 tracks to understand copy protection scheme.
"""
import struct

def read_woz2(path):
    with open(path, 'rb') as f:
        data = f.read()
    tmap = data[88:88+160]
    tracks = {}
    for i in range(160):
        offset = 256 + i * 8
        start_block = struct.unpack_from('<H', data, offset)[0]
        block_count = struct.unpack_from('<H', data, offset + 2)[0]
        bit_count = struct.unpack_from('<I', data, offset + 4)[0]
        if start_block == 0 and block_count == 0:
            continue
        byte_offset = start_block * 512
        byte_count = block_count * 512
        tracks[i] = {
            'bit_count': bit_count,
            'data': data[byte_offset:byte_offset + byte_count],
        }
    return tracks, tmap

def extract_bits(track_data, bit_count):
    bits = []
    for byte_idx in range(len(track_data)):
        for bit_idx in range(7, -1, -1):
            bits.append((track_data[byte_idx] >> bit_idx) & 1)
            if len(bits) >= bit_count:
                return bits
    return bits

def find_nibbles(bits):
    nibbles = []
    current = 0
    for b in bits:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles

def find_pattern(nibbles, pattern):
    """Find all occurrences of a byte pattern in nibble stream."""
    results = []
    for i in range(len(nibbles) - len(pattern)):
        match = True
        for j, p in enumerate(pattern):
            if p is not None and nibbles[i + j] != p:
                match = False
                break
        if match:
            results.append(i)
    return results

def decode_44(b1, b2):
    return ((b1 << 1) | 0x01) & b2

def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    tracks, tmap = read_woz2(woz_path)

    for track_idx in range(14):  # Only 14 tracks exist
        qt = track_idx * 4
        tidx = tmap[qt]
        if tidx == 0xFF or tidx not in tracks:
            continue

        t = tracks[tidx]
        bits = extract_bits(t['data'], t['bit_count'])
        nibbles = find_nibbles(bits)

        print(f"\n=== Track {track_idx} (index {tidx}) ===")
        print(f"  Bits: {t['bit_count']}, Nibbles: {len(nibbles)}")

        # Search for various prologue patterns
        patterns = {
            'D5 AA 96': [0xD5, 0xAA, 0x96],  # Standard address
            'D5 AA AD': [0xD5, 0xAA, 0xAD],  # Standard data
            'D5 AA B5': [0xD5, 0xAA, 0xB5],  # Alt data (some protections)
            'D4 AA 96': [0xD4, 0xAA, 0x96],  # Modified address
            'D5 AB 96': [0xD5, 0xAB, 0x96],  # Modified address
            'D5 AA 97': [0xD5, 0xAA, 0x97],  # Modified address
            'D5 AA':    [0xD5, 0xAA],         # Any D5 AA sequence
            'D5 only':  [0xD5],               # Any D5
        }

        for name, pat in patterns.items():
            matches = find_pattern(nibbles, pat)
            if matches and name not in ('D5 only',):
                print(f"  {name}: {len(matches)} matches at {matches[:10]}")
            elif name == 'D5 only' and len(matches) > 0:
                # Show what follows each D5
                d5_followers = {}
                for m in matches:
                    if m + 1 < len(nibbles):
                        follower = nibbles[m + 1]
                        d5_followers[follower] = d5_followers.get(follower, 0) + 1
                print(f"  D5 followers: {dict(sorted(d5_followers.items(), key=lambda x:-x[1]))}")

        # Show first 100 nibbles
        hex_str = ' '.join(f'{n:02X}' for n in nibbles[:100])
        print(f"  First 100 nibbles: {hex_str}")

        # If we find D5 AA 96 (standard address), decode address fields
        addr_matches = find_pattern(nibbles, [0xD5, 0xAA, 0x96])
        if addr_matches:
            for m in addr_matches[:16]:
                idx = m + 3
                if idx + 8 <= len(nibbles):
                    vol = decode_44(nibbles[idx], nibbles[idx+1])
                    trk = decode_44(nibbles[idx+2], nibbles[idx+3])
                    sec = decode_44(nibbles[idx+4], nibbles[idx+5])
                    cksum = decode_44(nibbles[idx+6], nibbles[idx+7])
                    ok = (vol ^ trk ^ sec ^ cksum) == 0
                    # Find what data prologue follows
                    data_prol = "?"
                    for di in range(idx+8, min(idx+80, len(nibbles)-3)):
                        if nibbles[di] == 0xD5:
                            data_prol = f"D5 {nibbles[di+1]:02X} {nibbles[di+2]:02X}"
                            break
                    print(f"  Addr: vol={vol:3d} trk={trk:2d} sec={sec:2d} cksum={'OK' if ok else 'BAD'} data={data_prol}")

        # Check for non-standard address markers
        # Look for any 3-byte sequence that repeats ~16 times (once per sector)
        if not addr_matches:
            # Dump more nibbles to spot patterns
            print(f"  First 300 nibbles:")
            for i in range(0, min(300, len(nibbles)), 50):
                chunk = nibbles[i:i+50]
                hex_str = ' '.join(f'{n:02X}' for n in chunk)
                print(f"    [{i:4d}] {hex_str}")

if __name__ == '__main__':
    main()

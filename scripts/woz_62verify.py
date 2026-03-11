#!/usr/bin/env python3
"""Verify the correct 6-and-2 decode by comparing with .dsk file."""
import struct

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


def read_woz_nibbles(woz_path, track_num):
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
    offset = 256 + tidx * 8
    sb = struct.unpack_from('<H', data, offset)[0]
    bc = struct.unpack_from('<H', data, offset + 2)[0]
    bits = struct.unpack_from('<I', data, offset + 4)[0]
    track_data = data[sb * 512:sb * 512 + bc * 512]
    bit_list = []
    for b in track_data:
        for i in range(7, -1, -1):
            bit_list.append((b >> i) & 1)
            if len(bit_list) >= bits:
                break
        if len(bit_list) >= bits:
            break
    nibbles = []
    current = 0
    for b in bit_list:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles


def decode_62_correct(encoded_342):
    """Correct 6-and-2 decode with reversed aux and group-of-3 bit packing."""
    # XOR chain
    decoded = [0] * 342
    prev = 0
    for k in range(342):
        decoded[k] = encoded_342[k] ^ prev
        prev = decoded[k]
    # Reconstruct: reversed aux, 3 groups with 2-bit shifting
    result = bytearray(256)
    for i in range(86):
        aux = decoded[85 - i]  # aux bytes are in reverse order
        for g in range(3):
            out_idx = i + g * 86
            if out_idx < 256:
                upper = decoded[86 + out_idx] << 2
                lower = (aux >> (g * 2)) & 0x03
                result[out_idx] = (upper | lower) & 0xFF
    return result


def main():
    # Read .dsk T0S0
    with open("E:/Apple/ApplePanic_original.dsk", 'rb') as f:
        dsk_data = f.read()
    dsk_t0s0 = dsk_data[0:256]

    # Read WOZ and decode
    nibbles = read_woz_nibbles("E:/Apple/Apple Panic - Disk 1, Side A.woz", 0)
    nib = nibbles + nibbles[:2000]

    for i in range(len(nibbles)):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0x96:
            for j in range(i + 11, i + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    didx = j + 3
                    encoded = [DECODE_62[nib[didx+k]] for k in range(343)]
                    woz_result = decode_62_correct(encoded[:342])

                    # Compare
                    match = sum(1 for k in range(256) if woz_result[k] == dsk_t0s0[k])
                    print(f"Match: {match}/256 bytes")

                    if match == 256:
                        print("PERFECT MATCH!")
                    else:
                        print("\nDifferences:")
                        for k in range(256):
                            if woz_result[k] != dsk_t0s0[k]:
                                print(f"  [{k:3d}] WOZ=${woz_result[k]:02X} DSK=${dsk_t0s0[k]:02X}")

                    # Show the decoded boot sector
                    print(f"\n=== Decoded boot sector (verified) ===")
                    for row in range(16):
                        off = row * 16
                        h = ' '.join(f'{woz_result[off+c]:02X}' for c in range(16))
                        a = ''.join(chr(woz_result[off+c]) if 32 <= woz_result[off+c] < 127 else '.'
                                    for c in range(16))
                        print(f"  ${0x0800+off:04X}: {h}  {a}")

                    return
            break


if __name__ == '__main__':
    main()

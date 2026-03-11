#!/usr/bin/env python3
"""Check ALL address fields on track 0 and decode their data fields."""
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

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def read_nibbles(woz_path, track_num):
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
    if tidx == 0xFF:
        return None
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


def decode_62_data(nibbles, idx):
    """Decode 6-and-2 data field (342 + 1 checksum nibbles)."""
    encoded = []
    for k in range(343):
        n = nibbles[idx + k]
        if n not in DECODE_62:
            return None
        encoded.append(DECODE_62[n])
    # XOR chain
    decoded = [0] * 342
    prev = 0
    for k in range(342):
        decoded[k] = encoded[k] ^ prev
        prev = decoded[k]
    cksum_ok = (prev == encoded[342])
    # Reconstruct 256 bytes
    result = bytearray(256)
    for k in range(256):
        upper = decoded[86 + k] << 2
        aux_idx = 85 - (k % 86)
        shift = (k // 86) * 2
        lower = (decoded[aux_idx] >> shift) & 0x03
        result[k] = (upper | lower) & 0xFF
    return bytes(result), cksum_ok


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    nibbles = read_nibbles(woz_path, 0)
    nib2 = nibbles + nibbles[:2000]

    print("=== ALL address fields on Track 0 ===\n")

    # Find ALL D5 xx xx prologues
    addr_fields = []
    i = 0
    while i < len(nibbles):
        if nib2[i] == 0xD5:
            b1 = nib2[i + 1]
            b2 = nib2[i + 2]

            if b1 == 0xAA and b2 == 0x96:
                # 16-sector address: D5 AA 96
                idx = i + 3
                vol = ((nib2[idx] << 1) | 1) & nib2[idx + 1]
                trk = ((nib2[idx + 2] << 1) | 1) & nib2[idx + 3]
                sec = ((nib2[idx + 4] << 1) | 1) & nib2[idx + 5]
                ck = ((nib2[idx + 6] << 1) | 1) & nib2[idx + 7]
                addr_fields.append(('D5AA96', i, vol, trk, sec, ck))
                i = idx + 8

            elif b2 == 0xB5:
                # 13-sector address: D5 xx B5
                idx = i + 3
                vol = ((nib2[idx] << 1) | 1) & nib2[idx + 1]
                trk = ((nib2[idx + 2] << 1) | 1) & nib2[idx + 3]
                sec = ((nib2[idx + 4] << 1) | 1) & nib2[idx + 5]
                ck = ((nib2[idx + 6] << 1) | 1) & nib2[idx + 7]
                addr_fields.append((f'D5{b1:02X}B5', i, vol, trk, sec, ck))
                i = idx + 8
            else:
                i += 1
        else:
            i += 1

    for atype, pos, vol, trk, sec, ck in addr_fields:
        print(f"  @{pos:5d}: {atype} vol={vol:3d} trk={trk} sec={sec:2d} ck={ck:02X}")

    # Now decode D5 AA 96 sectors with 6-and-2
    print("\n=== D5 AA 96 sectors (6-and-2 decode) ===\n")
    for atype, pos, vol, trk, sec, ck in addr_fields:
        if atype != 'D5AA96':
            continue
        # Find D5 AA AD data prologue
        idx = pos + 11  # skip address field
        for j in range(idx, idx + 100):
            if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                didx = j + 3
                result = decode_62_data(nib2, didx)
                if result:
                    data, ck_ok = result
                    first32 = ' '.join(f'{b:02X}' for b in data[:32])
                    print(f"  Sector {sec}: cksum={'OK' if ck_ok else 'BAD'}")
                    print(f"    {first32}")
                    # Disassemble from $0801 equivalent
                    print(f"    byte0=${data[0]:02X} ({data[0]})")
                    # Show as code from byte 1
                    print(f"    Code at byte 1: ", end='')
                    for b in range(1, min(16, len(data))):
                        print(f'{data[b]:02X} ', end='')
                    print()
                else:
                    # Check how many valid 6-and-2 nibbles
                    valid62 = sum(1 for k in range(343) if nib2[didx + k] in DECODE_62)
                    valid53 = sum(1 for k in range(411) if nib2[didx + k] in DECODE_53)
                    print(f"  Sector {sec}: decode FAILED (valid62={valid62}, valid53={valid53})")
                break
        else:
            print(f"  Sector {sec}: no data field found")

    # Count sectors by type
    types_96 = [f for f in addr_fields if f[0] == 'D5AA96']
    types_b5 = [f for f in addr_fields if 'B5' in f[0]]
    print(f"\nSummary: {len(types_96)} D5AA96 sectors, {len(types_b5)} D5xxB5 sectors")

    # For the D5 AA 96 S0, show full hex dump
    for atype, pos, vol, trk, sec, ck in addr_fields:
        if atype == 'D5AA96' and sec == 0:
            idx = pos + 11
            for j in range(idx, idx + 100):
                if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                    didx = j + 3
                    result = decode_62_data(nib2, didx)
                    if result:
                        data, _ = result
                        print(f"\n=== Full hex dump of D5 AA 96 S0 ===")
                        for row in range(16):
                            off = row * 16
                            hexvals = ' '.join(f'{data[off + c]:02X}' for c in range(16))
                            print(f"  ${0x0800 + off:04X}: {hexvals}")
                    break


if __name__ == '__main__':
    main()

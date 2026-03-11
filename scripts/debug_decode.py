#!/usr/bin/env python3
"""Debug the 5-and-3 sector decode by checking intermediate values."""
import struct, sys
sys.path.insert(0, 'E:/Apple')


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


def build_53_gcr_table():
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


def decode_44(b1, b2):
    return ((b1 << 1) | 1) & b2


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    nibbles = read_woz_nibbles(woz_path, 0)
    nib = nibbles + nibbles[:5000]

    orig_table = build_53_gcr_table()

    # Corrupt table: ASL x3 on positions $99-$FF (as stage 2 does)
    corr_table = list(orig_table)
    for i in range(0x99, 0x100):
        corr_table[i] = (corr_table[i] << 3) & 0xFF

    print("=== GCR table valid entries (corrupted) ===")
    for y in range(0xAB, 0x100):
        if orig_table[y] != 0 or y == 0xAB:  # include AB which maps to 0
            print(f"  ${y:02X}: orig={orig_table[y]:02X}  corr={corr_table[y]:02X}")

    # Find sector 0
    for i in range(len(nibbles)):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib[idx+4], nib[idx+5])
            if sec != 0:
                continue
            for j in range(idx + 8, idx + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    data_idx = j + 3
                    print(f"\nSector 0 data at nibble offset {data_idx}")

                    # --- Read with ORIGINAL table (as boot RWTS does) ---
                    mem_orig = list(orig_table)
                    a = 0
                    ni = data_idx

                    # Phase 1: 154 secondary
                    y_counter = 0x9A
                    while y_counter > 0:
                        d = nib[ni]; ni += 1
                        a ^= mem_orig[d]
                        y_counter -= 1
                        mem_orig[y_counter] = a

                    # Phase 2: 256 primary
                    pri_orig = [0] * 256
                    for k in range(256):
                        d = nib[ni]; ni += 1
                        a ^= mem_orig[d]
                        pri_orig[k] = a

                    # Checksum
                    d = nib[ni]; ni += 1
                    a ^= mem_orig[d]
                    print(f"Original table checksum: ${a:02X} ({'PASS' if a == 0 else 'FAIL'})")

                    # Check if secondary values have bits 2-0 = 0
                    sec_orig = mem_orig[:154]
                    low_bits = [s & 0x07 for s in sec_orig]
                    print(f"Secondary low 3 bits (orig): nonzero count = {sum(1 for b in low_bits if b != 0)}")
                    print(f"Primary low 3 bits (orig): nonzero count = {sum(1 for b in pri_orig if b & 0x07 != 0)}")

                    # --- Read with CORRUPTED table (as stage 2 does) ---
                    mem_corr = list(corr_table)
                    a = 0
                    ni = data_idx

                    y_counter = 0x9A
                    while y_counter > 0:
                        d = nib[ni]; ni += 1
                        a ^= mem_corr[d]
                        y_counter -= 1
                        mem_corr[y_counter] = a

                    pri_corr = [0] * 256
                    for k in range(256):
                        d = nib[ni]; ni += 1
                        a ^= mem_corr[d]
                        pri_corr[k] = a

                    d = nib[ni]; ni += 1
                    a ^= mem_corr[d]
                    print(f"Corrupted table checksum: ${a:02X} ({'PASS' if a == 0 else 'FAIL'})")

                    sec_corr = mem_corr[:154]
                    low_bits_c = [s & 0x07 for s in sec_corr]
                    print(f"Secondary low 3 bits (corr): nonzero count = {sum(1 for b in low_bits_c if b != 0)}")
                    print(f"Primary low 3 bits (corr): nonzero count = {sum(1 for b in pri_corr if b & 0x07 != 0)}")

                    # Show first 10 secondary values with both tables
                    print("\n=== First 20 secondary values ===")
                    for k in range(20):
                        print(f"  sec[{k:3d}]: orig=${sec_orig[k]:02X}  corr=${sec_corr[k]:02X}")

                    print("\n=== First 20 primary values ===")
                    for k in range(20):
                        print(f"  pri[{k:3d}]: orig=${pri_orig[k]:02X}  corr=${pri_corr[k]:02X}")

                    # Now apply the $02D1 post-decode to the ORIGINAL data
                    # to verify it produces the known stage 2 code
                    mem_0300 = list(pri_orig)  # primary was stored at ($26) = $0300
                    mem_0800 = list(sec_orig) + [0] * (256 - len(sec_orig))
                    y = 0
                    for group in range(3):
                        for x in range(0x33):
                            sv = mem_0800[y]
                            c1 = sv & 1; sv >>= 1
                            cc = 0xCC + x
                            if cc < 256:
                                mem_0300[cc] = ((mem_0300[cc] << 1) | c1) & 0xFF
                            c2 = sv & 1; sv >>= 1
                            n9 = 0x99 + x
                            if n9 < 256:
                                mem_0300[n9] = ((mem_0300[n9] << 1) | c2) & 0xFF
                            pv = mem_0300[y]
                            pv = (pv << 3) & 0xFF
                            pv |= sv
                            mem_0300[y] = pv
                            y += 1

                    print("\n=== $02D1 post-decode result (first 16 bytes) ===")
                    h = ' '.join(f'{mem_0300[k]:02X}' for k in range(16))
                    print(f"  $0300: {h}")
                    print(f"  Expected: 99 B9 00 08 0A 0A 0A 99 00 08 C8 D0 F4 A6 2B A9")

                    # Now apply $0346 post-decode to CORRUPTED data
                    # Secondary at $0800[0..153], Primary at $0900[0..255]
                    # Output to ($40) = $B600
                    output = [0] * 256
                    oy = 0
                    for x in range(0x32, -1, -1):
                        a = sec_corr[x]
                        a >>= 1; a >>= 1; a >>= 1
                        zp3c = a
                        a >>= 1
                        zp2a = a
                        a >>= 1
                        output[oy] = a | pri_corr[x]; oy += 1

                        a = sec_corr[x + 0x33]
                        a >>= 1; a >>= 1; a >>= 1
                        carry = a & 1; a >>= 1
                        zp3c = ((zp3c << 1) | carry) & 0xFF
                        carry = a & 1; a >>= 1
                        zp2a = ((zp2a << 1) | carry) & 0xFF
                        output[oy] = a | pri_corr[x + 0x33]; oy += 1

                        a = sec_corr[x + 0x66]
                        a >>= 1; a >>= 1; a >>= 1
                        carry = a & 1; a >>= 1
                        zp3c = ((zp3c << 1) | carry) & 0xFF
                        carry = a & 1; a >>= 1
                        zp2a = ((zp2a << 1) | carry) & 0xFF
                        output[oy] = a | pri_corr[x + 0x66]; oy += 1

                        output[oy] = (zp2a & 0x07) | pri_corr[x + 0x99]; oy += 1
                        output[oy] = (zp3c & 0x07) | pri_corr[x + 0xCC]; oy += 1

                    a = sec_corr[0x99]
                    a >>= 1; a >>= 1; a >>= 1
                    output[oy] = a | pri_corr[0xFF]

                    print("\n=== $0346 post-decode result (first 32 bytes) ===")
                    for row in range(2):
                        off = row * 16
                        h = ' '.join(f'{output[off+c]:02X}' for c in range(16))
                        print(f"  ${0xB600+off:04X}: {h}")

                    return
            break

    print("Sector 0 not found!")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Check if sector 1's data spans the track wrap boundary and if
proper bit-level wrapping fixes the checksum."""
import struct, sys
sys.path.insert(0, 'E:/Apple')
from disasm_rwts import OPCODES

def main():
    with open('E:/Apple/Apple Panic - Disk 1, Side A.woz', 'rb') as f:
        data = f.read()
    tmap = data[88:88+160]
    tidx = tmap[0]
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

    print(f"Track 0: {len(bit_list)} bits")

    # Double the bit stream for proper wrap handling
    double_bits = bit_list + bit_list

    # Convert to nibbles
    nibbles = []
    current = 0
    for b in double_bits:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0

    print(f"Doubled stream: {len(nibbles)} nibbles")

    # Find where the wrap occurs in nibble indices
    current = 0
    single_rev_nibbles = 0
    for i, b in enumerate(bit_list):
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            single_rev_nibbles += 1
            current = 0
    remaining_bits = 0
    c = 0
    for b in bit_list:
        c = ((c << 1) | b) & 0xFF
        if c & 0x80:
            remaining_bits = 0
            c = 0
        else:
            remaining_bits += 1
    print(f"Single revolution: {single_rev_nibbles} nibbles, {remaining_bits} leftover bits at wrap")

    # Build GCR tables
    def build_table():
        t = [0] * 256
        x = 0
        for y in range(0xAB, 0x100):
            a = y; z = a; a = (a >> 1) & 0x7F; a = a | z
            if a != 0xFF: continue
            if y == 0xD5: continue
            t[y] = x; x += 1
        return t

    def decode_44(b1, b2):
        return ((b1 << 1) | 1) & b2

    orig_table = build_table()
    corr_table = list(orig_table)
    for i in range(0x99, 0x100):
        corr_table[i] = (corr_table[i] << 3) & 0xFF

    nib = nibbles

    # Find ALL sector 1 occurrences
    print("\n=== Finding all sector 1 occurrences ===")
    sec1_finds = []
    i = 0
    while i < len(nib) - 500:
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib[idx+4], nib[idx+5])
            if sec == 1:
                for j in range(idx + 8, idx + 200):
                    if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                        didx = j + 3
                        which = "1st rev" if i < single_rev_nibbles else "2nd rev (after wrap)"
                        print(f"  Sector 1 at nib[{i}], data at nib[{didx}] [{which}]")
                        sec1_finds.append((i, didx, which))

                        # Check checksums
                        for tname, table in [("orig", orig_table), ("corr", corr_table)]:
                            mem = list(table)
                            a = 0
                            ni = didx
                            y = 0x9A
                            while y > 0:
                                d = nib[ni]; ni += 1
                                a ^= mem[d]
                                y -= 1
                                mem[y] = a
                            pri = [0] * 256
                            for k in range(256):
                                d = nib[ni]; ni += 1
                                a ^= mem[d]
                                pri[k] = a
                            d = nib[ni]; ni += 1
                            a ^= mem[d]
                            status = "PASS" if a == 0 else f"FAIL(${a:02X})"
                            print(f"    {tname} checksum: {status}")

                        break
                i = idx + 8
            else:
                i = idx + 8
        else:
            i += 1

    # Decode the first occurrence (with proper bit-wrap now!)
    if len(sec1_finds) >= 1:
        print("\n=== Decoding sector 1 with proper bit-wrap ===")
        _, didx, _ = sec1_finds[0]

        mem = list(orig_table)
        a = 0
        ni = didx
        y = 0x9A
        while y > 0:
            d = nib[ni]; ni += 1
            a ^= mem[d]
            y -= 1
            mem[y] = a
        sec_data = mem[:154]
        pri = [0] * 256
        for k in range(256):
            d = nib[ni]; ni += 1
            a ^= mem[d]
            pri[k] = a
        d = nib[ni]; ni += 1
        a ^= mem[d]
        ck_ok = (a == 0)
        print(f"  Checksum: {'PASS' if ck_ok else f'FAIL(${a:02X})'}")

        # Apply 02D1 decode
        output = list(pri)
        iy = 0
        for g in range(3):
            for x in range(0x33):
                sv = sec_data[iy]
                c1 = sv & 1; sv >>= 1
                cc = 0xCC + x
                if cc < 256:
                    output[cc] = ((output[cc] << 1) | c1) & 0xFF
                c2 = sv & 1; sv >>= 1
                n9 = 0x99 + x
                if n9 < 256:
                    output[n9] = ((output[n9] << 1) | c2) & 0xFF
                pv = output[iy]
                pv = (pv << 3) & 0xFF
                pv |= sv
                output[iy] = pv
                iy += 1

        # Apply permutation
        perm = [0] * 256
        for k in range(51):
            perm[5*k+0] = output[50-k]
            perm[5*k+1] = output[101-k]
            perm[5*k+2] = output[152-k]
            perm[5*k+3] = output[203-k]
            perm[5*k+4] = output[254-k]
        perm[255] = ((sec_data[153] >> 2) | (output[255] << 3)) & 0xFF

        print(f"  First 32 bytes:")
        print(f"  {' '.join(f'{perm[j]:02X}' for j in range(16))}")
        print(f"  {' '.join(f'{perm[j]:02X}' for j in range(16, 32))}")

        score = sum(1 for b in perm[:48] if b in OPCODES)
        print(f"  Code-like score: {score}/48")

        # Compare with naive (non-wrapped) decode
        # Build naive nibbles (original method)
        naive_nibs = []
        nc = 0
        for b in bit_list:
            nc = ((nc << 1) | b) & 0xFF
            if nc & 0x80:
                naive_nibs.append(nc)
                nc = 0
        naive_nib = naive_nibs + naive_nibs[:5000]
        # Find sector 1 in naive
        didx1 = None
        for ii in range(len(naive_nibs)):
            if naive_nib[ii] == 0xD5 and naive_nib[ii+1] == 0xAA and naive_nib[ii+2] == 0xB5:
                iidx = ii + 3
                ssec = decode_44(naive_nib[iidx+4], naive_nib[iidx+5])
                if ssec != 1:
                    continue
                for jj in range(iidx + 8, iidx + 200):
                    if naive_nib[jj] == 0xD5 and naive_nib[jj+1] == 0xAA and naive_nib[jj+2] == 0xAD:
                        didx1 = jj + 3
                        break
                break
        mem1 = list(orig_table)
        a1 = 0
        ni1 = didx1
        nib_src = naive_nib  # use naive nibbles for comparison
        y1 = 0x9A
        while y1 > 0:
            d1 = nib_src[ni1]; ni1 += 1
            a1 ^= mem1[d1]
            y1 -= 1
            mem1[y1] = a1
        sec1_data = mem1[:154]
        pri1 = [0] * 256
        for k in range(256):
            d1 = nib_src[ni1]; ni1 += 1
            a1 ^= mem1[d1]
            pri1[k] = a1

        output1 = list(pri1)
        iy = 0
        for g in range(3):
            for x in range(0x33):
                sv = sec1_data[iy]
                c1 = sv & 1; sv >>= 1
                cc = 0xCC + x
                if cc < 256:
                    output1[cc] = ((output1[cc] << 1) | c1) & 0xFF
                c2 = sv & 1; sv >>= 1
                n9 = 0x99 + x
                if n9 < 256:
                    output1[n9] = ((output1[n9] << 1) | c2) & 0xFF
                pv = output1[iy]
                pv = (pv << 3) & 0xFF
                pv |= sv
                output1[iy] = pv
                iy += 1

        perm1 = [0] * 256
        for k in range(51):
            perm1[5*k+0] = output1[50-k]
            perm1[5*k+1] = output1[101-k]
            perm1[5*k+2] = output1[152-k]
            perm1[5*k+3] = output1[203-k]
            perm1[5*k+4] = output1[254-k]
        perm1[255] = ((sec1_data[153] >> 2) | (output1[255] << 3)) & 0xFF

        diffs = sum(1 for a, b in zip(perm, perm1) if a != b)
        print(f"\n  Differences between 1st and 2nd revolution decode: {diffs}/256")
        if diffs > 0:
            print(f"  First 16 bytes from 1st rev:")
            print(f"  {' '.join(f'{perm1[j]:02X}' for j in range(16))}")
            print(f"  *** WRAP BOUNDARY IS CAUSING DIFFERENT DECODE! ***")

            # Save the 2nd rev decode
            with open("E:/Apple/decoded_sectors/track00_sec01_wrap_fixed.bin", "wb") as f:
                f.write(bytes(perm))
            print(f"  Saved wrap-fixed sector 1 to decoded_sectors/track00_sec01_wrap_fixed.bin")

if __name__ == "__main__":
    main()

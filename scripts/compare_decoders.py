#!/usr/bin/env python3
"""
Compare the $02D1 (boot) and $0346 (stage 2) post-decode routines for sector 2.

The boot code has two different post-decode routines that should produce the
same 256 byte values but in different memory order. This script verifies that
applying the $02D1 decode followed by a permutation produces the same result
as the direct $0346 decode. Also validates that the corrupted GCR table values
are exactly the original values shifted left by 3 (ASL x3).

This is a diagnostic script used to derive the correct permutation mapping
between the two decode routines.

Usage:
    python compare_decoders.py

    Paths default to repo-relative locations (apple-panic/).

Expected output:
    Verification that sec_c == sec_o<<3 and pri_c == pri_o<<3, the first 16
    bytes from each decode method, and a count/list of any differences between
    the permuted $02D1 output and the direct $0346 output.
"""
import struct
from pathlib import Path

def read_woz_nibbles(woz_path, track_num):
    """Read a WOZ2 disk image and extract the nibble stream for a given track."""
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88+160]
    tidx = tmap[track_num*4]
    offset = 256+tidx*8
    sb = struct.unpack_from('<H', data, offset)[0]
    bc = struct.unpack_from('<H', data, offset+2)[0]
    bits = struct.unpack_from('<I', data, offset+4)[0]
    track_data = data[sb*512:sb*512+bc*512]
    bit_list = []
    for b in track_data:
        for i in range(7,-1,-1):
            bit_list.append((b>>i)&1)
            if len(bit_list) >= bits: break
        if len(bit_list) >= bits: break
    nibbles = []
    current = 0
    for b in bit_list:
        current = ((current<<1)|b)&0xFF
        if current&0x80:
            nibbles.append(current)
            current = 0
    return nibbles

def build_table():
    """Build the 5-and-3 GCR decode table exactly as the boot code does."""
    t = [0]*256
    x = 0
    for y in range(0xAB, 0x100):
        a = y; z = a; a = (a>>1)&0x7F; a = a|z
        if a != 0xFF: continue
        if y == 0xD5: continue
        t[y] = x; x += 1
    return t

def decode_44(b1, b2):
    """Decode a 4-and-4 encoded byte pair from the address field."""
    return ((b1<<1)|1)&b2

def rwts_read(nibbles, data_idx, table):
    """Simulate RWTS read: 154 secondary + 256 primary nibbles with XOR chain.

    Returns (secondary[0:154], primary[0:256], checksum_ok).
    """
    mem = list(table); a = 0; ni = data_idx
    y = 0x9A
    while y > 0:
        d = nibbles[ni]; ni += 1; a ^= mem[d]; y -= 1; mem[y] = a
    pri = [0]*256
    for k in range(256):
        d = nibbles[ni]; ni += 1; a ^= mem[d]; pri[k] = a
    d = nibbles[ni]; ni += 1; a ^= mem[d]
    return mem[:154], pri, (a == 0)

def main():
    """Compare $02D1+permutation vs $0346 direct decode for sector 2."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    nib = read_woz_nibbles(str(APPLE_PANIC / 'Apple Panic - Disk 1, Side A.woz'), 0)
    nib = nib + nib[:5000]
    orig = build_table()
    corr = list(orig)
    for i in range(0x99, 0x100):
        corr[i] = (corr[i]<<3)&0xFF

    # Find sector 2
    for i in range(len(nib)-500):
        if nib[i]==0xD5 and nib[i+1]==0xAA and nib[i+2]==0xB5:
            idx = i+3
            sec = decode_44(nib[idx+4], nib[idx+5])
            if sec != 2: continue
            for j in range(idx+8, idx+200):
                if nib[j]==0xD5 and nib[j+1]==0xAA and nib[j+2]==0xAD:
                    didx = j+3
                    sec_o, pri_o, ck_o = rwts_read(nib, didx, orig)
                    sec_c, pri_c, ck_c = rwts_read(nib, didx, corr)

                    # Verify relationship
                    for k in range(154):
                        assert sec_c[k] == (sec_o[k]<<3)&0xFF, f"sec mismatch at {k}"
                    for k in range(256):
                        assert pri_c[k] == (pri_o[k]<<3)&0xFF, f"pri mismatch at {k}"
                    print("sec_c == sec_o<<3 and pri_c == pri_o<<3: VERIFIED")

                    # Run $02D1
                    output_d1 = list(pri_o)
                    y = 0
                    for g in range(3):
                        for x in range(0x33):
                            sv = sec_o[y]
                            c1 = sv&1; sv >>= 1
                            cc = 0xCC+x
                            if cc < 256:
                                output_d1[cc] = ((output_d1[cc]<<1)|c1)&0xFF
                            c2 = sv&1; sv >>= 1
                            n9 = 0x99+x
                            if n9 < 256:
                                output_d1[n9] = ((output_d1[n9]<<1)|c2)&0xFF
                            pv = output_d1[y]
                            pv = (pv<<3)&0xFF
                            pv |= sv
                            output_d1[y] = pv
                            y += 1

                    # Apply permutation
                    perm = [0]*256
                    for k in range(51):
                        perm[5*k+0] = output_d1[50-k]
                        perm[5*k+1] = output_d1[101-k]
                        perm[5*k+2] = output_d1[152-k]
                        perm[5*k+3] = output_d1[203-k]
                        perm[5*k+4] = output_d1[254-k]
                    perm[255] = output_d1[255]

                    # Run $0346 directly
                    d46 = [0]*256
                    oy = 0
                    for x in range(0x32, -1, -1):
                        a = sec_c[x]
                        a >>= 1; a >>= 1; a >>= 1
                        zp3c = a; a >>= 1; zp2a = a; a >>= 1
                        d46[oy] = a|pri_c[x]; oy += 1

                        a = sec_c[x+0x33]
                        a >>= 1; a >>= 1; a >>= 1
                        carry = a&1; a >>= 1
                        zp3c = ((zp3c<<1)|carry)&0xFF
                        carry = a&1; a >>= 1
                        zp2a = ((zp2a<<1)|carry)&0xFF
                        d46[oy] = a|pri_c[x+0x33]; oy += 1

                        a = sec_c[x+0x66]
                        a >>= 1; a >>= 1; a >>= 1
                        carry = a&1; a >>= 1
                        zp3c = ((zp3c<<1)|carry)&0xFF
                        carry = a&1; a >>= 1
                        zp2a = ((zp2a<<1)|carry)&0xFF
                        d46[oy] = a|pri_c[x+0x66]; oy += 1

                        d46[oy] = (zp2a&0x07)|pri_c[x+0x99]; oy += 1
                        d46[oy] = (zp3c&0x07)|pri_c[x+0xCC]; oy += 1

                    a = sec_c[0x99]; a >>= 1; a >>= 1; a >>= 1
                    d46[255] = a|pri_c[0xFF]

                    # Compare
                    print(f"Perm first 16: {' '.join(f'{perm[i]:02X}' for i in range(16))}")
                    print(f"D46  first 16: {' '.join(f'{d46[i]:02X}' for i in range(16))}")

                    diffs = [(i, perm[i], d46[i]) for i in range(256) if perm[i] != d46[i]]
                    print(f"Differences: {len(diffs)}")
                    for i, p, d in diffs[:10]:
                        print(f"  [{i:3d}]: perm=${p:02X}  direct=${d:02X}")

                    # Check: what ARE the correct values?
                    # For byte 1: perm uses output_d1[101], direct uses (sec_c[101]>>5)|pri_c[101]
                    print(f"\nByte 1 detail:")
                    print(f"  sec_o[101]=${sec_o[101]:02X}  pri_o[101]=${pri_o[101]:02X}")
                    print(f"  02D1 formula: (pri<<3|sec>>2) = ${((pri_o[101]<<3)|(sec_o[101]>>2))&0xFF:02X}")
                    print(f"  output_d1[101] = ${output_d1[101]:02X}")
                    print(f"  0346 formula: (sec_c>>5|pri_c) = ${((sec_c[101]>>5)|pri_c[101])&0xFF:02X}")
                    return
            break

if __name__ == '__main__':
    main()

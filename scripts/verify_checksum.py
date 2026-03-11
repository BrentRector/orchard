#!/usr/bin/env python3
"""
Verify 5-and-3 sector checksums with both original and corrupted GCR tables.
Determines if checksum failures are copy protection or an emulator bug.
"""
import struct

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]

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
    """Build the 5-and-3 GCR decode table exactly as the boot code does at $020F."""
    table = [0] * 256  # $0800-$08FF
    x = 0  # decoded value counter
    for y in range(0xAB, 0x100):  # Y starts at $AB
        # TYA; STA $3C; LSR; ORA $3C
        a = y
        zp3c = a
        a = (a >> 1) & 0x7F  # LSR
        carry = y & 1
        a = a | zp3c  # ORA $3C

        if a != 0xFF:
            continue  # skip invalid nibbles
        if y == 0xD5:
            continue  # skip D5 (prolog marker)

        table[y] = x
        x += 1

    return table


def decode_44(b1, b2):
    return ((b1 << 1) | 1) & b2


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    nibbles = read_woz_nibbles(woz_path, 0)
    nib = nibbles + nibbles[:5000]  # extend for wrap-around

    # Build original GCR table
    table = build_53_gcr_table()

    # Build corrupted table (ASL x3, simulating $0301 loop)
    table_corrupted = list(table)
    for i in range(0x99, 0x100):  # $0301 loop: Y=$99 to $FF
        table_corrupted[i] = (table_corrupted[i] << 3) & 0xFF

    print("=== GCR Table Comparison (valid entries only) ===")
    for nv in ENCODE_53:
        orig = table[nv]
        corr = table_corrupted[nv]
        expected = (orig << 3) & 0xFF
        match = "OK" if corr == expected else "MISMATCH"
        print(f"  ${nv:02X}: orig=${orig:02X}  corrupted=${corr:02X}  expected(<<3)=${expected:02X}  {match}")

    # Find all D5 AA B5 address fields and their data fields
    print("\n=== Sector checksums with original and corrupted tables ===")

    sectors_found = {}
    i = 0
    while i < len(nibbles):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            vol = decode_44(nib[idx], nib[idx+1])
            trk = decode_44(nib[idx+2], nib[idx+3])
            sec = decode_44(nib[idx+4], nib[idx+5])

            # Find D5 AA AD data field
            search = idx + 8
            for j in range(search, search + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    didx = j + 3

                    # Read 154 secondary + 256 primary + 1 checksum = 411 nibbles
                    raw_nibs = nib[didx:didx + 411]

                    # Test with ORIGINAL table
                    xor_acc_orig = 0
                    for k in range(410):
                        xor_acc_orig ^= table[raw_nibs[k]]
                    cksum_orig = xor_acc_orig ^ table[raw_nibs[410]]

                    # Test with CORRUPTED table
                    xor_acc_corr = 0
                    for k in range(410):
                        xor_acc_corr ^= table_corrupted[raw_nibs[k]]
                    cksum_corr = xor_acc_corr ^ table_corrupted[raw_nibs[410]]

                    sectors_found[sec] = (cksum_orig, cksum_corr)

                    status_o = "PASS" if cksum_orig == 0 else f"FAIL(${cksum_orig:02X})"
                    status_c = "PASS" if cksum_corr == 0 else f"FAIL(${cksum_corr:02X})"
                    print(f"  S{sec:2d}: orig={status_o:12s} corrupted={status_c:12s}  "
                          f"first3nibs: ${raw_nibs[0]:02X} ${raw_nibs[1]:02X} ${raw_nibs[2]:02X}")
                    break
            i = j + 412 if 'j' in dir() else i + 1
        else:
            i += 1

    # Now simulate the EXACT boot code algorithm:
    # Phase 1: Read 154 secondary nibbles into $0800 (reversed), with XOR chain
    # Phase 2: Read 256 primary nibbles into $0900, with XOR chain continuing
    # Phase 3: Checksum nibble
    print("\n=== Boot code exact simulation ===")

    i = 0
    while i < len(nibbles):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib[idx+4], nib[idx+5])

            # Find data field
            search = idx + 8
            for j in range(search, search + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    didx = j + 3

                    # Simulate boot code data read with ORIGINAL table
                    mem = list(table)  # $0800 area = GCR table
                    a = 0  # A register starts at 0 (from EOR #$AD match)
                    nib_idx = didx

                    # Phase 1: Read 154 secondary nibbles
                    # $02A1: LDY #$9A (154)
                    y_counter = 0x9A  # 154
                    while y_counter > 0:
                        disk_nib = nib[nib_idx]; nib_idx += 1
                        a ^= mem[disk_nib]  # EOR $0800,Y (Y=nibble value)
                        y_counter -= 1
                        mem[y_counter] = a  # STA $0800,Y (Y=counter, reversed)

                    # Phase 2: Read 256 primary nibbles
                    pri_buf = [0] * 256
                    for k in range(256):
                        disk_nib = nib[nib_idx]; nib_idx += 1
                        a ^= mem[disk_nib]  # EOR $0800,Y (Y=nibble value)
                        pri_buf[k] = a  # STA ($26),Y

                    # Phase 3: Checksum
                    disk_nib = nib[nib_idx]; nib_idx += 1
                    a ^= mem[disk_nib]

                    status = "PASS" if a == 0 else f"FAIL(${a:02X})"
                    print(f"  S{sec:2d} (orig table): cksum={status}")

                    # Now with CORRUPTED table
                    mem_c = list(table_corrupted)
                    a = 0
                    nib_idx = didx

                    y_counter = 0x9A
                    while y_counter > 0:
                        disk_nib = nib[nib_idx]; nib_idx += 1
                        a ^= mem_c[disk_nib]
                        y_counter -= 1
                        mem_c[y_counter] = a  # This overwrites $0800-$0899

                    for k in range(256):
                        disk_nib = nib[nib_idx]; nib_idx += 1
                        a ^= mem_c[disk_nib]  # Uses table at $08AB+

                    disk_nib = nib[nib_idx]; nib_idx += 1
                    a ^= mem_c[disk_nib]

                    status = "PASS" if a == 0 else f"FAIL(${a:02X})"
                    print(f"  S{sec:2d} (corr table): cksum={status}")

                    break
            i = j + 412 if 'j' in dir() else i + 1
        else:
            i += 1


if __name__ == '__main__':
    main()

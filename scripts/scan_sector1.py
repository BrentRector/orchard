#!/usr/bin/env python3
"""
Scan Track 0 for ALL occurrences of sector 1 (and sector 11) address/data fields.

Checks whether there are multiple copies of the same sector on the track
(which can happen with copy protection or spiral tracks), whether they have
identical raw nibble data across revolutions, and whether their checksums
pass with the original vs corrupted GCR table. Extends the nibble stream
to three revolutions to catch all occurrences including wrap-around copies.

Usage:
    python scan_sector1.py

    Paths default to repo-relative locations (apple-panic/).

Expected output:
    List of all D5 AA B5 address fields found across 3 revolutions (with
    volume, track, sector, checksum), data field checksums for sectors 1
    and 11, occurrence counts, and a byte-level comparison of sector 1 data
    between revolutions.
"""
import struct
from pathlib import Path


def read_woz_nibbles(woz_path, track_num):
    """Read a WOZ2 track and return nibbles plus the total bit count."""
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
    return nibbles, bits


def build_53_gcr_table():
    """Build the 5-and-3 GCR decode table exactly as the boot code does."""
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
    """Decode a 4-and-4 encoded byte pair from the address field."""
    return ((b1 << 1) | 1) & b2


def main():
    """Scan for all sector 1 occurrences and compare across revolutions."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    nibbles, total_bits = read_woz_nibbles(woz_path, 0)

    print(f"Track 0: {len(nibbles)} nibbles, {total_bits} bits")

    # Extend for wrap-around (3 full revolutions)
    nib = nibbles + nibbles + nibbles

    orig_table = build_53_gcr_table()
    corr_table = list(orig_table)
    for i in range(0x99, 0x100):
        corr_table[i] = (corr_table[i] << 3) & 0xFF

    # Find ALL D5 AA B5 address fields
    print("\n=== All D5 AA B5 address fields ===")
    addr_fields = []
    i = 0
    while i < len(nib) - 20:
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            vol = decode_44(nib[idx], nib[idx+1])
            trk = decode_44(nib[idx+2], nib[idx+3])
            sec = decode_44(nib[idx+4], nib[idx+5])
            chk = decode_44(nib[idx+6], nib[idx+7])

            # XOR checksum
            computed = vol ^ trk ^ sec
            chk_ok = "OK" if computed == chk else f"BAD(exp ${computed:02X})"

            position_in_track = i % len(nibbles)
            revolution = i // len(nibbles)

            addr_fields.append((i, sec, revolution))
            print(f"  nib[{i:5d}] (rev {revolution}, pos {position_in_track:5d}): "
                  f"V={vol:3d} T={trk:2d} S={sec:2d} C=${chk:02X} {chk_ok}")

            # Look for data field after this address
            found_data = False
            for j in range(idx + 8, idx + 200):
                if j >= len(nib) - 3:
                    break
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    data_idx = j + 3
                    # Compute checksum with both tables
                    for table_name, table in [("orig", orig_table), ("corr", corr_table)]:
                        mem = list(table)
                        a = 0
                        ni = data_idx
                        y_counter = 0x9A
                        while y_counter > 0:
                            d = nib[ni]; ni += 1
                            a ^= mem[d]
                            y_counter -= 1
                            mem[y_counter] = a
                        for k in range(256):
                            d = nib[ni]; ni += 1
                            a ^= mem[d]
                        d = nib[ni]; ni += 1
                        a ^= mem[d]
                        status = "PASS" if a == 0 else f"FAIL(${a:02X})"
                        if sec == 1 or sec == 11:
                            print(f"    Data at nib[{j+3:5d}]: {table_name} cksum={status}")

                    found_data = True
                    break

            if not found_data and (sec == 1 or sec == 11):
                print(f"    NO DATA FIELD FOUND!")

            i = idx + 8
        else:
            i += 1

    # Count sector 1 occurrences
    s1_count = sum(1 for _, s, _ in addr_fields if s == 1)
    s11_count = sum(1 for _, s, _ in addr_fields if s == 11)
    print(f"\nSector 1 occurrences (across {len(nib)//len(nibbles)} revolutions): {s1_count}")
    print(f"Sector 11 occurrences: {s11_count}")

    # Check if sector 1 data is the same each revolution
    print("\n=== Sector 1 raw data comparison between revolutions ===")
    s1_data = []
    i = 0
    while i < len(nib) - 500:
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib[idx+4], nib[idx+5])
            if sec == 1:
                for j in range(idx + 8, idx + 200):
                    if j >= len(nib) - 450:
                        break
                    if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                        data = nib[j+3:j+3+411]
                        rev = i // len(nibbles)
                        s1_data.append((rev, i, data))
                        print(f"  Rev {rev} pos {i%len(nibbles):5d}: first 10 nibs = "
                              f"{' '.join(f'${b:02X}' for b in data[:10])}")
                        break
            i = idx + 8
        else:
            i += 1

    if len(s1_data) > 1:
        # Compare data between revolutions
        for k in range(1, len(s1_data)):
            match = s1_data[0][2] == s1_data[k][2]
            if not match:
                diffs = sum(1 for a, b in zip(s1_data[0][2], s1_data[k][2]) if a != b)
                print(f"  Rev 0 vs Rev {s1_data[k][0]}: DIFFERENT ({diffs} differing nibbles)")
            else:
                print(f"  Rev 0 vs Rev {s1_data[k][0]}: identical")


if __name__ == '__main__':
    main()

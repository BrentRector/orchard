#!/usr/bin/env python3
"""
Decode all 5-and-3 sectors from Track 0 using the verified $02D1 algorithm,
then apply the $0346 permutation to produce the correct memory layout.

This is the final, correct decode pipeline for Apple Panic's Track 0. It uses
bit-doubling for proper wrap handling, the verified $02D1 post-decode, and
the $0346 permutation mapping to produce the same output the real hardware
would place into memory.

The two decode routines ($02D1 and $0346) produce the same 256 byte values
but in different order. $02D1 is verified correct. The permutation maps
$02D1 output positions to $0346 output positions (which is what goes into memory).

Memory map: Sectors 0-9 -> $B600-$BFFF
Entry point: JMP $B700 (sector 1)

Usage:
    python decode_track0.py [--woz PATH] [--output-dir DIR]

    Defaults use repo-relative paths; override with CLI arguments.

Expected output:
    Per-sector hex dumps with checksum status, disassembly of code-like
    sectors, individual .bin files, a combined $B600-$BFFF memory image,
    and verification that sector 0 matches the known stage 2 code.
"""
import argparse
import struct
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from disasm_rwts import OPCODES, disasm


def read_woz_nibbles(woz_path, track_num):
    """Read WOZ track and convert to nibbles.
    Uses bit-doubling to handle sectors that span the track boundary.
    This is critical for copy-protected disks that deliberately place
    sector data across the wrap point (e.g., Apple Panic sector 1).
    """
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
    if tidx == 0xFF:
        return []
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
    # Double the bit stream to properly handle nibbles that span the
    # track boundary. Without this, leftover bits at the wrap point
    # cause nibble misalignment for any sector whose data crosses it.
    double_bits = bit_list + bit_list
    nibbles = []
    current = 0
    for b in double_bits:
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
    """Decode a 4-and-4 encoded byte pair from the address field."""
    return ((b1 << 1) | 1) & b2


def rwts_read(nibbles, data_idx, gcr_table):
    """Read 5-and-3 sector data using RWTS algorithm.
    Returns (secondary[0:154], primary[0:256], checksum_ok)
    """
    mem = list(gcr_table)
    a = 0
    ni = data_idx

    # Phase 1: 154 secondary nibbles, stored reversed
    y = 0x9A  # 154
    while y > 0:
        d = nibbles[ni]; ni += 1
        a ^= mem[d]
        y -= 1
        mem[y] = a

    # Phase 2: 256 primary nibbles
    pri = [0] * 256
    for k in range(256):
        d = nibbles[ni]; ni += 1
        a ^= mem[d]
        pri[k] = a

    # Phase 3: checksum
    d = nibbles[ni]; ni += 1
    a ^= mem[d]

    return mem[:154], pri, (a == 0)


def decode_02D1(secondary, primary):
    """Standard 5-and-3 post-decode (verified correct).
    Returns 256 bytes in $02D1 output order.
    Byte 255 only has 5 bits (low 3 bits lost).
    """
    output = list(primary)  # start with primary values

    y = 0
    for group in range(3):
        for x in range(0x33):  # 51 iterations
            sv = secondary[y]
            # LSR → carry → ROL output[$CC+x]
            c1 = sv & 1; sv >>= 1
            cc = 0xCC + x
            if cc < 256:
                output[cc] = ((output[cc] << 1) | c1) & 0xFF
            # LSR → carry → ROL output[$99+x]
            c2 = sv & 1; sv >>= 1
            n9 = 0x99 + x
            if n9 < 256:
                output[n9] = ((output[n9] << 1) | c2) & 0xFF
            # primary[y] ASL×3 | remaining sec bits
            pv = output[y]
            pv = (pv << 3) & 0xFF
            pv |= sv
            output[y] = pv
            y += 1

    return bytes(output)


def permute_02D1_to_0346(d1_output, secondary):
    """Apply the $0346 permutation to $02D1 output.

    $0346 output[5k+0] = $02D1 output[50-k]    (k=0..50)
    $0346 output[5k+1] = $02D1 output[101-k]
    $0346 output[5k+2] = $02D1 output[152-k]
    $0346 output[5k+3] = $02D1 output[$CB-k]    (=$99+50-k = 203-k)
    $0346 output[5k+4] = $02D1 output[$FE-k]    (=$CC+50-k = 254-k)
    $0346 output[255]  = (sec[153] >> 2) | (pri[255] << 3), reconstructed from secondary
    """
    out = [0] * 256
    for k in range(51):
        out[5*k + 0] = d1_output[50 - k]
        out[5*k + 1] = d1_output[101 - k]
        out[5*k + 2] = d1_output[152 - k]
        out[5*k + 3] = d1_output[203 - k]
        out[5*k + 4] = d1_output[254 - k]
    # Byte 255: $0346 reconstructs full 8 bits from sec[153] and pri[255]
    out[255] = ((secondary[153] >> 2) | (d1_output[255] << 3)) & 0xFF
    return bytes(out)


def find_all_53_sectors(nibbles):
    """Find all 5-and-3 sectors. nibbles is already bit-doubled (2 revolutions)."""
    nib = nibbles
    # Search only the first ~half (one revolution) for address fields,
    # but data fields may extend into the second half (across wrap)
    search_limit = len(nibbles) // 2 + 1000
    sectors = {}
    i = 0
    while i < search_limit:
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib[idx+4], nib[idx+5])
            for j in range(idx + 8, idx + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    sectors[sec] = j + 3
                    i = j + 412
                    break
            else:
                i += 1
        else:
            i += 1
    return sectors


def main():
    """Decode all Track 0 sectors and save verified memory image to disk."""
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Decode all 5-and-3 sectors from Track 0.")
    parser.add_argument("--woz", default=str(repo_root / "apple-panic" / "Apple Panic - Disk 1, Side A.woz"),
                        help="Path to the WOZ disk image")
    parser.add_argument("--output-dir", default=str(repo_root / "apple-panic" / "output"),
                        help="Directory for output files")
    args = parser.parse_args()

    woz_path = args.woz
    output_dir = args.output_dir
    os.makedirs(os.path.join(output_dir, "decoded_sectors"), exist_ok=True)

    nibbles = read_woz_nibbles(woz_path, 0)
    nib = nibbles  # already doubled via bit-doubling in read_woz_nibbles

    orig_table = build_53_gcr_table()
    corr_table = list(orig_table)
    for i in range(0x99, 0x100):
        corr_table[i] = (corr_table[i] << 3) & 0xFF

    sectors = find_all_53_sectors(nibbles)
    print(f"Track 0: {len(sectors)} sectors found")

    # Decode each sector using BOTH original and corrupted tables
    for sec_num in sorted(sectors.keys()):
        data_idx = sectors[sec_num]

        # Decode with ORIGINAL table + $02D1 post-decode (verified correct)
        sec_o, pri_o, ck_o = rwts_read(nib, data_idx, orig_table)
        d1_output = decode_02D1(sec_o, pri_o)

        # Apply $0346 permutation
        d46_output = permute_02D1_to_0346(d1_output, sec_o)

        # Also decode with corrupted table for checksum verification
        _, _, ck_c = rwts_read(nib, data_idx, corr_table)

        if sec_num <= 9:
            dest = 0xB600 + sec_num * 0x100
        else:
            dest = None

        dest_str = f"${dest:04X}" if dest else "????"
        ck_str = f"orig={'PASS' if ck_o else 'FAIL'} corr={'PASS' if ck_c else 'FAIL'}"

        print(f"\n=== Sector {sec_num:2d} -> {dest_str}  checksum: {ck_str} ===")

        # Show hex dump of permuted output (this is what goes into memory)
        for row in range(16):
            off = row * 16
            h = ' '.join(f'{d46_output[off+c]:02X}' for c in range(16))
            a = ''.join(chr(d46_output[off+c]) if 32 <= d46_output[off+c] < 127 else '.'
                       for c in range(16))
            addr = dest + off if dest else off
            print(f"  ${addr:04X}: {h}  {a}")

        # Save to file
        fname = os.path.join(output_dir, "decoded_sectors", f"track00_sec{sec_num:02d}_mem.bin")
        with open(fname, 'wb') as f:
            f.write(d46_output)

        # Try disassembly for sectors that look like code
        if dest:
            code_like = sum(1 for b in d46_output[:48] if b in OPCODES) / 48
            if code_like > 0.4:
                print(f"\n  --- Disassembly ---")
                disasm(d46_output, dest, dest, min(dest + 96, dest + 256))

    # Build full memory image
    memory = bytearray(0x0A00)  # $B600-$BFFF
    for sec_num in range(10):
        if sec_num in sectors:
            data_idx = sectors[sec_num]
            sec_o, pri_o, _ = rwts_read(nib, data_idx, orig_table)
            d1 = decode_02D1(sec_o, pri_o)
            d46 = permute_02D1_to_0346(d1, sec_o)
            off = sec_num * 256
            memory[off:off+256] = d46

    mem_path = os.path.join(output_dir, "decoded_sectors", "track0_B600_BFFF.bin")
    with open(mem_path, 'wb') as f:
        f.write(memory)
    print(f"\nSaved memory image ($B600-$BFFF) to {mem_path}")

    # Verify: decode sector 0 with $02D1 and check it matches known stage 2
    sec_o, pri_o, _ = rwts_read(nib, sectors[0], orig_table)
    d1 = decode_02D1(sec_o, pri_o)
    expected_start = bytes([0x99, 0xB9, 0x00, 0x08, 0x0A, 0x0A, 0x0A])
    if d1[:7] == expected_start:
        print("\nVerification: Sector 0 $02D1 decode matches known stage 2 code!")
    else:
        print(f"\nVerification FAILED: got {d1[:7].hex()} expected {expected_start.hex()}")


if __name__ == '__main__':
    main()

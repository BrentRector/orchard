#!/usr/bin/env python3
"""
Decode 5-and-3 sector 0 from Track 0 and disassemble it as stage 2 boot code.

After the RWTS at $0200 reads the first 5-and-3 sector, it performs a
post-decode at $02D1 that reconstructs 256 bytes at $0300. The RWTS then
JMPs to $0301, which is the "stage 2" loader. This script simulates that
exact decode process and disassembles the resulting code.

The stage 2 code at $0301 corrupts the GCR table (ASL x3), then enters a
sector-loading loop that reads sectors 0-9 into $B600-$BFFF using a different
post-decode routine at $0346.

Usage:
    python disasm_stage2.py [--woz PATH]

    Defaults use repo-relative paths; override with CLI arguments.

Expected output:
    Hex dump of $0300-$03FF, disassembly of the stage 2 code at $0301-$0345
    and the post-decode routine at $0346-$03A5, plus the sector loading loop
    at $0327-$033F, and key memory addresses like [$03FF] and [$03CC].
"""
import argparse
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from disasm_rwts import OPCODES, disasm

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def read_woz_nibbles(woz_path, track_num):
    """Read a WOZ2 disk image and extract the nibble stream for a given track."""
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


def decode_44(b1, b2):
    """Decode a 4-and-4 encoded byte pair from the address field."""
    return ((b1 << 1) | 1) & b2


def simulate_boot_decode(nibbles, data_idx):
    """Simulate exactly what the boot code at $02A1-$02D0 + $02D1-$02F9 does.

    The boot code:
    1. Reads 154 secondary nibbles via EOR $0800,Y into $0800 (reversed)
    2. Reads 256 primary nibbles via EOR $0800,Y into ($26) = $0300
    3. Checksum
    4. Post-decode at $02D1: combine secondary ($0800) + primary ($0300) → $0300
       Also populates $0399-$03CB and $03CC-$03FE via ROL
    """
    # Build GCR table at $0800
    gcr_table = [0] * 256
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
        gcr_table[y] = x
        x += 1

    # Phase 1: Read 154 secondary nibbles
    mem_0800 = list(gcr_table)  # GCR table is at $0800
    a = 0
    nib_idx = data_idx
    y_counter = 0x9A  # 154
    while y_counter > 0:
        disk_nib = nibbles[nib_idx]; nib_idx += 1
        a ^= mem_0800[disk_nib]
        y_counter -= 1
        mem_0800[y_counter] = a

    # Phase 2: Read 256 primary nibbles into $0300
    mem_0300 = [0] * 256
    for k in range(256):
        disk_nib = nibbles[nib_idx]; nib_idx += 1
        a ^= mem_0800[disk_nib]
        mem_0300[k] = a

    # Phase 3: Checksum
    disk_nib = nibbles[nib_idx]; nib_idx += 1
    a ^= mem_0800[disk_nib]
    if a != 0:
        print(f"  WARNING: checksum failed (${a:02X})")

    # Phase 4: Post-decode at $02D1
    # A=0 from checksum, TAY → Y=0
    # 3 groups of 51, using DEC $2A (initially $2A=3 from $0284: STY $2A when Y=3)
    # Actually $2A was set at $0286: STY $2A where Y=3 (from $0284: LDY #$03)
    # But wait - in the actual code flow, $02D1 is called AFTER sector read success.
    # At that point, $2A might have been set by the address field decode.
    # $0284: LDY #$03 ; $0286: STY $2A  → $2A = 3
    # After DEY loop (3 times), Y=0. Then PLP, CMP, BCS → data read.
    # After data read, RTS → $02D1 is called. $2A is still 3.

    # CRITICAL: $0399-$03CB and $03CC-$03FE are IN the same page as $0300!
    # The ROL operations modify mem_0300[0x99+x] and mem_0300[0xCC+x]
    # which were already filled with primary data from the EOR chain.

    y = 0  # TAY with A=0
    for group in range(3):
        for x in range(51):
            # LDA $0800,Y
            sec_val = mem_0800[y]
            # LSR
            carry = sec_val & 1
            sec_val >>= 1
            # ROL $03CC,X → operates on mem_0300[0xCC + x]
            cc_idx = 0xCC + x
            old_cc = mem_0300[cc_idx]
            mem_0300[cc_idx] = ((old_cc << 1) | carry) & 0xFF
            # LSR (carry from ROL is discarded by this LSR)
            carry2 = sec_val & 1
            sec_val >>= 1
            # ROL $0399,X → operates on mem_0300[0x99 + x]
            n9_idx = 0x99 + x
            old_99 = mem_0300[n9_idx]
            mem_0300[n9_idx] = ((old_99 << 1) | carry2) & 0xFF
            # STA $3C
            zp3c = sec_val
            # LDA ($26),Y → load from $0300+Y
            pri_val = mem_0300[y]
            # ASL×3
            pri_val = (pri_val << 3) & 0xFF
            # ORA $3C
            pri_val |= zp3c
            # STA ($26),Y
            mem_0300[y] = pri_val
            y += 1

    # After 3 groups: Y=$99
    # CPY $0300: check if mem_0300[0] == $99
    print(f"  [$0300] = ${mem_0300[0]:02X}, Y = ${y:02X}")
    if mem_0300[0] == y:
        print(f"  CPY $0300 -> EQUAL, RTS (boot continues)")
    else:
        print(f"  CPY $0300 -> NOT EQUAL, JMP $FF2D (error/reboot)")

    return bytes(mem_0300)


def main():
    """Decode 5-and-3 sector 0 and disassemble as stage 2 boot code."""
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Disassemble stage 2 boot code from a WOZ image.")
    parser.add_argument("--woz", default=str(repo_root / "apple-panic" / "Apple Panic - Disk 1, Side A.woz"),
                        help="Path to the WOZ disk image")
    args = parser.parse_args()

    woz_path = args.woz
    nibbles = read_woz_nibbles(woz_path, 0)
    nib = nibbles + nibbles[:5000]

    # Find 5-and-3 sector 0
    for i in range(len(nibbles)):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib[idx+4], nib[idx+5])
            if sec != 0:
                continue
            # Find data field
            for j in range(idx + 8, idx + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    print(f"Found 5-and-3 sector 0 data field at nibble offset {j+3}")

                    # Simulate the exact boot decode
                    stage2 = simulate_boot_decode(nib, j + 3)

                    print()
                    print("=== Hex dump ($0300-$03FF) ===")
                    for row in range(16):
                        off = row * 16
                        h = ' '.join(f'{stage2[off+c]:02X}' for c in range(16))
                        print(f"  ${0x0300+off:04X}: {h}")

                    print()
                    print("=== Disassembly ($0301-$0345) ===")
                    disasm(stage2, 0x0300, 0x0301, 0x0346)

                    print()
                    print("=== Disassembly ($0346-$03A5) ===")
                    disasm(stage2, 0x0300, 0x0346, 0x03A5)

                    # Show the key sector loop at $032D
                    print()
                    print("=== Sector loading loop ($0327-$033F) ===")
                    disasm(stage2, 0x0300, 0x0327, 0x0340)

                    # Show what's at $03FF (target sector count)
                    print(f"\n  [$03FF] = ${stage2[0xFF]:02X} (target for sector counter)")
                    print(f"  [$03CC] = ${stage2[0xCC]:02X} (used as destination page)")

                    return
            break

    print("Sector 0 not found!")


if __name__ == '__main__':
    main()

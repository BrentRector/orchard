#!/usr/bin/env python3
"""
Correct P5A ROM 5-and-3 byte reconstruction for Apple Panic WOZ decoding.

Implements the actual P5A (13-sector) controller ROM byte reconstruction
algorithm, based on the Apple-II-Disk-Tools nibblize_5_3.c source code.
This is the algorithm that correctly decodes the copy-protected disk's
5-and-3 encoded sector data.

On-disk order (411 nibbles per sector):
  - thr[153], thr[152], ..., thr[0]   (154 secondary bytes, reversed)
  - top[0], top[1], ..., top[255]      (256 primary bytes, forward)
  - checksum                            (1 byte)

After XOR-chain decode of the 411 sequential values:
  decoded[0..153]  -> thr[153-j] for j=0..153  (secondary, reversed)
  decoded[154..409] -> top[0..255]              (primary)

Reconstruction (groups of 5, i from 50 down to 0):
  For each group, 5 output bytes come from:
    byte A: top[i+0*51] << 3  | (thr[i+0*51] >> 2) & 7
    byte B: top[i+1*51] << 3  | (thr[i+1*51] >> 2) & 7
    byte C: top[i+2*51] << 3  | (thr[i+2*51] >> 2) & 7
    byte D: top[i+3*51] << 3  | reconst_from_bit1s
    byte E: top[i+4*51] << 3  | reconst_from_bit0s
  Final byte: top[5*51] << 3  | thr[3*51] & 7

Usage:
    python woz_p5a_decode.py

    Default paths (override by editing APPLE_PANIC / OUTPUT_DIR):
        woz_path - apple-panic/Apple Panic - Disk 1, Side A.woz
        Also reads apple-panic/ApplePanic_runtime.bin for comparison

Output:
    Decoded sector listing with checksums, boot sector analysis (byte 0 =
    sector count), per-sector comparison against cracked version (exact match
    or best-match percentage), writes track 0 image to track0_p5a.bin, and
    a 6502 disassembly of the boot sector.
"""
import os
import struct
from pathlib import Path

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}

GRP = 51


def read_track_nibbles(woz_path, track_num):
    """Read a WOZ2 file and return the nibble stream for the given track number."""
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


def decode_44(b1, b2):
    """Decode a 4-and-4 encoded byte pair (used in address field headers)."""
    return ((b1 << 1) | 0x01) & b2


def get_53_xor_decoded(nibbles, idx):
    """Read 411 nibbles, translate through table, XOR-chain decode."""
    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DECODE_53:
            return None
        translated.append(DECODE_53[nib])

    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    cksum_val = translated[410]
    cksum_ok = (prev == cksum_val)
    return decoded, cksum_ok


def reconstruct_p5a(decoded):
    """Reconstruct 256 bytes using the actual P5A ROM algorithm.

    decoded[0..153] = secondary buffer (thr), stored reversed on disk
    decoded[154..409] = primary buffer (top)

    thr[j] = decoded[153 - j]   (reverse the secondary)
    top[j] = decoded[154 + j]   (primary is in order)
    """
    # Build thr[] and top[] arrays
    thr = [0] * 154
    for j in range(154):
        thr[j] = decoded[153 - j]

    top = [0] * 256
    for j in range(256):
        top[j] = decoded[154 + j]

    # Reconstruct 256 bytes
    output = bytearray()

    for i in range(GRP - 1, -1, -1):  # i from 50 down to 0
        # Get secondary values for this group
        s0 = thr[0 * GRP + i] if (0 * GRP + i) < 154 else 0
        s1 = thr[1 * GRP + i] if (1 * GRP + i) < 154 else 0
        s2 = thr[2 * GRP + i] if (2 * GRP + i) < 154 else 0

        # Byte A: top[i+0*51] upper5, thr[i+0*51] bits 4,3,2 -> lower 3
        byte_a = (top[0 * GRP + i] << 3) | ((s0 >> 2) & 7)
        output.append(byte_a & 0xFF)

        # Byte B: top[i+1*51] upper5, thr[i+1*51] bits 4,3,2 -> lower 3
        byte_b = (top[1 * GRP + i] << 3) | ((s1 >> 2) & 7)
        output.append(byte_b & 0xFF)

        # Byte C: top[i+2*51] upper5, thr[i+2*51] bits 4,3,2 -> lower 3
        byte_c = (top[2 * GRP + i] << 3) | ((s2 >> 2) & 7)
        output.append(byte_c & 0xFF)

        # Byte D: top[i+3*51] upper5, lower3 from bit1 of s0,s1,s2
        d_low = ((s0 & 2) << 1) | (s1 & 2) | ((s2 & 2) >> 1)
        byte_d = (top[3 * GRP + i] << 3) | (d_low & 7)
        output.append(byte_d & 0xFF)

        # Byte E: top[i+4*51] upper5, lower3 from bit0 of s0,s1,s2
        e_low = ((s0 & 1) << 2) | ((s1 & 1) << 1) | (s2 & 1)
        byte_e = (top[4 * GRP + i] << 3) | (e_low & 7)
        output.append(byte_e & 0xFF)

    # Final (256th) byte: top[5*51] upper5, thr[3*51] lower 3
    final_top = top[5 * GRP] if 5 * GRP < 256 else 0
    final_thr = thr[3 * GRP] if 3 * GRP < 154 else 0
    byte_final = (final_top << 3) | (final_thr & 7)
    output.append(byte_final & 0xFF)

    return bytes(output[:256])


def find_sectors(nibbles, addr_byte2=None):
    """Find sectors with D5 xx B5 address prologues and D5 AA AD data prologues."""
    nib2 = nibbles + nibbles[:2000]
    sectors = {}

    for i in range(len(nibbles)):
        if nib2[i] != 0xD5 or nib2[i + 2] != 0xB5:
            continue
        if addr_byte2 is not None and nib2[i + 1] != addr_byte2:
            continue

        idx = i + 3
        if idx + 8 >= len(nib2):
            continue

        sec = decode_44(nib2[idx + 4], nib2[idx + 5])

        for j in range(idx + 8, idx + 80):
            if j + 2 >= len(nib2):
                break
            if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                didx = j + 3
                # Check for valid 5-and-3 data
                valid = sum(1 for k in range(411) if didx + k < len(nib2)
                            and nib2[didx + k] in DECODE_53)
                if valid >= 410 and sec not in sectors:
                    sectors[sec] = didx
                break

    return sectors, nib2


def main():
    """Decode track 0 using P5A reconstruction and compare with cracked version."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    OUTPUT_DIR = APPLE_PANIC / "output"
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    cracked = open(str(APPLE_PANIC / "ApplePanic_runtime.bin"), 'rb').read()

    nibbles = read_track_nibbles(woz_path, 0)
    sectors, nib2 = find_sectors(nibbles)
    print(f"Track 0 sectors found: {sorted(sectors.keys())}")

    # Decode all sectors
    t0_image = bytearray(13 * 256)
    for sec_num in sorted(sectors.keys()):
        raw = get_53_xor_decoded(nib2, sectors[sec_num])
        if raw:
            decoded, cksum_ok = raw
            sector_data = reconstruct_p5a(decoded)
            t0_image[sec_num * 256:(sec_num + 1) * 256] = sector_data
            ck = "OK" if cksum_ok else "BAD"
            first16 = ' '.join(f'{b:02X}' for b in sector_data[:16])
            print(f"  S{sec_num:2d} cksum={ck}: {first16}")

    # Boot sector analysis
    boot = t0_image[0:256]
    print(f"\nBoot sector byte 0 = ${boot[0]:02X} (sector count to load)")
    print(f"Boot sector first 32 bytes:")
    for row in range(2):
        off = row * 16
        line = ' '.join(f'{boot[off + c]:02X}' for c in range(16))
        print(f"  ${off:04X}: {line}")

    # Compare with cracked version
    print(f"\n=== Comparing T0 sectors with cracked version ===")
    for s in range(13):
        sec = t0_image[s * 256:(s + 1) * 256]
        if all(b == 0 for b in sec):
            print(f"  S{s:2d}: all zeros (missing)")
            continue
        for game_off in range(0, len(cracked), 256):
            game_page = cracked[game_off:game_off + 256]
            if sec == game_page:
                print(f"  S{s:2d}: EXACT MATCH at cracked offset ${game_off:04X}")
                break
        else:
            # Count best match
            best_match = 0
            best_off = 0
            for game_off in range(0, len(cracked), 256):
                game_page = cracked[game_off:game_off + 256]
                matches = sum(1 for a, b in zip(sec, game_page) if a == b)
                if matches > best_match:
                    best_match = matches
                    best_off = game_off
            pct = best_match * 100 // 256
            print(f"  S{s:2d}: best {best_match}/256 ({pct}%) at cracked ${best_off:04X}")

    # Write decoded track 0 to file for inspection
    os.makedirs(str(OUTPUT_DIR), exist_ok=True)
    out_path = str(OUTPUT_DIR / "track0_p5a.bin")
    with open(out_path, 'wb') as f:
        f.write(t0_image)
    print(f"\nWrote track 0 image to {out_path} ({len(t0_image)} bytes)")

    # Disassemble boot sector
    print(f"\n=== Boot sector disassembly (first 64 bytes) ===")
    disasm_boot(boot)


def disasm_boot(data, base=0x0800, count=64):
    """Simple 6502 disassembler for boot sector analysis."""
    OPCODES = {
        0x00: ("BRK", 1, "imp"), 0x01: ("ORA", 2, "izx"),
        0x05: ("ORA", 2, "zp"), 0x06: ("ASL", 2, "zp"),
        0x08: ("PHP", 1, "imp"), 0x09: ("ORA", 2, "imm"),
        0x0A: ("ASL", 1, "acc"), 0x10: ("BPL", 2, "rel"),
        0x11: ("ORA", 2, "izy"), 0x15: ("ORA", 2, "zpx"),
        0x18: ("CLC", 1, "imp"), 0x19: ("ORA", 3, "aby"),
        0x1D: ("ORA", 3, "abx"), 0x20: ("JSR", 3, "abs"),
        0x21: ("AND", 2, "izx"), 0x24: ("BIT", 2, "zp"),
        0x25: ("AND", 2, "zp"), 0x26: ("ROL", 2, "zp"),
        0x28: ("PLP", 1, "imp"), 0x29: ("AND", 2, "imm"),
        0x2A: ("ROL", 1, "acc"), 0x2C: ("BIT", 3, "abs"),
        0x30: ("BMI", 2, "rel"), 0x35: ("AND", 2, "zpx"),
        0x38: ("SEC", 1, "imp"), 0x39: ("AND", 3, "aby"),
        0x3D: ("AND", 3, "abx"), 0x40: ("RTI", 1, "imp"),
        0x41: ("EOR", 2, "izx"), 0x45: ("EOR", 2, "zp"),
        0x46: ("LSR", 2, "zp"), 0x48: ("PHA", 1, "imp"),
        0x49: ("EOR", 2, "imm"), 0x4A: ("LSR", 1, "acc"),
        0x4C: ("JMP", 3, "abs"), 0x4D: ("EOR", 3, "abs"),
        0x50: ("BVC", 2, "rel"), 0x55: ("EOR", 2, "zpx"),
        0x58: ("CLI", 1, "imp"), 0x59: ("EOR", 3, "aby"),
        0x5D: ("EOR", 3, "abx"), 0x60: ("RTS", 1, "imp"),
        0x61: ("ADC", 2, "izx"), 0x65: ("ADC", 2, "zp"),
        0x66: ("ROR", 2, "zp"), 0x68: ("PLA", 1, "imp"),
        0x69: ("ADC", 2, "imm"), 0x6A: ("ROR", 1, "acc"),
        0x6C: ("JMP", 3, "ind"), 0x6D: ("ADC", 3, "abs"),
        0x70: ("BVS", 2, "rel"), 0x75: ("ADC", 2, "zpx"),
        0x78: ("SEI", 1, "imp"), 0x79: ("ADC", 3, "aby"),
        0x7D: ("ADC", 3, "abx"), 0x81: ("STA", 2, "izx"),
        0x84: ("STY", 2, "zp"), 0x85: ("STA", 2, "zp"),
        0x86: ("STX", 2, "zp"), 0x88: ("DEY", 1, "imp"),
        0x8A: ("TXA", 1, "imp"), 0x8C: ("STY", 3, "abs"),
        0x8D: ("STA", 3, "abs"), 0x8E: ("STX", 3, "abs"),
        0x90: ("BCC", 2, "rel"), 0x91: ("STA", 2, "izy"),
        0x94: ("STY", 2, "zpx"), 0x95: ("STA", 2, "zpx"),
        0x96: ("STX", 2, "zpy"), 0x98: ("TYA", 1, "imp"),
        0x99: ("STA", 3, "aby"), 0x9A: ("TXS", 1, "imp"),
        0x9D: ("STA", 3, "abx"),
        0xA0: ("LDY", 2, "imm"), 0xA1: ("LDA", 2, "izx"),
        0xA2: ("LDX", 2, "imm"), 0xA4: ("LDY", 2, "zp"),
        0xA5: ("LDA", 2, "zp"), 0xA6: ("LDX", 2, "zp"),
        0xA8: ("TAY", 1, "imp"), 0xA9: ("LDA", 2, "imm"),
        0xAA: ("TAX", 1, "imp"), 0xAC: ("LDY", 3, "abs"),
        0xAD: ("LDA", 3, "abs"), 0xAE: ("LDX", 3, "abs"),
        0xB0: ("BCS", 2, "rel"), 0xB1: ("LDA", 2, "izy"),
        0xB4: ("LDY", 2, "zpx"), 0xB5: ("LDA", 2, "zpx"),
        0xB6: ("LDX", 2, "zpy"), 0xB8: ("CLV", 1, "imp"),
        0xB9: ("LDA", 3, "aby"), 0xBA: ("TSX", 1, "imp"),
        0xBC: ("LDY", 3, "abx"), 0xBD: ("LDA", 3, "abx"),
        0xBE: ("LDX", 3, "aby"),
        0xC0: ("CPY", 2, "imm"), 0xC1: ("CMP", 2, "izx"),
        0xC4: ("CPY", 2, "zp"), 0xC5: ("CMP", 2, "zp"),
        0xC6: ("DEC", 2, "zp"), 0xC8: ("INY", 1, "imp"),
        0xC9: ("CMP", 2, "imm"), 0xCA: ("DEX", 1, "imp"),
        0xCC: ("CPY", 3, "abs"), 0xCD: ("CMP", 3, "abs"),
        0xCE: ("DEC", 3, "abs"), 0xD0: ("BNE", 2, "rel"),
        0xD5: ("CMP", 2, "zpx"), 0xD8: ("CLD", 1, "imp"),
        0xD9: ("CMP", 3, "aby"), 0xDD: ("CMP", 3, "abx"),
        0xDE: ("DEC", 3, "abx"),
        0xE0: ("CPX", 2, "imm"), 0xE1: ("SBC", 2, "izx"),
        0xE4: ("CPX", 2, "zp"), 0xE5: ("SBC", 2, "zp"),
        0xE6: ("INC", 2, "zp"), 0xE8: ("INX", 1, "imp"),
        0xE9: ("SBC", 2, "imm"), 0xEA: ("NOP", 1, "imp"),
        0xEC: ("CPX", 3, "abs"), 0xED: ("SBC", 3, "abs"),
        0xEE: ("INC", 3, "abs"), 0xF0: ("BEQ", 2, "rel"),
        0xF5: ("SBC", 2, "zpx"), 0xF8: ("SED", 1, "imp"),
        0xF9: ("SBC", 3, "aby"), 0xFD: ("SBC", 3, "abx"),
        0xFE: ("INC", 3, "abx"),
        # Undocumented
        0x9C: ("SHY", 3, "abx"),
    }

    pc = 0
    lines = 0
    while pc < len(data) and pc < count:
        op = data[pc]
        addr = base + pc
        if op in OPCODES:
            mnem, size, mode = OPCODES[op]
            if size == 1:
                print(f"  ${addr:04X}: {op:02X}         {mnem}")
            elif size == 2:
                if pc + 1 < len(data):
                    b1 = data[pc + 1]
                    if mode == "imm":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} #${b1:02X}")
                    elif mode == "rel":
                        target = addr + 2 + (b1 if b1 < 128 else b1 - 256)
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} ${target:04X}")
                    elif mode == "zp":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} ${b1:02X}")
                    elif mode == "zpx":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} ${b1:02X},X")
                    elif mode == "zpy":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} ${b1:02X},Y")
                    elif mode == "izx":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} (${b1:02X},X)")
                    elif mode == "izy":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} (${b1:02X}),Y")
                    else:
                        print(f"  ${addr:04X}: {op:02X} {b1:02X}      {mnem} ${b1:02X}")
                else:
                    print(f"  ${addr:04X}: {op:02X}         {mnem} ???")
            elif size == 3:
                if pc + 2 < len(data):
                    b1 = data[pc + 1]
                    b2 = data[pc + 2]
                    val = b1 | (b2 << 8)
                    if mode == "abs":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X} {b2:02X}   {mnem} ${val:04X}")
                    elif mode == "abx":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X} {b2:02X}   {mnem} ${val:04X},X")
                    elif mode == "aby":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X} {b2:02X}   {mnem} ${val:04X},Y")
                    elif mode == "ind":
                        print(f"  ${addr:04X}: {op:02X} {b1:02X} {b2:02X}   {mnem} (${val:04X})")
                    else:
                        print(f"  ${addr:04X}: {op:02X} {b1:02X} {b2:02X}   {mnem} ${val:04X}")
                else:
                    print(f"  ${addr:04X}: {op:02X}         {mnem} ???")
            pc += size
        else:
            print(f"  ${addr:04X}: {op:02X}         .byte ${op:02X}")
            pc += 1
        lines += 1


if __name__ == '__main__':
    main()

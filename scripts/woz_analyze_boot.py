#!/usr/bin/env python3
"""
Analyze the 5-and-3 decoded track 0 sectors to understand the boot flow.

The D5 AA 96 sector on track 0 is an anti-copy trap. The real boot uses
D5 AA B5 13-sector format with a custom P5A controller ROM. This script
decodes all 13 sectors of track 0, disassembles interesting ones (skipping
high-$FF-count data sectors), identifies disk I/O code (LDA $C08C,X patterns)
and D5-prologue checks (EOR #$D5), and maps all JMP/JSR cross-references
between sectors. Sector 3 receives a full disassembly as it contains the
custom RWTS (Read/Write Track/Sector) routine.

Usage:
    python woz_analyze_boot.py

    Default paths (override by editing APPLE_PANIC):
        woz_path - apple-panic/Apple Panic - Disk 1, Side A.woz
        Also reads apple-panic/ApplePanic_runtime.bin for comparison

Output:
    Per-sector summary (checksum, $FF count, match quality, disk I/O markers),
    selective 6502 disassembly of code sectors, full disassembly of sector 3
    (custom RWTS), and a cross-reference table of all JMP/JSR targets in the
    $0800-$14FF range.
"""
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


def read_nibbles(woz_path, track_num):
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


def decode_53_sector(nibbles, idx):
    """Decode a 5-and-3 sector using the P5A ROM algorithm. Returns (256 bytes, cksum_ok)."""
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
    cksum_ok = (prev == translated[410])

    thr = [decoded[153 - j] for j in range(154)]
    top = [decoded[154 + j] for j in range(256)]

    output = bytearray()
    for i in range(GRP - 1, -1, -1):
        s0 = thr[0 * GRP + i] if (0 * GRP + i) < 154 else 0
        s1 = thr[1 * GRP + i] if (1 * GRP + i) < 154 else 0
        s2 = thr[2 * GRP + i] if (2 * GRP + i) < 154 else 0
        output.append(((top[0 * GRP + i] << 3) | ((s0 >> 2) & 7)) & 0xFF)
        output.append(((top[1 * GRP + i] << 3) | ((s1 >> 2) & 7)) & 0xFF)
        output.append(((top[2 * GRP + i] << 3) | ((s2 >> 2) & 7)) & 0xFF)
        d_low = ((s0 & 2) << 1) | (s1 & 2) | ((s2 & 2) >> 1)
        output.append(((top[3 * GRP + i] << 3) | (d_low & 7)) & 0xFF)
        e_low = ((s0 & 1) << 2) | ((s1 & 1) << 1) | (s2 & 1)
        output.append(((top[4 * GRP + i] << 3) | (e_low & 7)) & 0xFF)
    final_top = top[5 * GRP] if 5 * GRP < 256 else 0
    final_thr = thr[3 * GRP] if 3 * GRP < 154 else 0
    output.append(((final_top << 3) | (final_thr & 7)) & 0xFF)
    return bytes(output[:256]), cksum_ok


def find_53_sectors(nibbles):
    """Find D5 xx B5 sectors with valid 5-and-3 data fields. Returns (sectors dict, nib2)."""
    nib2 = nibbles + nibbles[:2000]
    sectors = {}
    for i in range(len(nibbles)):
        if nib2[i] != 0xD5 or nib2[i + 2] != 0xB5:
            continue
        idx = i + 3
        if idx + 8 >= len(nib2):
            continue
        sec = decode_44(nib2[idx + 4], nib2[idx + 5])
        if sec in sectors:
            continue
        for j in range(idx + 8, idx + 80):
            if j + 2 >= len(nib2):
                break
            if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                didx = j + 3
                valid = sum(1 for k in range(411) if didx + k < len(nib2)
                            and nib2[didx + k] in DECODE_53)
                if valid >= 410:
                    sectors[sec] = didx
                break
    return sectors, nib2


# Simple 6502 disassembler
OPCODES = {
    0x00: ("BRK", 1, "imp"), 0x01: ("ORA", 2, "izx"), 0x05: ("ORA", 2, "zp"),
    0x06: ("ASL", 2, "zp"), 0x08: ("PHP", 1, "imp"), 0x09: ("ORA", 2, "imm"),
    0x0A: ("ASL", 1, "acc"), 0x10: ("BPL", 2, "rel"), 0x18: ("CLC", 1, "imp"),
    0x20: ("JSR", 3, "abs"), 0x21: ("AND", 2, "izx"), 0x24: ("BIT", 2, "zp"),
    0x25: ("AND", 2, "zp"), 0x26: ("ROL", 2, "zp"), 0x28: ("PLP", 1, "imp"),
    0x29: ("AND", 2, "imm"), 0x2A: ("ROL", 1, "acc"), 0x2C: ("BIT", 3, "abs"),
    0x30: ("BMI", 2, "rel"), 0x38: ("SEC", 1, "imp"), 0x40: ("RTI", 1, "imp"),
    0x45: ("EOR", 2, "zp"), 0x46: ("LSR", 2, "zp"), 0x48: ("PHA", 1, "imp"),
    0x49: ("EOR", 2, "imm"), 0x4A: ("LSR", 1, "acc"), 0x4C: ("JMP", 3, "abs"),
    0x4D: ("EOR", 3, "abs"), 0x50: ("BVC", 2, "rel"), 0x58: ("CLI", 1, "imp"),
    0x60: ("RTS", 1, "imp"), 0x65: ("ADC", 2, "zp"), 0x66: ("ROR", 2, "zp"),
    0x68: ("PLA", 1, "imp"), 0x69: ("ADC", 2, "imm"), 0x6A: ("ROR", 1, "acc"),
    0x6C: ("JMP", 3, "ind"), 0x6D: ("ADC", 3, "abs"), 0x70: ("BVS", 2, "rel"),
    0x78: ("SEI", 1, "imp"), 0x81: ("STA", 2, "izx"), 0x84: ("STY", 2, "zp"),
    0x85: ("STA", 2, "zp"), 0x86: ("STX", 2, "zp"), 0x88: ("DEY", 1, "imp"),
    0x8A: ("TXA", 1, "imp"), 0x8C: ("STY", 3, "abs"), 0x8D: ("STA", 3, "abs"),
    0x8E: ("STX", 3, "abs"), 0x90: ("BCC", 2, "rel"), 0x91: ("STA", 2, "izy"),
    0x95: ("STA", 2, "zpx"), 0x98: ("TYA", 1, "imp"), 0x99: ("STA", 3, "aby"),
    0x9A: ("TXS", 1, "imp"), 0x9D: ("STA", 3, "abx"),
    0xA0: ("LDY", 2, "imm"), 0xA1: ("LDA", 2, "izx"), 0xA2: ("LDX", 2, "imm"),
    0xA4: ("LDY", 2, "zp"), 0xA5: ("LDA", 2, "zp"), 0xA6: ("LDX", 2, "zp"),
    0xA8: ("TAY", 1, "imp"), 0xA9: ("LDA", 2, "imm"), 0xAA: ("TAX", 1, "imp"),
    0xAC: ("LDY", 3, "abs"), 0xAD: ("LDA", 3, "abs"), 0xAE: ("LDX", 3, "abs"),
    0xB0: ("BCS", 2, "rel"), 0xB1: ("LDA", 2, "izy"), 0xB4: ("LDY", 2, "zpx"),
    0xB5: ("LDA", 2, "zpx"), 0xB9: ("LDA", 3, "aby"), 0xBA: ("TSX", 1, "imp"),
    0xBC: ("LDY", 3, "abx"), 0xBD: ("LDA", 3, "abx"), 0xBE: ("LDX", 3, "aby"),
    0xC0: ("CPY", 2, "imm"), 0xC4: ("CPY", 2, "zp"), 0xC5: ("CMP", 2, "zp"),
    0xC6: ("DEC", 2, "zp"), 0xC8: ("INY", 1, "imp"), 0xC9: ("CMP", 2, "imm"),
    0xCA: ("DEX", 1, "imp"), 0xCC: ("CPY", 3, "abs"), 0xCD: ("CMP", 3, "abs"),
    0xCE: ("DEC", 3, "abs"), 0xD0: ("BNE", 2, "rel"), 0xD5: ("CMP", 2, "zpx"),
    0xD8: ("CLD", 1, "imp"), 0xDD: ("CMP", 3, "abx"), 0xDE: ("DEC", 3, "abx"),
    0xE0: ("CPX", 2, "imm"), 0xE4: ("CPX", 2, "zp"), 0xE5: ("SBC", 2, "zp"),
    0xE6: ("INC", 2, "zp"), 0xE8: ("INX", 1, "imp"), 0xE9: ("SBC", 2, "imm"),
    0xEA: ("NOP", 1, "imp"), 0xEC: ("CPX", 3, "abs"), 0xED: ("SBC", 3, "abs"),
    0xEE: ("INC", 3, "abs"), 0xF0: ("BEQ", 2, "rel"), 0xF5: ("SBC", 2, "zpx"),
    0xF6: ("INC", 2, "zpx"), 0xF8: ("SED", 1, "imp"), 0xFD: ("SBC", 3, "abx"),
    0xFE: ("INC", 3, "abx"),
    0x9C: ("SHY", 3, "abx"),  # undocumented
}


def disasm(data, base, count=None):
    """Disassemble 6502 code. Returns list of (addr, bytes, mnemonic) tuples."""
    pc = 0
    lines = []
    limit = count if count else len(data)
    while pc < len(data) and len(lines) < limit:
        op = data[pc]
        addr = base + pc
        if op in OPCODES:
            mnem, size, mode = OPCODES[op]
            raw = data[pc:pc + size] if pc + size <= len(data) else data[pc:]
            if size == 1:
                text = mnem
            elif size == 2 and pc + 1 < len(data):
                b1 = data[pc + 1]
                if mode == "imm":
                    text = f"{mnem} #${b1:02X}"
                elif mode == "rel":
                    target = addr + 2 + (b1 if b1 < 128 else b1 - 256)
                    text = f"{mnem} ${target:04X}"
                elif mode == "zp":
                    text = f"{mnem} ${b1:02X}"
                elif mode == "zpx":
                    text = f"{mnem} ${b1:02X},X"
                elif mode == "izx":
                    text = f"{mnem} (${b1:02X},X)"
                elif mode == "izy":
                    text = f"{mnem} (${b1:02X}),Y"
                else:
                    text = f"{mnem} ${b1:02X}"
            elif size == 3 and pc + 2 < len(data):
                b1 = data[pc + 1]
                b2 = data[pc + 2]
                val = b1 | (b2 << 8)
                if mode == "abs":
                    text = f"{mnem} ${val:04X}"
                elif mode == "abx":
                    text = f"{mnem} ${val:04X},X"
                elif mode == "aby":
                    text = f"{mnem} ${val:04X},Y"
                elif mode == "ind":
                    text = f"{mnem} (${val:04X})"
                else:
                    text = f"{mnem} ${val:04X}"
            else:
                text = f"{mnem} ???"
            hex_str = ' '.join(f'{b:02X}' for b in raw)
            lines.append(f"  ${addr:04X}: {hex_str:10s} {text}")
            pc += size
        else:
            lines.append(f"  ${addr:04X}: {op:02X}         .byte ${op:02X}")
            pc += 1
    return lines


def main():
    """Decode track 0, disassemble boot sectors, and map cross-references."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    cracked = open(str(APPLE_PANIC / "ApplePanic_runtime.bin"), 'rb').read()

    nibbles = read_nibbles(woz_path, 0)
    sectors, nib2 = find_53_sectors(nibbles)

    print("=" * 70)
    print("TRACK 0 SECTOR ANALYSIS (5-and-3 decoded)")
    print("=" * 70)

    all_data = {}
    for sec_num in sorted(sectors.keys()):
        result = decode_53_sector(nib2, sectors[sec_num])
        if result:
            data, cksum_ok = result
            all_data[sec_num] = data

            base = 0x0800 + sec_num * 0x100
            ff_count = sum(1 for b in data if b == 0xFF)
            zero_count = sum(1 for b in data if b == 0x00)

            # Check for disk I/O patterns
            has_c08c = any(data[i:i+3] == bytes([0xBD, 0x8C, 0xC0])
                          for i in range(len(data) - 2))
            has_d5 = any(data[i:i+2] == bytes([0x49, 0xD5])
                         for i in range(len(data) - 1))

            # Check cracked match
            best_match = 0
            best_off = 0
            for off in range(0, len(cracked), 256):
                m = sum(1 for a, b in zip(data, cracked[off:off + 256]) if a == b)
                if m > best_match:
                    best_match = m
                    best_off = off

            ck = "OK" if cksum_ok else "BAD"
            match_str = "EXACT" if best_match == 256 else f"{best_match}/256 @${best_off:04X}"
            io_str = " [DISK I/O]" if has_c08c else ""
            d5_str = " [D5 CHECK]" if has_d5 else ""

            print(f"\nS{sec_num:2d} (${base:04X}) ck={ck} FFs={ff_count} match={match_str}{io_str}{d5_str}")
            first16 = ' '.join(f'{b:02X}' for b in data[:16])
            print(f"  {first16}")

            # Disassemble first 20 instructions of interesting sectors
            if ff_count < 20 and cksum_ok and sec_num != 5 and sec_num != 6:
                lines = disasm(data, base, 20)
                for line in lines:
                    print(line)

    # Full disassembly of sector 3 (disk read routine)
    if 3 in all_data:
        print(f"\n{'='*70}")
        print(f"SECTOR 3 ($0B00) — FULL DISASSEMBLY (Custom RWTS)")
        print(f"{'='*70}")
        lines = disasm(all_data[3], 0x0B00, 80)
        for line in lines:
            print(line)

    # Look for JMP/JSR targets that reference other sectors
    print(f"\n{'='*70}")
    print(f"CROSS-REFERENCES (JMP/JSR targets)")
    print(f"{'='*70}")
    for sec_num in sorted(all_data.keys()):
        data = all_data[sec_num]
        base = 0x0800 + sec_num * 0x100
        pc = 0
        while pc < len(data) - 2:
            op = data[pc]
            if op in (0x4C, 0x20) and pc + 2 < len(data):  # JMP abs, JSR abs
                target = data[pc + 1] | (data[pc + 2] << 8)
                mnem = "JMP" if op == 0x4C else "JSR"
                if 0x0800 <= target <= 0x14FF:
                    target_sec = (target - 0x0800) // 0x100
                    print(f"  ${base + pc:04X}: {mnem} ${target:04X} (sector {target_sec})")
                elif target < 0x0800 or target >= 0xC000:
                    print(f"  ${base + pc:04X}: {mnem} ${target:04X}")
                pc += 3
            elif op in OPCODES:
                _, size, _ = OPCODES[op]
                pc += size
            else:
                pc += 1


if __name__ == '__main__':
    main()

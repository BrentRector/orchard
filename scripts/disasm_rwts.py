#!/usr/bin/env python3
"""
Disassemble the Apple Panic boot RWTS (Read/Write Track/Sector) code.

Decodes the 6-and-2 boot sector from the WOZ image using the ROM-exact
algorithm, then disassembles it as code at $0200-$02FF. The boot sector
is initially loaded at $0800 by the P6 ROM, then self-relocates to $0200
where it serves as the disk RWTS for loading subsequent 5-and-3 sectors.

Also provides a reusable disasm() function and OPCODES table imported by
other scripts in this project (disasm_stage2.py, decode_all_sectors.py, etc.).

Usage:
    python disasm_rwts.py [--woz PATH]

    Defaults use repo-relative paths; override with CLI arguments.

Expected output:
    Boot sector hex dump at $0200-$02FF, full 6502 disassembly, and a summary
    of all JMP/JSR/JMP-indirect targets found in the code.
"""
import argparse
import struct
from pathlib import Path

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


def decode_boot_sector(woz_path):
    """Decode Track 0, Sector 0 from a WOZ image using ROM-exact 6-and-2.

    Finds the D5 AA 96 address field for sector 0, locates the corresponding
    D5 AA AD data field, and performs the full P6 ROM decode including the
    destructive LSR/ROL post-decode pass.

    Args:
        woz_path: Path to the WOZ2 disk image file.

    Returns:
        256-byte boot sector as bytes, or None if not found.
    """
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
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

    nibbles = []
    current = 0
    for b in bit_list:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0

    nib2 = nibbles + nibbles[:500]
    for i in range(len(nibbles)):
        if nib2[i] == 0xD5 and nib2[i+1] == 0xAA and nib2[i+2] == 0x96:
            idx = i + 3
            sec = ((nib2[idx+4] << 1) | 1) & nib2[idx+5]
            if sec != 0:
                continue
            for j in range(idx + 8, idx + 200):
                if nib2[j] == 0xD5 and nib2[j+1] == 0xAA and nib2[j+2] == 0xAD:
                    didx = j + 3
                    encoded = [DECODE_62[nib2[didx + k]] for k in range(342)]
                    # ROM-exact decode
                    aux_buf = [0] * 86
                    xor_acc = 0
                    for k in range(86):
                        xor_acc ^= encoded[k]
                        aux_buf[85 - k] = xor_acc
                    pri_buf = [0] * 256
                    for k in range(256):
                        xor_acc ^= encoded[86 + k]
                        pri_buf[k] = xor_acc
                    result = bytearray(256)
                    x = 0x56
                    for y in range(256):
                        x -= 1
                        if x < 0:
                            x = 0x55
                        a = pri_buf[y]
                        carry = aux_buf[x] & 1
                        aux_buf[x] >>= 1
                        a = ((a << 1) | carry) & 0xFF
                        carry2 = aux_buf[x] & 1
                        aux_buf[x] >>= 1
                        a = ((a << 1) | carry2) & 0xFF
                        result[y] = a
                    return bytes(result)
    return None


# 6502 opcode table
OPCODES = {
    0x00: ('BRK', 1, 'imp'), 0x01: ('ORA', 2, 'izx'), 0x05: ('ORA', 2, 'zp'),
    0x06: ('ASL', 2, 'zp'), 0x08: ('PHP', 1, 'imp'), 0x09: ('ORA', 2, 'imm'),
    0x0A: ('ASL', 1, 'acc'), 0x0D: ('ORA', 3, 'abs'), 0x0E: ('ASL', 3, 'abs'),
    0x10: ('BPL', 2, 'rel'), 0x11: ('ORA', 2, 'izy'), 0x15: ('ORA', 2, 'zpx'),
    0x16: ('ASL', 2, 'zpx'), 0x18: ('CLC', 1, 'imp'), 0x19: ('ORA', 3, 'aby'),
    0x1D: ('ORA', 3, 'abx'), 0x1E: ('ASL', 3, 'abx'),
    0x20: ('JSR', 3, 'abs'), 0x21: ('AND', 2, 'izx'), 0x24: ('BIT', 2, 'zp'),
    0x25: ('AND', 2, 'zp'), 0x26: ('ROL', 2, 'zp'), 0x28: ('PLP', 1, 'imp'),
    0x29: ('AND', 2, 'imm'), 0x2A: ('ROL', 1, 'acc'), 0x2C: ('BIT', 3, 'abs'),
    0x2D: ('AND', 3, 'abs'), 0x2E: ('ROL', 3, 'abs'),
    0x30: ('BMI', 2, 'rel'), 0x31: ('AND', 2, 'izy'), 0x35: ('AND', 2, 'zpx'),
    0x36: ('ROL', 2, 'zpx'), 0x38: ('SEC', 1, 'imp'), 0x39: ('AND', 3, 'aby'),
    0x3D: ('AND', 3, 'abx'), 0x3E: ('ROL', 3, 'abx'),
    0x40: ('RTI', 1, 'imp'), 0x41: ('EOR', 2, 'izx'), 0x45: ('EOR', 2, 'zp'),
    0x46: ('LSR', 2, 'zp'), 0x48: ('PHA', 1, 'imp'), 0x49: ('EOR', 2, 'imm'),
    0x4A: ('LSR', 1, 'acc'), 0x4C: ('JMP', 3, 'abs'), 0x4D: ('EOR', 3, 'abs'),
    0x4E: ('LSR', 3, 'abs'),
    0x50: ('BVC', 2, 'rel'), 0x51: ('EOR', 2, 'izy'), 0x55: ('EOR', 2, 'zpx'),
    0x56: ('LSR', 2, 'zpx'), 0x58: ('CLI', 1, 'imp'), 0x59: ('EOR', 3, 'aby'),
    0x5D: ('EOR', 3, 'abx'), 0x5E: ('LSR', 3, 'abx'),
    0x60: ('RTS', 1, 'imp'), 0x61: ('ADC', 2, 'izx'), 0x65: ('ADC', 2, 'zp'),
    0x66: ('ROR', 2, 'zp'), 0x68: ('PLA', 1, 'imp'), 0x69: ('ADC', 2, 'imm'),
    0x6A: ('ROR', 1, 'acc'), 0x6C: ('JMP', 3, 'ind'), 0x6D: ('ADC', 3, 'abs'),
    0x6E: ('ROR', 3, 'abs'),
    0x70: ('BVS', 2, 'rel'), 0x71: ('ADC', 2, 'izy'), 0x75: ('ADC', 2, 'zpx'),
    0x76: ('ROR', 2, 'zpx'), 0x78: ('SEI', 1, 'imp'), 0x79: ('ADC', 3, 'aby'),
    0x7D: ('ADC', 3, 'abx'), 0x7E: ('ROR', 3, 'abx'),
    0x81: ('STA', 2, 'izx'), 0x84: ('STY', 2, 'zp'), 0x85: ('STA', 2, 'zp'),
    0x86: ('STX', 2, 'zp'), 0x88: ('DEY', 1, 'imp'), 0x8A: ('TXA', 1, 'imp'),
    0x8C: ('STY', 3, 'abs'), 0x8D: ('STA', 3, 'abs'), 0x8E: ('STX', 3, 'abs'),
    0x90: ('BCC', 2, 'rel'), 0x91: ('STA', 2, 'izy'), 0x94: ('STY', 2, 'zpx'),
    0x95: ('STA', 2, 'zpx'), 0x96: ('STX', 2, 'zpy'), 0x98: ('TYA', 1, 'imp'),
    0x99: ('STA', 3, 'aby'), 0x9A: ('TXS', 1, 'imp'), 0x9C: ('SHY', 3, 'abx'),
    0x9D: ('STA', 3, 'abx'),
    0xA0: ('LDY', 2, 'imm'), 0xA1: ('LDA', 2, 'izx'), 0xA2: ('LDX', 2, 'imm'),
    0xA4: ('LDY', 2, 'zp'), 0xA5: ('LDA', 2, 'zp'), 0xA6: ('LDX', 2, 'zp'),
    0xA8: ('TAY', 1, 'imp'), 0xA9: ('LDA', 2, 'imm'), 0xAA: ('TAX', 1, 'imp'),
    0xAC: ('LDY', 3, 'abs'), 0xAD: ('LDA', 3, 'abs'), 0xAE: ('LDX', 3, 'abs'),
    0xB0: ('BCS', 2, 'rel'), 0xB1: ('LDA', 2, 'izy'), 0xB4: ('LDY', 2, 'zpx'),
    0xB5: ('LDA', 2, 'zpx'), 0xB6: ('LDX', 2, 'zpy'), 0xB8: ('CLV', 1, 'imp'),
    0xB9: ('LDA', 3, 'aby'), 0xBA: ('TSX', 1, 'imp'), 0xBC: ('LDY', 3, 'abx'),
    0xBD: ('LDA', 3, 'abx'), 0xBE: ('LDX', 3, 'aby'),
    0xC0: ('CPY', 2, 'imm'), 0xC1: ('CMP', 2, 'izx'), 0xC4: ('CPY', 2, 'zp'),
    0xC5: ('CMP', 2, 'zp'), 0xC6: ('DEC', 2, 'zp'), 0xC8: ('INY', 1, 'imp'),
    0xC9: ('CMP', 2, 'imm'), 0xCA: ('DEX', 1, 'imp'), 0xCC: ('CPY', 3, 'abs'),
    0xCD: ('CMP', 3, 'abs'), 0xCE: ('DEC', 3, 'abs'),
    0xD0: ('BNE', 2, 'rel'), 0xD1: ('CMP', 2, 'izy'), 0xD5: ('CMP', 2, 'zpx'),
    0xD6: ('DEC', 2, 'zpx'), 0xD8: ('CLD', 1, 'imp'), 0xD9: ('CMP', 3, 'aby'),
    0xDD: ('CMP', 3, 'abx'), 0xDE: ('DEC', 3, 'abx'),
    0xE0: ('CPX', 2, 'imm'), 0xE1: ('SBC', 2, 'izx'), 0xE4: ('CPX', 2, 'zp'),
    0xE5: ('SBC', 2, 'zp'), 0xE6: ('INC', 2, 'zp'), 0xE8: ('INX', 1, 'imp'),
    0xE9: ('SBC', 2, 'imm'), 0xEA: ('NOP', 1, 'imp'), 0xEC: ('CPX', 3, 'abs'),
    0xED: ('SBC', 3, 'abs'), 0xEE: ('INC', 3, 'abs'),
    0xF0: ('BEQ', 2, 'rel'), 0xF1: ('SBC', 2, 'izy'), 0xF5: ('SBC', 2, 'zpx'),
    0xF6: ('INC', 2, 'zpx'), 0xF8: ('SED', 1, 'imp'), 0xF9: ('SBC', 3, 'aby'),
    0xFD: ('SBC', 3, 'abx'), 0xFE: ('INC', 3, 'abx'),
}


def disasm(mem, base, start, end):
    """Disassemble 6502 code and print formatted assembly lines.

    Args:
        mem: Byte sequence containing the machine code.
        base: Memory address corresponding to mem[0].
        start: Address to begin disassembly.
        end: Address to stop disassembly.
    """
    pc = start
    while pc < end:
        off = pc - base
        if off < 0 or off >= len(mem):
            break
        op = mem[off]
        if op in OPCODES:
            name, size, mode = OPCODES[op]
            raw = ' '.join(f'{mem[off+k]:02X}' for k in range(min(size, end - pc)))
            if mode == 'imp' or mode == 'acc':
                print(f"  ${pc:04X}: {raw:8s}  {name}")
            elif mode == 'imm':
                print(f"  ${pc:04X}: {raw:8s}  {name} #${mem[off+1]:02X}")
            elif mode == 'zp':
                print(f"  ${pc:04X}: {raw:8s}  {name} ${mem[off+1]:02X}")
            elif mode == 'zpx':
                print(f"  ${pc:04X}: {raw:8s}  {name} ${mem[off+1]:02X},X")
            elif mode == 'zpy':
                print(f"  ${pc:04X}: {raw:8s}  {name} ${mem[off+1]:02X},Y")
            elif mode == 'abs':
                addr = mem[off+1] | (mem[off+2] << 8)
                print(f"  ${pc:04X}: {raw:8s}  {name} ${addr:04X}")
            elif mode == 'abx':
                addr = mem[off+1] | (mem[off+2] << 8)
                print(f"  ${pc:04X}: {raw:8s}  {name} ${addr:04X},X")
            elif mode == 'aby':
                addr = mem[off+1] | (mem[off+2] << 8)
                print(f"  ${pc:04X}: {raw:8s}  {name} ${addr:04X},Y")
            elif mode == 'izx':
                print(f"  ${pc:04X}: {raw:8s}  {name} (${mem[off+1]:02X},X)")
            elif mode == 'izy':
                print(f"  ${pc:04X}: {raw:8s}  {name} (${mem[off+1]:02X}),Y")
            elif mode == 'ind':
                addr = mem[off+1] | (mem[off+2] << 8)
                print(f"  ${pc:04X}: {raw:8s}  {name} (${addr:04X})")
            elif mode == 'rel':
                offset = mem[off+1]
                if offset >= 0x80:
                    offset -= 256
                target = pc + 2 + offset
                print(f"  ${pc:04X}: {raw:8s}  {name} ${target:04X}")
            pc += size
        else:
            print(f"  ${pc:04X}: {op:02X}         .byte ${op:02X}")
            pc += 1


def main():
    """Decode the boot sector and produce a full disassembly at $0200."""
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Disassemble the Apple Panic boot RWTS code.")
    parser.add_argument("--woz", default=str(repo_root / "apple-panic" / "Apple Panic - Disk 1, Side A.woz"),
                        help="Path to the WOZ disk image")
    args = parser.parse_args()

    woz_path = args.woz
    boot = decode_boot_sector(woz_path)
    if not boot:
        print("Failed to decode boot sector")
        return

    print(f"Boot sector decoded: {len(boot)} bytes")
    print(f"Byte 0 (sector count): ${boot[0]:02X}")
    print()

    # Hex dump
    print("=== Hex dump ($0200-$02FF when relocated) ===")
    for row in range(16):
        off = row * 16
        h = ' '.join(f'{boot[off+c]:02X}' for c in range(16))
        a = ''.join(chr(boot[off+c]) if 32 <= boot[off+c] < 127 else '.' for c in range(16))
        print(f"  ${0x0200+off:04X}: {h}  {a}")

    print()
    print("=== Full disassembly ($0200-$02FF) ===")
    disasm(boot, 0x0200, 0x0200, 0x0300)

    # Check what's at $0300+ (this is in the SAME 256-byte boot sector)
    # The boot sector is only 256 bytes, so $0300+ comes from memory initialized
    # by the code itself (GCR table, decoded sector data, etc.)
    # But the code also uses $0300-$03FF as buffer space

    # Let's look for any sector number table or skip logic in the code
    print()
    print("=== Key addresses and constants ===")
    # $3D = sector counter, $3E/$3F = read routine vector
    # $40/$41 = destination address, $26/$27 = raw data address
    # Look for any LDA/STA/CMP involving unusual patterns
    for i in range(256):
        if boot[i] == 0x4C:  # JMP
            addr = boot[i+1] | (boot[i+2] << 8)
            print(f"  JMP ${addr:04X} at ${0x0200+i:04X}")
        elif boot[i] == 0x20:  # JSR
            addr = boot[i+1] | (boot[i+2] << 8)
            print(f"  JSR ${addr:04X} at ${0x0200+i:04X}")
        elif boot[i] == 0x6C:  # JMP indirect
            addr = boot[i+1] | (boot[i+2] << 8)
            print(f"  JMP (${addr:04X}) at ${0x0200+i:04X}")


if __name__ == '__main__':
    main()

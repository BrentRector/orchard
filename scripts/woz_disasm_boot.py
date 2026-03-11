#!/usr/bin/env python3
"""Disassemble the decoded D5 AA 96 boot sector."""

# Boot sector data (verified against .dsk)
BOOT = bytes([
    0x00, 0xA0, 0x00, 0xBC, 0x00, 0x08, 0x9C, 0x00,
    0x00, 0xE8, 0xD0, 0xF4, 0x4C, 0x0C, 0x00, 0xA0,
    0xA8, 0x98, 0x87, 0x3E, 0x48, 0x07, 0x3C, 0xCA,
    0xFD, 0xD2, 0x0B, 0xC3, 0xD6, 0xF2, 0x06, 0x89,
    0x9A, 0x00, 0x09, 0xEA, 0xC8, 0xD3, 0xE9, 0x87,
    0x3E, 0x87, 0x26, 0xA9, 0x00, 0x86, 0x24, 0xA5,
    0x28, 0x20, 0x5C, 0x00, 0x20, 0xD2, 0x01, 0xAA,
    0xA8, 0x8E, 0x1C, 0x02, 0xA8, 0x03, 0x8E, 0x20,
    0x02, 0x4D, 0x00, 0x02, 0x00, 0x03, 0x00, 0x01,
    0x03, 0x00, 0x03, 0x00, 0x00, 0x01, 0x00, 0x02,
    0x00, 0x00, 0x02, 0x00, 0x01, 0x02, 0x00, 0x02,
    0x03, 0x00, 0x00, 0x00, 0x00, 0x18, 0x08, 0xBD,
    0x8C, 0xC2, 0x10, 0xF9, 0x48, 0xD6, 0xD2, 0xF4,
    0xBD, 0x8C, 0xC0, 0x10, 0xFA, 0xCB, 0xA8, 0xD0,
    0xF0, 0xEA, 0xBC, 0x8E, 0xC1, 0x13, 0xF8, 0xC8,
    0xB4, 0xF2, 0x09, 0x28, 0x93, 0xDC, 0x4A, 0xAC,
    0xF3, 0x1C, 0xD2, 0xDA, 0xA3, 0x00, 0x84, 0x2A,
    0xBC, 0x8E, 0xC2, 0x13, 0xF8, 0x28, 0x84, 0x3E,
    0xBD, 0x8F, 0xC0, 0x11, 0xFA, 0x27, 0x3C, 0x88,
    0xD0, 0xEE, 0x2B, 0xC4, 0x3E, 0xD2, 0xBF, 0xB0,
    0xBC, 0xA0, 0x9A, 0x84, 0x3C, 0xBC, 0x8C, 0xC0,
    0x10, 0xF8, 0x58, 0x00, 0x09, 0xA6, 0x3C, 0x8B,
    0x9A, 0x00, 0x08, 0xD0, 0xEC, 0x87, 0x3C, 0xBF,
    0x8C, 0xC0, 0x11, 0xF8, 0x59, 0x01, 0x08, 0xA4,
    0x3F, 0x90, 0x24, 0xC8, 0xD1, 0xEE, 0xBC, 0x8E,
    0xC1, 0x11, 0xF9, 0x59, 0x02, 0x08, 0xD2, 0x8F,
    0x62, 0xA9, 0xA1, 0x03, 0xB8, 0x01, 0x09, 0x48,
    0x3C, 0xCE, 0x00, 0x49, 0x3C, 0x98, 0x02, 0x84,
    0x3C, 0xB0, 0x26, 0x0B, 0x08, 0x08, 0x04, 0x3C,
    0x93, 0x24, 0xC8, 0xE9, 0xE2, 0x30, 0xD0, 0xE4,
    0xC4, 0x2A, 0xD3, 0xDC, 0xCC, 0x00, 0x00, 0xD0,
    0x00, 0x61, 0x00, 0x00, 0x4C, 0x2E, 0xFC, 0x00,
])

# 6502 opcode table: (mnemonic, addressing mode, length)
OPCODES = {
    0x00: ('BRK', 'imp', 1), 0x01: ('ORA', 'izx', 2), 0x05: ('ORA', 'zp', 2),
    0x06: ('ASL', 'zp', 2), 0x08: ('PHP', 'imp', 1), 0x09: ('ORA', 'imm', 2),
    0x0A: ('ASL', 'acc', 1), 0x0B: ('ANC', 'imm', 2),  # undocumented
    0x0D: ('ORA', 'abs', 3), 0x0E: ('ASL', 'abs', 3),
    0x10: ('BPL', 'rel', 2), 0x11: ('ORA', 'izy', 2), 0x13: ('SLO', 'izy', 2),
    0x15: ('ORA', 'zpx', 2), 0x16: ('ASL', 'zpx', 2),
    0x18: ('CLC', 'imp', 1), 0x19: ('ORA', 'aby', 3), 0x1C: ('NOP', 'abx', 3),
    0x1D: ('ORA', 'abx', 3), 0x1E: ('ASL', 'abx', 3),
    0x20: ('JSR', 'abs', 3), 0x21: ('AND', 'izx', 2), 0x24: ('BIT', 'zp', 2),
    0x25: ('AND', 'zp', 2), 0x26: ('ROL', 'zp', 2), 0x27: ('RLA', 'zp', 2),
    0x28: ('PLP', 'imp', 1), 0x29: ('AND', 'imm', 2), 0x2A: ('ROL', 'acc', 1),
    0x2B: ('ANC', 'imm', 2),
    0x2C: ('BIT', 'abs', 3), 0x2D: ('AND', 'abs', 3), 0x2E: ('ROL', 'abs', 3),
    0x30: ('BMI', 'rel', 2), 0x31: ('AND', 'izy', 2),
    0x35: ('AND', 'zpx', 2), 0x36: ('ROL', 'zpx', 2),
    0x38: ('SEC', 'imp', 1), 0x39: ('AND', 'aby', 3), 0x3C: ('NOP', 'abx', 3),
    0x3D: ('AND', 'abx', 3), 0x3E: ('ROL', 'abx', 3),
    0x40: ('RTI', 'imp', 1), 0x41: ('EOR', 'izx', 2),
    0x45: ('EOR', 'zp', 2), 0x46: ('LSR', 'zp', 2),
    0x48: ('PHA', 'imp', 1), 0x49: ('EOR', 'imm', 2), 0x4A: ('LSR', 'acc', 1),
    0x4C: ('JMP', 'abs', 3), 0x4D: ('EOR', 'abs', 3), 0x4E: ('LSR', 'abs', 3),
    0x50: ('BVC', 'rel', 2), 0x51: ('EOR', 'izy', 2),
    0x55: ('EOR', 'zpx', 2), 0x56: ('LSR', 'zpx', 2),
    0x58: ('CLI', 'imp', 1), 0x59: ('EOR', 'aby', 3), 0x5C: ('NOP', 'abx', 3),
    0x5D: ('EOR', 'abx', 3), 0x5E: ('LSR', 'abx', 3),
    0x60: ('RTS', 'imp', 1), 0x61: ('ADC', 'izx', 2),
    0x65: ('ADC', 'zp', 2), 0x66: ('ROR', 'zp', 2),
    0x68: ('PLA', 'imp', 1), 0x69: ('ADC', 'imm', 2), 0x6A: ('ROR', 'acc', 1),
    0x6C: ('JMP', 'ind', 3), 0x6D: ('ADC', 'abs', 3), 0x6E: ('ROR', 'abs', 3),
    0x70: ('BVS', 'rel', 2), 0x71: ('ADC', 'izy', 2),
    0x75: ('ADC', 'zpx', 2), 0x76: ('ROR', 'zpx', 2),
    0x78: ('SEI', 'imp', 1), 0x79: ('ADC', 'aby', 3),
    0x7D: ('ADC', 'abx', 3), 0x7E: ('ROR', 'abx', 3),
    0x81: ('STA', 'izx', 2), 0x84: ('STY', 'zp', 2), 0x85: ('STA', 'zp', 2),
    0x86: ('STX', 'zp', 2), 0x87: ('SAX', 'zp', 2),
    0x88: ('DEY', 'imp', 1), 0x8A: ('TXA', 'imp', 1), 0x8B: ('ANE', 'imm', 2),
    0x8C: ('STY', 'abs', 3), 0x8D: ('STA', 'abs', 3), 0x8E: ('STX', 'abs', 3),
    0x8F: ('SAX', 'abs', 3),
    0x90: ('BCC', 'rel', 2), 0x91: ('STA', 'izy', 2), 0x93: ('SHA', 'izy', 2),
    0x94: ('STY', 'zpx', 2), 0x95: ('STA', 'zpx', 2), 0x96: ('STX', 'zpy', 2),
    0x98: ('TYA', 'imp', 1), 0x99: ('STA', 'aby', 3), 0x9A: ('TXS', 'imp', 1),
    0x9C: ('SHY', 'abx', 3),  # undocumented
    0x9D: ('STA', 'abx', 3), 0x9E: ('SHX', 'aby', 3),
    0xA0: ('LDY', 'imm', 2), 0xA1: ('LDA', 'izx', 2), 0xA2: ('LDX', 'imm', 2),
    0xA3: ('LAX', 'izx', 2),
    0xA4: ('LDY', 'zp', 2), 0xA5: ('LDA', 'zp', 2), 0xA6: ('LDX', 'zp', 2),
    0xA7: ('LAX', 'zp', 2),
    0xA8: ('TAY', 'imp', 1), 0xA9: ('LDA', 'imm', 2), 0xAA: ('TAX', 'imp', 1),
    0xAC: ('LDY', 'abs', 3), 0xAD: ('LDA', 'abs', 3), 0xAE: ('LDX', 'abs', 3),
    0xAF: ('LAX', 'abs', 3),
    0xB0: ('BCS', 'rel', 2), 0xB1: ('LDA', 'izy', 2), 0xB3: ('LAX', 'izy', 2),
    0xB4: ('LDY', 'zpx', 2), 0xB5: ('LDA', 'zpx', 2), 0xB6: ('LDX', 'zpy', 2),
    0xB8: ('CLV', 'imp', 1), 0xB9: ('LDA', 'aby', 3), 0xBA: ('TSX', 'imp', 1),
    0xBC: ('LDY', 'abx', 3), 0xBD: ('LDA', 'abx', 3), 0xBE: ('LDX', 'aby', 3),
    0xBF: ('LAX', 'aby', 3),
    0xC0: ('CPY', 'imm', 2), 0xC1: ('CMP', 'izx', 2),
    0xC3: ('DCP', 'izx', 2),
    0xC4: ('CPY', 'zp', 2), 0xC5: ('CMP', 'zp', 2), 0xC6: ('DEC', 'zp', 2),
    0xC8: ('INY', 'imp', 1), 0xC9: ('CMP', 'imm', 2), 0xCA: ('DEX', 'imp', 1),
    0xCB: ('SBX', 'imm', 2),
    0xCC: ('CPY', 'abs', 3), 0xCD: ('CMP', 'abs', 3), 0xCE: ('DEC', 'abs', 3),
    0xD0: ('BNE', 'rel', 2), 0xD1: ('CMP', 'izy', 2), 0xD2: ('JAM', 'imp', 1),
    0xD3: ('DCP', 'izy', 2),
    0xD5: ('CMP', 'zpx', 2), 0xD6: ('DEC', 'zpx', 2),
    0xD8: ('CLD', 'imp', 1), 0xD9: ('CMP', 'aby', 3), 0xDC: ('NOP', 'abx', 3),
    0xDD: ('CMP', 'abx', 3), 0xDE: ('DEC', 'abx', 3),
    0xE0: ('CPX', 'imm', 2), 0xE1: ('SBC', 'izx', 2), 0xE2: ('NOP', 'imm', 2),
    0xE4: ('CPX', 'zp', 2), 0xE5: ('SBC', 'zp', 2), 0xE6: ('INC', 'zp', 2),
    0xE8: ('INX', 'imp', 1), 0xE9: ('SBC', 'imm', 2), 0xEA: ('NOP', 'imp', 1),
    0xEC: ('CPX', 'abs', 3), 0xED: ('SBC', 'abs', 3), 0xEE: ('INC', 'abs', 3),
    0xF0: ('BEQ', 'rel', 2), 0xF1: ('SBC', 'izy', 2), 0xF2: ('JAM', 'imp', 1),
    0xF3: ('ISB', 'izy', 2),
    0xF5: ('SBC', 'zpx', 2), 0xF6: ('INC', 'zpx', 2),
    0xF8: ('SED', 'imp', 1), 0xF9: ('SBC', 'aby', 3),
    0xFD: ('SBC', 'abx', 3), 0xFE: ('INC', 'abx', 3),
}


def disasm(data, base, start=0, end=None):
    if end is None:
        end = len(data)
    pc = start
    lines = []
    while pc < end:
        op = data[pc]
        info = OPCODES.get(op)
        if info is None:
            lines.append(f"  ${base+pc:04X}: {op:02X}          .byte ${op:02X}  ; unknown opcode")
            pc += 1
            continue
        mnem, mode, length = info
        if pc + length > len(data):
            break
        raw = ' '.join(f'{data[pc+k]:02X}' for k in range(length))
        raw = raw.ljust(8)

        if mode == 'imp' or mode == 'acc':
            operand = ''
        elif mode == 'imm':
            operand = f' #${data[pc+1]:02X}'
        elif mode == 'zp':
            operand = f' ${data[pc+1]:02X}'
        elif mode == 'zpx':
            operand = f' ${data[pc+1]:02X},X'
        elif mode == 'zpy':
            operand = f' ${data[pc+1]:02X},Y'
        elif mode == 'abs':
            addr = data[pc+1] | (data[pc+2] << 8)
            operand = f' ${addr:04X}'
        elif mode == 'abx':
            addr = data[pc+1] | (data[pc+2] << 8)
            operand = f' ${addr:04X},X'
        elif mode == 'aby':
            addr = data[pc+1] | (data[pc+2] << 8)
            operand = f' ${addr:04X},Y'
        elif mode == 'ind':
            addr = data[pc+1] | (data[pc+2] << 8)
            operand = f' (${addr:04X})'
        elif mode == 'izx':
            operand = f' (${data[pc+1]:02X},X)'
        elif mode == 'izy':
            operand = f' (${data[pc+1]:02X}),Y'
        elif mode == 'rel':
            offset = data[pc+1]
            if offset >= 0x80:
                offset -= 256
            target = base + pc + 2 + offset
            operand = f' ${target:04X}'
        else:
            operand = ''

        lines.append(f"  ${base+pc:04X}: {raw}  {mnem}{operand}")
        pc += length
    return lines


def main():
    # Byte 0 = $00. In the Apple II boot ROM:
    # - Autostart ROM: byte 0 = sector count, execution starts at $0801
    # - Integer ROM: byte 0 is part of code, execution starts at $0800
    # Let's try both

    print("=== Boot sector byte 0 = $00 ===")
    print("  If sector count: 0 pages -> just sector 0, JMP $0801")
    print("  If code: $00 = BRK -> halt\n")

    # Hmm, $00 sector count doesn't make sense. Let me check:
    # The Autostart ROM actually reads byte 0 differently.
    # It multiplies by 2 or something. Let me just disassemble from both $0800 and $0801.

    print("=== Disassembly from $0800 ===")
    lines = disasm(BOOT, 0x0800, 0)
    for line in lines:
        print(line)

    # Also show the data region ($0844-$085C which seems like a table)
    print("\n=== Hex dump of table area $0844-$085C ===")
    for off in range(0x44, 0x5D, 16):
        h = ' '.join(f'{BOOT[off+c]:02X}' for c in range(min(16, 0x5D - off)))
        print(f"  ${0x0800+off:04X}: {h}")


if __name__ == '__main__':
    main()

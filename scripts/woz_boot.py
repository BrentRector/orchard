#!/usr/bin/env python3
"""
Analyze the boot sector from Apple Panic WOZ to understand the custom loader.
"""
import struct

# 6502 opcode table (minimal for disassembly)
OPCODES = {
    0x00: ("BRK", 1), 0x01: ("ORA (zp,X)", 2), 0x05: ("ORA zp", 2),
    0x06: ("ASL zp", 2), 0x08: ("PHP", 1), 0x09: ("ORA #imm", 2),
    0x0A: ("ASL A", 1), 0x0D: ("ORA abs", 3), 0x0E: ("ASL abs", 3),
    0x10: ("BPL rel", 2), 0x11: ("ORA (zp),Y", 2), 0x15: ("ORA zp,X", 2),
    0x18: ("CLC", 1), 0x19: ("ORA abs,Y", 3), 0x1D: ("ORA abs,X", 3),
    0x20: ("JSR abs", 3), 0x21: ("AND (zp,X)", 2), 0x24: ("BIT zp", 2),
    0x25: ("AND zp", 2), 0x26: ("ROL zp", 2), 0x28: ("PLP", 1),
    0x29: ("AND #imm", 2), 0x2A: ("ROL A", 1), 0x2C: ("BIT abs", 3),
    0x2D: ("AND abs", 3), 0x2E: ("ROL abs", 3),
    0x30: ("BMI rel", 2), 0x31: ("AND (zp),Y", 2), 0x35: ("AND zp,X", 2),
    0x38: ("SEC", 1), 0x39: ("AND abs,Y", 3), 0x3D: ("AND abs,X", 3),
    0x40: ("RTI", 1), 0x41: ("EOR (zp,X)", 2), 0x45: ("EOR zp", 2),
    0x46: ("LSR zp", 2), 0x48: ("PHA", 1), 0x49: ("EOR #imm", 2),
    0x4A: ("LSR A", 1), 0x4C: ("JMP abs", 3), 0x4D: ("EOR abs", 3),
    0x4E: ("LSR abs", 3),
    0x50: ("BVC rel", 2), 0x51: ("EOR (zp),Y", 2), 0x55: ("EOR zp,X", 2),
    0x58: ("CLI", 1), 0x59: ("EOR abs,Y", 3), 0x5D: ("EOR abs,X", 3),
    0x60: ("RTS", 1), 0x61: ("ADC (zp,X)", 2), 0x65: ("ADC zp", 2),
    0x66: ("ROR zp", 2), 0x68: ("PLA", 1), 0x69: ("ADC #imm", 2),
    0x6A: ("ROR A", 1), 0x6C: ("JMP (abs)", 3), 0x6D: ("ADC abs", 3),
    0x6E: ("ROR abs", 3),
    0x70: ("BVS rel", 2), 0x71: ("ADC (zp),Y", 2), 0x75: ("ADC zp,X", 2),
    0x78: ("SEI", 1), 0x79: ("ADC abs,Y", 3), 0x7D: ("ADC abs,X", 3),
    0x81: ("STA (zp,X)", 2), 0x84: ("STY zp", 2), 0x85: ("STA zp", 2),
    0x86: ("STX zp", 2), 0x88: ("DEY", 1), 0x8A: ("TXA", 1),
    0x8C: ("STY abs", 3), 0x8D: ("STA abs", 3), 0x8E: ("STX abs", 3),
    0x90: ("BCC rel", 2), 0x91: ("STA (zp),Y", 2), 0x94: ("STY zp,X", 2),
    0x95: ("STA zp,X", 2), 0x96: ("STX zp,Y", 2), 0x98: ("TYA", 1),
    0x99: ("STA abs,Y", 3), 0x9A: ("TXS", 1), 0x9D: ("STA abs,X", 3),
    0xA0: ("LDY #imm", 2), 0xA1: ("LDA (zp,X)", 2), 0xA2: ("LDX #imm", 2),
    0xA4: ("LDY zp", 2), 0xA5: ("LDA zp", 2), 0xA6: ("LDX zp", 2),
    0xA8: ("TAY", 1), 0xA9: ("LDA #imm", 2), 0xAA: ("TAX", 1),
    0xAC: ("LDY abs", 3), 0xAD: ("LDA abs", 3), 0xAE: ("LDX abs", 3),
    0xB0: ("BCS rel", 2), 0xB1: ("LDA (zp),Y", 2), 0xB4: ("LDY zp,X", 2),
    0xB5: ("LDA zp,X", 2), 0xB6: ("LDX zp,Y", 2), 0xB8: ("CLV", 1),
    0xB9: ("LDA abs,Y", 3), 0xBA: ("TSX", 1), 0xBC: ("LDY abs,X", 3),
    0xBD: ("LDA abs,X", 3), 0xBE: ("LDX abs,Y", 3),
    0xC0: ("CPY #imm", 2), 0xC1: ("CMP (zp,X)", 2), 0xC4: ("CPY zp", 2),
    0xC5: ("CMP zp", 2), 0xC6: ("DEC zp", 2), 0xC8: ("INY", 1),
    0xC9: ("CMP #imm", 2), 0xCA: ("DEX", 1), 0xCC: ("CPY abs", 3),
    0xCD: ("CMP abs", 3), 0xCE: ("DEC abs", 3),
    0xD0: ("BNE rel", 2), 0xD1: ("CMP (zp),Y", 2), 0xD5: ("CMP zp,X", 2),
    0xD8: ("CLD", 1), 0xD9: ("CMP abs,Y", 3), 0xDD: ("CMP abs,X", 3),
    0xDE: ("DEC abs,X", 3),
    0xE0: ("CPX #imm", 2), 0xE1: ("SBC (zp,X)", 2), 0xE4: ("CPX zp", 2),
    0xE5: ("SBC zp", 2), 0xE6: ("INC zp", 2), 0xE8: ("INX", 1),
    0xE9: ("SBC #imm", 2), 0xEA: ("NOP", 1), 0xEC: ("CPX abs", 3),
    0xED: ("SBC abs", 3), 0xEE: ("INC abs", 3),
    0xF0: ("BEQ rel", 2), 0xF1: ("SBC (zp),Y", 2), 0xF5: ("SBC zp,X", 2),
    0xF8: ("SED", 1), 0xF9: ("SBC abs,Y", 3), 0xFD: ("SBC abs,X", 3),
    0xFE: ("INC abs,X", 3),
}

def disasm(data, base_addr, count=None):
    """Simple linear disassembly."""
    addr = 0
    lines = []
    while addr < len(data):
        if count is not None and len(lines) >= count:
            break
        opcode = data[addr]
        if opcode in OPCODES:
            mnem, size = OPCODES[opcode]
            if addr + size > len(data):
                break
            if size == 1:
                line = f"${base_addr+addr:04X}: {opcode:02X}         {mnem}"
            elif size == 2:
                op1 = data[addr+1]
                if 'rel' in mnem:
                    offset = op1 if op1 < 128 else op1 - 256
                    target = base_addr + addr + 2 + offset
                    bname = mnem.split(' ')[0]
                    line = f"${base_addr+addr:04X}: {opcode:02X} {op1:02X}      {bname} ${target:04X}"
                elif '#imm' in mnem:
                    bname = mnem.split(' ')[0]
                    line = f"${base_addr+addr:04X}: {opcode:02X} {op1:02X}      {bname} #${op1:02X}"
                else:
                    bname = mnem.split(' ')[0]
                    mode = mnem.split(' ')[1] if ' ' in mnem else ''
                    line = f"${base_addr+addr:04X}: {opcode:02X} {op1:02X}      {bname} ${op1:02X}{mode.replace('zp','').replace(',',',')}"
                    line = f"${base_addr+addr:04X}: {opcode:02X} {op1:02X}      {mnem.replace('zp', f'${op1:02X}').replace('imm', f'${op1:02X}')}"
            elif size == 3:
                op1 = data[addr+1]
                op2 = data[addr+2]
                val = op1 | (op2 << 8)
                line = f"${base_addr+addr:04X}: {opcode:02X} {op1:02X} {op2:02X}   {mnem.replace('abs', f'${val:04X}').replace('imm', f'${val:04X}')}"
            lines.append(line)
            addr += size
        else:
            lines.append(f"${base_addr+addr:04X}: {opcode:02X}         .byte ${opcode:02X}")
            addr += 1
    return lines


def main():
    # Read the raw decoded data
    with open("E:/Apple/ApplePanic_original_raw.bin", 'rb') as f:
        raw = f.read()

    # Track 0 has 14 sectors. Sector 0 is the boot sector.
    boot = raw[0:256]

    print("=== Boot Sector (Track 0, Sector 0) ===")
    print("Apple II boot ROM loads T0S0 to $0800 and jumps to $0801")
    print()

    # The boot sector loads at $0800. First byte is sector count for stage 2.
    print(f"Byte 0: ${boot[0]:02X} (sector count for boot ROM to load)")
    print()

    # Disassemble from $0801
    lines = disasm(boot[1:], 0x0801)
    for line in lines:
        print(f"  {line}")

    # Also look at track 0 sector 1 (if exists) - this is typically
    # the continuation of boot code
    if len(raw) >= 512:
        print(f"\n=== Track 0, Sector 1 (at $0900) ===")
        sec1 = raw[256:512]
        print("First 32 bytes:", ' '.join(f'{b:02X}' for b in sec1[:32]))
        lines = disasm(sec1, 0x0900)
        for line in lines[:30]:
            print(f"  {line}")

    # Check all track 0 sectors
    print(f"\n=== Track 0 all sectors ===")
    for i in range(14):
        if i * 256 + 256 <= len(raw):
            sec = raw[i*256:(i+1)*256]
            first = ' '.join(f'{b:02X}' for b in sec[:16])
            print(f"  Sector {i:2d}: {first}...")

    # Look at the decoded sector data for patterns
    # Check if any tracks contain the known game code
    # The game code at $7000 starts with 4C 65 74 (JMP $7465)
    print(f"\n=== Searching for game patterns in decoded data ===")
    for i in range(len(raw) - 3):
        if raw[i:i+3] == bytes([0x4C, 0x65, 0x74]):
            track = 0
            offset = i
            cumul = 0
            for t in range(14):
                # Each track has 13 or 14 sectors
                t_sectors = 14 if t in (0, 2, 3, 4, 8, 11, 13) else 13
                t_bytes = t_sectors * 256
                if offset < cumul + t_bytes:
                    s_in_track = (offset - cumul) // 256
                    print(f"  JMP $7465 at raw offset ${i:04X} (track {t}, sector ~{s_in_track})")
                    break
                cumul += t_bytes

    # Check if the data might be XOR encrypted
    # Track 2 shows lots of 24 01 repeating which is suspicious
    print(f"\n=== Checking for XOR encryption patterns ===")
    # If the data were XOR'd with a repeating key, the most common byte
    # pairs would reveal the key
    for track_num in range(14):
        # Get this track's data from raw sequential dump
        offset = 0
        for t in range(track_num):
            t_sectors = 14 if t in (0, 2, 3, 4, 8, 11, 13) else 13
            offset += t_sectors * 256
        t_sectors = 14 if track_num in (0, 2, 3, 4, 8, 11, 13) else 13
        track_data = raw[offset:offset + t_sectors * 256]

        # Count most common bytes
        from collections import Counter
        c = Counter(track_data)
        top = c.most_common(3)
        print(f"  Track {track_num:2d}: most common bytes: {[(f'${b:02X}', n) for b, n in top]}")


if __name__ == '__main__':
    main()

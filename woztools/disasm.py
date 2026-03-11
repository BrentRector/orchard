"""
6502 disassembler with recursive descent code/data classification.

Provides both linear disassembly (for quick hex dumps) and recursive
descent disassembly (for accurate code vs data separation).
"""

# 6502 opcode table: opcode -> (mnemonic, addressing_mode, byte_count)
OPCODES = {
    0x00: ("BRK", "IMP", 1), 0x01: ("ORA", "IZX", 2), 0x05: ("ORA", "ZP", 2),
    0x06: ("ASL", "ZP", 2), 0x08: ("PHP", "IMP", 1), 0x09: ("ORA", "IMM", 2),
    0x0A: ("ASL", "ACC", 1), 0x0D: ("ORA", "ABS", 3), 0x0E: ("ASL", "ABS", 3),
    0x10: ("BPL", "REL", 2), 0x11: ("ORA", "IZY", 2), 0x15: ("ORA", "ZPX", 2),
    0x16: ("ASL", "ZPX", 2), 0x18: ("CLC", "IMP", 1), 0x19: ("ORA", "ABY", 3),
    0x1D: ("ORA", "ABX", 3), 0x1E: ("ASL", "ABX", 3),
    0x20: ("JSR", "ABS", 3), 0x21: ("AND", "IZX", 2), 0x24: ("BIT", "ZP", 2),
    0x25: ("AND", "ZP", 2), 0x26: ("ROL", "ZP", 2), 0x28: ("PLP", "IMP", 1),
    0x29: ("AND", "IMM", 2), 0x2A: ("ROL", "ACC", 1), 0x2C: ("BIT", "ABS", 3),
    0x2D: ("AND", "ABS", 3), 0x2E: ("ROL", "ABS", 3),
    0x30: ("BMI", "REL", 2), 0x31: ("AND", "IZY", 2), 0x35: ("AND", "ZPX", 2),
    0x36: ("ROL", "ZPX", 2), 0x38: ("SEC", "IMP", 1), 0x39: ("AND", "ABY", 3),
    0x3D: ("AND", "ABX", 3), 0x3E: ("ROL", "ABX", 3),
    0x40: ("RTI", "IMP", 1), 0x41: ("EOR", "IZX", 2), 0x45: ("EOR", "ZP", 2),
    0x46: ("LSR", "ZP", 2), 0x48: ("PHA", "IMP", 1), 0x49: ("EOR", "IMM", 2),
    0x4A: ("LSR", "ACC", 1), 0x4C: ("JMP", "ABS", 3), 0x4D: ("EOR", "ABS", 3),
    0x4E: ("LSR", "ABS", 3),
    0x50: ("BVC", "REL", 2), 0x51: ("EOR", "IZY", 2), 0x55: ("EOR", "ZPX", 2),
    0x56: ("LSR", "ZPX", 2), 0x58: ("CLI", "IMP", 1), 0x59: ("EOR", "ABY", 3),
    0x5D: ("EOR", "ABX", 3), 0x5E: ("LSR", "ABX", 3),
    0x60: ("RTS", "IMP", 1), 0x61: ("ADC", "IZX", 2), 0x65: ("ADC", "ZP", 2),
    0x66: ("ROR", "ZP", 2), 0x68: ("PLA", "IMP", 1), 0x69: ("ADC", "IMM", 2),
    0x6A: ("ROR", "ACC", 1), 0x6C: ("JMP", "IND", 3), 0x6D: ("ADC", "ABS", 3),
    0x6E: ("ROR", "ABS", 3),
    0x70: ("BVS", "REL", 2), 0x71: ("ADC", "IZY", 2), 0x75: ("ADC", "ZPX", 2),
    0x76: ("ROR", "ZPX", 2), 0x78: ("SEI", "IMP", 1), 0x79: ("ADC", "ABY", 3),
    0x7D: ("ADC", "ABX", 3), 0x7E: ("ROR", "ABX", 3),
    0x81: ("STA", "IZX", 2), 0x84: ("STY", "ZP", 2), 0x85: ("STA", "ZP", 2),
    0x86: ("STX", "ZP", 2), 0x88: ("DEY", "IMP", 1), 0x8A: ("TXA", "IMP", 1),
    0x8C: ("STY", "ABS", 3), 0x8D: ("STA", "ABS", 3), 0x8E: ("STX", "ABS", 3),
    0x90: ("BCC", "REL", 2), 0x91: ("STA", "IZY", 2), 0x94: ("STY", "ZPX", 2),
    0x95: ("STA", "ZPX", 2), 0x96: ("STX", "ZPY", 2), 0x98: ("TYA", "IMP", 1),
    0x99: ("STA", "ABY", 3), 0x9A: ("TXS", "IMP", 1), 0x9D: ("STA", "ABX", 3),
    0xA0: ("LDY", "IMM", 2), 0xA1: ("LDA", "IZX", 2), 0xA2: ("LDX", "IMM", 2),
    0xA4: ("LDY", "ZP", 2), 0xA5: ("LDA", "ZP", 2), 0xA6: ("LDX", "ZP", 2),
    0xA8: ("TAY", "IMP", 1), 0xA9: ("LDA", "IMM", 2), 0xAA: ("TAX", "IMP", 1),
    0xAC: ("LDY", "ABS", 3), 0xAD: ("LDA", "ABS", 3), 0xAE: ("LDX", "ABS", 3),
    0xB0: ("BCS", "REL", 2), 0xB1: ("LDA", "IZY", 2), 0xB4: ("LDY", "ZPX", 2),
    0xB5: ("LDA", "ZPX", 2), 0xB6: ("LDX", "ZPY", 2), 0xB8: ("CLV", "IMP", 1),
    0xB9: ("LDA", "ABY", 3), 0xBA: ("TSX", "IMP", 1), 0xBC: ("LDY", "ABX", 3),
    0xBD: ("LDA", "ABX", 3), 0xBE: ("LDX", "ABY", 3),
    0xC0: ("CPY", "IMM", 2), 0xC1: ("CMP", "IZX", 2), 0xC4: ("CPY", "ZP", 2),
    0xC5: ("CMP", "ZP", 2), 0xC6: ("DEC", "ZP", 2), 0xC8: ("INY", "IMP", 1),
    0xC9: ("CMP", "IMM", 2), 0xCA: ("DEX", "IMP", 1), 0xCC: ("CPY", "ABS", 3),
    0xCD: ("CMP", "ABS", 3), 0xCE: ("DEC", "ABS", 3),
    0xD0: ("BNE", "REL", 2), 0xD1: ("CMP", "IZY", 2), 0xD5: ("CMP", "ZPX", 2),
    0xD6: ("DEC", "ZPX", 2), 0xD8: ("CLD", "IMP", 1), 0xD9: ("CMP", "ABY", 3),
    0xDD: ("CMP", "ABX", 3), 0xDE: ("DEC", "ABX", 3),
    0xE0: ("CPX", "IMM", 2), 0xE1: ("SBC", "IZX", 2), 0xE4: ("CPX", "ZP", 2),
    0xE5: ("SBC", "ZP", 2), 0xE6: ("INC", "ZP", 2), 0xE8: ("INX", "IMP", 1),
    0xE9: ("SBC", "IMM", 2), 0xEA: ("NOP", "IMP", 1), 0xEC: ("CPX", "ABS", 3),
    0xED: ("SBC", "ABS", 3), 0xEE: ("INC", "ABS", 3),
    0xF0: ("BEQ", "REL", 2), 0xF1: ("SBC", "IZY", 2), 0xF5: ("SBC", "ZPX", 2),
    0xF6: ("INC", "ZPX", 2), 0xF8: ("SED", "IMP", 1), 0xF9: ("SBC", "ABY", 3),
    0xFD: ("SBC", "ABX", 3), 0xFE: ("INC", "ABX", 3),
    # Undocumented NMOS 6502 opcodes
    0x04: ("NOP", "ZP", 2), 0x44: ("NOP", "ZP", 2), 0x64: ("NOP", "ZP", 2),
    0x0C: ("NOP", "ABS", 3),
    0x14: ("NOP", "ZPX", 2), 0x34: ("NOP", "ZPX", 2), 0x54: ("NOP", "ZPX", 2),
    0x74: ("NOP", "ZPX", 2), 0xD4: ("NOP", "ZPX", 2), 0xF4: ("NOP", "ZPX", 2),
    0x1A: ("NOP", "IMP", 1), 0x3A: ("NOP", "IMP", 1), 0x5A: ("NOP", "IMP", 1),
    0x7A: ("NOP", "IMP", 1), 0xDA: ("NOP", "IMP", 1), 0xFA: ("NOP", "IMP", 1),
    0x80: ("NOP", "IMM", 2), 0x82: ("NOP", "IMM", 2), 0x89: ("NOP", "IMM", 2),
    0xC2: ("NOP", "IMM", 2), 0xE2: ("NOP", "IMM", 2),
    0x1C: ("NOP", "ABX", 3), 0x3C: ("NOP", "ABX", 3), 0x5C: ("NOP", "ABX", 3),
    0x7C: ("NOP", "ABX", 3), 0xDC: ("NOP", "ABX", 3), 0xFC: ("NOP", "ABX", 3),
    0xA3: ("LAX", "IZX", 2), 0xA7: ("LAX", "ZP", 2), 0xAF: ("LAX", "ABS", 3),
    0xB3: ("LAX", "IZY", 2), 0xB7: ("LAX", "ZPY", 2), 0xBF: ("LAX", "ABY", 3),
    0xAB: ("LAX", "IMM", 2),
    0x83: ("SAX", "IZX", 2), 0x87: ("SAX", "ZP", 2), 0x8F: ("SAX", "ABS", 3),
    0x97: ("SAX", "ZPY", 2),
    0xEB: ("SBC", "IMM", 2),
    0xC3: ("DCP", "IZX", 2), 0xC7: ("DCP", "ZP", 2), 0xCF: ("DCP", "ABS", 3),
    0xD3: ("DCP", "IZY", 2), 0xD7: ("DCP", "ZPX", 2), 0xDB: ("DCP", "ABY", 3),
    0xDF: ("DCP", "ABX", 3),
    0xE3: ("ISC", "IZX", 2), 0xE7: ("ISC", "ZP", 2), 0xEF: ("ISC", "ABS", 3),
    0xF3: ("ISC", "IZY", 2), 0xF7: ("ISC", "ZPX", 2), 0xFB: ("ISC", "ABY", 3),
    0xFF: ("ISC", "ABX", 3),
    0x03: ("SLO", "IZX", 2), 0x07: ("SLO", "ZP", 2), 0x0F: ("SLO", "ABS", 3),
    0x13: ("SLO", "IZY", 2), 0x17: ("SLO", "ZPX", 2), 0x1B: ("SLO", "ABY", 3),
    0x1F: ("SLO", "ABX", 3),
    0x23: ("RLA", "IZX", 2), 0x27: ("RLA", "ZP", 2), 0x2F: ("RLA", "ABS", 3),
    0x33: ("RLA", "IZY", 2), 0x37: ("RLA", "ZPX", 2), 0x3B: ("RLA", "ABY", 3),
    0x3F: ("RLA", "ABX", 3),
    0x43: ("SRE", "IZX", 2), 0x47: ("SRE", "ZP", 2), 0x4F: ("SRE", "ABS", 3),
    0x53: ("SRE", "IZY", 2), 0x57: ("SRE", "ZPX", 2), 0x5B: ("SRE", "ABY", 3),
    0x5F: ("SRE", "ABX", 3),
    0x63: ("RRA", "IZX", 2), 0x67: ("RRA", "ZP", 2), 0x6F: ("RRA", "ABS", 3),
    0x73: ("RRA", "IZY", 2), 0x77: ("RRA", "ZPX", 2), 0x7B: ("RRA", "ABY", 3),
    0x7F: ("RRA", "ABX", 3),
    0x0B: ("ANC", "IMM", 2), 0x2B: ("ANC", "IMM", 2),
    0x4B: ("ALR", "IMM", 2), 0x6B: ("ARR", "IMM", 2), 0xCB: ("AXS", "IMM", 2),
    0x02: ("KIL", "IMP", 1), 0x12: ("KIL", "IMP", 1), 0x22: ("KIL", "IMP", 1),
    0x32: ("KIL", "IMP", 1), 0x42: ("KIL", "IMP", 1), 0x52: ("KIL", "IMP", 1),
    0x62: ("KIL", "IMP", 1), 0x72: ("KIL", "IMP", 1), 0x92: ("KIL", "IMP", 1),
    0xB2: ("KIL", "IMP", 1), 0xD2: ("KIL", "IMP", 1), 0xF2: ("KIL", "IMP", 1),
    0x93: ("SHA", "IZY", 2), 0x9F: ("SHA", "ABY", 3),
    0x9E: ("SHX", "ABY", 3), 0x9C: ("SHY", "ABX", 3),
    0x9B: ("TAS", "ABY", 3), 0xBB: ("LAS", "ABY", 3),
    0x8B: ("XAA", "IMM", 2),
}


# Apple II hardware register comments (generic, no game-specific bindings)
HARDWARE_COMMENTS = {
    0xC000: "read keyboard",
    0xC010: "clear keyboard strobe",
    0xC020: "toggle cassette output",
    0xC030: "toggle speaker",
    0xC050: "set graphics mode",
    0xC051: "set text mode",
    0xC052: "set full screen",
    0xC053: "set mixed mode",
    0xC054: "select page 1",
    0xC055: "select page 2",
    0xC056: "set lo-res",
    0xC057: "set hi-res",
}

ROM_COMMENTS = {
    0xFDED: "COUT (print character)",
    0xFC58: "HOME (clear screen)",
    0xFE89: "INPORT",
    0xFE93: "OUTPORT",
    0xFCA8: "WAIT",
    0xFF58: "IORTS",
}


def disassemble_region(data, base_addr, start=None, end=None):
    """Simple linear disassembly of a byte buffer.

    Args:
        data: bytes/bytearray to disassemble
        base_addr: memory address of first byte
        start: start address (default: base_addr)
        end: end address (default: base_addr + len(data))

    Returns: list of formatted strings
    """
    if start is None:
        start = base_addr
    if end is None:
        end = base_addr + len(data)

    lines = []
    addr = start
    while addr < end:
        offset = addr - base_addr
        if offset >= len(data):
            break
        opcode = data[offset]
        if opcode not in OPCODES:
            lines.append(f"  ${addr:04X}: {opcode:02X}       ???")
            addr += 1
            continue

        mnem, mode, size = OPCODES[opcode]
        if offset + size > len(data):
            lines.append(f"  ${addr:04X}: {opcode:02X}       ???")
            break

        raw = ' '.join(f'{data[offset + j]:02X}' for j in range(size))
        raw = raw.ljust(8)

        if mode == "IMP" or mode == "ACC":
            operand = ""
        elif mode == "IMM":
            operand = f" #${data[offset + 1]:02X}"
        elif mode == "ZP":
            operand = f" ${data[offset + 1]:02X}"
        elif mode == "ZPX":
            operand = f" ${data[offset + 1]:02X},X"
        elif mode == "ZPY":
            operand = f" ${data[offset + 1]:02X},Y"
        elif mode == "ABS":
            val = data[offset + 1] | (data[offset + 2] << 8)
            operand = f" ${val:04X}"
        elif mode == "ABX":
            val = data[offset + 1] | (data[offset + 2] << 8)
            operand = f" ${val:04X},X"
        elif mode == "ABY":
            val = data[offset + 1] | (data[offset + 2] << 8)
            operand = f" ${val:04X},Y"
        elif mode == "IND":
            val = data[offset + 1] | (data[offset + 2] << 8)
            operand = f" (${val:04X})"
        elif mode == "IZX":
            operand = f" (${data[offset + 1]:02X},X)"
        elif mode == "IZY":
            operand = f" (${data[offset + 1]:02X}),Y"
        elif mode == "REL":
            off8 = data[offset + 1]
            if off8 > 127:
                off8 -= 256
            target = (addr + 2 + off8) & 0xFFFF
            operand = f" ${target:04X}"
        else:
            operand = ""

        comment = ""
        if mode == "ABS" and size == 3:
            target = data[offset + 1] | (data[offset + 2] << 8)
            if target in HARDWARE_COMMENTS:
                comment = f"  ; {HARDWARE_COMMENTS[target]}"
            if mnem == "JSR" and target in ROM_COMMENTS:
                comment = f"  ; {ROM_COMMENTS[target]}"

        lines.append(f"  ${addr:04X}: {raw} {mnem}{operand}{comment}")
        addr += size

    return lines


class Disassembler:
    """Recursive descent 6502 disassembler with code/data classification.

    Usage:
        dis = Disassembler(mem, start=0x4000, end=0xA800)
        dis.data_regions = [(0x6000, 0x7000)]  # known data
        dis.trace(0x4000)  # trace from entry point
        dis.name_labels()
        add_hardware_comments(dis, mem)
        lines = dis.disassemble_range(0x4000, 0xA800)
    """

    UNDOC_MNEMONICS = frozenset((
        "SLO", "RLA", "SRE", "RRA", "SAX", "LAX", "DCP", "ISC",
        "ANC", "ALR", "ARR", "AXS", "KIL", "SHA", "SHX", "SHY",
        "TAS", "LAS", "XAA",
    ))

    def __init__(self, mem, start=0, end=None):
        self.mem = mem
        self.start = start
        self.end = end or len(mem)
        self.code = set()
        self.labels = {}
        self.comments = {}
        self.data_regions = []
        self.entry_points = []

    def in_data_region(self, addr):
        for ds, de in self.data_regions:
            if ds <= addr < de:
                return True
        return False

    def trace(self, addr, depth=0):
        if depth > 5000:
            return
        while self.start <= addr < self.end:
            if addr in self.code:
                return
            if self.in_data_region(addr):
                return
            opcode = self.mem[addr]
            if opcode not in OPCODES:
                return
            mnem, mode, size = OPCODES[opcode]
            if mnem in self.UNDOC_MNEMONICS:
                return
            if mnem == "NOP" and opcode != 0xEA:
                return
            if addr + size > self.end:
                return
            if any(self.in_data_region(addr + i) for i in range(1, size)):
                return
            for i in range(size):
                self.code.add(addr + i)

            if mode == "REL" and size == 2:
                offset = self.mem[addr + 1]
                if offset > 127:
                    offset -= 256
                target = addr + 2 + offset
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None
                    self.trace(target, depth + 1)

            if mnem == "JSR" and size == 3:
                target = self.mem[addr + 1] | (self.mem[addr + 2] << 8)
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None
                    self.trace(target, depth + 1)

            if mnem == "JMP" and mode == "ABS" and size == 3:
                target = self.mem[addr + 1] | (self.mem[addr + 2] << 8)
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None
                    self.trace(target, depth + 1)
                return

            if mnem == "JMP" and mode == "IND":
                return

            if mnem in ("RTS", "RTI", "BRK"):
                return

            addr += size

    def name_labels(self):
        sorted_addrs = sorted(self.labels.keys())
        for addr in sorted_addrs:
            if self.labels[addr] is not None:
                continue
            is_sub = False
            for check_addr in self.code:
                if self.mem[check_addr] == 0x20:  # JSR
                    if check_addr + 2 < self.end:
                        target = self.mem[check_addr + 1] | (self.mem[check_addr + 2] << 8)
                        if target == addr:
                            is_sub = True
                            break
            if is_sub:
                self.labels[addr] = f"SUB_{addr:04X}"
            else:
                self.labels[addr] = f"L_{addr:04X}"

    def format_operand(self, addr, mnem, mode, size):
        if mode == "IMP" or mode == "ACC":
            return ""
        elif mode == "IMM":
            return f"#${self.mem[addr+1]:02X}"
        elif mode == "ZP":
            return f"${self.mem[addr+1]:02X}"
        elif mode == "ZPX":
            return f"${self.mem[addr+1]:02X},X"
        elif mode == "ZPY":
            return f"${self.mem[addr+1]:02X},Y"
        elif mode in ("ABS", "ABX", "ABY"):
            val = self.mem[addr+1] | (self.mem[addr+2] << 8)
            label = self.labels.get(val)
            suffix = ""
            if mode == "ABX":
                suffix = ",X"
            elif mode == "ABY":
                suffix = ",Y"
            if label:
                return f"{label}{suffix}"
            return f"${val:04X}{suffix}"
        elif mode == "IND":
            val = self.mem[addr+1] | (self.mem[addr+2] << 8)
            label = self.labels.get(val)
            if label:
                return f"({label})"
            return f"(${val:04X})"
        elif mode == "IZX":
            return f"(${self.mem[addr+1]:02X},X)"
        elif mode == "IZY":
            return f"(${self.mem[addr+1]:02X}),Y"
        elif mode == "REL":
            offset = self.mem[addr+1]
            if offset > 127:
                offset -= 256
            target = addr + 2 + offset
            label = self.labels.get(target)
            if label:
                return label
            return f"${target:04X}"
        return ""

    def disassemble_range(self, start, end):
        """Disassemble a range with code/data classification.
        Returns list of (addr, label, instruction, comment) tuples."""
        lines = []
        addr = start
        while addr < end:
            label = self.labels.get(addr, "")
            label_str = label if label else ""

            if addr in self.code:
                opcode = self.mem[addr]
                if opcode in OPCODES:
                    mnem, mode, size = OPCODES[opcode]
                    operand = self.format_operand(addr, mnem, mode, size)
                    instr = f"{mnem} {operand}" if operand else mnem
                    comment = self.comments.get(addr, "")
                    lines.append((addr, label_str, instr, comment))
                    addr += size
                else:
                    lines.append((addr, label_str, f"DFB ${self.mem[addr]:02X}", ""))
                    addr += 1
            else:
                data_start = addr
                data_bytes = []
                while addr < end and addr not in self.code:
                    if addr in self.labels and addr != data_start:
                        break
                    data_bytes.append(self.mem[addr])
                    addr += 1
                    if len(data_bytes) >= 16:
                        break

                if len(data_bytes) >= 8 and all(b == data_bytes[0] for b in data_bytes):
                    fill_val = data_bytes[0]
                    while addr < end and addr not in self.code:
                        if addr in self.labels:
                            break
                        if self.mem[addr] != fill_val:
                            break
                        data_bytes.append(self.mem[addr])
                        addr += 1
                    comment = self.comments.get(data_start, "")
                    lines.append((data_start, label_str,
                                  f"DS   {len(data_bytes)},${fill_val:02X}", comment))
                else:
                    hex_str = "".join(f"{b:02X}" for b in data_bytes)
                    comment = self.comments.get(data_start, "")
                    lines.append((data_start, label_str, f"HEX {hex_str}", comment))

        return lines


def add_hardware_comments(dis, mem):
    """Add comments for hardware register accesses to a Disassembler."""
    for addr in sorted(dis.code):
        opcode = mem[addr]
        if opcode in OPCODES:
            mnem, mode, size = OPCODES[opcode]
            if mode == "ABS" and size == 3:
                target = mem[addr + 1] | (mem[addr + 2] << 8)
                if target in HARDWARE_COMMENTS:
                    dis.comments[addr] = HARDWARE_COMMENTS[target]
                if mnem == "JSR" and target in ROM_COMMENTS:
                    dis.comments[addr] = ROM_COMMENTS[target]

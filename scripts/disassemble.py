#!/usr/bin/env python3
"""
Apple Panic (1981) - Disassembler
Reads the runtime memory image and produces a Merlin32-syntax assembly source.
Uses recursive descent from known entry points to classify code vs data.
"""

import sys
from collections import defaultdict

# 6502 instruction table: opcode -> (mnemonic, addressing_mode, byte_count)
# Addressing modes: IMP, ACC, IMM, ZP, ZPX, ZPY, ABS, ABX, ABY, IND, IZX, IZY, REL
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
    # --- Undocumented NMOS 6502 opcodes used by games ---
    # NOP variants (skip bytes, do nothing)
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
    # LAX (LDA+LDX combined)
    0xA3: ("LAX", "IZX", 2), 0xA7: ("LAX", "ZP", 2), 0xAF: ("LAX", "ABS", 3),
    0xB3: ("LAX", "IZY", 2), 0xB7: ("LAX", "ZPY", 2), 0xBF: ("LAX", "ABY", 3),
    # SAX (STA & STX combined)
    0x83: ("SAX", "IZX", 2), 0x87: ("SAX", "ZP", 2), 0x8F: ("SAX", "ABS", 3),
    0x97: ("SAX", "ZPY", 2),
    # SBC variant
    0xEB: ("SBC", "IMM", 2),
    # DCP (DEC + CMP)
    0xC3: ("DCP", "IZX", 2), 0xC7: ("DCP", "ZP", 2), 0xCF: ("DCP", "ABS", 3),
    0xD3: ("DCP", "IZY", 2), 0xD7: ("DCP", "ZPX", 2), 0xDB: ("DCP", "ABY", 3),
    0xDF: ("DCP", "ABX", 3),
    # ISC/ISB (INC + SBC)
    0xE3: ("ISC", "IZX", 2), 0xE7: ("ISC", "ZP", 2), 0xEF: ("ISC", "ABS", 3),
    0xF3: ("ISC", "IZY", 2), 0xF7: ("ISC", "ZPX", 2), 0xFB: ("ISC", "ABY", 3),
    0xFF: ("ISC", "ABX", 3),
    # SLO (ASL + ORA)
    0x03: ("SLO", "IZX", 2), 0x07: ("SLO", "ZP", 2), 0x0F: ("SLO", "ABS", 3),
    0x13: ("SLO", "IZY", 2), 0x17: ("SLO", "ZPX", 2), 0x1B: ("SLO", "ABY", 3),
    0x1F: ("SLO", "ABX", 3),
    # RLA (ROL + AND)
    0x23: ("RLA", "IZX", 2), 0x27: ("RLA", "ZP", 2), 0x2F: ("RLA", "ABS", 3),
    0x33: ("RLA", "IZY", 2), 0x37: ("RLA", "ZPX", 2), 0x3B: ("RLA", "ABY", 3),
    0x3F: ("RLA", "ABX", 3),
    # SRE (LSR + EOR)
    0x43: ("SRE", "IZX", 2), 0x47: ("SRE", "ZP", 2), 0x4F: ("SRE", "ABS", 3),
    0x53: ("SRE", "IZY", 2), 0x57: ("SRE", "ZPX", 2), 0x5B: ("SRE", "ABY", 3),
    0x5F: ("SRE", "ABX", 3),
    # RRA (ROR + ADC)
    0x63: ("RRA", "IZX", 2), 0x67: ("RRA", "ZP", 2), 0x6F: ("RRA", "ABS", 3),
    0x73: ("RRA", "IZY", 2), 0x77: ("RRA", "ZPX", 2), 0x7B: ("RRA", "ABY", 3),
    0x7F: ("RRA", "ABX", 3),
    # ANC
    0x0B: ("ANC", "IMM", 2), 0x2B: ("ANC", "IMM", 2),
    # ALR (AND + LSR)
    0x4B: ("ALR", "IMM", 2),
    # ARR (AND + ROR)
    0x6B: ("ARR", "IMM", 2),
    # AXS/SBX
    0xCB: ("AXS", "IMM", 2),
    # Remaining: treat unknown single-byte as NOP to avoid blocking trace
    0x02: ("KIL", "IMP", 1), 0x12: ("KIL", "IMP", 1), 0x22: ("KIL", "IMP", 1),
    0x32: ("KIL", "IMP", 1), 0x42: ("KIL", "IMP", 1), 0x52: ("KIL", "IMP", 1),
    0x62: ("KIL", "IMP", 1), 0x72: ("KIL", "IMP", 1), 0x92: ("KIL", "IMP", 1),
    0xB2: ("KIL", "IMP", 1), 0xD2: ("KIL", "IMP", 1), 0xF2: ("KIL", "IMP", 1),
    # SHA/SHX/SHY/TAS/LAS (rare but exist)
    0x93: ("SHA", "IZY", 2), 0x9F: ("SHA", "ABY", 3),
    0x9E: ("SHX", "ABY", 3), 0x9C: ("SHY", "ABX", 3),
    0x9B: ("TAS", "ABY", 3), 0xBB: ("LAS", "ABY", 3),
    0xAB: ("LAX", "IMM", 2),
}

def load_image(path):
    with open(path, 'rb') as f:
        return bytearray(f.read())

def is_branch(mnemonic):
    return mnemonic in ("BPL","BMI","BVC","BVS","BCC","BCS","BNE","BEQ")

def is_unconditional_end(mnemonic):
    return mnemonic in ("RTS","RTI","JMP","BRK")

class Disassembler:
    def __init__(self, mem, start=0, end=None):
        self.mem = mem
        self.start = start
        self.end = end or len(mem)
        self.code = set()       # addresses that are code
        self.labels = {}        # addr -> label name
        self.comments = {}      # addr -> comment
        self.data_regions = []  # (start, end) pairs that must NOT be traced as code
        self.entry_points = []

    def in_data_region(self, addr):
        """Check if an address falls within a known data region."""
        for ds, de in self.data_regions:
            if ds <= addr < de:
                return True
        return False

    # Opcodes that are undocumented/illegal on NMOS 6502 — commercial 1981
    # software would never use these. Stop tracing if encountered.
    UNDOC_MNEMONICS = frozenset(("SLO","RLA","SRE","RRA","SAX","LAX","DCP","ISC",
                                 "ANC","ALR","ARR","AXS","KIL","SHA","SHX","SHY",
                                 "TAS","LAS"))

    def trace(self, addr, depth=0):
        """Recursive descent tracing from an address."""
        if depth > 5000:
            return
        while self.start <= addr < self.end:
            if addr in self.code:
                return  # already traced
            if self.in_data_region(addr):
                return  # known data, don't trace
            opcode = self.mem[addr]
            if opcode not in OPCODES:
                return  # hit data or illegal opcode
            mnem, mode, size = OPCODES[opcode]
            # Stop at undocumented opcodes — we hit data
            if mnem in self.UNDOC_MNEMONICS:
                return
            # Also stop at unofficial NOP variants (only $EA is legit)
            if mnem == "NOP" and opcode != 0xEA:
                return
            # Check bounds
            if addr + size > self.end:
                return
            # Don't trace into data regions
            if any(self.in_data_region(addr + i) for i in range(1, size)):
                return
            # Mark as code
            for i in range(size):
                self.code.add(addr + i)

            # Handle branches
            if mode == "REL" and size == 2:
                offset = self.mem[addr + 1]
                if offset > 127:
                    offset -= 256
                target = addr + 2 + offset
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None  # will be named later
                    self.trace(target, depth + 1)

            # Handle JSR
            if mnem == "JSR" and size == 3:
                target = self.mem[addr+1] | (self.mem[addr+2] << 8)
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None
                    self.trace(target, depth + 1)

            # Handle JMP absolute
            if mnem == "JMP" and mode == "ABS" and size == 3:
                target = self.mem[addr+1] | (self.mem[addr+2] << 8)
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None
                    self.trace(target, depth + 1)
                return  # unconditional jump, stop linear tracing

            # Handle JMP indirect
            if mnem == "JMP" and mode == "IND":
                return  # can't follow indirect jump statically

            if mnem in ("RTS", "RTI", "BRK"):
                return

            addr += size

    def name_labels(self):
        """Assign names to all discovered labels."""
        # Sort labels by address
        sorted_addrs = sorted(self.labels.keys())
        sub_count = 0
        loc_count = 0
        for addr in sorted_addrs:
            if self.labels[addr] is not None:
                continue
            # Check if this is a JSR target (subroutine)
            is_sub = False
            # Search for JSR to this address in code
            for check_addr in self.code:
                if self.mem[check_addr] == 0x20:  # JSR
                    if check_addr + 2 < self.end:
                        target = self.mem[check_addr+1] | (self.mem[check_addr+2] << 8)
                        if target == addr:
                            is_sub = True
                            break
            if is_sub:
                self.labels[addr] = f"SUB_{addr:04X}"
            else:
                self.labels[addr] = f"L_{addr:04X}"

    def format_operand(self, addr, mnem, mode, size):
        """Format the operand in Merlin32 syntax."""
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
        elif mode == "ABS":
            val = self.mem[addr+1] | (self.mem[addr+2] << 8)
            if val in self.labels and self.labels[val]:
                return self.labels[val]
            return f"${val:04X}"
        elif mode == "ABX":
            val = self.mem[addr+1] | (self.mem[addr+2] << 8)
            if val in self.labels and self.labels[val]:
                return f"{self.labels[val]},X"
            return f"${val:04X},X"
        elif mode == "ABY":
            val = self.mem[addr+1] | (self.mem[addr+2] << 8)
            if val in self.labels and self.labels[val]:
                return f"{self.labels[val]},Y"
            return f"${val:04X},Y"
        elif mode == "IND":
            val = self.mem[addr+1] | (self.mem[addr+2] << 8)
            if val in self.labels and self.labels[val]:
                return f"({self.labels[val]})"
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
            if target in self.labels and self.labels[target]:
                return self.labels[target]
            return f"${target:04X}"
        return ""

    def disassemble_range(self, start, end):
        """Disassemble a range, returning list of (addr, label, instruction, comment) tuples."""
        lines = []
        addr = start
        while addr < end:
            label = self.labels.get(addr, "")
            if label:
                label_str = label
            else:
                label_str = ""

            if addr in self.code:
                opcode = self.mem[addr]
                if opcode in OPCODES:
                    mnem, mode, size = OPCODES[opcode]
                    operand = self.format_operand(addr, mnem, mode, size)
                    if operand:
                        instr = f"{mnem} {operand}"
                    else:
                        instr = mnem
                    comment = self.comments.get(addr, "")
                    lines.append((addr, label_str, instr, comment))
                    addr += size
                else:
                    lines.append((addr, label_str, f"DFB ${self.mem[addr]:02X}", "illegal opcode"))
                    addr += 1
            else:
                # Data byte - collect consecutive data bytes
                data_start = addr
                data_bytes = []
                while addr < end and addr not in self.code:
                    if addr in self.labels and addr != data_start:
                        break  # stop at label boundary
                    data_bytes.append(self.mem[addr])
                    addr += 1
                    if len(data_bytes) >= 16:
                        break

                # Check for runs of identical bytes (use DS directive)
                if len(data_bytes) >= 8 and all(b == data_bytes[0] for b in data_bytes):
                    # Peek ahead to see if the run continues
                    fill_val = data_bytes[0]
                    while addr < end and addr not in self.code:
                        if addr in self.labels:
                            break
                        if self.mem[addr] != fill_val:
                            break
                        data_bytes.append(self.mem[addr])
                        addr += 1
                    comment = self.comments.get(data_start, "")
                    if fill_val == 0x00:
                        lines.append((data_start, label_str, f"DS   {len(data_bytes)},$00", comment + " ; zeroed"))
                    elif fill_val == 0xFF:
                        lines.append((data_start, label_str, f"DS   {len(data_bytes)},$FF", comment + " ; unused"))
                    else:
                        lines.append((data_start, label_str, f"DS   {len(data_bytes)},${fill_val:02X}", comment))
                else:
                    hex_str = "".join(f"{b:02X}" for b in data_bytes)
                    comment = self.comments.get(data_start, "")
                    lines.append((data_start, label_str, f"HEX {hex_str}", comment))

        return lines

    def linear_disassemble(self, start, end):
        """Force-disassemble a range linearly as code (no tracing needed).
        Returns list of (addr, label, instruction, comment) tuples."""
        lines = []
        addr = start
        while addr < end:
            label = self.labels.get(addr, "")
            label_str = label if label else ""
            opcode = self.mem[addr]
            if opcode in OPCODES:
                mnem, mode, size = OPCODES[opcode]
                if addr + size > end:
                    # Not enough bytes for full instruction, emit as data
                    remaining = end - addr
                    hex_str = "".join(f"{self.mem[addr+i]:02X}" for i in range(remaining))
                    lines.append((addr, label_str, f"HEX {hex_str}", ""))
                    addr = end
                    break
                operand = self.format_operand(addr, mnem, mode, size)
                if operand:
                    instr = f"{mnem} {operand}"
                else:
                    instr = mnem
                comment = self.comments.get(addr, "")
                lines.append((addr, label_str, instr, comment))
                addr += size
            else:
                # Unknown opcode - emit as data byte
                lines.append((addr, label_str, f"DFB ${self.mem[addr]:02X}", f"unknown opcode ${opcode:02X}"))
                addr += 1
        return lines


def add_hardware_comments(dis, mem):
    """Add comments for hardware register accesses."""
    hw_comments = {
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
    rom_comments = {
        0xFDED: "COUT (print character)",
        0xFC58: "HOME (clear screen)",
        0xFE89: "INPORT",
        0xFE93: "OUTPORT",
    }

    for addr in sorted(dis.code):
        opcode = mem[addr]
        if opcode in OPCODES:
            mnem, mode, size = OPCODES[opcode]
            if mode == "ABS" and size == 3:
                target = mem[addr+1] | (mem[addr+2] << 8)
                if target in hw_comments:
                    dis.comments[addr] = hw_comments[target]
                if mnem == "JSR" and target in rom_comments:
                    dis.comments[addr] = rom_comments[target]
            if mode == "IMM" and mnem == "CMP":
                val = mem[addr+1]
                key_names = {
                    0xC9: "key 'I' (up)", 0xCA: "key 'J' (left)",
                    0xCB: "key 'K' (right)", 0xCD: "key 'M' (down)",
                    0xC4: "key 'D' (dig)", 0xD5: "key 'U' (dig)",
                    0xD8: "key 'X' (stomp)", 0xC5: "key 'E' (stomp)",
                    0x8D: "carriage return",
                }
                if val in key_names:
                    dis.comments[addr] = key_names[val]


def generate_source(mem, output_path):
    """Generate the full Merlin32 assembly source."""

    # Create disassembler for the main game code region
    dis = Disassembler(mem, 0x6000, 0xA800)

    # Define known data regions that must NOT be traced as code
    # $6000-$6FFF: Pre-game data (shape tables, level data copied to low memory)
    # $7003-$706B: Font bitmaps (12 chars × 8 bytes) + HGR address constants
    dis.data_regions = [
        (0x6000, 0x7000),   # Pre-entry data (not code)
        (0x7003, 0x706B),   # Font bitmaps + HGR constants
    ]

    # Known entry points
    entry_points = [0x7000]  # JMP $7465 at $7000

    # First trace from $7000
    dis.trace(0x7000)

    # Also trace the clean loader
    dis_loader = Disassembler(mem, 0x1900, 0x193A)
    dis_loader.trace(0x1900)

    # Multi-pass: follow all JSR/JMP targets, then gap-fill, repeat
    passes = 0
    while passes < 50:
        prev_code_size = len(dis.code)

        # Pass A: Follow all JSR/JMP targets from known code
        for addr in sorted(dis.code):
            opcode = mem[addr]
            if opcode in OPCODES:
                mnem, mode, size = OPCODES[opcode]
                if mnem in ("JSR", "JMP") and mode == "ABS" and size == 3:
                    target = mem[addr+1] | (mem[addr+2] << 8)
                    if 0x6000 <= target < 0xA800 and target not in dis.code:
                        dis.trace(target)

        # Pass B: Gap-fill — try tracing from untouched regions between code blocks.
        # Many subroutines are reached via indirect jumps or jump tables and won't
        # be found by recursive descent alone. We probe each gap and accept if the
        # trace produces "reasonable" code (no undocumented opcodes, terminates cleanly).
        LEGIT_OPCODES = set()
        for op, (mn, md, sz) in OPCODES.items():
            if mn not in ("SLO","RLA","SRE","RRA","SAX","LAX","DCP","ISC","ANC",
                          "ALR","ARR","AXS","KIL","SHA","SHX","SHY","TAS","LAS",
                          "NOP") or (mn == "NOP" and op == 0xEA):
                LEGIT_OPCODES.add(op)

        for probe_addr in range(0x706B, 0xA800):
            if probe_addr in dis.code:
                continue
            if dis.in_data_region(probe_addr):
                continue
            opcode = mem[probe_addr]
            if opcode not in LEGIT_OPCODES:
                continue
            # Try a speculative trace — save state and roll back if bad
            saved_code = set(dis.code)
            saved_labels = dict(dis.labels)
            dis.trace(probe_addr)
            new_code = dis.code - saved_code
            if not new_code:
                continue
            # Check quality: no undocumented opcodes at instruction starts
            # We need to walk instructions, not just check every byte
            has_undoc = False
            # Find instruction start addresses (lowest addr in each instruction)
            instr_starts = set()
            for a in sorted(new_code):
                if a in instr_starts:
                    continue
                if mem[a] in OPCODES:
                    mn, md, sz = OPCODES[mem[a]]
                    instr_starts.add(a)
                    if mn in ("SLO","RLA","SRE","RRA","SAX","LAX","DCP","ISC","ANC",
                              "ALR","ARR","AXS","KIL","SHA","SHX","SHY","TAS","LAS"):
                        has_undoc = True
                        break
                    if mn == "NOP" and mem[a] != 0xEA:
                        has_undoc = True
                        break
                    # Skip operand bytes
                    for j in range(1, sz):
                        instr_starts.add(a + j)  # mark as "part of instruction"
            if has_undoc or len(new_code) < 3:
                # Roll back — this was likely data, not code
                dis.code = saved_code
                dis.labels = saved_labels
            # else: keep the new code

        passes += 1
        if len(dis.code) == prev_code_size:
            break  # Converged

    # Name all labels
    dis.name_labels()
    dis_loader.name_labels()
    dis_loader.labels[0x1900] = "INIT"

    # Add well-known labels with descriptive names
    sub_names = {
        0x7000: "GAME_START",
        0x706B: "HGR_CALC_ADDR",
        0x709C: "HGR_LINE_SETUP",
        0x70D0: "SPLIT_DIGITS",
        0x70EA: "SCREEN_SAVE",
        0x7125: "SCREEN_RESTORE",
        0x7165: "DRAW_NUMBER",
        0x71B5: "DRAW_CHAR",
        0x71E8: "SFX_SCORE",
        0x720F: "SFX_EXTRA_LIFE",
        0x722F: "DRAW_LIVES",
        0x7264: "DRAW_SCORE",
        0x72A0: "ADD_SCORE",
        0x72DF: "DRAW_BONUS",
        0x731C: "TICK_BONUS",
        0x7387: "DRAW_HISCORE",
        0x73C3: "BONUS_TO_SCORE",
        0x73FD: "CLEAR_STATUS_BAR",
        0x7436: "CHECK_HISCORE",
        0x7465: "GAME_INIT",
        0x7552: "SELECT_BG_PATTERN",
        0x757C: "CLEAR_ENEMY_STATE",
        0x758B: "LEVEL_SETUP",
        0x763B: "CHECK_EXTRA_LIFE",
        0x768E: "SHOW_LIVES_SFX",
        0x769F: "DELAY_LOOP",
        0x7A3C: "HGR_CALC_ADDR_ALT",
        0x7A6D: "SPRITE_POS_SETUP",
        0x7A8C: "READ_KEYBOARD",
        0x7AB4: "PLAYER_MOVE",
        0x7BD5: "SPRITE_WALK_R",
        0x7BED: "SPRITE_WALK_L",
        0x7C05: "SPRITE_CLIMB",
        0x7C1E: "SPRITE_DIG_L",
        0x7C35: "SPRITE_DIG_R",
        0x7C4C: "SPRITE_STAND",
        0x7C66: "DRAW_PLAYER",
        0x7CDD: "CHECK_PLATFORM",
        0x7D19: "SPRITE_DISPATCH",
        0x7D60: "ERASE_PLAYER",
        0x7DFD: "UPDATE_PLAYER",
        0x7E09: "MOVE_AND_DRAW",
        0x7E1D: "COPY_HGR_PAGES",
        0x7E40: "DRAW_STATUS_BORDER",
        0x7E9E: "CLEAR_SCREEN",
        0x7EC4: "DRAW_PLATFORMS",
        0x7F19: "DRAW_PLAT_TOP",
        0x7F3E: "DRAW_PLAT_BOT",
        0x7F63: "DRAW_FLOORS",
        0x7F7F: "DRAW_FLOOR",
        0x7FD3: "GAME_DELAY",
        0x801A: "LOOKUP_HOLE",
        0x80C3: "CLEAR_HOLES",
        0x80D3: "VALIDATE_DIG",
        0x817F: "VALIDATE_STOMP",
        0x81A9: "CHECK_LADDER",
        0x8272: "DIG_ANIM",
        0x82C1: "FIND_HOLE_SLOT",
        0x82DA: "CREATE_HOLE",
        0x8311: "DRAW_HOLE",
        0x8393: "DRAW_TIMER_BAR",
        0x83C6: "TICK_TIMER_BAR",
        0x8402: "FILL_HOLE",
        0x844E: "STOMP_ANIM",
        0x848E: "SFX_IMPACT",
        0x84A4: "ERASE_ENEMY",
        0x850F: "DRAW_ENEMY",
        0x860E: "UPDATE_ENEMY_SPR",
        0x8650: "DRAW_ENEMY_MOVE",
        0x8702: "CHECK_COLLISION",
        0x87C6: "ENEMY_AI_TICK",
        0x87F5: "ENEMY_STOP",
        0x8854: "ENEMY_VS_ENEMY",
        0x8890: "ENEMY_FLOOR_CHK",
        0x890B: "ENEMY_AI_DECIDE",
        0x8A18: "ENEMY_EDGE_CHK",
        0x8A2C: "PSEUDO_RANDOM",
        0x8A83: "ENEMY_POS_INIT",
        0x8A9F: "ENEMY_VS_PLAYER",
        0x8B60: "HOLE_AT_POS",
        0x8B76: "ENEMY_HOLE_FALL",
        0x8C51: "ERASE_CUR_ENEMY",
        0x8C79: "DRAW_CUR_ENEMY",
        0x8CA1: "ENEMY_TRAPPED",
        0x8D20: "ENEMY_LANDED",
        0x8D35: "CLEAR_HOLE_ENTRY",
        0x8E00: "DRAW_ALL_ENEMIES",
        0x8E23: "ENEMY_UPDATE",
        0x8E4B: "ENEMY_DISPATCH",
        0x8E5C: "ENEMY_SPAWN_NOP",
        0x8F6E: "ENEMY_CRUSH_CHK",
        0x8FE2: "ENEMY_DEATH",
        0x9023: "AWARD_SCORE",
        0x904D: "BONUS_KILL_CHK",
        0x906E: "SCORE_MULTIPLY",
        0x908A: "POST_KILL",
        0x912B: "SFX_SPAWN",
        0x9138: "DELAY_SHORT",
        0x9140: "DELAY_MEDIUM",
        0x914B: "DELAY_LONG",
        0x9156: "RESPAWN_ANIM",
        0x9193: "ANIM_FRAME_DELAY",
        0x919E: "SFX_RESPAWN_A",
        0x91BE: "SFX_RESPAWN_B",
        0x91DE: "DELAY_TINY",
    }
    # Add data labels (variables and tables within game code region)
    data_labels = {
        0x70BB: "SCORE_DIGITS",
        0x70C1: "HISCORE_DIGITS",
        0x70C7: "BONUS_PENALTY",
        0x70C8: "BONUS_DIGITS",
        0x70CC: "DISPLAY_POS",
        0x70CE: "FONT_DRAW_TMP",
        0x7160: "SCREEN_BLK_VARS",
        0x7162: "TENS_DIGIT",
        0x7163: "ONES_DIGIT",
        0x7464: "CURRENT_LEVEL",
        0x722E: "LIVES_COUNT",
        0x731B: "BONUS_TICK_CTR",
        0x7551: "BG_PAT_INDEX",
        0x758A: "LEVEL_SETUP_CTR",
        0x761A: "ENEMY_COUNT_TBL",
        0x7780: "ENEMY_TYPE_TBL",
        0x7803: "HOLE_X_TABLE",
        0x7904: "HOLE_DEPTH_TBL",
        0x7A05: "SPRITE_Y_ROW",
        0x7A06: "SPRITE_X_COL",
        0x7A0D: "PLAYER_Y",
        0x7A0E: "PLAYER_X",
        0x7A0F: "PLAYER_LAST_DIR",
        0x7A10: "PLAYER_ACTION",
        0x7A12: "KEY_CODE_TABLE",
        0x7A1B: "BOUNDARY_RIGHT",
        0x7A1C: "BOUNDARY_LEFT",
        0x7A22: "PLR_SPR_PTRS",
        0x7C65: "DIG_SPR_TOGGLE",
        0x7E6E: "LEVEL_MAP_TBL",
        0x803B: "PLR_ON_GROUND",
        0x803C: "PLR_MOVING",
        0x803D: "PLR_SAVED_DIR",
        0x826C: "DIG_TARGET_ROW",
        0x826D: "DIG_TARGET_COL",
        0x826F: "DIG_ANIM_CTR",
        0x8270: "DIG_HOLE_SLOT",
        0x838B: "HOLE_DEPTH_OFFS",
        0x8391: "HOURGLASS_TIMER",
        0x8392: "TIMER_TICK_CTR",
        0x8445: "TIMER_BAR_MASKS",
        0x849E: "ENEMY_DRAW_X",
        0x849F: "ENEMY_DRAW_Y",
        0x84A2: "ENEMY_ROW_CTR",
        0x8581: "ENEMY_ACTIVE",
        0x858B: "ENEMY_SPR_LO_T",
        0x8595: "ENEMY_SPR_HI_T",
        0x859F: "ENEMY_TYPE",
        0x85A9: "ENEMY_X_POS",
        0x85B3: "ENEMY_Y_POS",
        0x85BD: "ENEMY_MOVE_DIR",
        0x85C7: "ENEMY_TRAPPED",
        0x85D1: "ENEMY_CUR_FRAME",
        0x85DB: "ENEMY_ALT_FRAME",
        0x85E5: "ENEMY_FALL_DEPTH",
        0x85EF: "ENEMY_HOLE_REF",
        0x85F9: "ENEMY_CUR_SLOT",
        0x8A9B: "RANDOM_INDEX",
        0x8E60: "CHAIN_KILL_FLAG",
        0x904C: "KILL_COUNTER",
        0x9091: "KILL_BONUS_BASE",
        0x9097: "KILL_BONUS_ACCUM",
    }
    for addr, name in sub_names.items():
        dis.labels[addr] = name
    for addr, name in data_labels.items():
        dis.labels[addr] = name

    # Add hardware comments
    add_hardware_comments(dis, mem)
    add_hardware_comments(dis_loader, mem)

    # Add section comments for key addresses
    section_comments = {
        0x7000: "===== GAME ENTRY - jumps to initialization =====",
        0x706B: "===== HGR ADDRESS CALCULATION =====\n; Converts Y-row in $7063 to HGR screen address in $02-$05",
        0x709C: "; Setup HGR line - computes column offset and bit position",
        0x70D0: "; Split accumulator into tens/ones digits for display",
        0x70EA: "; Save 8x5 block of HGR screen to $0700 buffer",
        0x7125: "; Restore 8x5 block of HGR screen from $0700 buffer",
        0x7165: "===== SCORE/NUMBER DISPLAY ENGINE =====",
        0x71B5: "; Draw single font character glyph from $7003 table",
        0x71E8: "===== SOUND EFFECTS =====\n; Rising-falling speaker tone (score change)",
        0x720F: "; Sustained buzz (extra life earned)",
        0x722F: "===== SCORE & STATUS DISPLAY =====\n; Draw remaining lives count",
        0x7264: "; Draw 6-digit current score ($70BB-$70C0)",
        0x72A0: "; Add ones/tens digits to score with BCD carry",
        0x72DF: "; Draw 4-digit bonus countdown timer",
        0x731C: "; Decrement bonus timer every 32 frames",
        0x7387: "; Draw 6-digit high score ($70C1-$70C6)",
        0x73C3: "; Transfer remaining bonus to score at level end",
        0x73FD: "; Clear 8-row status bar area at bottom",
        0x7436: "; Compare current score vs high score, update if higher",
        0x7465: "===== GAME INITIALIZATION =====\n; Zero score, set 3 lives, level 1, start game",
        0x7552: "===== LEVEL SETUP =====\n; Select background pattern based on level",
        0x757C: "; Clear all enemy state slots (110 bytes)",
        0x758B: "; Initialize enemy positions, ladders for current level",
        0x763B: "; Award extra life when score threshold reached",
        0x768E: "; Flash lives display with sound effect",
        0x769F: "; CPU burn delay loop",
        0x7A3C: "===== ALTERNATE HGR CALC (FOR SPRITES) =====",
        0x7A8C: "===== INPUT HANDLING =====\n; Read keyboard, match against IJKM/DUEX key table",
        0x7AB4: "===== PLAYER MOVEMENT CONTROLLER =====\n; Master: reads input, validates against platforms/ladders,\n; handles falling, digging, stomping",
        0x7BD5: "===== SPRITE FRAME SELECTION =====\n; Walk right animation frames",
        0x7BED: "; Walk left animation frames",
        0x7C05: "; Climbing animation frames",
        0x7C1E: "; Digging left animation frames",
        0x7C35: "; Digging right animation frames",
        0x7C4C: "; Standing/idle pose",
        0x7C66: "===== PLAYER SPRITE RENDERING =====\n; Draw player using XOR with page 2 background restore",
        0x7CDD: "; Test if position intersects platform or ladder\n; Returns: 0=air, 1=top, 2=bottom, 3=on-ladder",
        0x7D19: "; Select sprite pointer routine based on action code",
        0x7D60: "; Erase player sprite via XOR",
        0x7DFD: "; Full player frame: erase, move, redraw, delay",
        0x7E09: "; Erase sprite, read input, move, redraw",
        0x7E1D: "===== GRAPHICS ENGINE =====\n; Copy HGR page 1 to page 2 (background snapshot)",
        0x7E40: "; Draw decorative border at rows $B0-$B1",
        0x7E9E: "; Clear HGR screen and set graphics mode",
        0x7EC4: "; Draw all platforms and ladders from level map",
        0x7F19: "; Draw platform segment top half",
        0x7F3E: "; Draw platform segment bottom half",
        0x7F63: "; Draw all 5 floor levels",
        0x7F7F: "; Draw one floor: solid top + open interior with walls",
        0x7FD3: "; Adjustable delay with walking sound clicks",
        0x801A: "===== HOLE MANAGEMENT =====\n; Search hole table for hole at given position",
        0x80C3: "; Clear all hole tables",
        0x80D3: "; Validate dig action: must be on floor edge, target clear",
        0x817F: "; Validate stomp: must be on floor edge with hole below",
        0x81A9: "; Check if player can step onto ladder",
        0x8272: "; Multi-frame digging animation controller",
        0x82C1: "; Find empty slot in hole table",
        0x82DA: "; Place new hole in table and draw it",
        0x8311: "; Draw hole tile with depth-based frame",
        0x8393: "===== TIMER BAR =====\n; Draw 3-row bonus timer bar at row $B4",
        0x83C6: "; Shrink timer bar by masking one column per tick",
        0x8402: "; Fill hole: decrement depth, redraw, clear when empty",
        0x844E: "; Multi-frame stomping animation controller",
        0x848E: "; Short percussive speaker tone for dig/stomp",
        0x84A4: "===== ENEMY SPRITE RENDERING =====\n; Erase enemy sprite via XOR",
        0x850F: "; Draw enemy sprite with mask+OR compositing",
        0x860E: "; Swap animation frames, erase old, draw new position",
        0x8650: "; Draw enemy with directional offset",
        0x8702: "===== COLLISION DETECTION =====\n; Bounding box test: returns 1=overlap, 0=clear",
        0x87C6: "===== ENEMY AI ENGINE =====\n; Per-enemy update: check hole, handle trapped, move",
        0x87F5: "; Stop enemy, redraw in idle pose",
        0x8854: "; Check current enemy vs all other enemies",
        0x8890: "; Check if enemy is at a floor/ladder junction",
        0x890B: "; Master AI: evaluate edges, ladders, player pos, pick dir",
        0x8A18: "; Return 1 if enemy mid-traversal, 0 if on floor edge",
        0x8A2C: "; Read pseudo-random byte from ROM $F800",
        0x8A83: "; Copy enemy pos from state tables to drawing params",
        0x8A9F: "; Bounding box test: enemy vs player -> death if overlap",
        0x8B60: "; Search hole table for hole at column A, row Y",
        0x8B76: "; Check if enemy over hole -> begin fall if yes",
        0x8C51: "; Erase current enemy sprite from screen",
        0x8C79: "; Draw current enemy sprite to screen",
        0x8CA1: "; Handle enemy trapped in hole: count down or climb out",
        0x8D20: "; Check if falling enemy landed on a floor",
        0x8D35: "; Clear hole table entry at fall column",
        0x8E00: "===== ENEMY MANAGEMENT =====\n; Draw all enemies at starting positions",
        0x8E23: "; Update one enemy per call (round-robin through slots)",
        0x8E4B: "; Call AI if enemy active, else check spawn",
        0x8F6E: "; Check if falling enemy crushes another enemy below",
        0x8FE2: "; Handle enemy death: award score, remove, check bonus",
        0x9023: "; Tally bonus multiplier and display kill score",
        0x904D: "; Check bonus kill conditions for chain scoring",
        0x906E: "; Accumulate chain-kill bonus values",
        0x908A: "; Clear hole at kill position, increment kill counter",
        0x912B: "===== ENEMY SOUND EFFECTS =====\n; Two-tone spawn beep",
        0x9156: "; 4-phase respawn animation with sound",
        0x9300: "===== LEVEL TRANSITION =====\n; Cap level at 7, jump to level load",
    }
    for addr, comment in section_comments.items():
        dis.comments[addr] = comment

    # Count code vs data in game region
    code_bytes = sum(1 for a in range(0x6000, 0xA800) if a in dis.code)
    data_bytes = 0xA800 - 0x6000 - code_bytes

    print(f"Game region $6000-$A7FF: {code_bytes} code bytes, {data_bytes} data bytes")
    print(f"Labels: {len(dis.labels)}")
    print(f"Trace passes: {passes}")

    # Generate the source file
    with open(output_path, 'w') as f:
        # ===== HEADER =====
        f.write(";=============================================================================\n")
        f.write("; APPLE PANIC (1981) - Ben Serki / Broderbund Software\n")
        f.write("; Clean reconstruction from cracked binary\n")
        f.write("; All cracking group artifacts removed\n")
        f.write(";\n")
        f.write("; Assembler: Merlin32 syntax\n")
        f.write("; Target: Apple ][+ with 48K RAM, DOS 3.3\n")
        f.write("; Load: BRUN APPLE PANIC (loads at $0000, 43008 bytes)\n")
        f.write(";\n")
        f.write("; Build verification:\n")
        f.write(";   Total size: $A800 (43008) bytes\n")
        f.write(";   Game code MD5 ($6000-$A7FF): ffcd8c18f189fdd28894d51b03525083\n")
        f.write(";=============================================================================\n\n")

        # ===== EQUATES =====
        f.write(";=============================================================================\n")
        f.write("; HARDWARE EQUATES\n")
        f.write(";=============================================================================\n\n")
        f.write("KBD      EQU  $C000           ; Keyboard data (bit 7 = key ready)\n")
        f.write("KBDSTRB  EQU  $C010           ; Keyboard strobe (clear bit 7)\n")
        f.write("SPKR     EQU  $C030           ; Speaker toggle\n")
        f.write("TXTCLR   EQU  $C050           ; Graphics mode (clear text)\n")
        f.write("TXTSET   EQU  $C051           ; Text mode\n")
        f.write("MIXCLR   EQU  $C052           ; Full screen (no text window)\n")
        f.write("MIXSET   EQU  $C053           ; Mixed mode (4 lines text)\n")
        f.write("TXTPAGE1 EQU  $C054           ; Display page 1\n")
        f.write("TXTPAGE2 EQU  $C055           ; Display page 2\n")
        f.write("LORES    EQU  $C056           ; Lo-res graphics\n")
        f.write("HIRES    EQU  $C057           ; Hi-res graphics\n\n")

        f.write("; --- Monitor ROM Entry Points ---\n")
        f.write("COUT     EQU  $FDED           ; Character output\n")
        f.write("HOME     EQU  $FC58           ; Clear screen\n\n")

        f.write("; --- Key Codes (High ASCII) ---\n")
        f.write("KEY_UP   EQU  $C9             ; 'I' key - move up\n")
        f.write("KEY_LEFT EQU  $CA             ; 'J' key - move left\n")
        f.write("KEY_RT   EQU  $CB             ; 'K' key - move right\n")
        f.write("KEY_DOWN EQU  $CD             ; 'M' key - move down\n")
        f.write("KEY_DIG1 EQU  $C4             ; 'D' key - dig hole\n")
        f.write("KEY_DIG2 EQU  $D5             ; 'U' key - dig hole (alt)\n")
        f.write("KEY_STP1 EQU  $D8             ; 'X' key - stomp/fill\n")
        f.write("KEY_STP2 EQU  $C5             ; 'E' key - stomp/fill (alt)\n\n")

        # ===== ZERO PAGE =====
        f.write(";=============================================================================\n")
        f.write("; ZERO PAGE VARIABLES ($0000-$00FF)\n")
        f.write("; Game uses: $00-$09 (pointers), $E0-$E1 (delay/sound)\n")
        f.write("; Rest contains Applesoft BASIC state / CHRGET routine\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0000\n\n")

        # Zero page with labeled game variables
        zp_labels = {
            0x00: ("ENEMY_SPR_LO", "Enemy sprite data pointer (low)"),
            0x01: ("ENEMY_SPR_HI", "Enemy sprite data pointer (high)"),
            0x02: ("HGR_ADDR1_LO", "HGR page 1 address (low)"),
            0x03: ("HGR_ADDR1_HI", "HGR page 1 address (high)"),
            0x04: ("HGR_ADDR2_LO", "HGR page 2 address (low)"),
            0x05: ("HGR_ADDR2_HI", "HGR page 2 address (high)"),
            0x06: ("SPR_OFF_LO",   "Sprite data offset (low)"),
            0x07: ("SPR_OFF_HI",   "Sprite data offset (high)"),
            0x08: ("PLR_SPR_LO",   "Player sprite frame ptr (low)"),
            0x09: ("PLR_SPR_HI",   "Player sprite frame ptr (high)"),
            0xE0: ("DELAY_PARAM",  "Delay parameter storage"),
            0xE1: ("WALK_SND_PHASE","Walking sound phase toggle (0/1)"),
        }
        addr = 0
        while addr < 0x100:
            if addr in zp_labels:
                name, desc = zp_labels[addr]
                f.write(f"{name:13s} DFB ${mem[addr]:02X}             ; ${addr:02X} - {desc}\n")
                addr += 1
            else:
                # Find next labeled address
                next_label = min([a for a in zp_labels if a > addr], default=0x100)
                chunk = min(16, next_label - addr)
                hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}")
                f.write(f"  ; ${addr:02X}\n")
                addr += chunk
        f.write("\n")

        # ===== STACK =====
        f.write(";=============================================================================\n")
        f.write("; STACK PAGE ($0100-$01FF)\n")
        f.write("; Repeating pattern F8 9E FA 98 FD 88 (pre-loaded stack data)\n")
        f.write("; Last 30 bytes: residual return addresses from boot chain\n")
        f.write("; $103B used as player Y-position variable (self-modifying code)\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0100\n\n")
        # Find where the repeating pattern ends
        pattern = bytes([0xF8, 0x9E, 0xFA, 0x98, 0xFD, 0x88])
        pat_end = 0x100
        for i in range(0x100, 0x200):
            pos = (i - 0x100) % 6
            if mem[i] != pattern[pos]:
                pat_end = i
                break
        else:
            pat_end = 0x200

        if pat_end > 0x100:
            count = pat_end - 0x100
            f.write(f";--- Repeating pattern F8 9E FA 98 FD 88 ({count} bytes) ---\n")
            f.write("STACK_DATA\n")
            addr = 0x100
            while addr < pat_end:
                chunk = min(16, pat_end - addr)
                hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}\n")
                addr += chunk

        if pat_end < 0x200:
            remaining = 0x200 - pat_end
            f.write(f"\n;--- Residual boot chain data ({remaining} bytes at ${pat_end:04X}) ---\n")
            f.write("STACK_BOOT_RES\n")
            addr = pat_end
            while addr < 0x200:
                chunk = min(16, 0x200 - addr)
                hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}\n")
                addr += chunk
        f.write("\n")

        # ===== RWTS CODE =====
        f.write(";=============================================================================\n")
        f.write("; DISK I/O CODE ($0200-$03A3) - DOS 3.3 RWTS routines\n")
        f.write("; Sector read/write and nibble encode/decode.\n")
        f.write("; Resident in RAM from boot; not called during gameplay.\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0200\n\n")
        f.write("RWTS_READ\n")
        # Force linear disassembly of RWTS - it's all executable code
        rwts_dis = Disassembler(mem, 0x0200, 0x03A4)
        # Trace to discover branch targets for labels
        rwts_dis.trace(0x0200)
        # Also trace from known sub-entry points within RWTS
        for ep in range(0x0200, 0x03A4):
            if mem[ep] == 0x60:  # RTS - next byte might be entry point
                if ep + 1 < 0x03A4:
                    rwts_dis.trace(ep + 1)
        rwts_dis.name_labels()
        # Use linear disassembly to ensure every byte is decoded as code
        rwts_lines = rwts_dis.linear_disassemble(0x0200, 0x03A4)
        for raddr, rlabel, rinstr, rcomment in rwts_lines:
            if rlabel:
                f.write(f"{rlabel}\n")
            if rcomment:
                f.write(f"         {rinstr:30s} ; {rcomment}\n")
            else:
                f.write(f"         {rinstr}\n")

        # RWTS padding - check content
        f.write("\n;--- RWTS Padding ($03A4-$03FF) ---\n")
        f.write("; Unused bytes after RWTS code; mostly $FF with a few residual values\n")
        f.write("RWTS_PAD\n")
        # Check if mostly $FF - use RTS + DS if so
        rts_byte = mem[0x03A4]
        if rts_byte == 0x60:
            f.write("         RTS                            ; end of RWTS\n")
            # Check remaining bytes
            all_ff = all(mem[i] == 0xFF for i in range(0x03A5, 0x03F4))
            if all_ff:
                f.write("         DS   79,$FF           ; unused padding\n")
            else:
                addr = 0x03A5
                while addr < 0x03F4:
                    chunk = min(16, 0x03F4 - addr)
                    hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                    f.write(f"         HEX {hex_str}\n")
                    addr += chunk
            # Last 12 bytes may have residual data
            hex_str = "".join(f"{mem[0x03F4+i]:02X}" for i in range(12))
            f.write(f"         HEX {hex_str}  ; residual boot chain data\n")
        else:
            addr = 0x03A4
            while addr < 0x0400:
                chunk = min(16, 0x0400 - addr)
                hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}\n")
                addr += chunk
        f.write("\n")

        # ===== MAIN GAME LOOP (in text page area) =====
        f.write(";=============================================================================\n")
        f.write("; MAIN GAME LOOP DISPATCHER ($0400-$04FF)\n")
        f.write("; Executable code in text page 1 area (not displayed in HGR mode).\n")
        f.write("; Called from L_74E9: dispatches enemy updates + player processing.\n")
        f.write("; Entry point varies by timer value for speed scaling:\n")
        f.write(";   $0400: 4x enemy updates (timer >= $1E)\n")
        f.write(";   $0403: 3x enemy updates (timer >= $14)\n")
        f.write(";   $0406: 2x enemy updates (timer >= $0A)\n")
        f.write(";   $0409: 1x enemy update  (timer >= $01)\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0400\n\n")
        f.write("GAME_LOOP\n")
        # Disassemble $0400-$04FF as code using linear disassembly
        # This is executable code placed in text page 1 (not displayed in HGR mode)
        loop_dis = Disassembler(mem, 0x0400, 0x0500)
        loop_dis.trace(0x0400)
        # Also trace from alternate entry points and after every RTS/JMP
        for ep in [0x0403, 0x0406, 0x0409]:
            loop_dis.trace(ep)
        # Find more entry points by scanning for RTS/JMP and tracing after them
        for probe in range(0x0400, 0x0500):
            if probe in loop_dis.code:
                op = mem[probe]
                if op in OPCODES:
                    mn, md, sz = OPCODES[op]
                    if mn in ("RTS", "JMP") and probe + sz < 0x0500:
                        loop_dis.trace(probe + sz)
        loop_dis.name_labels()
        add_hardware_comments(loop_dis, mem)
        # Use linear disassembly for complete coverage
        loop_lines = loop_dis.linear_disassemble(0x0400, 0x0500)
        for laddr, llabel, linstr, lcomment in loop_lines:
            if llabel:
                f.write(f"{llabel}\n")
            if lcomment:
                f.write(f"         {linstr:30s} ; {lcomment}\n")
            else:
                f.write(f"         {linstr}\n")
        f.write("\n")

        # ===== TEXT PAGE 1 =====
        f.write(";=============================================================================\n")
        f.write("; TEXT PAGE 1 BLANK SCREEN ($0500-$07FF)\n")
        f.write("; $A0 = space, $FF = screen hole bytes (used by Disk II controller)\n")
        f.write("; Not displayed during gameplay (HGR mode active)\n")
        f.write("; $0700-$0777 reused as HGR screen save buffer at runtime\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0500\n\n")
        # Text page 1 has a regular structure: 120 bytes of $A0 (spaces) + 8 bytes screen hole
        # repeated for each text line group. Use DS for the fill regions.
        txt_sections = [
            (0x0500, 0x0578, "TXT_LINE1",   "120 spaces (text line 1a)"),
            (0x0578, 0x0580, "SCRN_HOLE_1", None),  # 8 bytes screen hole
            (0x0580, 0x05F8, "TXT_LINE1B",  "120 spaces (text line 1b)"),
            (0x05F8, 0x0600, "SCRN_HOLE_2", None),
            (0x0600, 0x0678, "TXT_LINE2",   "120 spaces (text line 2a)"),
            (0x0678, 0x0680, "SCRN_HOLE_3", None),
            (0x0680, 0x06F8, "TXT_LINE2B",  "120 spaces (text line 2b)"),
            (0x06F8, 0x0700, "SCRN_HOLE_4", None),
            (0x0700, 0x0778, "HGR_SAVE_BUF","120 bytes (reused as HGR screen save buffer)"),
            (0x0778, 0x0780, "SCRN_HOLE_5", None),
            (0x0780, 0x07F8, "TXT_LINE3B",  "120 spaces (text line 3b)"),
            (0x07F8, 0x0800, "SCRN_HOLE_6", None),
        ]
        for start_a, end_a, label, ds_desc in txt_sections:
            f.write(f"{label}\n")
            size = end_a - start_a
            if ds_desc:
                # Check if all bytes are the same value
                fill_val = mem[start_a]
                all_same = all(mem[i] == fill_val for i in range(start_a, end_a))
                if all_same:
                    f.write(f"         DS   {size},${fill_val:02X}           ; {ds_desc}\n")
                else:
                    # Mixed content - output as HEX
                    addr = start_a
                    while addr < end_a:
                        chunk = min(16, end_a - addr)
                        hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                        f.write(f"         HEX {hex_str}\n")
                        addr += chunk
            else:
                # Screen holes - always output actual bytes (8 bytes)
                hex_str = "".join(f"{mem[start_a+i]:02X}" for i in range(size))
                f.write(f"         HEX {hex_str}  ; screen hole (Disk II / peripheral)\n")
        f.write("\n")

        # ===== SPRITE DATA =====
        f.write(";=============================================================================\n")
        f.write("; PLATFORM TILE BITMAPS ($0800-$097F)\n")
        f.write("; 8 bit-shift variants of platform/ladder tiles\n")
        f.write("; 48 bytes per shift position (3 bytes wide x 16 rows)\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0800\n\n")
        for shift in range(8):
            base = 0x0800 + shift * 0x30
            f.write(f"TILE_SHIFT{shift}                      ; Shift {shift}: platform tile shifted {shift} pixel(s) right\n")
            f.write(f";   3 bytes/row x 16 rows = 48 bytes\n")
            a = base
            while a < base + 0x30:
                chunk = min(16, base + 0x30 - a)
                hex_str = "".join(f"{mem[a+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}\n")
                a += chunk
        f.write("\n")

        # Loader artifact
        f.write(";--- Loader Artifact ($0980-$09AF) ---\n")
        f.write("; Contains 'EDASM.OBJ' text remnant - not used by game\n")
        f.write("LOADER_ARTIFACT\n")
        addr = 0x0980
        while addr < 0x09B0:
            chunk = min(16, 0x09B0 - addr)
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
            f.write(f"         HEX {hex_str}\n")
            addr += chunk

        # Padding
        f.write("\n;--- Unused padding ($09B0-$09FF) ---\n")
        f.write("         DS   80,$FF\n\n")

        # Character sprite data
        f.write(";=============================================================================\n")
        f.write("; CHARACTER SPRITE FRAMES ($0A00-$0BBF)\n")
        f.write("; Sprite bitmap data for game characters\n")
        f.write("; 7 frames, 64 bytes each (3 bytes wide x 10 rows + padding)\n")
        f.write(";=============================================================================\n\n")
        char_frame_names = [
            "Standing/idle",
            "Walk frame 1",
            "Walk frame 2",
            "Digging",
            "Walk frame 3",
            "Walk frame 4",
            "Falling/jumping",
        ]
        for frame in range(7):
            base = 0x0A00 + frame * 0x40
            desc = char_frame_names[frame] if frame < len(char_frame_names) else f"Frame {frame}"
            f.write(f"CHAR_FRAME_{frame}                     ; {desc} at ${base:04X}\n")
            f.write(f";   64 bytes: 3 bytes/row x 10 rows + 34 bytes padding\n")
            a = base
            while a < base + 0x40:
                chunk = min(16, base + 0x40 - a)
                hex_str = "".join(f"{mem[a+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}\n")
                a += chunk

        # Empty frame slot
        f.write("\n;--- Empty frame slot ($0BC0-$0BFF) ---\n")
        f.write("         DS   64,$00\n\n")

        # Background theme data
        f.write(";=============================================================================\n")
        f.write("; BACKGROUND THEME TILE PATTERNS ($0C00-$0D7C)\n")
        f.write("; 4 visual themes, 48 bytes each (3 color layers x 16 bytes)\n")
        f.write("; Selected by SELECT_BG_PATTERN based on level/lives\n")
        f.write("; Loaded into level map table at $7E6E during level setup\n")
        f.write(";=============================================================================\n\n")
        for theme in range(4):
            base = 0x0C00 + theme * 0x30
            f.write(f"BG_THEME_{theme}                       ; Theme {theme} at ${base:04X}\n")
            a = base
            while a < base + 0x30:
                chunk = min(16, base + 0x30 - a)
                hex_str = "".join(f"{mem[a+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}\n")
                a += chunk
        # Remaining themes (duplicates)
        f.write("\n;--- Themes 4-7 (duplicates of theme 3) ---\n")
        addr = 0x0CC0
        while addr < 0x0D7D:
            chunk = min(16, 0x0D7D - addr)
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
            f.write(f"         HEX {hex_str}\n")
            addr += chunk
        f.write("\n")

        # ===== CLEARED EDASM REGION =====
        f.write(";=============================================================================\n")
        f.write("; CLEARED REGION ($0D7D-$0FFC)\n")
        f.write("; Cracker overwrote with EDASM code; zeroed in clean reconstruction.\n")
        f.write("; $0E00-$0E7F: Enemy spawn position table (populated at runtime)\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0D7D\n")
        f.write("         DS   131,$00          ; $0D7D-$0DFF: padding\n")
        f.write("ENEMY_SPAWN_TBL                  ; $0E00: enemy X/Y positions per level config\n")
        f.write("         DS   128,$00          ; 4 configs x 8 enemies x 2 bytes (X,Y)\n")
        f.write("         DS   381,$00          ; $0E80-$0FFC: runtime scratch\n\n")

        # ===== ENEMY SPRITE DATA =====
        f.write(";=============================================================================\n")
        f.write("; ENEMY SPRITE DATA ($0FFD-$15FF)\n")
        f.write("; 3 enemy types, 512 bytes each (8 shift variants x 2 frames)\n")
        f.write("; 3 bytes wide x 10 rows = 30 bytes per shifted frame\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $0FFD\n\n")
        # Header bytes
        hex_str = "".join(f"{mem[0x0FFD+i]:02X}" for i in range(3))
        f.write(f"         HEX {hex_str}             ; padding/alignment\n\n")

        enemy_type_names = ["Bug", "Spider", "Ghost"]
        for etype in range(3):
            base = 0x1000 + etype * 0x200
            f.write(f"ENEMY_TYPE{etype}_SPR                   ; {enemy_type_names[etype]} sprites at ${base:04X}\n")
            # Each enemy type: 16 shifted frames (8 shifts x 2 animation frames)
            # Each frame: 30 bytes (3 bytes wide x 10 rows) + 2 bytes padding = 32 bytes
            for frame in range(16):
                shift = frame // 2
                anim = frame % 2
                frame_base = base + frame * 0x20
                f.write(f";--- shift {shift}, anim {anim} at ${frame_base:04X} ---\n")
                addr = frame_base
                while addr < frame_base + 0x20:
                    chunk = min(16, frame_base + 0x20 - addr)
                    hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                    f.write(f"         HEX {hex_str}\n")
                    addr += chunk
            f.write("\n")

        # ===== SPRITE MASKS =====
        f.write(";=============================================================================\n")
        f.write("; SPRITE TRANSPARENCY MASKS ($1600-$16FF)\n")
        f.write("; AND mask for background preservation during enemy rendering\n")
        f.write("; 8 shift variants x 30 bytes = 240 bytes of mask data\n")
        f.write(";=============================================================================\n\n")
        for shift in range(8):
            base = 0x1600 + shift * 0x20
            f.write(f"SPR_MASK_SHIFT{shift}                  ; Mask shift {shift}\n")
            addr = base
            while addr < base + 0x20:
                chunk = min(16, base + 0x20 - addr)
                hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
                f.write(f"         HEX {hex_str}\n")
                addr += chunk
        f.write("\n")

        # ===== SOLID FILL PATTERN =====
        f.write(";=============================================================================\n")
        f.write("; SOLID FILL PATTERN ($1700-$17FC)\n")
        f.write("; Repeating FF FF 00 00 pattern for screen fill operations\n")
        f.write(";=============================================================================\n\n")
        f.write("; Repeating 4-byte pattern: FF FF 00 00\n")
        f.write("; Used by screen fill routines for striped fill effect\n")
        f.write("FILL_PATTERN\n")
        # Count how many times the FFFF0000 pattern repeats
        pat = bytes([0xFF, 0xFF, 0x00, 0x00])
        pat_count = 0
        addr = 0x1700
        while addr + 4 <= 0x17FD:
            if mem[addr:addr+4] == pat:
                pat_count += 1
                addr += 4
            else:
                break
        if pat_count > 0:
            f.write(f";   {pat_count} repetitions of FF FF 00 00 = {pat_count * 4} bytes\n")
        # Output actual data
        addr = 0x1700
        while addr < 0x17FD:
            chunk = min(16, 0x17FD - addr)
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
            f.write(f"         HEX {hex_str}\n")
            addr += chunk
        f.write("\n")

        # ===== IDENTITY TABLE =====
        f.write(";=============================================================================\n")
        f.write("; IDENTITY LOOKUP TABLE ($1800-$18FF)\n")
        f.write("; 256 bytes: $00,$01,$02,...,$FF\n")
        f.write("; Used as lookup table via zero-page indirect addressing\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $17FD\n")
        # Output actual bytes from $17FD-$17FF (padding before table)
        pad_hex = "".join(f"{mem[0x17FD+i]:02X}" for i in range(3))
        f.write(f"         HEX {pad_hex}             ; padding before table\n")
        f.write("IDTABLE                          ; $1800\n")
        f.write("; Sequential values $00-$FF used as identity lookup:\n")
        f.write(";   LDA (ptr),Y with ptr pointing here returns Y in A\n")
        for row in range(16):
            base = 0x1800 + row * 16
            vals = "".join(f"{mem[base+col]:02X}" for col in range(16))
            f.write(f"         HEX {vals}  ; ${row*16:02X}-${row*16+15:02X}\n")
        f.write("\n")

        # ===== CLEAN LOADER =====
        f.write(";=============================================================================\n")
        f.write("; CLEAN LOADER ($1900)\n")
        f.write("; Replaces cracker's relocation routine\n")
        f.write("; Sets hi-res full-screen graphics mode and starts the game\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $1900\n\n")
        f.write("INIT     LDA TXTCLR           ; Enable graphics mode\n")
        f.write("         LDA MIXCLR           ; Full screen (no text window)\n")
        f.write("         LDA HIRES            ; Enable hi-res mode\n")
        f.write("         JMP GAME_START       ; Start the game\n\n")

        # Fill remaining init area with zeros
        loader_size = 12  # 3x LDA abs (3 bytes each) + JMP (3 bytes)
        remaining = 0x193A - 0x1900 - loader_size
        if remaining > 0:
            f.write(f"         DS  {remaining},$00       ; zeroed (was cracker relocation code)\n\n")

        # ===== GAME STATE VARIABLES =====
        f.write(";=============================================================================\n")
        f.write("; GAME STATE VARIABLES ($193A-$1FFC)\n")
        f.write("; Zeroed at load time\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $193A\n")
        f.write(f"         DS   {0x1FFD - 0x193A},$00   ; {0x1FFD - 0x193A} bytes zeroed game state\n\n")

        # ===== PRE-HGR DATA + HGR DISPLAY PAGES =====
        f.write(";=============================================================================\n")
        f.write("; PRE-HGR DATA ($1FFD-$1FFF)\n")
        f.write("; 3 alignment bytes before HGR page 1\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $1FFD\n\n")
        hex_str = "".join(f"{mem[0x1FFD+i]:02X}" for i in range(3))
        f.write(f"PRE_HGR  HEX {hex_str}             ; alignment bytes\n\n")

        f.write(";=============================================================================\n")
        f.write("; HGR DISPLAY PAGES ($2000-$5FFF)\n")
        f.write("; 16KB - used as display buffers at runtime\n")
        f.write("; Page 1: $2000-$3FFF (background + sprites)\n")
        f.write("; Page 2: $4000-$5FFF (background snapshot for XOR restore)\n")
        f.write("; Content at load time is overwritten by game initialization.\n")
        f.write("; Original disk image contained pre-shifted sprite data here,\n")
        f.write("; but these pages are cleared and redrawn before gameplay begins.\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $2000\n")
        f.write("HGR_PAGE1\n")
        f.write("         DS   $2000,$00        ; 8KB HGR page 1 (cleared by game init)\n")
        f.write("HGR_PAGE2\n")
        f.write("         DS   $2000,$00        ; 8KB HGR page 2 (cleared by game init)\n")
        f.write("\n")

        # ===== PLAYER SPRITE DATA ($6000-$6EFF) =====
        f.write(";=============================================================================\n")
        f.write("; PLAYER SPRITE DATA ($6000-$6EFF)\n")
        f.write("; Pre-shifted HGR bitmaps for player animations.\n")
        f.write("; Each animation has 7 pixel-shift variants x 48 bytes per frame.\n")
        f.write("; Animations: walk-right, walk-left, climb, dig-left, dig-right, stand\n")
        f.write("; Referenced via pointer table at $7A22-$7A35\n")
        f.write(";=============================================================================\n\n")
        f.write("         ORG  $6000\n\n")

        # Output player sprite data with frame labels
        # Each animation block = 7 shifts x 48 bytes = 336 bytes ($150)
        # But blocks are actually 0x300 = 768 bytes each (7 shifts x ~109 bytes?)
        # Let me use the known pointer addresses from the sprite pointer table
        sprite_labels = {
            0x6000: ("PLR_WALK_R0", "Walk right frame 0 (7 shifts x 48 bytes)"),
            0x6150: ("PLR_WALK_R0B", "Walk right frame 0 continued"),
            0x6300: ("PLR_WALK_R1", "Walk right frame 1 (also walk left frame 0)"),
            0x6450: ("PLR_WALK_R1B", "Walk right frame 1 continued"),
            0x6600: ("PLR_CLIMB_0", "Climb frame 0 (7 shifts x 48 bytes)"),
            0x6750: ("PLR_CLIMB_0B", "Climb frame 0 continued"),
            0x6900: ("PLR_DIG_L0",  "Dig left frame 0 (7 shifts x 48 bytes)"),
            0x6A50: ("PLR_DIG_L0B", "Dig left frame 0 continued"),
            0x6C00: ("PLR_DIG_L1",  "Dig left frame 1 (7 shifts x 48 bytes)"),
            0x6D50: ("PLR_DIG_L1B", "Dig left frame 1 continued"),
        }
        # Also add per-shift labels within each animation block
        for anim_base, (anim_name, _) in list(sprite_labels.items()):
            if anim_base % 0x300 == 0:  # only for main blocks
                for shift in range(7):
                    shift_addr = anim_base + shift * 48
                    if shift_addr not in sprite_labels and shift > 0:
                        sprite_labels[shift_addr] = (f"{anim_name}_S{shift}", f"pixel shift {shift}")

        addr = 0x6000
        while addr < 0x6F00:
            if addr in sprite_labels:
                name, desc = sprite_labels[addr]
                f.write(f"\n{name}                          ; {desc}\n")
            chunk = min(16, 0x6F00 - addr)
            next_lbl = min([a for a in sprite_labels if a > addr], default=0x6F00)
            chunk = min(chunk, next_lbl - addr)
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(chunk))
            f.write(f"         HEX {hex_str}\n")
            addr += chunk

        # Platform tile data
        f.write("\n;=============================================================================\n")
        f.write("; PLATFORM TILE GRAPHICS ($6F00-$6FBF)\n")
        f.write("; Masks and patterns for platform/ladder rendering\n")
        f.write("; Used by DRAW_PLAT_TOP and DRAW_PLAT_BOT\n")
        f.write(";=============================================================================\n\n")
        f.write("PLAT_TILE_MASK                    ; AND mask ($6F00-$6F3F)\n")
        addr = 0x6F00
        while addr < 0x6F40:
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(min(16, 0x6F40-addr)))
            f.write(f"         HEX {hex_str}\n")
            addr += min(16, 0x6F40-addr)
        f.write("PLAT_TILE_TOP                     ; Top half pattern ($6F40-$6F7F)\n")
        addr = 0x6F40
        while addr < 0x6F80:
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(min(16, 0x6F80-addr)))
            f.write(f"         HEX {hex_str}\n")
            addr += min(16, 0x6F80-addr)
        f.write("PLAT_TILE_BOT                     ; Bottom half pattern ($6F80-$6FBF)\n")
        addr = 0x6F80
        while addr < 0x6FC0:
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(min(16, 0x6FC0-addr)))
            f.write(f"         HEX {hex_str}\n")
            addr += min(16, 0x6FC0-addr)
        f.write("TILE_EXTRA                        ; Additional tile patterns ($6FC0-$6FFF)\n")
        addr = 0x6FC0
        while addr < 0x7000:
            hex_str = "".join(f"{mem[addr+i]:02X}" for i in range(min(16, 0x7000-addr)))
            f.write(f"         HEX {hex_str}\n")
            addr += min(16, 0x7000-addr)

        # ===== MAIN GAME CODE =====
        f.write("\n;=============================================================================\n")
        f.write("; MAIN GAME CODE ($7000-$A7FF)\n")
        f.write("; All game logic: rendering, sound, AI, input, scoring.\n")
        f.write("; Entry: GAME_START ($7000) -> JMP GAME_INIT ($7465)\n")
        f.write(";=============================================================================\n\n")

        # Disassemble the game code region (only $7000+ since $6000 already output)
        lines = dis.disassemble_range(0x7000, 0xA800)

        # Static section headers for data regions
        data_headers = {
            0x7003: ";--------------------------------------\n"
                    "; FONT & ICON DATA ($7003-$7062)\n"
                    "; 8 bytes per char: digits 0-9, blank,\n"
                    "; player icon for lives display\n"
                    ";--------------------------------------",
            0x7063: ";--------------------------------------\n"
                    "; HGR CALC VARIABLES ($7063-$706A)\n"
                    "; $7063=Y-row  $7064=X-col  $7067=bit-pos\n"
                    "; $7068=byte-col  $7069=page1-hi  $706A=page2-hi\n"
                    ";--------------------------------------",
        }

        for addr, label, instr, comment in lines:
            # Add static section headers
            if addr in data_headers:
                f.write(f"\n{data_headers[addr]}\n")

            # Add section comments from the analysis
            if comment and comment.startswith("====="):
                # Multi-line section comment - render as block comment
                f.write(f"\n;--------------------------------------\n")
                for cline in comment.split("\n"):
                    # Strip leading "; " from sub-lines to avoid double semicolons
                    cline = cline.lstrip("; ")
                    f.write(f"; {cline}\n")
                f.write(f";--------------------------------------\n")
                comment = ""  # don't repeat as inline

            # Format the line
            if label:
                f.write(f"{label}\n")

            if comment:
                # Strip leading "; " from inline comments too
                comment = comment.lstrip("; ")
                f.write(f"         {instr:30s} ; {comment}\n")
            else:
                f.write(f"         {instr}\n")

        f.write("\n;=============================================================================\n")
        f.write("; END OF APPLE PANIC\n")
        f.write(";=============================================================================\n")

    return code_bytes, data_bytes, len(dis.labels)


def main():
    mem = load_image("E:/Apple/ApplePanic_runtime.bin")
    print(f"Loaded runtime image: {len(mem)} bytes")

    code, data, labels = generate_source(mem, "E:/Apple/ApplePanic.asm")
    print(f"\nSource generated: E:/Apple/ApplePanic.asm")
    print(f"  Code bytes in $6000-$A7FF: {code}")
    print(f"  Data bytes in $6000-$A7FF: {data}")
    print(f"  Labels generated: {labels}")

if __name__ == "__main__":
    main()

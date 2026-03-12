"""
6502 disassembler with recursive descent code/data classification.

Provides both linear disassembly (for quick hex dumps) and recursive
descent disassembly (for accurate code vs data separation).

Overview
--------
The MOS 6502 is an 8-bit processor used in the Apple II, Commodore 64, NES,
and many other systems. It has 151 documented opcodes (plus numerous
undocumented ones) using 13 addressing modes, with instructions ranging
from 1 to 3 bytes in length.

This module provides two disassembly approaches:

  - **Linear disassembly** (``disassemble_region``): Treats every byte as code
    and disassembles sequentially. Fast but cannot distinguish code from data.

  - **Recursive descent disassembly** (``Disassembler`` class): Traces execution
    paths starting from known entry points, following branches, jumps, and
    subroutine calls. Only bytes reachable by following control flow are marked
    as code; everything else is treated as data. This produces much more
    accurate output for programs that interleave code and data.

Usage
-----
    from nibbler.disasm import Disassembler, add_hardware_comments

    # Load a binary into a memory buffer:
    mem = bytearray(0x10000)
    mem[0x4000:0x4000+len(binary)] = binary

    # Linear disassembly:
    lines = disassemble_region(binary, base_addr=0x4000)

    # Recursive descent disassembly:
    dis = Disassembler(mem, start=0x4000, end=0xA800)
    dis.data_regions = [(0x6000, 0x7000)]  # Mark known data regions
    dis.trace(0x4000)                       # Trace from entry point
    dis.name_labels()                       # Generate SUB_/L_ label names
    add_hardware_comments(dis, mem)         # Annotate Apple II I/O accesses
    lines = dis.disassemble_range(0x4000, 0xA800)

Expected Output
---------------
``disassemble_range`` returns a list of (addr, label, instruction, comment) tuples:
    [(0x4000, 'SUB_4000', 'LDA #$05', ''),
     (0x4002, '',          'STA $C030', 'toggle speaker'),
     (0x4005, 'L_4005',   'BNE L_4002', ''),
     ...]
"""

# ── 6502 Opcode Table ───────────────────────────────────────────────
#
# OPCODES maps each opcode byte (0x00..0xFF) to a 3-tuple:
#   (mnemonic, addressing_mode, byte_count)
#
# - mnemonic: The instruction name (e.g., "LDA", "STA", "JMP").
# - addressing_mode: A short code identifying how the operand is interpreted.
#   See the addressing mode reference below.
# - byte_count: Total instruction length including the opcode byte (1, 2, or 3).
#
# Opcodes not present in this dict are undefined (illegal on the NMOS 6502
# but some have well-known undocumented behaviors, which are included here).
#
# ── Addressing Mode Reference ───────────────────────────────────────
#
#   Code   Name              Syntax         Bytes  Description
#   ----   ----              ------         -----  -----------
#   IMP    Implied           (none)         1      Operand is implicit (e.g., CLC)
#   ACC    Accumulator       A              1      Operates on the accumulator (e.g., ASL A)
#   IMM    Immediate         #$nn           2      8-bit constant follows opcode
#   ZP     Zero Page         $nn            2      8-bit address in page zero ($00-$FF)
#   ZPX    Zero Page,X       $nn,X          2      Zero page address + X register
#   ZPY    Zero Page,Y       $nn,Y          2      Zero page address + Y register
#   ABS    Absolute          $nnnn          3      Full 16-bit address (little-endian)
#   ABX    Absolute,X        $nnnn,X        3      16-bit address + X register
#   ABY    Absolute,Y        $nnnn,Y        3      16-bit address + Y register
#   IND    Indirect          ($nnnn)        3      JMP only — read target from pointer
#   IZX    Indexed Indirect  ($nn,X)        2      Zero page pointer + X, then indirect
#   IZY    Indirect Indexed  ($nn),Y        2      Zero page pointer indirect, then + Y
#   REL    Relative          $nnnn          2      Signed 8-bit offset for branches
#
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
    # ── Undocumented NMOS 6502 opcodes ──────────────────────────────
    # These opcodes are not part of the official MOS specification but have
    # well-documented behavior on NMOS 6502 chips. Some games and copy
    # protection schemes use them. They are included here so the disassembler
    # can handle them rather than treating their operand bytes as data.
    #
    # NOP variants (various addressing modes, different cycle counts):
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
    # LAX: Load both A and X from memory (LDA + LDX combined)
    0xA3: ("LAX", "IZX", 2), 0xA7: ("LAX", "ZP", 2), 0xAF: ("LAX", "ABS", 3),
    0xB3: ("LAX", "IZY", 2), 0xB7: ("LAX", "ZPY", 2), 0xBF: ("LAX", "ABY", 3),
    0xAB: ("LAX", "IMM", 2),
    # SAX: Store (A AND X) to memory
    0x83: ("SAX", "IZX", 2), 0x87: ("SAX", "ZP", 2), 0x8F: ("SAX", "ABS", 3),
    0x97: ("SAX", "ZPY", 2),
    # SBC duplicate (behaves identically to $E9)
    0xEB: ("SBC", "IMM", 2),
    # DCP: Decrement memory then compare with A (DEC + CMP combined)
    0xC3: ("DCP", "IZX", 2), 0xC7: ("DCP", "ZP", 2), 0xCF: ("DCP", "ABS", 3),
    0xD3: ("DCP", "IZY", 2), 0xD7: ("DCP", "ZPX", 2), 0xDB: ("DCP", "ABY", 3),
    0xDF: ("DCP", "ABX", 3),
    # ISC (aka ISB): Increment memory then subtract from A (INC + SBC combined)
    0xE3: ("ISC", "IZX", 2), 0xE7: ("ISC", "ZP", 2), 0xEF: ("ISC", "ABS", 3),
    0xF3: ("ISC", "IZY", 2), 0xF7: ("ISC", "ZPX", 2), 0xFB: ("ISC", "ABY", 3),
    0xFF: ("ISC", "ABX", 3),
    # SLO: Shift left then OR with A (ASL + ORA combined)
    0x03: ("SLO", "IZX", 2), 0x07: ("SLO", "ZP", 2), 0x0F: ("SLO", "ABS", 3),
    0x13: ("SLO", "IZY", 2), 0x17: ("SLO", "ZPX", 2), 0x1B: ("SLO", "ABY", 3),
    0x1F: ("SLO", "ABX", 3),
    # RLA: Rotate left then AND with A (ROL + AND combined)
    0x23: ("RLA", "IZX", 2), 0x27: ("RLA", "ZP", 2), 0x2F: ("RLA", "ABS", 3),
    0x33: ("RLA", "IZY", 2), 0x37: ("RLA", "ZPX", 2), 0x3B: ("RLA", "ABY", 3),
    0x3F: ("RLA", "ABX", 3),
    # SRE: Shift right then XOR with A (LSR + EOR combined)
    0x43: ("SRE", "IZX", 2), 0x47: ("SRE", "ZP", 2), 0x4F: ("SRE", "ABS", 3),
    0x53: ("SRE", "IZY", 2), 0x57: ("SRE", "ZPX", 2), 0x5B: ("SRE", "ABY", 3),
    0x5F: ("SRE", "ABX", 3),
    # RRA: Rotate right then add to A (ROR + ADC combined)
    0x63: ("RRA", "IZX", 2), 0x67: ("RRA", "ZP", 2), 0x6F: ("RRA", "ABS", 3),
    0x73: ("RRA", "IZY", 2), 0x77: ("RRA", "ZPX", 2), 0x7B: ("RRA", "ABY", 3),
    0x7F: ("RRA", "ABX", 3),
    # ANC: AND with immediate, then copy N flag to C (AND + set carry from bit 7)
    0x0B: ("ANC", "IMM", 2), 0x2B: ("ANC", "IMM", 2),
    # ALR: AND with immediate then shift right (AND + LSR combined)
    0x4B: ("ALR", "IMM", 2),
    # ARR: AND with immediate then rotate right (AND + ROR combined, with BCD quirks)
    0x6B: ("ARR", "IMM", 2),
    # AXS: (A AND X) minus immediate, result in X (no borrow)
    0xCB: ("AXS", "IMM", 2),
    # KIL: Halt the processor (jams the CPU; requires reset to recover)
    0x02: ("KIL", "IMP", 1), 0x12: ("KIL", "IMP", 1), 0x22: ("KIL", "IMP", 1),
    0x32: ("KIL", "IMP", 1), 0x42: ("KIL", "IMP", 1), 0x52: ("KIL", "IMP", 1),
    0x62: ("KIL", "IMP", 1), 0x72: ("KIL", "IMP", 1), 0x92: ("KIL", "IMP", 1),
    0xB2: ("KIL", "IMP", 1), 0xD2: ("KIL", "IMP", 1), 0xF2: ("KIL", "IMP", 1),
    # Unstable undocumented opcodes (behavior varies between chip revisions):
    0x93: ("SHA", "IZY", 2), 0x9F: ("SHA", "ABY", 3),
    0x9E: ("SHX", "ABY", 3), 0x9C: ("SHY", "ABX", 3),
    0x9B: ("TAS", "ABY", 3), 0xBB: ("LAS", "ABY", 3),
    0x8B: ("XAA", "IMM", 2),
}


# ── Apple II Hardware Register Comments ─────────────────────────────
# Maps memory-mapped I/O addresses to human-readable descriptions.
# The Apple II maps hardware registers to the $C000-$C0FF range (soft switches).
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

# Maps Apple II Monitor ROM entry points to their conventional names.
# These are standard subroutine addresses that programs call via JSR.
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

    Disassembles every byte sequentially as code, with no attempt to
    distinguish code from data. Useful for quick inspection of small regions
    known to be code, or for hex-dump-style output.

    Each output line includes the address, raw hex bytes, mnemonic, operand,
    and (for absolute-addressed instructions) any known hardware register
    or ROM entry point comment.

    Args:
        data: bytes/bytearray to disassemble.
        base_addr: Memory address corresponding to the first byte of data.
        start: Address to begin disassembly (default: base_addr).
        end: Address to stop disassembly (default: base_addr + len(data)).

    Returns:
        List of formatted strings, one per instruction. Example:
            ['  $4000: A9 05    LDA #$05',
             '  $4002: 8D 30 C0 STA $C030  ; toggle speaker']
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
        # Unknown opcode: emit as raw byte with "???"
        if opcode not in OPCODES:
            lines.append(f"  ${addr:04X}: {opcode:02X}       ???")
            addr += 1
            continue

        mnem, mode, size = OPCODES[opcode]
        # Instruction extends past end of data: emit partial and stop
        if offset + size > len(data):
            lines.append(f"  ${addr:04X}: {opcode:02X}       ???")
            break

        # Format raw hex bytes, left-justified to 8 chars for alignment
        raw = ' '.join(f'{data[offset + j]:02X}' for j in range(size))
        raw = raw.ljust(8)

        # Format the operand according to addressing mode
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
            val = data[offset + 1] | (data[offset + 2] << 8)  # Little-endian
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
            # Signed 8-bit offset, relative to the NEXT instruction (addr + 2)
            off8 = data[offset + 1]
            if off8 > 127:
                off8 -= 256  # Convert unsigned to signed
            target = (addr + 2 + off8) & 0xFFFF
            operand = f" ${target:04X}"
        else:
            operand = ""

        # Add hardware/ROM comments for absolute-addressed instructions
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

    This disassembler uses recursive descent tracing to determine which bytes
    are executable code and which are data. Starting from known entry points,
    it follows all control flow paths (branches, jumps, subroutine calls)
    and marks every reachable byte as code. Bytes not reached by any trace
    are treated as data.

    The algorithm:
      1. Begin at an entry point address.
      2. Decode the instruction at the current address.
      3. If it is a branch (REL mode), recursively trace the branch target
         AND continue with the fall-through path.
      4. If it is JSR, recursively trace the subroutine AND continue after
         the JSR (assuming the subroutine returns).
      5. If it is JMP (absolute), recursively trace the target and STOP
         tracing the current path (unconditional jump).
      6. If it is JMP (indirect), RTS, RTI, or BRK, STOP tracing the
         current path (control flow cannot be statically determined).
      7. Otherwise, advance to the next instruction and repeat.

    Data region detection heuristics:
      - User-specified data_regions are always respected.
      - Undocumented opcodes (SLO, RLA, etc.) terminate a trace, since real
        programs almost never use them — their presence usually means the
        tracer has wandered into data.
      - Multi-byte NOP variants (opcode != 0xEA) also terminate a trace,
        as they typically indicate data misinterpreted as code.
      - If an instruction's operand bytes overlap a known data region, the
        trace stops.

    The 5000-depth recursion limit prevents infinite loops and excessive
    stack usage on pathological inputs. In practice, legitimate 6502 programs
    rarely exceed a few hundred levels of trace depth.

    Usage:
        dis = Disassembler(mem, start=0x4000, end=0xA800)
        dis.data_regions = [(0x6000, 0x7000)]  # known data
        dis.trace(0x4000)  # trace from entry point
        dis.name_labels()
        add_hardware_comments(dis, mem)
        lines = dis.disassemble_range(0x4000, 0xA800)
    """

    # Set of undocumented (illegal) instruction mnemonics.
    # When the tracer encounters one of these, it stops tracing the current
    # path because undocumented opcodes almost never appear in real code —
    # they usually indicate the tracer has strayed into a data region.
    UNDOC_MNEMONICS = frozenset((
        "SLO", "RLA", "SRE", "RRA", "SAX", "LAX", "DCP", "ISC",
        "ANC", "ALR", "ARR", "AXS", "KIL", "SHA", "SHX", "SHY",
        "TAS", "LAS", "XAA",
    ))

    def __init__(self, mem, start=0, end=None):
        """Initialize the disassembler.

        Args:
            mem: Full 64K memory image (bytearray or bytes). The disassembler
                reads from this buffer using addresses as indices.
            start: Lowest address to consider as disassemblable code/data.
            end: One past the highest address to consider (exclusive).
        """
        self.mem = mem
        self.start = start
        self.end = end or len(mem)
        self.code = set()           # Set of addresses confirmed as code bytes
        self.labels = {}            # addr -> label name (or None = unnamed)
        self.comments = {}          # addr -> comment string
        self.data_regions = []      # List of (start, end) tuples for known data
        self.entry_points = []      # Record of trace entry points (informational)

    def in_data_region(self, addr):
        """Check if addr falls within any user-specified data region."""
        for ds, de in self.data_regions:
            if ds <= addr < de:
                return True
        return False

    def trace(self, addr, depth=0):
        """Recursively trace code starting at addr, marking reachable bytes.

        This is the core of the recursive descent algorithm. It follows
        execution flow from the given address, marking each instruction's
        bytes in self.code and recording branch/jump/call targets in
        self.labels for later naming.

        Tracing stops when it encounters:
          - An address already traced (prevents infinite loops on back-edges)
          - A user-defined data region
          - An undefined or undocumented opcode (likely data, not code)
          - A multi-byte NOP (opcode != $EA, likely data)
          - An instruction that extends past self.end
          - An instruction whose operand bytes overlap a data region
          - An unconditional control transfer (JMP, RTS, RTI, BRK)
          - Recursion depth > 5000 (safety limit to prevent stack overflow;
            legitimate programs rarely exceed a few hundred levels)

        Args:
            addr: Address to begin tracing.
            depth: Current recursion depth (internal use; callers should
                leave at default 0).
        """
        # Safety limit: prevent stack overflow on pathological input.
        # 5000 is generous enough for real programs (which rarely nest
        # beyond ~200 levels) while preventing runaway recursion on
        # adversarial or corrupt data.
        if depth > 5000:
            return
        while self.start <= addr < self.end:
            # Already traced this address — we've merged with a known path
            if addr in self.code:
                return
            # Address falls in a user-marked data region
            if self.in_data_region(addr):
                return
            opcode = self.mem[addr]
            # Undefined opcode — probably data, not code
            if opcode not in OPCODES:
                return
            mnem, mode, size = OPCODES[opcode]
            # Undocumented opcode — almost certainly data, stop tracing
            if mnem in self.UNDOC_MNEMONICS:
                return
            # Multi-byte NOP (opcode != $EA) — likely data misinterpreted
            if mnem == "NOP" and opcode != 0xEA:
                return
            # Instruction extends past the analyzable region
            if addr + size > self.end:
                return
            # Check that operand bytes don't overlap a data region
            if any(self.in_data_region(addr + i) for i in range(1, size)):
                return
            # Mark all bytes of this instruction as code
            for i in range(size):
                self.code.add(addr + i)

            # Handle branch instructions (conditional jumps)
            if mode == "REL" and size == 2:
                offset = self.mem[addr + 1]
                if offset > 127:
                    offset -= 256  # Sign-extend the 8-bit offset
                target = addr + 2 + offset  # Branch target = next instruction + offset
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None  # Mark for later naming
                    # Recursively trace the branch target
                    self.trace(target, depth + 1)
                # Fall through: continue tracing the non-taken path

            # Handle JSR (subroutine call)
            if mnem == "JSR" and size == 3:
                target = self.mem[addr + 1] | (self.mem[addr + 2] << 8)
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None
                    # Recursively trace the subroutine
                    self.trace(target, depth + 1)
                # Fall through: continue after JSR (assuming it returns)

            # Handle JMP absolute (unconditional jump)
            if mnem == "JMP" and mode == "ABS" and size == 3:
                target = self.mem[addr + 1] | (self.mem[addr + 2] << 8)
                if self.start <= target < self.end:
                    if target not in self.labels:
                        self.labels[target] = None
                    # Trace the jump target, then STOP (no fall-through)
                    self.trace(target, depth + 1)
                return  # Unconditional jump — no fall-through path

            # Handle JMP indirect — target is determined at runtime, cannot trace
            if mnem == "JMP" and mode == "IND":
                return

            # Handle RTS, RTI, BRK — execution returns to caller or halts
            if mnem in ("RTS", "RTI", "BRK"):
                return

            # Advance to the next instruction (fall-through)
            addr += size

    def name_labels(self):
        """Assign human-readable names to all discovered labels.

        Labels are named based on how they are referenced:
          - SUB_xxxx: Address is the target of at least one JSR instruction
            (i.e., it is a subroutine entry point).
          - L_xxxx: Address is the target of a branch or JMP but never a JSR
            (i.e., it is a local code label).

        Only labels with no existing name (value is None) are renamed.
        Pre-assigned labels (e.g., user-provided names) are preserved.
        """
        sorted_addrs = sorted(self.labels.keys())
        for addr in sorted_addrs:
            # Skip labels that already have a name
            if self.labels[addr] is not None:
                continue
            # Check if any JSR in the code set targets this address
            is_sub = False
            for check_addr in self.code:
                if self.mem[check_addr] == 0x20:  # 0x20 = JSR opcode
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
        """Format the operand of an instruction as a string.

        Substitutes symbolic label names where available. For example, if
        address $4050 has the label "SUB_4050", then "JSR $4050" becomes
        "JSR SUB_4050".

        Args:
            addr: Address of the instruction (used to read operand bytes
                from self.mem).
            mnem: Instruction mnemonic (e.g., "LDA", "JSR").
            mode: Addressing mode code (e.g., "ABS", "REL", "IMM").
            size: Instruction byte count (1, 2, or 3).

        Returns:
            Formatted operand string (e.g., "#$05", "SUB_4050", "$C030,X").
            Returns empty string for IMP and ACC modes.
        """
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
            val = self.mem[addr+1] | (self.mem[addr+2] << 8)  # Little-endian
            label = self.labels.get(val)
            suffix = ""
            if mode == "ABX":
                suffix = ",X"
            elif mode == "ABY":
                suffix = ",Y"
            # Use symbolic label if one exists for this address
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
                offset -= 256  # Sign-extend
            target = addr + 2 + offset
            label = self.labels.get(target)
            if label:
                return label
            return f"${target:04X}"
        return ""

    def disassemble_range(self, start, end):
        """Disassemble a range with code/data classification.

        Bytes in self.code are disassembled as instructions. All other bytes
        are emitted as data directives:
          - HEX: Raw hex bytes (for short data runs or mixed data)
          - DS: Fill directive for runs of 8+ identical bytes (e.g., "DS 32,$00")

        Data emission is broken at label boundaries so that labels are
        always placed correctly. Data runs are capped at 16 bytes per line
        for readability.

        Args:
            start: First address to disassemble.
            end: One past the last address to disassemble (exclusive).

        Returns:
            List of (addr, label, instruction, comment) tuples.
        """
        lines = []
        addr = start
        while addr < end:
            label = self.labels.get(addr, "")
            label_str = label if label else ""

            if addr in self.code:
                # Emit as a code instruction
                opcode = self.mem[addr]
                if opcode in OPCODES:
                    mnem, mode, size = OPCODES[opcode]
                    operand = self.format_operand(addr, mnem, mode, size)
                    instr = f"{mnem} {operand}" if operand else mnem
                    comment = self.comments.get(addr, "")
                    lines.append((addr, label_str, instr, comment))
                    addr += size
                else:
                    # Should not happen (code set only contains known opcodes),
                    # but handle gracefully as a data byte.
                    lines.append((addr, label_str, f"DFB ${self.mem[addr]:02X}", ""))
                    addr += 1
            else:
                # Emit as data: collect consecutive non-code bytes
                data_start = addr
                data_bytes = []
                while addr < end and addr not in self.code:
                    # Break at label boundaries to ensure labels appear correctly
                    if addr in self.labels and addr != data_start:
                        break
                    data_bytes.append(self.mem[addr])
                    addr += 1
                    # Cap at 16 bytes per line for readability
                    if len(data_bytes) >= 16:
                        break

                # Detect fill regions: 8+ identical bytes get a compact DS directive
                if len(data_bytes) >= 8 and all(b == data_bytes[0] for b in data_bytes):
                    fill_val = data_bytes[0]
                    # Extend the fill run as far as possible
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
                    # Emit as raw hex bytes
                    hex_str = "".join(f"{b:02X}" for b in data_bytes)
                    comment = self.comments.get(data_start, "")
                    lines.append((data_start, label_str, f"HEX {hex_str}", comment))

        return lines


def add_hardware_comments(dis, mem):
    """Add comments for hardware register accesses to a Disassembler.

    Scans all code bytes in the disassembler's code set for absolute-addressed
    instructions that reference known Apple II hardware registers ($C0xx) or
    known Monitor ROM entry points ($Fxxx). Matching instructions get a
    comment added to dis.comments.

    Args:
        dis: A Disassembler instance (must have trace() already called).
        mem: The same memory buffer used by the disassembler.
    """
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

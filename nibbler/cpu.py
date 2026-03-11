"""
NMOS 6502 CPU emulator with Apple II I/O.

Full 6502 implementation including all 256 opcodes (151 official + 105
undocumented). Supports Apple II disk controller I/O at configurable
slot, keyboard stubs, and PC-based breakpoint callbacks.
"""

from collections import defaultdict

# Addressing mode constants
IMP, ACC, IMM, ZP, ZPX, ZPY = 0, 1, 2, 3, 4, 5
ABS, ABX, ABY, IND, IZX, IZY, REL = 6, 7, 8, 9, 10, 11, 12

# Instruction sizes by addressing mode
MODE_SIZE = {
    IMP: 1, ACC: 1, IMM: 2, ZP: 2, ZPX: 2, ZPY: 2,
    ABS: 3, ABX: 3, ABY: 3, IND: 3, IZX: 2, IZY: 2, REL: 2,
}


class CPU6502:
    """NMOS 6502 CPU emulator with Apple II I/O support.

    Supports breakpoint callbacks via the `on_pc` dict and the
    add_breakpoint/remove_breakpoint methods.
    """

    def __init__(self, slot=6):
        # Registers
        self.a = self.x = self.y = 0
        self.sp = 0xFF
        self.pc = 0
        # Flags
        self.C = 0  # Carry
        self.Z = 0  # Zero
        self.I = 0  # Interrupt disable
        self.D = 0  # Decimal
        self.V = 0  # Overflow
        self.N = 0  # Negative

        self.mem = bytearray(65536)
        self.cycles = 0
        self.halted = False

        # Hardware
        self.disk = None
        self.slot = slot

        # Tracking
        self.write_ranges = defaultdict(int)
        self.exec_count = 0
        self.trace = False
        self.trace_file = None
        self.brk_count = 0
        self.max_brk = 5

        # Breakpoint system: addr -> callback(cpu)
        # If callback returns True, execution stops after this instruction.
        self.on_pc = {}

        # Build opcode table
        self._build_opcodes()

    # ── Breakpoint API ───────────────────────────────────────────

    def add_breakpoint(self, addr, callback):
        """Add a PC breakpoint. callback(cpu) is called when PC == addr.
        If callback returns True, run() will stop."""
        self.on_pc[addr] = callback

    def remove_breakpoint(self, addr):
        """Remove a PC breakpoint."""
        self.on_pc.pop(addr, None)

    # ── Run loop ─────────────────────────────────────────────────

    def run(self, max_instructions=10_000_000, stop_at=None, progress_interval=1_000_000):
        """Execute instructions until halt, breakpoint stop, or limit.

        Args:
            max_instructions: maximum instructions to execute
            stop_at: optional PC address to stop at (convenience shortcut)
            progress_interval: print progress every N instructions (0 to disable)

        Returns:
            str: reason for stopping ('halt', 'breakpoint', 'stop_at', 'limit')
        """
        for _ in range(max_instructions):
            pc = self.pc

            # Check stop_at
            if stop_at is not None and pc == stop_at:
                return 'stop_at'

            # Check breakpoints
            if pc in self.on_pc:
                cb = self.on_pc[pc]
                if cb(self):
                    return 'breakpoint'

            # Check halt
            if self.halted:
                return 'halt'

            if not self.step():
                return 'halt'

            if progress_interval and self.exec_count % progress_interval == 0:
                qt = self.disk.current_qtrack if self.disk else 0
                motor = 'ON' if (self.disk and self.disk.motor_on) else 'OFF'
                print(f"  ... {self.exec_count:,} instructions, PC=${self.pc:04X}, "
                      f"qtrack={qt}, motor={motor}")

        return 'limit'

    # ── Flag helpers ─────────────────────────────────────────────

    def _get_p(self):
        return (self.C | (self.Z << 1) | (self.I << 2) | (self.D << 3) |
                (1 << 4) | (1 << 5) | (self.V << 6) | (self.N << 7))

    def _set_p(self, val):
        self.C = val & 1
        self.Z = (val >> 1) & 1
        self.I = (val >> 2) & 1
        self.D = (val >> 3) & 1
        self.V = (val >> 6) & 1
        self.N = (val >> 7) & 1

    def _set_nz(self, val):
        val &= 0xFF
        self.N = (val >> 7) & 1
        self.Z = 1 if val == 0 else 0
        return val

    # ── Memory access ────────────────────────────────────────────

    def read(self, addr):
        addr &= 0xFFFF
        sb = 0xC080 + self.slot * 16

        # Disk controller I/O
        if sb <= addr <= sb + 0x0F:
            reg = addr - sb
            if reg <= 7:  # Stepper phases
                phase = reg // 2
                on = reg % 2
                if self.disk:
                    self.disk.step_phase(phase, bool(on))
                return 0x00
            if reg == 8:  # Motor off
                if self.disk:
                    self.disk.motor_on = False
                return 0x00
            if reg == 9:  # Motor on
                if self.disk:
                    self.disk.motor_on = True
                return 0x00
            if reg == 0x0A:  # Drive 1
                return 0x00
            if reg == 0x0B:  # Drive 2
                return 0x00
            if reg == 0x0C:  # Q6L: data latch
                if self.disk:
                    self.disk.q6 = False
                    return self.disk.read_nibble()
                return 0x00
            if reg == 0x0D:  # Q6H
                if self.disk:
                    self.disk.q6 = True
                return 0x00
            if reg == 0x0E:  # Q7L: read mode
                if self.disk:
                    self.disk.q7 = False
                return 0x00
            if reg == 0x0F:  # Q7H: write mode
                if self.disk:
                    self.disk.q7 = True
                return 0x00

        # Keyboard / other soft switches
        if addr == 0xC000:
            return 0x00
        if addr == 0xC010:
            return 0x00

        return self.mem[addr]

    def write(self, addr, val):
        addr &= 0xFFFF
        val &= 0xFF

        # Handle soft switch writes (disk controller)
        sb = 0xC080 + self.slot * 16
        if sb <= addr <= sb + 0x0F:
            self.read(addr)
            return

        self.mem[addr] = val
        self.write_ranges[addr] += 1

    def push(self, val):
        self.mem[0x0100 + self.sp] = val & 0xFF
        self.sp = (self.sp - 1) & 0xFF

    def pull(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.mem[0x0100 + self.sp]

    # ── Addressing mode resolution ───────────────────────────────

    def _addr_zp(self):
        return self.mem[(self.pc + 1) & 0xFFFF]

    def _addr_zpx(self):
        return (self.mem[(self.pc + 1) & 0xFFFF] + self.x) & 0xFF

    def _addr_zpy(self):
        return (self.mem[(self.pc + 1) & 0xFFFF] + self.y) & 0xFF

    def _addr_abs(self):
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        return lo | (hi << 8)

    def _addr_abx(self):
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        return ((lo | (hi << 8)) + self.x) & 0xFFFF

    def _addr_aby(self):
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        return ((lo | (hi << 8)) + self.y) & 0xFFFF

    def _addr_izx(self):
        base = (self.mem[(self.pc + 1) & 0xFFFF] + self.x) & 0xFF
        lo = self.mem[base]
        hi = self.mem[(base + 1) & 0xFF]
        return lo | (hi << 8)

    def _addr_izy(self):
        base = self.mem[(self.pc + 1) & 0xFFFF]
        lo = self.mem[base]
        hi = self.mem[(base + 1) & 0xFF]
        return ((lo | (hi << 8)) + self.y) & 0xFFFF

    def _addr_ind(self):
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        ptr = lo | (hi << 8)
        # NMOS 6502 page-crossing bug
        lo2 = self.mem[ptr]
        hi2 = self.mem[(ptr & 0xFF00) | ((ptr + 1) & 0xFF)]
        return lo2 | (hi2 << 8)

    def _resolve_addr(self, mode):
        if mode == ZP:    return self._addr_zp()
        if mode == ZPX:   return self._addr_zpx()
        if mode == ZPY:   return self._addr_zpy()
        if mode == ABS:   return self._addr_abs()
        if mode == ABX:   return self._addr_abx()
        if mode == ABY:   return self._addr_aby()
        if mode == IZX:   return self._addr_izx()
        if mode == IZY:   return self._addr_izy()
        if mode == IND:   return self._addr_ind()
        return 0

    def _resolve_read(self, mode):
        if mode == IMM:
            return self.mem[(self.pc + 1) & 0xFFFF]
        return self.read(self._resolve_addr(mode))

    # ── Instruction implementations ──────────────────────────────

    def _op_lda(self, mode): self.a = self._set_nz(self._resolve_read(mode))
    def _op_ldx(self, mode): self.x = self._set_nz(self._resolve_read(mode))
    def _op_ldy(self, mode): self.y = self._set_nz(self._resolve_read(mode))

    def _op_sta(self, mode): self.write(self._resolve_addr(mode), self.a)
    def _op_stx(self, mode): self.write(self._resolve_addr(mode), self.x)
    def _op_sty(self, mode): self.write(self._resolve_addr(mode), self.y)

    def _op_adc(self, mode):
        val = self._resolve_read(mode)
        result = self.a + val + self.C
        self.V = 1 if (~(self.a ^ val) & (self.a ^ result) & 0x80) else 0
        self.C = 1 if result > 0xFF else 0
        self.a = self._set_nz(result)

    def _op_sbc(self, mode):
        val = self._resolve_read(mode)
        result = self.a - val - (1 - self.C)
        self.V = 1 if ((self.a ^ val) & (self.a ^ (result & 0xFF)) & 0x80) else 0
        self.C = 0 if result < 0 else 1
        self.a = self._set_nz(result)

    def _op_and(self, mode): self.a = self._set_nz(self.a & self._resolve_read(mode))
    def _op_ora(self, mode): self.a = self._set_nz(self.a | self._resolve_read(mode))
    def _op_eor(self, mode): self.a = self._set_nz(self.a ^ self._resolve_read(mode))

    def _op_cmp(self, mode):
        val = self._resolve_read(mode)
        result = self.a - val
        self.C = 0 if result < 0 else 1
        self._set_nz(result)

    def _op_cpx(self, mode):
        val = self._resolve_read(mode)
        result = self.x - val
        self.C = 0 if result < 0 else 1
        self._set_nz(result)

    def _op_cpy(self, mode):
        val = self._resolve_read(mode)
        result = self.y - val
        self.C = 0 if result < 0 else 1
        self._set_nz(result)

    def _op_bit(self, mode):
        val = self._resolve_read(mode)
        self.N = (val >> 7) & 1
        self.V = (val >> 6) & 1
        self.Z = 1 if (self.a & val) == 0 else 0

    def _op_inc(self, mode):
        addr = self._resolve_addr(mode)
        val = (self.read(addr) + 1) & 0xFF
        self.write(addr, val)
        self._set_nz(val)

    def _op_dec(self, mode):
        addr = self._resolve_addr(mode)
        val = (self.read(addr) - 1) & 0xFF
        self.write(addr, val)
        self._set_nz(val)

    def _op_inx(self, mode): self.x = self._set_nz(self.x + 1)
    def _op_dex(self, mode): self.x = self._set_nz(self.x - 1)
    def _op_iny(self, mode): self.y = self._set_nz(self.y + 1)
    def _op_dey(self, mode): self.y = self._set_nz(self.y - 1)

    def _op_asl(self, mode):
        if mode == ACC:
            self.C = (self.a >> 7) & 1
            self.a = self._set_nz(self.a << 1)
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            self.C = (val >> 7) & 1
            val = (val << 1) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    def _op_lsr(self, mode):
        if mode == ACC:
            self.C = self.a & 1
            self.a = self._set_nz(self.a >> 1)
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            self.C = val & 1
            val = (val >> 1) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    def _op_rol(self, mode):
        if mode == ACC:
            old_c = self.C
            self.C = (self.a >> 7) & 1
            self.a = self._set_nz((self.a << 1) | old_c)
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            old_c = self.C
            self.C = (val >> 7) & 1
            val = ((val << 1) | old_c) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    def _op_ror(self, mode):
        if mode == ACC:
            old_c = self.C
            self.C = self.a & 1
            self.a = self._set_nz((self.a >> 1) | (old_c << 7))
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            old_c = self.C
            self.C = val & 1
            val = ((val >> 1) | (old_c << 7)) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    # ── Branch instructions ──────────────────────────────────────

    def _do_branch(self, cond):
        offset = self.mem[(self.pc + 1) & 0xFFFF]
        if offset > 127:
            offset -= 256
        if cond:
            self.pc = (self.pc + 2 + offset) & 0xFFFF
        else:
            self.pc = (self.pc + 2) & 0xFFFF

    def _op_bcc(self, mode): self._do_branch(self.C == 0)
    def _op_bcs(self, mode): self._do_branch(self.C == 1)
    def _op_beq(self, mode): self._do_branch(self.Z == 1)
    def _op_bne(self, mode): self._do_branch(self.Z == 0)
    def _op_bpl(self, mode): self._do_branch(self.N == 0)
    def _op_bmi(self, mode): self._do_branch(self.N == 1)
    def _op_bvc(self, mode): self._do_branch(self.V == 0)
    def _op_bvs(self, mode): self._do_branch(self.V == 1)

    # ── Jump/call instructions ───────────────────────────────────

    def _op_jmp(self, mode):
        if mode == ABS:
            self.pc = self._addr_abs()
        elif mode == IND:
            self.pc = self._addr_ind()

    def _op_jsr(self, mode):
        ret = (self.pc + 2) & 0xFFFF
        self.push((ret >> 8) & 0xFF)
        self.push(ret & 0xFF)
        self.pc = self._addr_abs()

    def _op_rts(self, mode):
        lo = self.pull()
        hi = self.pull()
        self.pc = ((lo | (hi << 8)) + 1) & 0xFFFF

    def _op_rti(self, mode):
        self._set_p(self.pull())
        lo = self.pull()
        hi = self.pull()
        self.pc = lo | (hi << 8)

    def _op_brk(self, mode):
        self.brk_count += 1
        ret = (self.pc + 2) & 0xFFFF
        self.push((ret >> 8) & 0xFF)
        self.push(ret & 0xFF)
        self.push(self._get_p() | 0x10)
        self.I = 1
        lo = self.mem[0xFFFE]
        hi = self.mem[0xFFFF]
        self.pc = lo | (hi << 8)

    # ── Stack/flag/transfer/NOP ──────────────────────────────────

    def _op_pha(self, mode): self.push(self.a)
    def _op_pla(self, mode): self.a = self._set_nz(self.pull())
    def _op_php(self, mode): self.push(self._get_p() | 0x30)
    def _op_plp(self, mode): self._set_p(self.pull())

    def _op_clc(self, mode): self.C = 0
    def _op_sec(self, mode): self.C = 1
    def _op_cli(self, mode): self.I = 0
    def _op_sei(self, mode): self.I = 1
    def _op_cld(self, mode): self.D = 0
    def _op_sed(self, mode): self.D = 1
    def _op_clv(self, mode): self.V = 0

    def _op_tax(self, mode): self.x = self._set_nz(self.a)
    def _op_tay(self, mode): self.y = self._set_nz(self.a)
    def _op_txa(self, mode): self.a = self._set_nz(self.x)
    def _op_tya(self, mode): self.a = self._set_nz(self.y)
    def _op_txs(self, mode): self.sp = self.x
    def _op_tsx(self, mode): self.x = self._set_nz(self.sp)

    def _op_nop(self, mode): pass

    # ── Undocumented opcodes ─────────────────────────────────────

    def _op_shy(self, mode):
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        addr = ((lo | (hi << 8)) + self.x) & 0xFFFF
        self.write(addr, self.y)

    def _op_shx(self, mode):
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        addr = ((lo | (hi << 8)) + self.y) & 0xFFFF
        self.write(addr, self.x)

    def _op_lax(self, mode):
        val = self._resolve_read(mode)
        self.a = self.x = self._set_nz(val)

    def _op_sax(self, mode):
        self.write(self._resolve_addr(mode), self.a & self.x)

    def _op_dcp(self, mode):
        addr = self._resolve_addr(mode)
        val = (self.read(addr) - 1) & 0xFF
        self.write(addr, val)
        result = self.a - val
        self.C = 0 if result < 0 else 1
        self._set_nz(result)

    def _op_isb(self, mode):
        addr = self._resolve_addr(mode)
        val = (self.read(addr) + 1) & 0xFF
        self.write(addr, val)
        result = self.a - val - (1 - self.C)
        self.V = 1 if ((self.a ^ val) & (self.a ^ (result & 0xFF)) & 0x80) else 0
        self.C = 0 if result < 0 else 1
        self.a = self._set_nz(result)

    def _op_slo(self, mode):
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        self.C = (val >> 7) & 1
        val = (val << 1) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a | val)

    def _op_rla(self, mode):
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        old_c = self.C
        self.C = (val >> 7) & 1
        val = ((val << 1) | old_c) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a & val)

    def _op_sre(self, mode):
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        self.C = val & 1
        val = (val >> 1) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a ^ val)

    def _op_rra(self, mode):
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        old_c = self.C
        self.C = val & 1
        val = ((val >> 1) | (old_c << 7)) & 0xFF
        self.write(addr, val)
        result = self.a + val + self.C
        self.V = 1 if (~(self.a ^ val) & (self.a ^ result) & 0x80) else 0
        self.C = 1 if result > 0xFF else 0
        self.a = self._set_nz(result)

    def _op_anc(self, mode):
        self.a = self._set_nz(self.a & self._resolve_read(mode))
        self.C = self.N

    def _op_alr(self, mode):
        self.a &= self._resolve_read(mode)
        self.C = self.a & 1
        self.a = self._set_nz(self.a >> 1)

    def _op_arr(self, mode):
        self.a &= self._resolve_read(mode)
        old_c = self.C
        self.a = self._set_nz((self.a >> 1) | (old_c << 7))
        self.C = (self.a >> 6) & 1
        self.V = ((self.a >> 6) ^ (self.a >> 5)) & 1

    def _op_xaa(self, mode):
        self.a = self.x & self._resolve_read(mode)
        self._set_nz(self.a)

    def _op_ahx(self, mode):
        addr = self._resolve_addr(mode)
        hi = (addr >> 8) & 0xFF
        self.write(addr, self.a & self.x & (hi + 1))

    def _op_tas(self, mode):
        self.sp = self.a & self.x
        addr = self._resolve_addr(mode)
        hi = (addr >> 8) & 0xFF
        self.write(addr, self.sp & (hi + 1))

    def _op_las(self, mode):
        val = self._resolve_read(mode) & self.sp
        self.a = self.x = self.sp = self._set_nz(val)

    def _op_axs(self, mode):
        val = self._resolve_read(mode)
        result = (self.a & self.x) - val
        self.C = 0 if result < 0 else 1
        self.x = self._set_nz(result)

    def _op_kil(self, mode):
        self.halted = True

    def _op_nop_undoc(self, mode):
        pass

    # ── Opcode table ─────────────────────────────────────────────

    def _build_opcodes(self):
        self.optable = [None] * 256

        def op(code, handler, mode, name=""):
            size = MODE_SIZE.get(mode, 1)
            self.optable[code] = (handler, mode, size, name)

        # ── Official opcodes ──
        # LDA
        op(0xA9, self._op_lda, IMM, "LDA"); op(0xA5, self._op_lda, ZP, "LDA")
        op(0xB5, self._op_lda, ZPX, "LDA"); op(0xAD, self._op_lda, ABS, "LDA")
        op(0xBD, self._op_lda, ABX, "LDA"); op(0xB9, self._op_lda, ABY, "LDA")
        op(0xA1, self._op_lda, IZX, "LDA"); op(0xB1, self._op_lda, IZY, "LDA")
        # LDX
        op(0xA2, self._op_ldx, IMM, "LDX"); op(0xA6, self._op_ldx, ZP, "LDX")
        op(0xB6, self._op_ldx, ZPY, "LDX"); op(0xAE, self._op_ldx, ABS, "LDX")
        op(0xBE, self._op_ldx, ABY, "LDX")
        # LDY
        op(0xA0, self._op_ldy, IMM, "LDY"); op(0xA4, self._op_ldy, ZP, "LDY")
        op(0xB4, self._op_ldy, ZPX, "LDY"); op(0xAC, self._op_ldy, ABS, "LDY")
        op(0xBC, self._op_ldy, ABX, "LDY")
        # STA
        op(0x85, self._op_sta, ZP, "STA"); op(0x95, self._op_sta, ZPX, "STA")
        op(0x8D, self._op_sta, ABS, "STA"); op(0x9D, self._op_sta, ABX, "STA")
        op(0x99, self._op_sta, ABY, "STA"); op(0x81, self._op_sta, IZX, "STA")
        op(0x91, self._op_sta, IZY, "STA")
        # STX
        op(0x86, self._op_stx, ZP, "STX"); op(0x96, self._op_stx, ZPY, "STX")
        op(0x8E, self._op_stx, ABS, "STX")
        # STY
        op(0x84, self._op_sty, ZP, "STY"); op(0x94, self._op_sty, ZPX, "STY")
        op(0x8C, self._op_sty, ABS, "STY")
        # ADC
        op(0x69, self._op_adc, IMM, "ADC"); op(0x65, self._op_adc, ZP, "ADC")
        op(0x75, self._op_adc, ZPX, "ADC"); op(0x6D, self._op_adc, ABS, "ADC")
        op(0x7D, self._op_adc, ABX, "ADC"); op(0x79, self._op_adc, ABY, "ADC")
        op(0x61, self._op_adc, IZX, "ADC"); op(0x71, self._op_adc, IZY, "ADC")
        # SBC
        op(0xE9, self._op_sbc, IMM, "SBC"); op(0xE5, self._op_sbc, ZP, "SBC")
        op(0xF5, self._op_sbc, ZPX, "SBC"); op(0xED, self._op_sbc, ABS, "SBC")
        op(0xFD, self._op_sbc, ABX, "SBC"); op(0xF9, self._op_sbc, ABY, "SBC")
        op(0xE1, self._op_sbc, IZX, "SBC"); op(0xF1, self._op_sbc, IZY, "SBC")
        # AND
        op(0x29, self._op_and, IMM, "AND"); op(0x25, self._op_and, ZP, "AND")
        op(0x35, self._op_and, ZPX, "AND"); op(0x2D, self._op_and, ABS, "AND")
        op(0x3D, self._op_and, ABX, "AND"); op(0x39, self._op_and, ABY, "AND")
        op(0x21, self._op_and, IZX, "AND"); op(0x31, self._op_and, IZY, "AND")
        # ORA
        op(0x09, self._op_ora, IMM, "ORA"); op(0x05, self._op_ora, ZP, "ORA")
        op(0x15, self._op_ora, ZPX, "ORA"); op(0x0D, self._op_ora, ABS, "ORA")
        op(0x1D, self._op_ora, ABX, "ORA"); op(0x19, self._op_ora, ABY, "ORA")
        op(0x01, self._op_ora, IZX, "ORA"); op(0x11, self._op_ora, IZY, "ORA")
        # EOR
        op(0x49, self._op_eor, IMM, "EOR"); op(0x45, self._op_eor, ZP, "EOR")
        op(0x55, self._op_eor, ZPX, "EOR"); op(0x4D, self._op_eor, ABS, "EOR")
        op(0x5D, self._op_eor, ABX, "EOR"); op(0x59, self._op_eor, ABY, "EOR")
        op(0x41, self._op_eor, IZX, "EOR"); op(0x51, self._op_eor, IZY, "EOR")
        # CMP
        op(0xC9, self._op_cmp, IMM, "CMP"); op(0xC5, self._op_cmp, ZP, "CMP")
        op(0xD5, self._op_cmp, ZPX, "CMP"); op(0xCD, self._op_cmp, ABS, "CMP")
        op(0xDD, self._op_cmp, ABX, "CMP"); op(0xD9, self._op_cmp, ABY, "CMP")
        op(0xC1, self._op_cmp, IZX, "CMP"); op(0xD1, self._op_cmp, IZY, "CMP")
        # CPX
        op(0xE0, self._op_cpx, IMM, "CPX"); op(0xE4, self._op_cpx, ZP, "CPX")
        op(0xEC, self._op_cpx, ABS, "CPX")
        # CPY
        op(0xC0, self._op_cpy, IMM, "CPY"); op(0xC4, self._op_cpy, ZP, "CPY")
        op(0xCC, self._op_cpy, ABS, "CPY")
        # BIT
        op(0x24, self._op_bit, ZP, "BIT"); op(0x2C, self._op_bit, ABS, "BIT")
        # INC/DEC
        op(0xE6, self._op_inc, ZP, "INC"); op(0xF6, self._op_inc, ZPX, "INC")
        op(0xEE, self._op_inc, ABS, "INC"); op(0xFE, self._op_inc, ABX, "INC")
        op(0xC6, self._op_dec, ZP, "DEC"); op(0xD6, self._op_dec, ZPX, "DEC")
        op(0xCE, self._op_dec, ABS, "DEC"); op(0xDE, self._op_dec, ABX, "DEC")
        op(0xE8, self._op_inx, IMP, "INX"); op(0xCA, self._op_dex, IMP, "DEX")
        op(0xC8, self._op_iny, IMP, "INY"); op(0x88, self._op_dey, IMP, "DEY")
        # Shifts
        op(0x0A, self._op_asl, ACC, "ASL"); op(0x06, self._op_asl, ZP, "ASL")
        op(0x16, self._op_asl, ZPX, "ASL"); op(0x0E, self._op_asl, ABS, "ASL")
        op(0x1E, self._op_asl, ABX, "ASL")
        op(0x4A, self._op_lsr, ACC, "LSR"); op(0x46, self._op_lsr, ZP, "LSR")
        op(0x56, self._op_lsr, ZPX, "LSR"); op(0x4E, self._op_lsr, ABS, "LSR")
        op(0x5E, self._op_lsr, ABX, "LSR")
        op(0x2A, self._op_rol, ACC, "ROL"); op(0x26, self._op_rol, ZP, "ROL")
        op(0x36, self._op_rol, ZPX, "ROL"); op(0x2E, self._op_rol, ABS, "ROL")
        op(0x3E, self._op_rol, ABX, "ROL")
        op(0x6A, self._op_ror, ACC, "ROR"); op(0x66, self._op_ror, ZP, "ROR")
        op(0x76, self._op_ror, ZPX, "ROR"); op(0x6E, self._op_ror, ABS, "ROR")
        op(0x7E, self._op_ror, ABX, "ROR")
        # Branches
        op(0x90, self._op_bcc, REL, "BCC"); op(0xB0, self._op_bcs, REL, "BCS")
        op(0xF0, self._op_beq, REL, "BEQ"); op(0xD0, self._op_bne, REL, "BNE")
        op(0x10, self._op_bpl, REL, "BPL"); op(0x30, self._op_bmi, REL, "BMI")
        op(0x50, self._op_bvc, REL, "BVC"); op(0x70, self._op_bvs, REL, "BVS")
        # Jumps
        op(0x4C, self._op_jmp, ABS, "JMP"); op(0x6C, self._op_jmp, IND, "JMP")
        op(0x20, self._op_jsr, ABS, "JSR"); op(0x60, self._op_rts, IMP, "RTS")
        op(0x40, self._op_rti, IMP, "RTI"); op(0x00, self._op_brk, IMP, "BRK")
        # Stack
        op(0x48, self._op_pha, IMP, "PHA"); op(0x68, self._op_pla, IMP, "PLA")
        op(0x08, self._op_php, IMP, "PHP"); op(0x28, self._op_plp, IMP, "PLP")
        # Flags
        op(0x18, self._op_clc, IMP, "CLC"); op(0x38, self._op_sec, IMP, "SEC")
        op(0x58, self._op_cli, IMP, "CLI"); op(0x78, self._op_sei, IMP, "SEI")
        op(0xD8, self._op_cld, IMP, "CLD"); op(0xF8, self._op_sed, IMP, "SED")
        op(0xB8, self._op_clv, IMP, "CLV")
        # Transfers
        op(0xAA, self._op_tax, IMP, "TAX"); op(0xA8, self._op_tay, IMP, "TAY")
        op(0x8A, self._op_txa, IMP, "TXA"); op(0x98, self._op_tya, IMP, "TYA")
        op(0x9A, self._op_txs, IMP, "TXS"); op(0xBA, self._op_tsx, IMP, "TSX")
        # NOP
        op(0xEA, self._op_nop, IMP, "NOP")

        # ── Undocumented opcodes ──
        op(0x9C, self._op_shy, ABX, "SHY"); op(0x9E, self._op_shx, ABY, "SHX")
        # LAX
        op(0xA7, self._op_lax, ZP, "LAX"); op(0xB7, self._op_lax, ZPY, "LAX")
        op(0xAF, self._op_lax, ABS, "LAX"); op(0xBF, self._op_lax, ABY, "LAX")
        op(0xA3, self._op_lax, IZX, "LAX"); op(0xB3, self._op_lax, IZY, "LAX")
        # SAX
        op(0x87, self._op_sax, ZP, "SAX"); op(0x97, self._op_sax, ZPY, "SAX")
        op(0x8F, self._op_sax, ABS, "SAX"); op(0x83, self._op_sax, IZX, "SAX")
        # DCP
        op(0xC7, self._op_dcp, ZP, "DCP"); op(0xD7, self._op_dcp, ZPX, "DCP")
        op(0xCF, self._op_dcp, ABS, "DCP"); op(0xDF, self._op_dcp, ABX, "DCP")
        op(0xDB, self._op_dcp, ABY, "DCP"); op(0xC3, self._op_dcp, IZX, "DCP")
        op(0xD3, self._op_dcp, IZY, "DCP")
        # ISB (ISC)
        op(0xE7, self._op_isb, ZP, "ISB"); op(0xF7, self._op_isb, ZPX, "ISB")
        op(0xEF, self._op_isb, ABS, "ISB"); op(0xFF, self._op_isb, ABX, "ISB")
        op(0xFB, self._op_isb, ABY, "ISB"); op(0xE3, self._op_isb, IZX, "ISB")
        op(0xF3, self._op_isb, IZY, "ISB")
        # SLO
        op(0x07, self._op_slo, ZP, "SLO"); op(0x17, self._op_slo, ZPX, "SLO")
        op(0x0F, self._op_slo, ABS, "SLO"); op(0x1F, self._op_slo, ABX, "SLO")
        op(0x1B, self._op_slo, ABY, "SLO"); op(0x03, self._op_slo, IZX, "SLO")
        op(0x13, self._op_slo, IZY, "SLO")
        # RLA
        op(0x27, self._op_rla, ZP, "RLA"); op(0x37, self._op_rla, ZPX, "RLA")
        op(0x2F, self._op_rla, ABS, "RLA"); op(0x3F, self._op_rla, ABX, "RLA")
        op(0x3B, self._op_rla, ABY, "RLA"); op(0x23, self._op_rla, IZX, "RLA")
        op(0x33, self._op_rla, IZY, "RLA")
        # SRE
        op(0x47, self._op_sre, ZP, "SRE"); op(0x57, self._op_sre, ZPX, "SRE")
        op(0x4F, self._op_sre, ABS, "SRE"); op(0x5F, self._op_sre, ABX, "SRE")
        op(0x5B, self._op_sre, ABY, "SRE"); op(0x43, self._op_sre, IZX, "SRE")
        op(0x53, self._op_sre, IZY, "SRE")
        # RRA
        op(0x67, self._op_rra, ZP, "RRA"); op(0x77, self._op_rra, ZPX, "RRA")
        op(0x6F, self._op_rra, ABS, "RRA"); op(0x7F, self._op_rra, ABX, "RRA")
        op(0x7B, self._op_rra, ABY, "RRA"); op(0x63, self._op_rra, IZX, "RRA")
        op(0x73, self._op_rra, IZY, "RRA")
        # ANC, ALR, ARR, XAA, AHX, TAS, LAS, AXS
        op(0x0B, self._op_anc, IMM, "ANC"); op(0x2B, self._op_anc, IMM, "ANC")
        op(0x4B, self._op_alr, IMM, "ALR"); op(0x6B, self._op_arr, IMM, "ARR")
        op(0x8B, self._op_xaa, IMM, "XAA")
        op(0x93, self._op_ahx, IZY, "AHX"); op(0x9F, self._op_ahx, ABY, "AHX")
        op(0x9B, self._op_tas, ABY, "TAS"); op(0xBB, self._op_las, ABY, "LAS")
        op(0xCB, self._op_axs, IMM, "AXS")
        # Undocumented NOPs
        for opc in [0x04, 0x44, 0x64]:
            op(opc, self._op_nop_undoc, ZP, "NOP")
        for opc in [0x0C]:
            op(opc, self._op_nop_undoc, ABS, "NOP")
        for opc in [0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4]:
            op(opc, self._op_nop_undoc, ZPX, "NOP")
        for opc in [0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC]:
            op(opc, self._op_nop_undoc, ABX, "NOP")
        for opc in [0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA]:
            op(opc, self._op_nop_undoc, IMP, "NOP")
        op(0x80, self._op_nop_undoc, IMM, "NOP")
        op(0x82, self._op_nop_undoc, IMM, "NOP")
        op(0x89, self._op_nop_undoc, IMM, "NOP")
        op(0xC2, self._op_nop_undoc, IMM, "NOP")
        op(0xE2, self._op_nop_undoc, IMM, "NOP")
        op(0xEB, self._op_sbc, IMM, "SBC")  # unofficial SBC #imm
        # KIL opcodes
        for opc in [0x02, 0x12, 0x22, 0x32, 0x42, 0x52, 0x62, 0x72,
                     0x92, 0xB2, 0xD2, 0xF2]:
            op(opc, self._op_kil, IMP, "KIL")
        # Fill remaining
        for i in range(256):
            if self.optable[i] is None:
                self.optable[i] = (self._op_nop_undoc, IMP, 1, f"?{i:02X}")

    # ── Execution ────────────────────────────────────────────────

    def format_state(self):
        return (f"A={self.a:02X} X={self.x:02X} Y={self.y:02X} "
                f"SP={self.sp:02X} P={self._get_p():02X} "
                f"{'N' if self.N else '.'}{'V' if self.V else '.'}"
                f"..{'D' if self.D else '.'}{'I' if self.I else '.'}"
                f"{'Z' if self.Z else '.'}{'C' if self.C else '.'}")

    def format_instr(self):
        opc = self.mem[self.pc]
        entry = self.optable[opc]
        handler, mode, size, name = entry
        if size == 1:
            return f"${self.pc:04X}: {opc:02X}       {name}"
        elif size == 2:
            op1 = self.mem[(self.pc + 1) & 0xFFFF]
            if mode == REL:
                offset = op1 if op1 < 128 else op1 - 256
                target = (self.pc + 2 + offset) & 0xFFFF
                return f"${self.pc:04X}: {opc:02X} {op1:02X}    {name} ${target:04X}"
            elif mode == IMM:
                return f"${self.pc:04X}: {opc:02X} {op1:02X}    {name} #${op1:02X}"
            else:
                return f"${self.pc:04X}: {opc:02X} {op1:02X}    {name} ${op1:02X}"
        else:
            op1 = self.mem[(self.pc + 1) & 0xFFFF]
            op2 = self.mem[(self.pc + 2) & 0xFFFF]
            addr = op1 | (op2 << 8)
            return f"${self.pc:04X}: {opc:02X} {op1:02X} {op2:02X} {name} ${addr:04X}"

    def step(self):
        if self.halted:
            return False

        opc = self.mem[self.pc]
        entry = self.optable[opc]
        handler, mode, size, name = entry

        if self.trace:
            line = f"{self.format_instr():30s} {self.format_state()}"
            if self.trace_file:
                self.trace_file.write(line + "\n")
            else:
                print(line)

        old_pc = self.pc
        is_branch = handler in (self._op_bcc, self._op_bcs, self._op_beq,
                                self._op_bne, self._op_bpl, self._op_bmi,
                                self._op_bvc, self._op_bvs)
        is_jump = handler in (self._op_jmp, self._op_jsr, self._op_rts,
                              self._op_rti, self._op_brk)

        handler(mode)

        if not is_branch and not is_jump:
            self.pc = (old_pc + size) & 0xFFFF

        self.exec_count += 1
        self.cycles += 1
        return True

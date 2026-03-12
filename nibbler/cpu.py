"""
NMOS 6502 CPU emulator with Apple II I/O.

Full 6502 implementation including all 256 opcodes (151 official + 105
undocumented/illegal). Supports Apple II disk controller I/O at a configurable
slot, keyboard stubs, and PC-based breakpoint callbacks.

Usage::

    from cpu import CPU6502

    cpu = CPU6502(slot=6)

    # Load a ROM image into memory at a given base address
    rom = open("program.bin", "rb").read()
    cpu.mem[0x0800:0x0800 + len(rom)] = rom
    cpu.pc = 0x0800

    # Optionally attach a disk controller for Apple II disk I/O
    cpu.disk = some_disk_controller_object

    # Run until halt, breakpoint, or instruction limit
    reason = cpu.run(max_instructions=1_000_000)

    # Or single-step
    cpu.step()

Breakpoint API::

    def my_hook(cpu):
        print(f"Hit ${cpu.pc:04X}, A={cpu.a:02X}")
        return True  # return True to stop execution

    cpu.add_breakpoint(0x0800, my_hook)
    cpu.run()

The emulator does NOT model cycle-accurate timing or decimal mode arithmetic.
Cycle counts are incremented by 1 per instruction (used only as a rough
measure of progress, not for hardware-accurate timing).
"""

from collections import defaultdict

# ── Addressing Mode Constants ─────────────────────────────────────────
# Each constant identifies a 6502 addressing mode, used as keys into
# MODE_SIZE and by the opcode table to tell handlers how to fetch operands.
IMP, ACC, IMM, ZP, ZPX, ZPY = 0, 1, 2, 3, 4, 5
ABS, ABX, ABY, IND, IZX, IZY, REL = 6, 7, 8, 9, 10, 11, 12

# Instruction byte sizes by addressing mode (includes the opcode byte).
# IMP/ACC = 1 byte (opcode only), IMM/ZP/ZPX/ZPY/IZX/IZY/REL = 2 bytes,
# ABS/ABX/ABY/IND = 3 bytes.
MODE_SIZE = {
    IMP: 1, ACC: 1, IMM: 2, ZP: 2, ZPX: 2, ZPY: 2,
    ABS: 3, ABX: 3, ABY: 3, IND: 3, IZX: 2, IZY: 2, REL: 2,
}


class CPU6502:
    """NMOS 6502 CPU emulator with Apple II I/O support.

    Emulates the full NMOS 6502 instruction set including all 105 undocumented
    opcodes.  Provides memory-mapped I/O for an Apple II disk controller at a
    configurable slot and stub handlers for the keyboard soft switches.

    Supports breakpoint callbacks via the ``on_pc`` dict and the
    ``add_breakpoint``/``remove_breakpoint`` methods.

    Attributes:
        a, x, y: 8-bit CPU registers (accumulator, X index, Y index).
        sp: 8-bit stack pointer (addresses $0100-$01FF in memory).
        pc: 16-bit program counter.
        C, Z, I, D, V, N: Individual processor status flags.
        mem: 64 KB flat address space as a bytearray.
        cycles: Rough instruction counter (incremented by 1 per instruction).
        halted: True after a KIL opcode or manual halt.
        disk: Optional disk controller object for Apple II I/O.
        slot: Apple II peripheral slot number (0-7) for disk I/O base address.
        trace: When True, each executed instruction is printed/logged.
        on_pc: Dict mapping addresses to breakpoint callback functions.
    """

    def __init__(self, slot=6):
        """Initialize CPU state, memory, and opcode dispatch table.

        Args:
            slot: Apple II peripheral slot number (0-7). Determines the
                  base address for disk controller I/O soft switches at
                  $C080 + slot*16 .. $C08F + slot*16.  Default is slot 6,
                  the standard disk controller slot.
        """
        # ── Registers ─────────────────────────────────────────────
        self.a = self.x = self.y = 0       # 8-bit general-purpose registers
        self.sp = 0xFF                     # Stack pointer (stack is $0100-$01FF)
        self.pc = 0                        # 16-bit program counter

        # ── Processor Status Flags ────────────────────────────────
        self.C = 0  # Carry
        self.Z = 0  # Zero
        self.I = 0  # Interrupt disable
        self.D = 0  # Decimal (not functionally implemented for arithmetic)
        self.V = 0  # Overflow
        self.N = 0  # Negative (sign bit)

        # ── Memory ────────────────────────────────────────────────
        self.mem = bytearray(65536)  # 64 KB flat address space

        self.cycles = 0       # Rough per-instruction cycle counter
        self.halted = False   # Set True by KIL opcode to stop execution

        # ── Hardware I/O ──────────────────────────────────────────
        self.disk = None      # Disk controller object (e.g., DiskII)
        self.slot = slot      # Apple II slot for disk I/O base address

        # ── Diagnostics / Tracing ─────────────────────────────────
        self.write_ranges = defaultdict(int)  # addr -> write count histogram
        self.exec_count = 0                   # Total instructions executed
        self.trace = False                    # Enable per-instruction trace output
        self.trace_file = None                # File object for trace output (None = stdout)
        self.brk_count = 0                    # Number of BRK instructions encountered
        self.max_brk = 5                      # Threshold (informational, not enforced)

        # ── Breakpoint System ─────────────────────────────────────
        # Maps address -> callback(cpu).
        # If callback returns True, run() stops after this instruction.
        self.on_pc = {}

        # Build the 256-entry opcode dispatch table
        self._build_opcodes()

    # ── Breakpoint API ───────────────────────────────────────────

    def add_breakpoint(self, addr, callback):
        """Register a PC breakpoint.

        Args:
            addr: 16-bit address to break on.
            callback: Function called as callback(cpu) when PC == addr.
                      If it returns True, run() will stop execution.
        """
        self.on_pc[addr] = callback

    def remove_breakpoint(self, addr):
        """Remove a PC breakpoint (no-op if addr has no breakpoint)."""
        self.on_pc.pop(addr, None)

    # ── Run Loop ─────────────────────────────────────────────────

    def run(self, max_instructions=10_000_000, stop_at=None, progress_interval=1_000_000):
        """Execute instructions until a stop condition is met.

        Stop conditions checked each iteration, in order:
          1. ``stop_at`` -- if PC equals this address, return immediately.
          2. ``on_pc`` breakpoint -- if a registered callback returns True.
          3. ``halted`` flag -- set by KIL opcode or external code.
          4. ``step()`` returns False -- also triggered by halted state.
          5. ``max_instructions`` limit reached.

        Args:
            max_instructions: Hard upper bound on instructions to execute.
            stop_at: Optional PC address that triggers an immediate stop
                     (convenience shortcut equivalent to a breakpoint that
                     always returns True).
            progress_interval: Print a status line every N instructions.
                               Set to 0 to disable progress output.

        Returns:
            str: Reason for stopping -- one of:
                 'halt', 'breakpoint', 'stop_at', 'limit'.
        """
        for _ in range(max_instructions):
            pc = self.pc

            # Check stop_at (convenience breakpoint)
            if stop_at is not None and pc == stop_at:
                return 'stop_at'

            # Check registered breakpoints
            if pc in self.on_pc:
                cb = self.on_pc[pc]
                if cb(self):
                    return 'breakpoint'

            # Check halt (KIL or external)
            if self.halted:
                return 'halt'

            # Execute one instruction; step() returns False if halted
            if not self.step():
                return 'halt'

            # Periodic progress reporting
            if progress_interval and self.exec_count % progress_interval == 0:
                qt = self.disk.current_qtrack if self.disk else 0
                motor = 'ON' if (self.disk and self.disk.motor_on) else 'OFF'
                print(f"  ... {self.exec_count:,} instructions, PC=${self.pc:04X}, "
                      f"qtrack={qt}, motor={motor}")

        return 'limit'

    # ── Flag Helpers ─────────────────────────────────────────────

    def _get_p(self):
        """Pack individual flag attributes into the 8-bit processor status byte.

        Bit layout of the P register:
          Bit 7: N (Negative)
          Bit 6: V (Overflow)
          Bit 5: 1 (always set, unused)
          Bit 4: B (Break -- always 1 when read via PHP/BRK)
          Bit 3: D (Decimal)
          Bit 2: I (Interrupt disable)
          Bit 1: Z (Zero)
          Bit 0: C (Carry)
        """
        # Bits 4 and 5 are always set when P is pushed or read
        return (self.C | (self.Z << 1) | (self.I << 2) | (self.D << 3) |
                (1 << 4) | (1 << 5) | (self.V << 6) | (self.N << 7))

    def _set_p(self, val):
        """Unpack an 8-bit status byte into individual flag attributes.

        Bits 4 (B) and 5 (unused) are ignored -- they have no storage in
        the real 6502 and are only artifacts of how P is pushed to the stack.
        """
        self.C = val & 1
        self.Z = (val >> 1) & 1
        self.I = (val >> 2) & 1
        self.D = (val >> 3) & 1
        self.V = (val >> 6) & 1
        self.N = (val >> 7) & 1

    def _set_nz(self, val):
        """Set the N and Z flags from an 8-bit result value. Returns val & 0xFF."""
        val &= 0xFF
        self.N = (val >> 7) & 1            # Bit 7 is the sign/negative bit
        self.Z = 1 if val == 0 else 0
        return val

    # ── Memory Access ────────────────────────────────────────────

    def read(self, addr):
        """Read a byte from the 64 KB address space.

        Intercepts reads to Apple II soft-switch ranges:
          - Disk controller I/O at $C0s0-$C0sF (where s = $80 + slot*16)
          - Keyboard data at $C000, keyboard strobe clear at $C010

        For disk controller addresses, the 16 registers ($C0s0-$C0sF) are:
          $00-$07: Stepper motor phases 0-3 (even=off, odd=on)
          $08: Motor off
          $09: Motor on
          $0A: Select drive 1
          $0B: Select drive 2
          $0C: Q6L -- read data latch (shift register output)
          $0D: Q6H -- (write protect sense when Q7L)
          $0E: Q7L -- select read mode
          $0F: Q7H -- select write mode
        """
        addr &= 0xFFFF
        # Compute disk controller I/O base: $C080 + slot * 16
        sb = 0xC080 + self.slot * 16       # e.g., slot 6 -> $C0E0

        # ── Disk controller soft switches ($C0s0-$C0sF) ──────────
        if sb <= addr <= sb + 0x0F:
            reg = addr - sb                # Register offset 0x00-0x0F
            if reg <= 7:                   # Stepper motor phase registers
                phase = reg // 2           # Phase number 0-3
                on = reg % 2               # 0 = phase off, 1 = phase on
                if self.disk:
                    self.disk.step_phase(phase, bool(on))
                return 0x00
            if reg == 8:                   # $C0s8: Motor off
                if self.disk:
                    self.disk.motor_on = False
                return 0x00
            if reg == 9:                   # $C0s9: Motor on
                if self.disk:
                    self.disk.motor_on = True
                return 0x00
            if reg == 0x0A:                # $C0sA: Select drive 1
                return 0x00
            if reg == 0x0B:                # $C0sB: Select drive 2
                return 0x00
            if reg == 0x0C:                # $C0sC: Q6L -- read data latch
                if self.disk:
                    self.disk.q6 = False
                    return self.disk.read_nibble()
                return 0x00
            if reg == 0x0D:                # $C0sD: Q6H
                if self.disk:
                    self.disk.q6 = True
                return 0x00
            if reg == 0x0E:                # $C0sE: Q7L -- read mode
                if self.disk:
                    self.disk.q7 = False
                return 0x00
            if reg == 0x0F:                # $C0sF: Q7H -- write mode
                if self.disk:
                    self.disk.q7 = True
                return 0x00

        # ── Keyboard soft switches (stubs) ────────────────────────
        if addr == 0xC000:                 # Keyboard data (bit 7 = key available)
            return 0x00                    # Stub: no key pressed
        if addr == 0xC010:                 # Keyboard strobe clear
            return 0x00                    # Stub: acknowledge

        return self.mem[addr]

    def write(self, addr, val):
        """Write a byte to the 64 KB address space.

        Writes to the disk controller soft-switch range are redirected to
        read() (accessing a soft switch is the trigger, regardless of
        read vs. write). All other writes go to the flat memory array and
        are recorded in write_ranges for diagnostics.
        """
        addr &= 0xFFFF
        val &= 0xFF

        # Disk controller soft switches: a write triggers the same
        # side effects as a read (the Disk II hardware is latch-based).
        sb = 0xC080 + self.slot * 16
        if sb <= addr <= sb + 0x0F:
            self.read(addr)
            return

        self.mem[addr] = val
        self.write_ranges[addr] += 1       # Track write frequency per address

    def push(self, val):
        """Push a byte onto the hardware stack at $0100+SP, then decrement SP."""
        self.mem[0x0100 + self.sp] = val & 0xFF   # Stack page is $0100-$01FF
        self.sp = (self.sp - 1) & 0xFF             # SP wraps within 0x00-0xFF

    def pull(self):
        """Increment SP, then pull (read) a byte from the stack at $0100+SP."""
        self.sp = (self.sp + 1) & 0xFF
        return self.mem[0x0100 + self.sp]

    # ── Addressing Mode Resolution ───────────────────────────────

    def _addr_zp(self):
        """Zero-page: operand byte is the address ($00xx)."""
        return self.mem[(self.pc + 1) & 0xFFFF]

    def _addr_zpx(self):
        """Zero-page,X: (operand + X) wrapped to zero page."""
        return (self.mem[(self.pc + 1) & 0xFFFF] + self.x) & 0xFF

    def _addr_zpy(self):
        """Zero-page,Y: (operand + Y) wrapped to zero page."""
        return (self.mem[(self.pc + 1) & 0xFFFF] + self.y) & 0xFF

    def _addr_abs(self):
        """Absolute: 16-bit address from two operand bytes (little-endian)."""
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        return lo | (hi << 8)

    def _addr_abx(self):
        """Absolute,X: 16-bit base address + X register."""
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        return ((lo | (hi << 8)) + self.x) & 0xFFFF

    def _addr_aby(self):
        """Absolute,Y: 16-bit base address + Y register."""
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        return ((lo | (hi << 8)) + self.y) & 0xFFFF

    def _addr_izx(self):
        """Indexed indirect (X): pointer at zero-page address (operand + X)."""
        base = (self.mem[(self.pc + 1) & 0xFFFF] + self.x) & 0xFF
        lo = self.mem[base]
        hi = self.mem[(base + 1) & 0xFF]   # Wraps within zero page
        return lo | (hi << 8)

    def _addr_izy(self):
        """Indirect indexed (Y): pointer at zero-page address, then + Y."""
        base = self.mem[(self.pc + 1) & 0xFFFF]
        lo = self.mem[base]
        hi = self.mem[(base + 1) & 0xFF]   # Wraps within zero page
        return ((lo | (hi << 8)) + self.y) & 0xFFFF

    def _addr_ind(self):
        """Indirect (JMP only): 16-bit pointer with NMOS page-crossing bug.

        The NMOS 6502 has a hardware bug: if the pointer address is $xxFF,
        the high byte is fetched from $xx00 instead of $(xx+1)00.  For
        example, JMP ($10FF) reads the low byte from $10FF and the high
        byte from $1000, NOT $1100.
        """
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        ptr = lo | (hi << 8)
        lo2 = self.mem[ptr]
        # NMOS page-crossing bug: high byte wraps within the same page
        hi2 = self.mem[(ptr & 0xFF00) | ((ptr + 1) & 0xFF)]
        return lo2 | (hi2 << 8)

    def _resolve_addr(self, mode):
        """Dispatch to the appropriate addressing mode handler and return the
        resolved effective address."""
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
        """Resolve the operand value: for IMM mode, return the literal byte;
        for all other modes, read from the resolved address."""
        if mode == IMM:
            return self.mem[(self.pc + 1) & 0xFFFF]
        return self.read(self._resolve_addr(mode))

    # ── Instruction Implementations ──────────────────────────────
    # Simple load/store/transfer instructions set N and Z flags from the
    # result value.  No individual docstrings for these -- they map 1:1
    # to the 6502 instruction set reference.

    def _op_lda(self, mode): self.a = self._set_nz(self._resolve_read(mode))
    def _op_ldx(self, mode): self.x = self._set_nz(self._resolve_read(mode))
    def _op_ldy(self, mode): self.y = self._set_nz(self._resolve_read(mode))

    def _op_sta(self, mode): self.write(self._resolve_addr(mode), self.a)
    def _op_stx(self, mode): self.write(self._resolve_addr(mode), self.x)
    def _op_sty(self, mode): self.write(self._resolve_addr(mode), self.y)

    def _op_adc(self, mode):
        """Add with carry: A = A + M + C.

        Overflow flag (V) detection uses the standard two's-complement formula:
          V is set when both operands have the same sign (bit 7) but the
          result has a different sign.  Expressed as a bitmask:
            ~(A ^ M)   -- bits where A and M have the SAME sign
            (A ^ R)    -- bits where A and result have DIFFERENT signs
            & 0x80     -- isolate bit 7 (the sign bit)
          If that expression is non-zero, signed overflow occurred.
        """
        val = self._resolve_read(mode)
        result = self.a + val + self.C
        # Overflow: set if sign of A and val match, but sign of result differs
        self.V = 1 if (~(self.a ^ val) & (self.a ^ result) & 0x80) else 0
        self.C = 1 if result > 0xFF else 0  # Unsigned carry out of bit 7
        self.a = self._set_nz(result)

    def _op_sbc(self, mode):
        """Subtract with borrow: A = A - M - (1-C).

        Overflow flag (V) uses the subtraction variant of the formula:
          (A ^ M)     -- bits where A and M have DIFFERENT signs
          (A ^ R)     -- bits where A and result have DIFFERENT signs
          & 0x80      -- isolate bit 7
        Subtraction overflow occurs when operands have different signs and
        the result's sign matches the subtrahend rather than the minuend.
        """
        val = self._resolve_read(mode)
        result = self.a - val - (1 - self.C)   # Borrow is inverted carry
        # Overflow: set when subtracting a negative from a positive (or vice
        # versa) produces a result whose sign doesn't match the minuend (A).
        self.V = 1 if ((self.a ^ val) & (self.a ^ (result & 0xFF)) & 0x80) else 0
        self.C = 0 if result < 0 else 1        # Borrow: C=0 means borrow occurred
        self.a = self._set_nz(result)

    def _op_and(self, mode): self.a = self._set_nz(self.a & self._resolve_read(mode))
    def _op_ora(self, mode): self.a = self._set_nz(self.a | self._resolve_read(mode))
    def _op_eor(self, mode): self.a = self._set_nz(self.a ^ self._resolve_read(mode))

    def _op_cmp(self, mode):
        val = self._resolve_read(mode)
        result = self.a - val
        self.C = 0 if result < 0 else 1    # C=1 if A >= M (unsigned)
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
        """BIT - Test bits in memory.

        Unusual flag behavior compared to other instructions:
          N := bit 7 of the memory value (NOT of A & M)
          V := bit 6 of the memory value (NOT of A & M)
          Z := 1 if (A AND M) == 0, else 0
        N and V are set from the memory operand directly, independent of A.
        Only Z reflects the actual AND result.
        """
        val = self._resolve_read(mode)
        self.N = (val >> 7) & 1            # N comes from memory bit 7, not the AND
        self.V = (val >> 6) & 1            # V comes from memory bit 6, not the AND
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
        """Arithmetic Shift Left: shift all bits left, bit 7 goes into C, 0 fills bit 0."""
        if mode == ACC:
            self.C = (self.a >> 7) & 1     # Old bit 7 -> Carry
            self.a = self._set_nz(self.a << 1)
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            self.C = (val >> 7) & 1
            val = (val << 1) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    def _op_lsr(self, mode):
        """Logical Shift Right: shift all bits right, bit 0 goes into C, 0 fills bit 7."""
        if mode == ACC:
            self.C = self.a & 1            # Old bit 0 -> Carry
            self.a = self._set_nz(self.a >> 1)
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            self.C = val & 1
            val = (val >> 1) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    def _op_rol(self, mode):
        """Rotate Left through carry.

        9-bit rotation: [C] <- [b7 b6 b5 b4 b3 b2 b1 b0] <- [C]
        The old carry becomes the new bit 0, and the old bit 7 becomes
        the new carry.  This is a 9-bit rotate (8 data bits + carry).
        """
        if mode == ACC:
            old_c = self.C
            self.C = (self.a >> 7) & 1     # Old bit 7 -> new Carry
            self.a = self._set_nz((self.a << 1) | old_c)  # Old Carry -> new bit 0
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            old_c = self.C
            self.C = (val >> 7) & 1
            val = ((val << 1) | old_c) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    def _op_ror(self, mode):
        """Rotate Right through carry.

        9-bit rotation: [C] -> [b7 b6 b5 b4 b3 b2 b1 b0] -> [C]
        The old carry becomes the new bit 7, and the old bit 0 becomes
        the new carry.  This is a 9-bit rotate (8 data bits + carry).
        """
        if mode == ACC:
            old_c = self.C
            self.C = self.a & 1            # Old bit 0 -> new Carry
            self.a = self._set_nz((self.a >> 1) | (old_c << 7))  # Old Carry -> new bit 7
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            old_c = self.C
            self.C = val & 1
            val = ((val >> 1) | (old_c << 7)) & 0xFF
            self.write(addr, val)
            self._set_nz(val)

    # ── Branch Instructions ──────────────────────────────────────

    def _do_branch(self, cond):
        """Shared branch logic: read signed 8-bit offset and conditionally branch.

        The offset byte is treated as signed (-128 to +127).  The branch
        target is calculated relative to the address of the NEXT instruction
        (PC + 2), not the branch instruction itself.
        """
        offset = self.mem[(self.pc + 1) & 0xFFFF]
        if offset > 127:                   # Convert unsigned byte to signed
            offset -= 256
        if cond:
            self.pc = (self.pc + 2 + offset) & 0xFFFF  # Branch taken
        else:
            self.pc = (self.pc + 2) & 0xFFFF           # Branch not taken (skip operand)

    def _op_bcc(self, mode): self._do_branch(self.C == 0)
    def _op_bcs(self, mode): self._do_branch(self.C == 1)
    def _op_beq(self, mode): self._do_branch(self.Z == 1)
    def _op_bne(self, mode): self._do_branch(self.Z == 0)
    def _op_bpl(self, mode): self._do_branch(self.N == 0)
    def _op_bmi(self, mode): self._do_branch(self.N == 1)
    def _op_bvc(self, mode): self._do_branch(self.V == 0)
    def _op_bvs(self, mode): self._do_branch(self.V == 1)

    # ── Jump / Call Instructions ─────────────────────────────────

    def _op_jmp(self, mode):
        if mode == ABS:
            self.pc = self._addr_abs()
        elif mode == IND:
            self.pc = self._addr_ind()

    def _op_jsr(self, mode):
        """Jump to Subroutine: push return address - 1, then jump.

        The 6502 pushes (PC + 2), which is the address of the LAST byte of
        the JSR instruction, not the next instruction.  RTS adds 1 to
        compensate, yielding the correct return address.
        """
        ret = (self.pc + 2) & 0xFFFF       # Address of last byte of JSR
        self.push((ret >> 8) & 0xFF)       # Push high byte first
        self.push(ret & 0xFF)              # Then low byte
        self.pc = self._addr_abs()

    def _op_rts(self, mode):
        """Return from Subroutine: pull address from stack and add 1.

        Compensates for JSR having pushed (target - 1).
        """
        lo = self.pull()
        hi = self.pull()
        self.pc = ((lo | (hi << 8)) + 1) & 0xFFFF  # +1 to get past the JSR operand

    def _op_rti(self, mode):
        """Return from Interrupt: restore P flags and PC from stack."""
        self._set_p(self.pull())           # Restore processor status
        lo = self.pull()
        hi = self.pull()
        self.pc = lo | (hi << 8)           # Restore full 16-bit PC

    def _op_brk(self, mode):
        """Software interrupt (BRK).

        Pushes PC+2 (skipping the padding byte after BRK), pushes P with
        the B flag (bit 4) set, sets the I flag, and jumps to the IRQ/BRK
        vector at $FFFE/$FFFF.
        """
        self.brk_count += 1
        ret = (self.pc + 2) & 0xFFFF       # Skip BRK + padding byte
        self.push((ret >> 8) & 0xFF)
        self.push(ret & 0xFF)
        self.push(self._get_p() | 0x10)    # 0x10 = B flag (bit 4) set
        self.I = 1                         # Disable further interrupts
        lo = self.mem[0xFFFE]              # IRQ/BRK vector low byte
        hi = self.mem[0xFFFF]              # IRQ/BRK vector high byte
        self.pc = lo | (hi << 8)

    # ── Stack / Flag / Transfer / NOP ────────────────────────────

    def _op_pha(self, mode): self.push(self.a)
    def _op_pla(self, mode): self.a = self._set_nz(self.pull())
    def _op_php(self, mode): self.push(self._get_p() | 0x30)  # 0x30 = bits 4,5 always set
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
    def _op_txs(self, mode): self.sp = self.x    # TXS does NOT set N/Z flags
    def _op_tsx(self, mode): self.x = self._set_nz(self.sp)

    def _op_nop(self, mode): pass

    # ── Undocumented / Illegal Opcodes ───────────────────────────
    # These opcodes are not part of the official 6502 instruction set but
    # are produced by the NMOS silicon and have deterministic (if sometimes
    # odd) behavior.  Some copy-protected Apple II software relies on them.
    #
    # References:
    #   - "Extra Instructions Of The 65XX Series CPU" (NMOS 6510 Unintended
    #     Opcodes), by Groepaz/Hitmen
    #   - "64doc" by John West and Marko Makela
    #   - "No More Secrets" (VICE test suite)

    def _op_shy(self, mode):
        """SHY (9C) -- Store (Y AND (high_byte_of_address + 1)) at addr+X.

        Undocumented. Also known as SAY/SYA. Stores Y ANDed with the high
        byte of the target address plus 1.  This is a simplified version
        that just stores Y (the AND with high+1 can affect the stored
        address on page-crossing, which is the truly weird NMOS glitch
        behavior -- not fully emulated here).
        """
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        addr = ((lo | (hi << 8)) + self.x) & 0xFFFF
        self.write(addr, self.y)

    def _op_shx(self, mode):
        """SHX (9E) -- Store (X AND (high_byte_of_address + 1)) at addr+Y.

        Undocumented. Also known as SXA/XAS. The X-register counterpart
        of SHY.  Simplified: stores X at the indexed address.
        """
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        addr = ((lo | (hi << 8)) + self.y) & 0xFFFF
        self.write(addr, self.x)

    def _op_lax(self, mode):
        """LAX -- Load both A and X with the same memory value.

        Undocumented. Equivalent to LDA + LDX with the same operand.
        Sets N and Z from the loaded value.
        """
        val = self._resolve_read(mode)
        self.a = self.x = self._set_nz(val)

    def _op_sax(self, mode):
        """SAX -- Store (A AND X) into memory.

        Undocumented. Also known as AXS (not to be confused with the
        immediate-mode AXS/SBX). Does NOT affect any flags.
        """
        self.write(self._resolve_addr(mode), self.a & self.x)

    def _op_dcp(self, mode):
        """DCP -- Decrement memory, then Compare with A.

        Undocumented. Equivalent to DEC + CMP with the same address.
        Decrements the memory value, then compares A with the result
        (setting C, N, Z as CMP would).
        """
        addr = self._resolve_addr(mode)
        val = (self.read(addr) - 1) & 0xFF     # DEC
        self.write(addr, val)
        result = self.a - val                  # CMP
        self.C = 0 if result < 0 else 1
        self._set_nz(result)

    def _op_isb(self, mode):
        """ISB (ISC) -- Increment memory, then Subtract from A with borrow.

        Undocumented. Equivalent to INC + SBC with the same address.
        Increments the memory value, then subtracts it from A (with borrow).
        Sets V and C flags using the same overflow formula as SBC.
        """
        addr = self._resolve_addr(mode)
        val = (self.read(addr) + 1) & 0xFF     # INC
        self.write(addr, val)
        result = self.a - val - (1 - self.C)   # SBC
        # Overflow: same formula as _op_sbc (see SBC docstring)
        self.V = 1 if ((self.a ^ val) & (self.a ^ (result & 0xFF)) & 0x80) else 0
        self.C = 0 if result < 0 else 1
        self.a = self._set_nz(result)

    def _op_slo(self, mode):
        """SLO -- Shift Left memory, then OR with A.

        Undocumented. Equivalent to ASL + ORA with the same address.
        Shifts the memory value left (bit 7 -> C), then ORs the result
        into A.
        """
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        self.C = (val >> 7) & 1                # ASL: old bit 7 -> Carry
        val = (val << 1) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a | val)    # ORA

    def _op_rla(self, mode):
        """RLA -- Rotate Left memory, then AND with A.

        Undocumented. Equivalent to ROL + AND with the same address.
        Rotates the memory value left through carry, then ANDs the
        result into A.
        """
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        old_c = self.C
        self.C = (val >> 7) & 1                # ROL: old bit 7 -> new Carry
        val = ((val << 1) | old_c) & 0xFF      # Old Carry -> new bit 0
        self.write(addr, val)
        self.a = self._set_nz(self.a & val)    # AND

    def _op_sre(self, mode):
        """SRE (LSE) -- Shift Right memory, then EOR with A.

        Undocumented. Equivalent to LSR + EOR with the same address.
        Shifts the memory value right (bit 0 -> C), then XORs the
        result into A.
        """
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        self.C = val & 1                       # LSR: old bit 0 -> Carry
        val = (val >> 1) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a ^ val)    # EOR

    def _op_rra(self, mode):
        """RRA -- Rotate Right memory, then Add to A with carry.

        Undocumented. Equivalent to ROR + ADC with the same address.
        Rotates the memory value right through carry, then adds the
        result to A.  Sets V and C using the same overflow formula as ADC.
        """
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        old_c = self.C
        self.C = val & 1                       # ROR: old bit 0 -> new Carry
        val = ((val >> 1) | (old_c << 7)) & 0xFF  # Old Carry -> new bit 7
        self.write(addr, val)
        # ADC phase: add rotated value to A with carry (which is the bit
        # that just fell out of the ROR)
        result = self.a + val + self.C
        # Overflow: same formula as _op_adc (see ADC docstring)
        self.V = 1 if (~(self.a ^ val) & (self.a ^ result) & 0x80) else 0
        self.C = 1 if result > 0xFF else 0
        self.a = self._set_nz(result)

    def _op_anc(self, mode):
        """ANC -- AND immediate, then copy N flag into C.

        Undocumented. ANDs the immediate value with A, sets N and Z,
        then copies the N flag (bit 7 of result) into C.  Effectively
        an AND that also sets carry from the sign bit.
        """
        self.a = self._set_nz(self.a & self._resolve_read(mode))
        self.C = self.N                        # Copy sign bit to carry

    def _op_alr(self, mode):
        """ALR (ASR) -- AND immediate, then Logical Shift Right A.

        Undocumented. Equivalent to AND #imm + LSR A.  ANDs the
        immediate with A, then shifts A right. Bit 0 of the AND result
        goes into carry.
        """
        self.a &= self._resolve_read(mode)     # AND
        self.C = self.a & 1                    # Old bit 0 -> Carry
        self.a = self._set_nz(self.a >> 1)     # LSR

    def _op_arr(self, mode):
        """ARR -- AND immediate, then Rotate Right A (with quirky flag behavior).

        Undocumented. ANDs the immediate with A, then rotates right through
        carry.  Unlike normal ROR, the flag behavior is unusual:
          C := bit 6 of the result (not bit 0)
          V := bit 6 XOR bit 5 of the result
        This is due to internal bus conflicts in the NMOS silicon.
        """
        self.a &= self._resolve_read(mode)     # AND
        old_c = self.C
        self.a = self._set_nz((self.a >> 1) | (old_c << 7))  # ROR
        # Quirky flag setting (not the normal ROR flags):
        self.C = (self.a >> 6) & 1             # C from bit 6 (not bit 0)
        self.V = ((self.a >> 6) ^ (self.a >> 5)) & 1  # V from bit 6 XOR bit 5

    def _op_xaa(self, mode):
        """XAA (ANE) -- Transfer X to A, then AND with immediate.

        Undocumented and UNSTABLE. Exact behavior varies between 6502 chips
        and depends on analog effects.  The commonly emulated version is
        A = X AND #imm.  Some references include an additional OR with a
        "magic constant" that varies per chip.
        """
        self.a = self.x & self._resolve_read(mode)
        self._set_nz(self.a)

    def _op_ahx(self, mode):
        """AHX (SHA/AXA) -- Store (A AND X AND (high_byte + 1)) at address.

        Undocumented. Stores the triple-AND of A, X, and (high byte of the
        target address + 1).  The high byte + 1 factor is an artifact of
        the NMOS internal bus behavior during indexed addressing.
        """
        addr = self._resolve_addr(mode)
        hi = (addr >> 8) & 0xFF
        self.write(addr, self.a & self.x & (hi + 1))

    def _op_tas(self, mode):
        """TAS (SHS/XAS) -- Set SP to (A AND X), then store (SP AND (high_byte + 1)).

        Undocumented. First sets SP = A AND X, then stores
        SP AND (high byte of address + 1) at the target address.
        Combines a stack pointer set with a weird memory store.
        """
        self.sp = self.a & self.x              # SP = A AND X
        addr = self._resolve_addr(mode)
        hi = (addr >> 8) & 0xFF
        self.write(addr, self.sp & (hi + 1))   # Store SP AND (H+1)

    def _op_las(self, mode):
        """LAS (LAR) -- AND memory with SP, store result in A, X, and SP.

        Undocumented. Reads memory, ANDs with the stack pointer, and puts
        the result into A, X, and SP simultaneously.  Sets N and Z flags.
        """
        val = self._resolve_read(mode) & self.sp
        self.a = self.x = self.sp = self._set_nz(val)

    def _op_axs(self, mode):
        """AXS (SBX) -- Set X to (A AND X) minus immediate, without borrow.

        Undocumented. Computes (A AND X) - immediate.  Sets carry as CMP
        would (C=1 if no borrow, C=0 if borrow).  Unlike SBC, this does
        NOT use the carry flag as input (no borrow chain).
        """
        val = self._resolve_read(mode)
        result = (self.a & self.x) - val       # No borrow input (unlike SBC)
        self.C = 0 if result < 0 else 1        # Carry set like CMP
        self.x = self._set_nz(result)

    def _op_kil(self, mode):
        """KIL (JAM/HLT) -- Halt the processor.

        Undocumented. Locks up the real 6502 until a hardware reset.  In
        this emulator, sets the halted flag to stop execution.
        """
        self.halted = True

    def _op_nop_undoc(self, mode):
        """Undocumented NOP -- no operation, but consumes the operand bytes
        indicated by its addressing mode (useful for skipping 1-2 bytes)."""
        pass

    # ── Opcode Dispatch Table ────────────────────────────────────

    def _build_opcodes(self):
        """Build the 256-entry opcode dispatch table.

        Each entry is a tuple: (handler_func, addressing_mode, byte_size, name).
        All 256 byte values are mapped -- official opcodes to their documented
        handlers, and the remaining slots to undocumented opcode handlers
        (LAX, SAX, DCP, ISB, SLO, RLA, SRE, RRA, KIL, etc.).  Any opcode
        not explicitly assigned is filled with a 1-byte undocumented NOP.
        """
        self.optable = [None] * 256

        def op(code, handler, mode, name=""):
            size = MODE_SIZE.get(mode, 1)
            self.optable[code] = (handler, mode, size, name)

        # ── Official Opcodes ─────────────────────────────────────
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

        # ── Undocumented Opcodes ─────────────────────────────────
        op(0x9C, self._op_shy, ABX, "SHY"); op(0x9E, self._op_shx, ABY, "SHX")
        # LAX: load A and X simultaneously
        op(0xA7, self._op_lax, ZP, "LAX"); op(0xB7, self._op_lax, ZPY, "LAX")
        op(0xAF, self._op_lax, ABS, "LAX"); op(0xBF, self._op_lax, ABY, "LAX")
        op(0xA3, self._op_lax, IZX, "LAX"); op(0xB3, self._op_lax, IZY, "LAX")
        # SAX: store A AND X
        op(0x87, self._op_sax, ZP, "SAX"); op(0x97, self._op_sax, ZPY, "SAX")
        op(0x8F, self._op_sax, ABS, "SAX"); op(0x83, self._op_sax, IZX, "SAX")
        # DCP: decrement + compare
        op(0xC7, self._op_dcp, ZP, "DCP"); op(0xD7, self._op_dcp, ZPX, "DCP")
        op(0xCF, self._op_dcp, ABS, "DCP"); op(0xDF, self._op_dcp, ABX, "DCP")
        op(0xDB, self._op_dcp, ABY, "DCP"); op(0xC3, self._op_dcp, IZX, "DCP")
        op(0xD3, self._op_dcp, IZY, "DCP")
        # ISB (ISC): increment + subtract with borrow
        op(0xE7, self._op_isb, ZP, "ISB"); op(0xF7, self._op_isb, ZPX, "ISB")
        op(0xEF, self._op_isb, ABS, "ISB"); op(0xFF, self._op_isb, ABX, "ISB")
        op(0xFB, self._op_isb, ABY, "ISB"); op(0xE3, self._op_isb, IZX, "ISB")
        op(0xF3, self._op_isb, IZY, "ISB")
        # SLO: shift left + OR
        op(0x07, self._op_slo, ZP, "SLO"); op(0x17, self._op_slo, ZPX, "SLO")
        op(0x0F, self._op_slo, ABS, "SLO"); op(0x1F, self._op_slo, ABX, "SLO")
        op(0x1B, self._op_slo, ABY, "SLO"); op(0x03, self._op_slo, IZX, "SLO")
        op(0x13, self._op_slo, IZY, "SLO")
        # RLA: rotate left + AND
        op(0x27, self._op_rla, ZP, "RLA"); op(0x37, self._op_rla, ZPX, "RLA")
        op(0x2F, self._op_rla, ABS, "RLA"); op(0x3F, self._op_rla, ABX, "RLA")
        op(0x3B, self._op_rla, ABY, "RLA"); op(0x23, self._op_rla, IZX, "RLA")
        op(0x33, self._op_rla, IZY, "RLA")
        # SRE: shift right + EOR
        op(0x47, self._op_sre, ZP, "SRE"); op(0x57, self._op_sre, ZPX, "SRE")
        op(0x4F, self._op_sre, ABS, "SRE"); op(0x5F, self._op_sre, ABX, "SRE")
        op(0x5B, self._op_sre, ABY, "SRE"); op(0x43, self._op_sre, IZX, "SRE")
        op(0x53, self._op_sre, IZY, "SRE")
        # RRA: rotate right + ADC
        op(0x67, self._op_rra, ZP, "RRA"); op(0x77, self._op_rra, ZPX, "RRA")
        op(0x6F, self._op_rra, ABS, "RRA"); op(0x7F, self._op_rra, ABX, "RRA")
        op(0x7B, self._op_rra, ABY, "RRA"); op(0x63, self._op_rra, IZX, "RRA")
        op(0x73, self._op_rra, IZY, "RRA")
        # ANC, ALR, ARR, XAA, AHX, TAS, LAS, AXS (immediate / indexed)
        op(0x0B, self._op_anc, IMM, "ANC"); op(0x2B, self._op_anc, IMM, "ANC")
        op(0x4B, self._op_alr, IMM, "ALR"); op(0x6B, self._op_arr, IMM, "ARR")
        op(0x8B, self._op_xaa, IMM, "XAA")
        op(0x93, self._op_ahx, IZY, "AHX"); op(0x9F, self._op_ahx, ABY, "AHX")
        op(0x9B, self._op_tas, ABY, "TAS"); op(0xBB, self._op_las, ABY, "LAS")
        op(0xCB, self._op_axs, IMM, "AXS")
        # Undocumented NOPs (various sizes, consume operand bytes but do nothing)
        for opc in [0x04, 0x44, 0x64]:             # 2-byte ZP NOPs
            op(opc, self._op_nop_undoc, ZP, "NOP")
        for opc in [0x0C]:                         # 3-byte ABS NOP
            op(opc, self._op_nop_undoc, ABS, "NOP")
        for opc in [0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4]:  # 2-byte ZPX NOPs
            op(opc, self._op_nop_undoc, ZPX, "NOP")
        for opc in [0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC]:  # 3-byte ABX NOPs
            op(opc, self._op_nop_undoc, ABX, "NOP")
        for opc in [0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA]:  # 1-byte IMP NOPs
            op(opc, self._op_nop_undoc, IMP, "NOP")
        # 2-byte IMM NOPs
        op(0x80, self._op_nop_undoc, IMM, "NOP")
        op(0x82, self._op_nop_undoc, IMM, "NOP")
        op(0x89, self._op_nop_undoc, IMM, "NOP")
        op(0xC2, self._op_nop_undoc, IMM, "NOP")
        op(0xE2, self._op_nop_undoc, IMM, "NOP")
        # 0xEB: unofficial mirror of SBC #imm (same behavior as 0xE9)
        op(0xEB, self._op_sbc, IMM, "SBC")
        # KIL opcodes: halt the processor (12 opcodes scattered through the map)
        for opc in [0x02, 0x12, 0x22, 0x32, 0x42, 0x52, 0x62, 0x72,
                     0x92, 0xB2, 0xD2, 0xF2]:
            op(opc, self._op_kil, IMP, "KIL")
        # Fill any remaining unassigned slots with 1-byte NOPs
        for i in range(256):
            if self.optable[i] is None:
                self.optable[i] = (self._op_nop_undoc, IMP, 1, f"?{i:02X}")

    # ── Execution / Single-Step ──────────────────────────────────

    def format_state(self):
        """Return a human-readable string of all CPU register and flag values."""
        return (f"A={self.a:02X} X={self.x:02X} Y={self.y:02X} "
                f"SP={self.sp:02X} P={self._get_p():02X} "
                f"{'N' if self.N else '.'}{'V' if self.V else '.'}"
                f"..{'D' if self.D else '.'}{'I' if self.I else '.'}"
                f"{'Z' if self.Z else '.'}{'C' if self.C else '.'}")

    def format_instr(self):
        """Return a disassembly string for the instruction at the current PC.

        Format: "$ADDR: XX [XX [XX]] MNEMONIC operand"
        """
        opc = self.mem[self.pc]
        entry = self.optable[opc]
        handler, mode, size, name = entry
        if size == 1:
            return f"${self.pc:04X}: {opc:02X}       {name}"
        elif size == 2:
            op1 = self.mem[(self.pc + 1) & 0xFFFF]
            if mode == REL:
                # Branch target: PC + 2 (instruction size) + signed offset
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
        """Execute a single instruction and advance PC.

        Returns:
            bool: True if an instruction was executed, False if CPU is halted.

        PC advancement logic:
          - Branch instructions (Bxx) set PC directly in their handler
            (to the branch target or PC+2), so step() must NOT add the
            instruction size again.
          - Jump/call instructions (JMP, JSR, RTS, RTI, BRK) also set PC
            directly in their handlers.
          - All other instructions: step() advances PC by the instruction's
            byte size after the handler returns.

        The is_branch / is_jump checks identify which category the current
        instruction falls into, so step() knows whether to auto-advance PC.
        """
        if self.halted:
            return False

        opc = self.mem[self.pc]
        entry = self.optable[opc]
        handler, mode, size, name = entry

        # Optional trace output: print/log disassembly + register state
        if self.trace:
            line = f"{self.format_instr():30s} {self.format_state()}"
            if self.trace_file:
                self.trace_file.write(line + "\n")
            else:
                print(line)

        old_pc = self.pc

        # Identify instructions that set PC themselves (branches and jumps).
        # For these, step() must NOT auto-advance PC after the handler runs.
        is_branch = handler in (self._op_bcc, self._op_bcs, self._op_beq,
                                self._op_bne, self._op_bpl, self._op_bmi,
                                self._op_bvc, self._op_bvs)
        is_jump = handler in (self._op_jmp, self._op_jsr, self._op_rts,
                              self._op_rti, self._op_brk)

        # Execute the instruction
        handler(mode)

        # Auto-advance PC for non-branch, non-jump instructions
        if not is_branch and not is_jump:
            self.pc = (old_pc + size) & 0xFFFF

        self.exec_count += 1
        self.cycles += 1                   # Simplified: 1 cycle per instruction
        return True

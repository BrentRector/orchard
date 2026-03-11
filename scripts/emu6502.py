#!/usr/bin/env python3
"""
6502 Emulator for Apple Panic boot tracing.
Emulates enough Apple II hardware to boot the copy-protected disk
and capture decrypted game code from memory.
"""
import struct
from collections import defaultdict

# ── WOZ2 reader and nibble streamer ──────────────────────────────────

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


class WOZDisk:
    """WOZ2 disk image with nibble streaming for emulated disk I/O."""

    def __init__(self, path):
        self.nibble_tracks = {}  # quarter-track -> [nibbles]
        self.current_qtrack = 0  # quarter-track position
        self.nibble_pos = 0
        self.motor_on = True
        self.phases = [False] * 4  # stepper phases
        self.data_latch = 0
        self.q6 = False  # Q6 state (False = data latch read)
        self.q7 = False  # Q7 state (False = read mode)
        self._parse(path)

    def _parse(self, path):
        with open(path, 'rb') as f:
            data = f.read()
        tmap = data[88:88 + 160]
        tracks_raw = {}
        for i in range(160):
            offset = 256 + i * 8
            sb = struct.unpack_from('<H', data, offset)[0]
            bc = struct.unpack_from('<H', data, offset + 2)[0]
            bits = struct.unpack_from('<I', data, offset + 4)[0]
            if sb == 0 and bc == 0:
                continue
            tracks_raw[i] = {
                'bit_count': bits,
                'data': data[sb * 512:sb * 512 + bc * 512],
            }
        # Convert each track to nibbles
        for qt in range(160):
            tidx = tmap[qt]
            if tidx == 0xFF or tidx not in tracks_raw:
                continue
            t = tracks_raw[tidx]
            self.nibble_tracks[qt] = self._to_nibbles(t['data'], t['bit_count'])

    @staticmethod
    def _to_nibbles(track_data, bit_count):
        bits = []
        for b in track_data:
            for i in range(7, -1, -1):
                bits.append((b >> i) & 1)
                if len(bits) >= bit_count:
                    break
            if len(bits) >= bit_count:
                break
        # Double the bit stream to handle sectors spanning the track
        # boundary (copy protection technique used by Apple Panic)
        double_bits = bits + bits
        nibbles = []
        current = 0
        for b in double_bits:
            current = ((current << 1) | b) & 0xFF
            if current & 0x80:
                nibbles.append(current)
                current = 0
        return nibbles

    def read_nibble(self):
        """Return next nibble from current track (called when Q6L is read)."""
        if not self.motor_on:
            return 0x00
        qt = self.current_qtrack
        track = self.nibble_tracks.get(qt)
        if not track or len(track) == 0:
            return 0xFF
        nib = track[self.nibble_pos % len(track)]
        self.nibble_pos = (self.nibble_pos + 1) % len(track)
        return nib

    def step_phase(self, phase, on):
        """Handle stepper motor phase switch. Phases 0-3 control head position."""
        self.phases[phase] = on
        if not on:
            return
        # Determine direction based on which phase turned on relative to current
        current_phase = (self.current_qtrack // 2) % 4
        diff = (phase - current_phase + 4) % 4
        if diff == 1:
            self.current_qtrack = min(self.current_qtrack + 2, 159)
        elif diff == 3:
            self.current_qtrack = max(self.current_qtrack - 2, 0)
        elif diff == 2:
            pass  # half-track: don't move for now
        self.nibble_pos = 0  # reset position on track change


# ── 6502 CPU Emulator ────────────────────────────────────────────────

# Addressing mode constants
IMP, ACC, IMM, ZP, ZPX, ZPY = 0, 1, 2, 3, 4, 5
ABS, ABX, ABY, IND, IZX, IZY, REL = 6, 7, 8, 9, 10, 11, 12

# Instruction sizes by addressing mode
MODE_SIZE = {
    IMP: 1, ACC: 1, IMM: 2, ZP: 2, ZPX: 2, ZPY: 2,
    ABS: 3, ABX: 3, ABY: 3, IND: 3, IZX: 2, IZY: 2, REL: 2,
}


class CPU6502:
    """NMOS 6502 CPU emulator with Apple II I/O."""

    def __init__(self):
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
        self.slot = 6

        # Tracking
        self.write_ranges = defaultdict(int)
        self.exec_count = 0
        self.trace = False
        self.trace_file = None
        self.brk_count = 0
        self.max_brk = 5

        # Build opcode table
        self._build_opcodes()

    # ── Flag helpers ────────────────────────────────────────────

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

    # ── Memory access ───────────────────────────────────────────

    def read(self, addr):
        addr &= 0xFFFF
        sb = 0xC080 + self.slot * 16  # $C0E0 for slot 6

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

        # Keyboard / other soft switches (return benign values)
        if addr == 0xC000:  # keyboard
            return 0x00
        if addr == 0xC010:  # keyboard strobe clear
            return 0x00

        return self.mem[addr]

    def write(self, addr, val):
        addr &= 0xFFFF
        val &= 0xFF

        # Handle soft switch writes (disk controller)
        sb = 0xC080 + self.slot * 16
        if sb <= addr <= sb + 0x0F:
            self.read(addr)  # Soft switches respond to any access
            return

        self.mem[addr] = val
        self.write_ranges[addr] += 1

    def push(self, val):
        self.mem[0x0100 + self.sp] = val & 0xFF
        self.sp = (self.sp - 1) & 0xFF

    def pull(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.mem[0x0100 + self.sp]

    # ── Addressing mode resolution ──────────────────────────────

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
        zp = (self.mem[(self.pc + 1) & 0xFFFF] + self.x) & 0xFF
        lo = self.mem[zp]
        hi = self.mem[(zp + 1) & 0xFF]
        return lo | (hi << 8)

    def _addr_izy(self):
        zp = self.mem[(self.pc + 1) & 0xFFFF]
        lo = self.mem[zp]
        hi = self.mem[(zp + 1) & 0xFF]
        return ((lo | (hi << 8)) + self.y) & 0xFFFF

    def _addr_ind(self):
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        addr = lo | (hi << 8)
        # NMOS 6502 bug: wraps within page
        tgt_lo = self.mem[addr]
        tgt_hi = self.mem[(addr & 0xFF00) | ((addr + 1) & 0xFF)]
        return tgt_lo | (tgt_hi << 8)

    def _resolve_read(self, mode):
        """Get the value for read-type instructions."""
        if mode == IMM:
            return self.mem[(self.pc + 1) & 0xFFFF]
        if mode == ZP:
            return self.mem[self._addr_zp()]
        if mode == ZPX:
            return self.mem[self._addr_zpx()]
        if mode == ZPY:
            return self.mem[self._addr_zpy()]
        if mode == ABS:
            return self.read(self._addr_abs())
        if mode == ABX:
            return self.read(self._addr_abx())
        if mode == ABY:
            return self.read(self._addr_aby())
        if mode == IZX:
            return self.read(self._addr_izx())
        if mode == IZY:
            return self.read(self._addr_izy())
        if mode == ACC:
            return self.a
        return 0

    def _resolve_addr(self, mode):
        """Get the address for write/RMW instructions."""
        if mode == ZP:
            return self._addr_zp()
        if mode == ZPX:
            return self._addr_zpx()
        if mode == ZPY:
            return self._addr_zpy()
        if mode == ABS:
            return self._addr_abs()
        if mode == ABX:
            return self._addr_abx()
        if mode == ABY:
            return self._addr_aby()
        if mode == IZX:
            return self._addr_izx()
        if mode == IZY:
            return self._addr_izy()
        return 0

    # ── Instruction implementations ─────────────────────────────

    def _op_lda(self, mode):
        self.a = self._set_nz(self._resolve_read(mode))

    def _op_ldx(self, mode):
        self.x = self._set_nz(self._resolve_read(mode))

    def _op_ldy(self, mode):
        self.y = self._set_nz(self._resolve_read(mode))

    def _op_sta(self, mode):
        self.write(self._resolve_addr(mode), self.a)

    def _op_stx(self, mode):
        self.write(self._resolve_addr(mode), self.x)

    def _op_sty(self, mode):
        self.write(self._resolve_addr(mode), self.y)

    def _op_adc(self, mode):
        val = self._resolve_read(mode)
        if self.D:
            # BCD mode
            al = (self.a & 0x0F) + (val & 0x0F) + self.C
            if al > 9:
                al += 6
            ah = (self.a >> 4) + (val >> 4) + (1 if al > 15 else 0)
            self.Z = 1 if ((self.a + val + self.C) & 0xFF) == 0 else 0
            self.N = (ah >> 3) & 1
            self.V = 1 if (~(self.a ^ val) & (self.a ^ (ah << 4)) & 0x80) else 0
            if ah > 9:
                ah += 6
            self.C = 1 if ah > 15 else 0
            self.a = ((ah << 4) | (al & 0x0F)) & 0xFF
        else:
            result = self.a + val + self.C
            self.V = 1 if (~(self.a ^ val) & (self.a ^ result) & 0x80) else 0
            self.C = 1 if result > 0xFF else 0
            self.a = self._set_nz(result)

    def _op_sbc(self, mode):
        val = self._resolve_read(mode)
        if self.D:
            al = (self.a & 0x0F) - (val & 0x0F) - (1 - self.C)
            if al < 0:
                al = ((al - 6) & 0x0F) | 0x10  # borrow from high nibble
            ah = (self.a >> 4) - (val >> 4) - (1 if al & 0x10 else 0)
            result = self.a - val - (1 - self.C)
            self.C = 0 if result < 0 else 1
            self.V = 1 if ((self.a ^ val) & (self.a ^ (result & 0xFF)) & 0x80) else 0
            if ah < 0:
                ah -= 6
            self.a = self._set_nz(result)
            self.a = ((ah << 4) | (al & 0x0F)) & 0xFF
        else:
            result = self.a - val - (1 - self.C)
            self.V = 1 if ((self.a ^ val) & (self.a ^ (result & 0xFF)) & 0x80) else 0
            self.C = 0 if result < 0 else 1
            self.a = self._set_nz(result)

    def _op_and(self, mode):
        self.a = self._set_nz(self.a & self._resolve_read(mode))

    def _op_ora(self, mode):
        self.a = self._set_nz(self.a | self._resolve_read(mode))

    def _op_eor(self, mode):
        self.a = self._set_nz(self.a ^ self._resolve_read(mode))

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
        val = self._set_nz(self.read(addr) + 1)
        self.write(addr, val)

    def _op_dec(self, mode):
        addr = self._resolve_addr(mode)
        val = self._set_nz(self.read(addr) - 1)
        self.write(addr, val)

    def _op_inx(self, mode):
        self.x = self._set_nz(self.x + 1)

    def _op_dex(self, mode):
        self.x = self._set_nz(self.x - 1)

    def _op_iny(self, mode):
        self.y = self._set_nz(self.y + 1)

    def _op_dey(self, mode):
        self.y = self._set_nz(self.y - 1)

    def _op_asl(self, mode):
        if mode == ACC:
            self.C = (self.a >> 7) & 1
            self.a = self._set_nz(self.a << 1)
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            self.C = (val >> 7) & 1
            self.write(addr, self._set_nz(val << 1))

    def _op_lsr(self, mode):
        if mode == ACC:
            self.C = self.a & 1
            self.a = self._set_nz(self.a >> 1)
        else:
            addr = self._resolve_addr(mode)
            val = self.read(addr)
            self.C = val & 1
            self.write(addr, self._set_nz(val >> 1))

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
            self.write(addr, self._set_nz((val << 1) | old_c))

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
            self.write(addr, self._set_nz((val >> 1) | (old_c << 7)))

    def _branch(self, cond):
        offset = self.mem[(self.pc + 1) & 0xFFFF]
        self.pc = (self.pc + 2) & 0xFFFF
        if cond:
            if offset & 0x80:
                offset -= 256
            self.pc = (self.pc + offset) & 0xFFFF

    def _op_bcc(self, mode):
        self._branch(self.C == 0)

    def _op_bcs(self, mode):
        self._branch(self.C == 1)

    def _op_beq(self, mode):
        self._branch(self.Z == 1)

    def _op_bne(self, mode):
        self._branch(self.Z == 0)

    def _op_bpl(self, mode):
        self._branch(self.N == 0)

    def _op_bmi(self, mode):
        self._branch(self.N == 1)

    def _op_bvc(self, mode):
        self._branch(self.V == 0)

    def _op_bvs(self, mode):
        self._branch(self.V == 1)

    def _op_jmp(self, mode):
        if mode == ABS:
            self.pc = self._addr_abs()
        elif mode == IND:
            self.pc = self._addr_ind()

    def _op_jsr(self, mode):
        ret = (self.pc + 2) & 0xFFFF  # address of last byte of instruction
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
        self.pc = (lo | (hi << 8)) & 0xFFFF

    def _op_brk(self, mode):
        self.brk_count += 1
        ret = (self.pc + 2) & 0xFFFF
        self.push((ret >> 8) & 0xFF)
        self.push(ret & 0xFF)
        self.push(self._get_p() | 0x10)  # B flag set
        self.I = 1
        lo = self.mem[0xFFFE]
        hi = self.mem[0xFFFF]
        self.pc = lo | (hi << 8)

    def _op_pha(self, mode):
        self.push(self.a)

    def _op_pla(self, mode):
        self.a = self._set_nz(self.pull())

    def _op_php(self, mode):
        self.push(self._get_p() | 0x30)  # B and bit5 set

    def _op_plp(self, mode):
        self._set_p(self.pull())

    def _op_clc(self, mode):
        self.C = 0

    def _op_sec(self, mode):
        self.C = 1

    def _op_cli(self, mode):
        self.I = 0

    def _op_sei(self, mode):
        self.I = 1

    def _op_cld(self, mode):
        self.D = 0

    def _op_sed(self, mode):
        self.D = 1

    def _op_clv(self, mode):
        self.V = 0

    def _op_nop(self, mode):
        pass

    def _op_tax(self, mode):
        self.x = self._set_nz(self.a)

    def _op_tay(self, mode):
        self.y = self._set_nz(self.a)

    def _op_txa(self, mode):
        self.a = self._set_nz(self.x)

    def _op_tya(self, mode):
        self.a = self._set_nz(self.y)

    def _op_txs(self, mode):
        self.sp = self.x

    def _op_tsx(self, mode):
        self.x = self._set_nz(self.sp)

    # ── Undocumented opcodes ────────────────────────────────────

    def _op_shy(self, mode):
        """$9C: SHY abs,X - Store Y & (H+1) to addr.
        We implement BOTH: try straight STY first (some NMOS chips)."""
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        addr = ((lo | (hi << 8)) + self.x) & 0xFFFF
        # Use straight Y store (most likely for this protection scheme)
        self.write(addr, self.y)

    def _op_shx(self, mode):
        """$9E: SHX abs,Y - Store X & (H+1) to addr."""
        lo = self.mem[(self.pc + 1) & 0xFFFF]
        hi = self.mem[(self.pc + 2) & 0xFFFF]
        addr = ((lo | (hi << 8)) + self.y) & 0xFFFF
        self.write(addr, self.x)

    def _op_lax(self, mode):
        """$A7/$B7/$AF/$BF/$A3/$B3: LAX - Load A and X."""
        val = self._resolve_read(mode)
        self.a = self.x = self._set_nz(val)

    def _op_sax(self, mode):
        """$87/$97/$8F/$83: SAX - Store A & X."""
        self.write(self._resolve_addr(mode), self.a & self.x)

    def _op_dcp(self, mode):
        """$C7/$D7/$CF/$DF/$DB/$C3/$D3: DCP - DEC then CMP."""
        addr = self._resolve_addr(mode)
        val = (self.read(addr) - 1) & 0xFF
        self.write(addr, val)
        result = self.a - val
        self.C = 0 if result < 0 else 1
        self._set_nz(result)

    def _op_isb(self, mode):
        """$E7/$F7/$EF/$FF/$FB/$E3/$F3: ISB/ISC - INC then SBC."""
        addr = self._resolve_addr(mode)
        val = (self.read(addr) + 1) & 0xFF
        self.write(addr, val)
        # Do SBC with the new value
        old_d = self.D
        result = self.a - val - (1 - self.C)
        self.V = 1 if ((self.a ^ val) & (self.a ^ (result & 0xFF)) & 0x80) else 0
        self.C = 0 if result < 0 else 1
        self.a = self._set_nz(result)

    def _op_slo(self, mode):
        """$07/$17/$0F/$1F/$1B/$03/$13: SLO - ASL then ORA."""
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        self.C = (val >> 7) & 1
        val = (val << 1) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a | val)

    def _op_rla(self, mode):
        """$27/$37/$2F/$3F/$3B/$23/$33: RLA - ROL then AND."""
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        old_c = self.C
        self.C = (val >> 7) & 1
        val = ((val << 1) | old_c) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a & val)

    def _op_sre(self, mode):
        """$47/$57/$4F/$5F/$5B/$43/$53: SRE - LSR then EOR."""
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        self.C = val & 1
        val = (val >> 1) & 0xFF
        self.write(addr, val)
        self.a = self._set_nz(self.a ^ val)

    def _op_rra(self, mode):
        """$67/$77/$6F/$7F/$7B/$63/$73: RRA - ROR then ADC."""
        addr = self._resolve_addr(mode)
        val = self.read(addr)
        old_c = self.C
        self.C = val & 1
        val = ((val >> 1) | (old_c << 7)) & 0xFF
        self.write(addr, val)
        # ADC
        result = self.a + val + self.C
        self.V = 1 if (~(self.a ^ val) & (self.a ^ result) & 0x80) else 0
        self.C = 1 if result > 0xFF else 0
        self.a = self._set_nz(result)

    def _op_anc(self, mode):
        """$0B/$2B: ANC - AND then copy N to C."""
        self.a = self._set_nz(self.a & self._resolve_read(mode))
        self.C = self.N

    def _op_alr(self, mode):
        """$4B: ALR - AND then LSR."""
        self.a &= self._resolve_read(mode)
        self.C = self.a & 1
        self.a = self._set_nz(self.a >> 1)

    def _op_arr(self, mode):
        """$6B: ARR - AND then ROR."""
        self.a &= self._resolve_read(mode)
        old_c = self.C
        self.a = self._set_nz((self.a >> 1) | (old_c << 7))
        self.C = (self.a >> 6) & 1
        self.V = ((self.a >> 6) ^ (self.a >> 5)) & 1

    def _op_xaa(self, mode):
        """$8B: XAA/ANE - unstable."""
        self.a = self.x & self._resolve_read(mode)
        self._set_nz(self.a)

    def _op_ahx(self, mode):
        """$93/$9F: AHX/SHA - Store A & X & (H+1)."""
        addr = self._resolve_addr(mode)
        hi = (addr >> 8) & 0xFF
        self.write(addr, self.a & self.x & (hi + 1))

    def _op_tas(self, mode):
        """$9B: TAS/SHS."""
        self.sp = self.a & self.x
        addr = self._resolve_addr(mode)
        hi = (addr >> 8) & 0xFF
        self.write(addr, self.sp & (hi + 1))

    def _op_las(self, mode):
        """$BB: LAS/LAR."""
        val = self._resolve_read(mode) & self.sp
        self.a = self.x = self.sp = self._set_nz(val)

    def _op_axs(self, mode):
        """$CB: AXS/SBX - (A & X) - imm -> X."""
        val = self._resolve_read(mode)
        result = (self.a & self.x) - val
        self.C = 0 if result < 0 else 1
        self.x = self._set_nz(result)

    def _op_kil(self, mode):
        """Halt the CPU."""
        self.halted = True

    def _op_nop_undoc(self, mode):
        """Undocumented NOP variants - just consume bytes."""
        pass

    # ── Opcode table ────────────────────────────────────────────

    def _build_opcodes(self):
        """Build the full 256-entry opcode dispatch table."""
        # (handler, mode, size, name)
        self.optable = [None] * 256

        def op(code, handler, mode, name=""):
            size = MODE_SIZE.get(mode, 1)
            self.optable[code] = (handler, mode, size, name)

        # ── Official opcodes ──
        # LDA
        op(0xA9, self._op_lda, IMM, "LDA")
        op(0xA5, self._op_lda, ZP, "LDA")
        op(0xB5, self._op_lda, ZPX, "LDA")
        op(0xAD, self._op_lda, ABS, "LDA")
        op(0xBD, self._op_lda, ABX, "LDA")
        op(0xB9, self._op_lda, ABY, "LDA")
        op(0xA1, self._op_lda, IZX, "LDA")
        op(0xB1, self._op_lda, IZY, "LDA")
        # LDX
        op(0xA2, self._op_ldx, IMM, "LDX")
        op(0xA6, self._op_ldx, ZP, "LDX")
        op(0xB6, self._op_ldx, ZPY, "LDX")
        op(0xAE, self._op_ldx, ABS, "LDX")
        op(0xBE, self._op_ldx, ABY, "LDX")
        # LDY
        op(0xA0, self._op_ldy, IMM, "LDY")
        op(0xA4, self._op_ldy, ZP, "LDY")
        op(0xB4, self._op_ldy, ZPX, "LDY")
        op(0xAC, self._op_ldy, ABS, "LDY")
        op(0xBC, self._op_ldy, ABX, "LDY")
        # STA
        op(0x85, self._op_sta, ZP, "STA")
        op(0x95, self._op_sta, ZPX, "STA")
        op(0x8D, self._op_sta, ABS, "STA")
        op(0x9D, self._op_sta, ABX, "STA")
        op(0x99, self._op_sta, ABY, "STA")
        op(0x81, self._op_sta, IZX, "STA")
        op(0x91, self._op_sta, IZY, "STA")
        # STX
        op(0x86, self._op_stx, ZP, "STX")
        op(0x96, self._op_stx, ZPY, "STX")
        op(0x8E, self._op_stx, ABS, "STX")
        # STY
        op(0x84, self._op_sty, ZP, "STY")
        op(0x94, self._op_sty, ZPX, "STY")
        op(0x8C, self._op_sty, ABS, "STY")
        # ADC
        op(0x69, self._op_adc, IMM, "ADC")
        op(0x65, self._op_adc, ZP, "ADC")
        op(0x75, self._op_adc, ZPX, "ADC")
        op(0x6D, self._op_adc, ABS, "ADC")
        op(0x7D, self._op_adc, ABX, "ADC")
        op(0x79, self._op_adc, ABY, "ADC")
        op(0x61, self._op_adc, IZX, "ADC")
        op(0x71, self._op_adc, IZY, "ADC")
        # SBC
        op(0xE9, self._op_sbc, IMM, "SBC")
        op(0xE5, self._op_sbc, ZP, "SBC")
        op(0xF5, self._op_sbc, ZPX, "SBC")
        op(0xED, self._op_sbc, ABS, "SBC")
        op(0xFD, self._op_sbc, ABX, "SBC")
        op(0xF9, self._op_sbc, ABY, "SBC")
        op(0xE1, self._op_sbc, IZX, "SBC")
        op(0xF1, self._op_sbc, IZY, "SBC")
        # AND
        op(0x29, self._op_and, IMM, "AND")
        op(0x25, self._op_and, ZP, "AND")
        op(0x35, self._op_and, ZPX, "AND")
        op(0x2D, self._op_and, ABS, "AND")
        op(0x3D, self._op_and, ABX, "AND")
        op(0x39, self._op_and, ABY, "AND")
        op(0x21, self._op_and, IZX, "AND")
        op(0x31, self._op_and, IZY, "AND")
        # ORA
        op(0x09, self._op_ora, IMM, "ORA")
        op(0x05, self._op_ora, ZP, "ORA")
        op(0x15, self._op_ora, ZPX, "ORA")
        op(0x0D, self._op_ora, ABS, "ORA")
        op(0x1D, self._op_ora, ABX, "ORA")
        op(0x19, self._op_ora, ABY, "ORA")
        op(0x01, self._op_ora, IZX, "ORA")
        op(0x11, self._op_ora, IZY, "ORA")
        # EOR
        op(0x49, self._op_eor, IMM, "EOR")
        op(0x45, self._op_eor, ZP, "EOR")
        op(0x55, self._op_eor, ZPX, "EOR")
        op(0x4D, self._op_eor, ABS, "EOR")
        op(0x5D, self._op_eor, ABX, "EOR")
        op(0x59, self._op_eor, ABY, "EOR")
        op(0x41, self._op_eor, IZX, "EOR")
        op(0x51, self._op_eor, IZY, "EOR")
        # CMP
        op(0xC9, self._op_cmp, IMM, "CMP")
        op(0xC5, self._op_cmp, ZP, "CMP")
        op(0xD5, self._op_cmp, ZPX, "CMP")
        op(0xCD, self._op_cmp, ABS, "CMP")
        op(0xDD, self._op_cmp, ABX, "CMP")
        op(0xD9, self._op_cmp, ABY, "CMP")
        op(0xC1, self._op_cmp, IZX, "CMP")
        op(0xD1, self._op_cmp, IZY, "CMP")
        # CPX
        op(0xE0, self._op_cpx, IMM, "CPX")
        op(0xE4, self._op_cpx, ZP, "CPX")
        op(0xEC, self._op_cpx, ABS, "CPX")
        # CPY
        op(0xC0, self._op_cpy, IMM, "CPY")
        op(0xC4, self._op_cpy, ZP, "CPY")
        op(0xCC, self._op_cpy, ABS, "CPY")
        # BIT
        op(0x24, self._op_bit, ZP, "BIT")
        op(0x2C, self._op_bit, ABS, "BIT")
        # INC/DEC
        op(0xE6, self._op_inc, ZP, "INC")
        op(0xF6, self._op_inc, ZPX, "INC")
        op(0xEE, self._op_inc, ABS, "INC")
        op(0xFE, self._op_inc, ABX, "INC")
        op(0xC6, self._op_dec, ZP, "DEC")
        op(0xD6, self._op_dec, ZPX, "DEC")
        op(0xCE, self._op_dec, ABS, "DEC")
        op(0xDE, self._op_dec, ABX, "DEC")
        op(0xE8, self._op_inx, IMP, "INX")
        op(0xCA, self._op_dex, IMP, "DEX")
        op(0xC8, self._op_iny, IMP, "INY")
        op(0x88, self._op_dey, IMP, "DEY")
        # Shifts
        op(0x0A, self._op_asl, ACC, "ASL")
        op(0x06, self._op_asl, ZP, "ASL")
        op(0x16, self._op_asl, ZPX, "ASL")
        op(0x0E, self._op_asl, ABS, "ASL")
        op(0x1E, self._op_asl, ABX, "ASL")
        op(0x4A, self._op_lsr, ACC, "LSR")
        op(0x46, self._op_lsr, ZP, "LSR")
        op(0x56, self._op_lsr, ZPX, "LSR")
        op(0x4E, self._op_lsr, ABS, "LSR")
        op(0x5E, self._op_lsr, ABX, "LSR")
        op(0x2A, self._op_rol, ACC, "ROL")
        op(0x26, self._op_rol, ZP, "ROL")
        op(0x36, self._op_rol, ZPX, "ROL")
        op(0x2E, self._op_rol, ABS, "ROL")
        op(0x3E, self._op_rol, ABX, "ROL")
        op(0x6A, self._op_ror, ACC, "ROR")
        op(0x66, self._op_ror, ZP, "ROR")
        op(0x76, self._op_ror, ZPX, "ROR")
        op(0x6E, self._op_ror, ABS, "ROR")
        op(0x7E, self._op_ror, ABX, "ROR")
        # Branches
        op(0x90, self._op_bcc, REL, "BCC")
        op(0xB0, self._op_bcs, REL, "BCS")
        op(0xF0, self._op_beq, REL, "BEQ")
        op(0xD0, self._op_bne, REL, "BNE")
        op(0x10, self._op_bpl, REL, "BPL")
        op(0x30, self._op_bmi, REL, "BMI")
        op(0x50, self._op_bvc, REL, "BVC")
        op(0x70, self._op_bvs, REL, "BVS")
        # Jumps
        op(0x4C, self._op_jmp, ABS, "JMP")
        op(0x6C, self._op_jmp, IND, "JMP")
        op(0x20, self._op_jsr, ABS, "JSR")
        op(0x60, self._op_rts, IMP, "RTS")
        op(0x40, self._op_rti, IMP, "RTI")
        op(0x00, self._op_brk, IMP, "BRK")
        # Stack
        op(0x48, self._op_pha, IMP, "PHA")
        op(0x68, self._op_pla, IMP, "PLA")
        op(0x08, self._op_php, IMP, "PHP")
        op(0x28, self._op_plp, IMP, "PLP")
        # Flags
        op(0x18, self._op_clc, IMP, "CLC")
        op(0x38, self._op_sec, IMP, "SEC")
        op(0x58, self._op_cli, IMP, "CLI")
        op(0x78, self._op_sei, IMP, "SEI")
        op(0xD8, self._op_cld, IMP, "CLD")
        op(0xF8, self._op_sed, IMP, "SED")
        op(0xB8, self._op_clv, IMP, "CLV")
        # Transfers
        op(0xAA, self._op_tax, IMP, "TAX")
        op(0xA8, self._op_tay, IMP, "TAY")
        op(0x8A, self._op_txa, IMP, "TXA")
        op(0x98, self._op_tya, IMP, "TYA")
        op(0x9A, self._op_txs, IMP, "TXS")
        op(0xBA, self._op_tsx, IMP, "TSX")
        # NOP
        op(0xEA, self._op_nop, IMP, "NOP")

        # ── Undocumented opcodes ──
        op(0x9C, self._op_shy, ABX, "SHY")  # Key one for boot code
        op(0x9E, self._op_shx, ABY, "SHX")

        # LAX
        op(0xA7, self._op_lax, ZP, "LAX")
        op(0xB7, self._op_lax, ZPY, "LAX")
        op(0xAF, self._op_lax, ABS, "LAX")
        op(0xBF, self._op_lax, ABY, "LAX")
        op(0xA3, self._op_lax, IZX, "LAX")
        op(0xB3, self._op_lax, IZY, "LAX")

        # SAX
        op(0x87, self._op_sax, ZP, "SAX")
        op(0x97, self._op_sax, ZPY, "SAX")
        op(0x8F, self._op_sax, ABS, "SAX")
        op(0x83, self._op_sax, IZX, "SAX")

        # DCP
        op(0xC7, self._op_dcp, ZP, "DCP")
        op(0xD7, self._op_dcp, ZPX, "DCP")
        op(0xCF, self._op_dcp, ABS, "DCP")
        op(0xDF, self._op_dcp, ABX, "DCP")
        op(0xDB, self._op_dcp, ABY, "DCP")
        op(0xC3, self._op_dcp, IZX, "DCP")
        op(0xD3, self._op_dcp, IZY, "DCP")

        # ISB (ISC)
        op(0xE7, self._op_isb, ZP, "ISB")
        op(0xF7, self._op_isb, ZPX, "ISB")
        op(0xEF, self._op_isb, ABS, "ISB")
        op(0xFF, self._op_isb, ABX, "ISB")
        op(0xFB, self._op_isb, ABY, "ISB")
        op(0xE3, self._op_isb, IZX, "ISB")
        op(0xF3, self._op_isb, IZY, "ISB")

        # SLO
        op(0x07, self._op_slo, ZP, "SLO")
        op(0x17, self._op_slo, ZPX, "SLO")
        op(0x0F, self._op_slo, ABS, "SLO")
        op(0x1F, self._op_slo, ABX, "SLO")
        op(0x1B, self._op_slo, ABY, "SLO")
        op(0x03, self._op_slo, IZX, "SLO")
        op(0x13, self._op_slo, IZY, "SLO")

        # RLA
        op(0x27, self._op_rla, ZP, "RLA")
        op(0x37, self._op_rla, ZPX, "RLA")
        op(0x2F, self._op_rla, ABS, "RLA")
        op(0x3F, self._op_rla, ABX, "RLA")
        op(0x3B, self._op_rla, ABY, "RLA")
        op(0x23, self._op_rla, IZX, "RLA")
        op(0x33, self._op_rla, IZY, "RLA")

        # SRE
        op(0x47, self._op_sre, ZP, "SRE")
        op(0x57, self._op_sre, ZPX, "SRE")
        op(0x4F, self._op_sre, ABS, "SRE")
        op(0x5F, self._op_sre, ABX, "SRE")
        op(0x5B, self._op_sre, ABY, "SRE")
        op(0x43, self._op_sre, IZX, "SRE")
        op(0x53, self._op_sre, IZY, "SRE")

        # RRA
        op(0x67, self._op_rra, ZP, "RRA")
        op(0x77, self._op_rra, ZPX, "RRA")
        op(0x6F, self._op_rra, ABS, "RRA")
        op(0x7F, self._op_rra, ABX, "RRA")
        op(0x7B, self._op_rra, ABY, "RRA")
        op(0x63, self._op_rra, IZX, "RRA")
        op(0x73, self._op_rra, IZY, "RRA")

        # ANC
        op(0x0B, self._op_anc, IMM, "ANC")
        op(0x2B, self._op_anc, IMM, "ANC")
        # ALR
        op(0x4B, self._op_alr, IMM, "ALR")
        # ARR
        op(0x6B, self._op_arr, IMM, "ARR")
        # XAA
        op(0x8B, self._op_xaa, IMM, "XAA")
        # AHX
        op(0x93, self._op_ahx, IZY, "AHX")
        op(0x9F, self._op_ahx, ABY, "AHX")
        # TAS
        op(0x9B, self._op_tas, ABY, "TAS")
        # LAS
        op(0xBB, self._op_las, ABY, "LAS")
        # AXS
        op(0xCB, self._op_axs, IMM, "AXS")

        # Undocumented NOPs (various sizes)
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
        op(0xEB, self._op_sbc, IMM, "SBC")  # $EB = unofficial SBC #imm

        # KIL opcodes
        for opc in [0x02, 0x12, 0x22, 0x32, 0x42, 0x52, 0x62, 0x72,
                     0x92, 0xB2, 0xD2, 0xF2]:
            op(opc, self._op_kil, IMP, "KIL")

        # Fill remaining as 1-byte NOPs (shouldn't normally be reached)
        for i in range(256):
            if self.optable[i] is None:
                self.optable[i] = (self._op_nop_undoc, IMP, 1, f"?{i:02X}")

    # ── Execution ───────────────────────────────────────────────

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

        # Save instruction PC, then execute handler
        old_pc = self.pc
        is_branch = handler in (self._op_bcc, self._op_bcs, self._op_beq,
                                self._op_bne, self._op_bpl, self._op_bmi,
                                self._op_bvc, self._op_bvs)
        is_jump = handler in (self._op_jmp, self._op_jsr, self._op_rts,
                              self._op_rti, self._op_brk)

        # Execute handler FIRST (PC still points to instruction for operand reads)
        handler(mode)

        # Advance PC AFTER handler, unless handler already set PC
        if not is_branch and not is_jump:
            self.pc = (old_pc + size) & 0xFFFF

        self.exec_count += 1
        self.cycles += 1  # simplified
        return True


# ── Main: Boot and trace ─────────────────────────────────────────────

def decode_boot_sector_from_woz(woz_path):
    """Decode Track 0, Sector 0 from the WOZ image using 6-and-2."""
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[0]

    offset_entry = 256 + tidx * 8
    sb = struct.unpack_from('<H', data, offset_entry)[0]
    bc = struct.unpack_from('<H', data, offset_entry + 2)[0]
    bits = struct.unpack_from('<I', data, offset_entry + 4)[0]
    track_data = data[sb * 512:sb * 512 + bc * 512]

    # Convert to nibbles
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

    # Find first D5 AA 96 address field with sector 0, then its data field
    # For simplicity, find ALL D5 AA AD data prologues and decode sector 0
    nib2 = nibbles + nibbles[:500]

    # Find address prologues and match to data fields
    sectors = {}
    i = 0
    while i < len(nibbles):
        if nib2[i] == 0xD5 and nib2[i + 1] == 0xAA and nib2[i + 2] == 0x96:
            idx = i + 3
            vol = ((nib2[idx] << 1) | 1) & nib2[idx + 1]
            trk = ((nib2[idx + 2] << 1) | 1) & nib2[idx + 3]
            sec = ((nib2[idx + 4] << 1) | 1) & nib2[idx + 5]

            # Find following D5 AA AD
            j = idx + 8
            while j < len(nib2) - 346:
                if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                    # Decode 6-and-2
                    didx = j + 3
                    encoded = []
                    valid = True
                    for k in range(342):
                        n = nib2[didx + k]
                        if n not in DECODE_62:
                            valid = False
                            break
                        encoded.append(DECODE_62[n])
                    if valid:
                        cksum_nib = nib2[didx + 342]
                        cksum_val = DECODE_62.get(cksum_nib, -1)
                        # === ROM-exact decode ===
                        # Phase 1: XOR chain for aux (86 bytes), stored reversed
                        aux_buf = [0] * 86
                        xor_acc = 0
                        for k in range(86):
                            xor_acc ^= encoded[k]
                            aux_buf[85 - k] = xor_acc
                        # Phase 2: XOR chain for primary (256 bytes), continuous
                        pri_buf = [0] * 256
                        for k in range(256):
                            xor_acc ^= encoded[86 + k]
                            pri_buf[k] = xor_acc
                        # Phase 3: Post-decode with destructive LSR/ROL
                        result = bytearray(256)
                        x = 0x56  # aux index (starts at 86)
                        for y in range(256):
                            x -= 1
                            if x < 0:
                                x = 0x55  # reset to 85
                            a = pri_buf[y]
                            # First LSR/ROL: extract bit 0 of aux
                            carry = aux_buf[x] & 1
                            aux_buf[x] >>= 1
                            a = ((a << 1) | carry) & 0xFF
                            # Second LSR/ROL: extract next bit
                            carry2 = aux_buf[x] & 1
                            aux_buf[x] >>= 1
                            a = ((a << 1) | carry2) & 0xFF
                            result[y] = a
                        sectors[sec] = bytes(result)
                    break
                j += 1
            i = j + 343 if j < len(nib2) - 346 else i + 1
        else:
            i += 1

    return sectors


def decode_53_sector(nibbles, idx):
    """Decode one 5-and-3 encoded sector using the correct P5A ROM algorithm.
    nibbles: list of nibbles, idx: start of 411 data nibbles.
    Returns (sector_bytes, checksum_ok) or None.
    """
    ENCODE_53 = [
        0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
        0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
        0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
        0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
    ]
    DEC53 = {v: i for i, v in enumerate(ENCODE_53)}
    GRP = 51

    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DEC53:
            return None
        translated.append(DEC53[nib])

    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    cksum_ok = (prev == translated[410])

    # decoded[0..153] = secondary (thr), stored reversed on disk
    # decoded[154..409] = primary (top)
    thr = [decoded[153 - j] for j in range(154)]
    top = [decoded[154 + j] for j in range(256)]

    # Reconstruct 256 bytes
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


def decode_44(b1, b2):
    return ((b1 << 1) | 0x01) & b2


def decode_track_53(woz_path, track_num):
    """Decode all 5-and-3 sectors from a track. Returns dict sector_num -> bytes."""
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
    if tidx == 0xFF:
        return {}

    offset = 256 + tidx * 8
    sb = struct.unpack_from('<H', data, offset)[0]
    bc = struct.unpack_from('<H', data, offset + 2)[0]
    bits_count = struct.unpack_from('<I', data, offset + 4)[0]
    track_data = data[sb * 512:sb * 512 + bc * 512]

    bit_list = []
    for b in track_data:
        for i in range(7, -1, -1):
            bit_list.append((b >> i) & 1)
            if len(bit_list) >= bits_count:
                break
        if len(bit_list) >= bits_count:
            break

    nibbles = []
    current = 0
    for b in bit_list:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0

    nib2 = nibbles + nibbles[:2000]

    ENCODE_53 = [
        0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
        0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
        0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
        0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
    ]
    DEC53 = set(ENCODE_53)

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
                            and nib2[didx + k] in DEC53)
                if valid >= 410:
                    result = decode_53_sector(nib2, didx)
                    if result:
                        sector_data, ck_ok = result
                        sectors[sec] = sector_data
                break

    return sectors


def build_gcr_table(mem):
    """Build the GCR decode table at $0356+ exactly as the boot ROM does.
    This maps nibble values ($80-$FF range) to 6-bit decoded values (0-63).
    Accessed via EOR $02D6,Y where Y = raw nibble."""
    y = 0  # decoded value counter
    for x in range(3, 128):
        # Validate nibble pattern (no consecutive zero bits)
        a = (x << 1) & 0xFF
        if (a & x) == 0:
            continue
        a = a | x
        a = (~a) & 0xFF
        a = a & 0x7E
        # Check carry (from ASL) - skip if set
        if (x << 1) & 0x100:
            continue
        # Check for consecutive zeros
        valid = True
        while a != 0:
            if (x << 1) & 0x100:
                valid = False
                break
            a = (a >> 1) & 0xFF
        if valid:
            mem[0x0356 + x] = y
            y += 1


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"

    print("=" * 70)
    print("APPLE PANIC BOOT TRACE EMULATOR")
    print("=" * 70)

    # Load WOZ disk for nibble streaming
    print("Loading WOZ disk image...")
    disk = WOZDisk(woz_path)

    # Decode boot sector using ROM-exact algorithm
    print("Decoding D5 AA 96 sector 0 (ROM-exact 6-and-2)...")
    sectors_62 = decode_boot_sector_from_woz(woz_path)
    if 0 not in sectors_62:
        print("ERROR: No D5 AA 96 sector 0 found!")
        return
    boot = sectors_62[0]
    print(f"  Byte 0 (sector count): ${boot[0]:02X}")
    print(f"  First 16: " + ' '.join(f'{b:02X}' for b in boot[:16]))

    # Create CPU
    cpu = CPU6502()
    cpu.disk = disk

    # Load boot sector at $0800
    for i, b in enumerate(boot):
        cpu.mem[0x0800 + i] = b

    # Build GCR decode table at $0356 (as boot ROM does before loading sector)
    build_gcr_table(cpu.mem)

    # Set up Apple II+ Monitor ROM stubs
    # $FF58 = IORTS (just RTS) - used by boot ROM for slot detection
    cpu.mem[0xFF58] = 0x60  # RTS

    # $FCA8 = WAIT routine (delay loop, we make it instant)
    # Real: SEC / PHA / SBC #1 / BNE / PLA / SBC #1 / BNE / RTS
    # For emulation, just RTS (delays don't matter)
    cpu.mem[0xFCA8] = 0x60  # RTS

    # IRQ/BRK handler at $FA40 (simplified)
    brk_handler = bytes([
        0xD8,             # CLD
        0x85, 0x45,       # STA $45
        0x68,             # PLA
        0x48,             # PHA
        0x29, 0x10,       # AND #$10
        0xD0, 0x03,       # BNE +3 (→ BRK path)
        0x6C, 0xFE, 0x03, # JMP ($03FE) - IRQ vector
        0xA5, 0x45,       # LDA $45
        0x6C, 0xF0, 0x03, # JMP ($03F0) - BRK vector
    ])
    for i, b in enumerate(brk_handler):
        cpu.mem[0xFA40 + i] = b
    cpu.mem[0xFFFE] = 0x40
    cpu.mem[0xFFFF] = 0xFA  # IRQ/BRK → $FA40

    # BRK software vector ($03F0) - initially halt trap
    # Put a KIL instruction at $FF10 to catch unexpected BRKs
    cpu.mem[0xFF10] = 0x02  # KIL
    cpu.mem[0x03F0] = 0x10
    cpu.mem[0x03F1] = 0xFF  # BRK → $FF10 (halt)

    # Initial state after P6 boot ROM completes:
    # - JMP $0801
    # - X = slot * 16 = $60
    # - Motor on, head on track 0
    # - Stack used minimally (JSR $FF58 leaves return addr)
    cpu.pc = 0x0801
    cpu.x = 0x60  # slot 6
    cpu.sp = 0xFD  # boot ROM uses some stack for JSR
    cpu.a = 0x00
    cpu.y = 0x00
    # $2B = slot * 16 (set by boot ROM)
    cpu.mem[0x2B] = 0x60

    # Motor on, head on track 0
    disk.motor_on = True
    disk.current_qtrack = 0

    # Enable trace to file
    trace_path = "E:/Apple/boot_trace.log"
    cpu.trace = True
    cpu.trace_file = open(trace_path, 'w')

    print(f"\nStarting execution at $0801 (X=$60)...")
    print(f"Trace log: {trace_path}")

    max_instructions = 5_000_000
    mem_before = bytearray(cpu.mem)

    for i in range(max_instructions):
        if not cpu.step():
            print(f"\n  CPU halted at ${cpu.pc:04X} after {cpu.exec_count} instructions")
            break

        pc = cpu.pc

        # Milestone breakpoints
        if pc == 0x020F and cpu.exec_count < 1000:
            print(f"  >> JMP $020F reached (boot code relocated to $0200)")
        if pc == 0x7465:
            print(f"\n  *** GAME ENTRY POINT $7465 reached at instr {cpu.exec_count}!")
            break

        if cpu.exec_count % 500000 == 0:
            print(f"  ... {cpu.exec_count} instructions, PC=${pc:04X} "
                  f"A={cpu.a:02X} X={cpu.x:02X} Y={cpu.y:02X}")

        # Detect infinite BRK loop
        if cpu.brk_count > 10:
            print(f"\n  Too many BRKs ({cpu.brk_count}), stopping")
            print(f"  Last PC=${pc:04X}, state: {cpu.format_state()}")
            break

    cpu.trace_file.close()

    # Summary
    print(f"\n{'=' * 70}")
    print("EXECUTION SUMMARY")
    print(f"{'=' * 70}")
    print(f"Total instructions: {cpu.exec_count}")
    print(f"Final PC: ${cpu.pc:04X}")
    print(f"Final state: {cpu.format_state()}")

    # Memory modifications
    print(f"\nMemory regions modified:")
    modified_ranges = []
    start = None
    for addr in range(65536):
        if cpu.mem[addr] != mem_before[addr]:
            if start is None:
                start = addr
        else:
            if start is not None:
                modified_ranges.append((start, addr - 1))
                start = None
    if start is not None:
        modified_ranges.append((start, 65535))
    for s, e in modified_ranges:
        print(f"  ${s:04X}-${e:04X} ({e - s + 1} bytes)")

    # Show zero page state
    print(f"\nZero page (modified bytes):")
    for addr in range(256):
        if cpu.mem[addr] != mem_before[addr]:
            print(f"  ${addr:02X} = ${cpu.mem[addr]:02X}")

    # Show page 3 vectors
    print(f"\nPage 3 vectors:")
    print(f"  $03F0/$03F1 (BRK): ${cpu.mem[0x03F1]:02X}{cpu.mem[0x03F0]:02X}")

    # Show first 100 trace lines
    print(f"\nFirst 100 trace lines:")
    with open(trace_path) as f:
        for i, line in enumerate(f):
            if i >= 100:
                print(f"  ... ({cpu.exec_count - 100} more lines)")
                break
            print(f"  {line.rstrip()}")

    # Save memory dump
    with open("E:/Apple/emu_memory_dump.bin", 'wb') as f:
        f.write(cpu.mem)
    print(f"\nMemory dump saved: E:/Apple/emu_memory_dump.bin")


if __name__ == '__main__':
    main()

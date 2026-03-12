#!/usr/bin/env python3
"""
Decode the boot sector EXACTLY as the Disk II P6 boot ROM does it.

Implements five different 6-and-2 decode methods (A through E) and compares
them all against the .dsk file to determine which is correct. Method E is the
cycle-accurate ROM simulation that faithfully reproduces the destructive
LSR/ROL post-decode loop.

The real P6 PROM ($C600) algorithm:
1. Build GCR decode table at $0356 (indexed by nibble-$80)
2. Find D5 AA 96 address field, check T=0, S=0
3. Find D5 AA AD data field
4. Read 86 aux nibbles with XOR chain, stored in REVERSE order at $0300-$0355
   (first nibble -> aux[85], last -> aux[0])
5. Read 256 primary nibbles with CONTINUOUS XOR chain into $0800-$08FF
6. Read checksum nibble, verify
7. Post-decode: for each output byte Y=0..255:
   X cycles 85,84,...,0 (reset to 85 when negative)
   LDA ($26),Y   ; get primary[Y]
   LSR $0300,X   ; extract bit 0 of aux[X] -> carry
   ROL A         ; shift primary left, insert carry at bit 0
   LSR $0300,X   ; extract bit 1 -> carry (aux already shifted)
   ROL A         ; shift left, insert carry at bit 0
   STA ($26),Y   ; store result

   Result = (primary << 2) | (aux_bit0 << 1) | aux_bit1

   Note: LSR is DESTRUCTIVE - each group of 86 output bytes shifts
   aux by 2 more, extracting the next pair of bits.

Usage:
    python boot_rom_decode.py

    Paths default to repo-relative locations (apple-panic/).

Expected output:
    Results of five decode methods (A-E) with first 16 bytes of each,
    comparison matrix showing which methods match the .dsk file,
    hex dump and disassembly of the ROM-exact (Method E) result.
"""
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


def read_woz_nibbles(woz_path, track_num):
    """Read a WOZ2 disk image and extract the nibble stream for a given track."""
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
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
    """Decode a 4-and-4 encoded byte pair from the address field."""
    return ((b1 << 1) | 0x01) & b2


def main():
    """Compare five different 6-and-2 decode methods against the .dsk file."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    nibbles = read_woz_nibbles(woz_path, 0)
    nib = nibbles + nibbles[:2000]

    print("=" * 70)
    print("BOOT ROM EXACT DECODE - Multiple methods compared")
    print("=" * 70)

    # Find the D5 AA 96 address field for T=0, S=0
    data_idx = None
    for i in range(len(nibbles)):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0x96:
            idx = i + 3
            vol = decode_44(nib[idx], nib[idx+1])
            trk = decode_44(nib[idx+2], nib[idx+3])
            sec = decode_44(nib[idx+4], nib[idx+5])
            ck = decode_44(nib[idx+6], nib[idx+7])
            print(f"\nFound D5 AA 96 at nibble {i}: vol={vol} trk={trk} sec={sec} ck={ck}")
            if trk == 0 and sec == 0:
                # Find D5 AA AD
                for j in range(idx + 8, idx + 200):
                    if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                        data_idx = j + 3
                        print(f"  Data field at nibble {j}")
                        break
                if data_idx:
                    break

    if not data_idx:
        print("ERROR: No D5 AA 96 T0 S0 data field found!")
        return

    # Read 343 raw nibbles and GCR translate
    raw_nibbles = nib[data_idx:data_idx + 343]
    encoded = []
    for n in raw_nibbles[:342]:
        if n not in DECODE_62:
            print(f"  Invalid nibble: ${n:02X}")
            encoded.append(0)
        else:
            encoded.append(DECODE_62[n])
    cksum_nib = raw_nibbles[342]
    cksum_val = DECODE_62.get(cksum_nib, -1)

    print(f"\n  First 8 raw nibbles: {' '.join(f'${n:02X}' for n in raw_nibbles[:8])}")
    print(f"  First 8 GCR decoded: {' '.join(f'${v:02X}' for v in encoded[:8])}")

    # ================================================================
    # METHOD A: My previous "correct" decode (matched .dsk file)
    #   XOR chain, reversed aux (decoded[85-i]), standard bit order
    # ================================================================
    decoded = [0] * 342
    prev = 0
    for k in range(342):
        decoded[k] = encoded[k] ^ prev
        prev = decoded[k]
    xor_ok = (prev == cksum_val)

    result_a = bytearray(256)
    for i in range(86):
        aux = decoded[85 - i]  # reversed
        for g in range(3):
            out_idx = i + g * 86
            if out_idx < 256:
                upper = decoded[86 + out_idx] << 2
                lower = (aux >> (g * 2)) & 0x03  # standard bit order
                result_a[out_idx] = (upper | lower) & 0xFF

    print(f"\n--- Method A: Previous 'correct' (matched .dsk) ---")
    print(f"  XOR checksum: {'OK' if xor_ok else 'BAD'}")
    print(f"  Byte 0: ${result_a[0]:02X}")
    print(f"  First 16: {' '.join(f'{b:02X}' for b in result_a[:16])}")

    # ================================================================
    # METHOD B: ROM-exact decode
    #   XOR chain, FORWARD aux order (decoded[i]), ROM bit order (a0<<1|a1)
    # ================================================================
    # The ROM stores aux in reverse (first nibble at [85]), then reads
    # counting down from [85]. Net effect: forward XOR chain order.
    # The ROM's two LSR/ROL pairs give (bit0<<1)|bit1 instead of
    # the standard (bit1<<1)|bit0.

    result_b = bytearray(256)
    for i in range(86):
        aux = decoded[i]  # forward order (ROM effective order)
        for g in range(3):
            out_idx = i + g * 86
            if out_idx < 256:
                upper = decoded[86 + out_idx] << 2
                # ROM bit extraction: LSR gets bit0 first, then bit1
                # After g groups of 2 shifts:
                shifted = aux >> (g * 2)
                bit0 = shifted & 1
                bit1 = (shifted >> 1) & 1
                lower = (bit0 << 1) | bit1  # ROM order
                result_b[out_idx] = (upper | lower) & 0xFF

    print(f"\n--- Method B: ROM-exact (forward aux, ROM bit order) ---")
    print(f"  Byte 0: ${result_b[0]:02X}")
    print(f"  First 16: {' '.join(f'{b:02X}' for b in result_b[:16])}")

    # ================================================================
    # METHOD C: Forward aux, standard bit order
    # ================================================================
    result_c = bytearray(256)
    for i in range(86):
        aux = decoded[i]  # forward order
        for g in range(3):
            out_idx = i + g * 86
            if out_idx < 256:
                upper = decoded[86 + out_idx] << 2
                lower = (aux >> (g * 2)) & 0x03
                result_c[out_idx] = (upper | lower) & 0xFF

    print(f"\n--- Method C: Forward aux, standard bit order ---")
    print(f"  Byte 0: ${result_c[0]:02X}")
    print(f"  First 16: {' '.join(f'{b:02X}' for b in result_c[:16])}")

    # ================================================================
    # METHOD D: Reversed aux, ROM bit order
    # ================================================================
    result_d = bytearray(256)
    for i in range(86):
        aux = decoded[85 - i]  # reversed
        for g in range(3):
            out_idx = i + g * 86
            if out_idx < 256:
                upper = decoded[86 + out_idx] << 2
                shifted = aux >> (g * 2)
                bit0 = shifted & 1
                bit1 = (shifted >> 1) & 1
                lower = (bit0 << 1) | bit1  # ROM order
                result_d[out_idx] = (upper | lower) & 0xFF

    print(f"\n--- Method D: Reversed aux, ROM bit order ---")
    print(f"  Byte 0: ${result_d[0]:02X}")
    print(f"  First 16: {' '.join(f'{b:02X}' for b in result_d[:16])}")

    # ================================================================
    # METHOD E: Cycle-accurate ROM simulation
    #   Simulates the actual $0300 buffer and destructive LSR
    # ================================================================
    # Phase 1: Read aux into $0300 buffer (reverse order, XOR chain)
    aux_buf = [0] * 86  # $0300-$0355
    xor_acc = 0  # XOR accumulator (starts at 0 from EOR #$AD → 0)
    for k in range(86):
        xor_acc ^= encoded[k]
        aux_buf[85 - k] = xor_acc  # store in reverse

    # Phase 2: Read primary into $0800 buffer (continue XOR chain)
    pri_buf = [0] * 256
    for k in range(256):
        xor_acc ^= encoded[86 + k]
        pri_buf[k] = xor_acc

    # Checksum
    xor_acc ^= cksum_val if cksum_val >= 0 else 0
    print(f"\n--- Method E: Cycle-accurate ROM simulation ---")
    print(f"  XOR checksum final: ${xor_acc:02X} ({'OK' if xor_acc == 0 else 'BAD'})")

    # Phase 3: Post-decode with destructive LSR/ROL
    result_e = bytearray(256)
    x = 0x56  # starts at 86
    for y in range(256):
        x -= 1
        if x < 0:
            x = 0x55  # reset to 85 (BMI branches before DEX goes negative? No: DEX then BMI)
            # Actually: DEX first (86→85, or 0→-1=0xFF which is negative)
            # Wait: X is 8-bit. $56 → DEX → $55. $00 → DEX → $FF. $FF has bit 7 set → BMI taken.
            # So X goes: 85, 84, ..., 1, 0, then DEX→$FF (negative) → reset to $56, DEX→$55
            # Hmm wait, the code is:
            # C6D7: LDX #$56
            # C6D9: DEX
            # C6DA: BMI $C6D7
            # So: first DEX: X=$55=85. Not negative.
            # When X=0: DEX → X=$FF. $FF is negative (bit 7 set). BMI taken → LDX #$56 → DEX → $55.
            x = 0x55  # 85

        a = pri_buf[y]

        # First LSR/ROL pair
        carry = aux_buf[x] & 1
        aux_buf[x] >>= 1
        new_carry = (a >> 7) & 1
        a = ((a << 1) | carry) & 0xFF
        # carry for next operation is the bit shifted out (old bit 7)

        # Second LSR/ROL pair
        carry2 = aux_buf[x] & 1
        aux_buf[x] >>= 1
        a = ((a << 1) | carry2) & 0xFF

        result_e[y] = a

    print(f"  Byte 0: ${result_e[0]:02X}")
    print(f"  First 16: {' '.join(f'{b:02X}' for b in result_e[:16])}")

    # ================================================================
    # Compare all methods
    # ================================================================
    print(f"\n{'=' * 70}")
    print("COMPARISON")
    print(f"{'=' * 70}")

    # Compare with .dsk file
    try:
        with open(str(APPLE_PANIC / "ApplePanic_original.dsk"), 'rb') as f:
            dsk = f.read()
        dsk_s0 = dsk[0:256]
        for name, result in [("A", result_a), ("B", result_b), ("C", result_c),
                             ("D", result_d), ("E", result_e)]:
            match = sum(1 for k in range(256) if result[k] == dsk_s0[k])
            print(f"  Method {name} vs .dsk: {match}/256")
    except FileNotFoundError:
        pass

    # Compare methods with each other
    for n1, r1 in [("A", result_a), ("B", result_b), ("C", result_c),
                    ("D", result_d), ("E", result_e)]:
        diffs = []
        for n2, r2 in [("A", result_a), ("B", result_b), ("C", result_c),
                        ("D", result_d), ("E", result_e)]:
            if n1 < n2:
                d = sum(1 for k in range(256) if r1[k] != r2[k])
                if d > 0:
                    diffs.append(f"{n1}!={n2}:{d}")
        if diffs:
            print(f"  {', '.join(diffs)}")

    # Show hex dump of method E (ROM-exact)
    print(f"\n{'=' * 70}")
    print("Method E (ROM-exact) hex dump:")
    print(f"{'=' * 70}")
    for row in range(16):
        off = row * 16
        h = ' '.join(f'{result_e[off+c]:02X}' for c in range(16))
        a = ''.join(chr(result_e[off+c]) if 32 <= result_e[off+c] < 127 else '.'
                    for c in range(16))
        print(f"  ${0x0800+off:04X}: {h}  {a}")

    # Show hex dump of method A for comparison
    print(f"\nMethod A (previous) hex dump:")
    for row in range(16):
        off = row * 16
        h = ' '.join(f'{result_a[off+c]:02X}' for c in range(16))
        print(f"  ${0x0800+off:04X}: {h}")

    # Disassemble from $0801 for method E
    print(f"\n{'=' * 70}")
    print("Method E disassembly from $0801:")
    print(f"{'=' * 70}")
    s = result_e
    pc = 1
    opcodes = {
        0xA0: ('LDY #', 2), 0xA2: ('LDX #', 2), 0xA9: ('LDA #', 2),
        0x85: ('STA ', 2), 0xA5: ('LDA ', 2), 0x86: ('STX ', 2),
        0xA6: ('LDX ', 2), 0x84: ('STY ', 2), 0xA4: ('LDY ', 2),
        0x4C: ('JMP ', 3), 0x20: ('JSR ', 3),
        0xAD: ('LDA ', 3), 0x8D: ('STA ', 3),
        0xBD: ('LDA ', 3), 0x9D: ('STA ', 3),
        0xB9: ('LDA ', 3), 0x99: ('STA ', 3),
        0xBC: ('LDY ', 3), 0xBE: ('LDX ', 3),
        0xE8: ('INX', 1), 0xC8: ('INY', 1),
        0xCA: ('DEX', 1), 0x88: ('DEY', 1),
        0x18: ('CLC', 1), 0x38: ('SEC', 1),
        0x60: ('RTS', 1), 0xEA: ('NOP', 1),
        0xD0: ('BNE ', 2), 0xF0: ('BEQ ', 2),
        0x90: ('BCC ', 2), 0xB0: ('BCS ', 2),
        0x10: ('BPL ', 2), 0x30: ('BMI ', 2),
        0x29: ('AND #', 2), 0x09: ('ORA #', 2), 0x49: ('EOR #', 2),
        0xC9: ('CMP #', 2), 0xE0: ('CPX #', 2), 0xC0: ('CPY #', 2),
        0x48: ('PHA', 1), 0x68: ('PLA', 1),
        0x00: ('BRK', 1), 0x9C: ('SHY ', 3),
        0x91: ('STA (zp),Y ', 2), 0xB1: ('LDA (zp),Y ', 2),
        0x69: ('ADC #', 2), 0xE9: ('SBC #', 2),
        0xE6: ('INC ', 2), 0xC6: ('DEC ', 2),
        0xEE: ('INC ', 3), 0xCE: ('DEC ', 3),
        0x78: ('SEI', 1), 0xD8: ('CLD', 1),
        0x2C: ('BIT ', 3), 0x24: ('BIT ', 2),
    }
    for _ in range(30):
        if pc >= 256:
            break
        op = s[pc]
        if op in opcodes:
            name, size = opcodes[op]
            raw = ' '.join(f'{s[pc+k]:02X}' for k in range(min(size, 256-pc)))
            if size == 1:
                print(f"  ${0x0800+pc:04X}: {raw:8s}  {name}")
            elif size == 2:
                if name.startswith('B') and name != 'BIT ' and name != 'BRK':
                    off_val = s[pc+1] if pc+1 < 256 else 0
                    if off_val >= 0x80:
                        off_val -= 256
                    target = 0x0800 + pc + 2 + off_val
                    print(f"  ${0x0800+pc:04X}: {raw:8s}  {name}${target:04X}")
                else:
                    print(f"  ${0x0800+pc:04X}: {raw:8s}  {name}${s[pc+1]:02X}")
            else:
                if pc+2 < 256:
                    addr = s[pc+1] | (s[pc+2] << 8)
                    print(f"  ${0x0800+pc:04X}: {raw:8s}  {name}${addr:04X}")
                else:
                    print(f"  ${0x0800+pc:04X}: {raw:8s}  {name}???")
            pc += size
        else:
            print(f"  ${0x0800+pc:04X}: {op:02X}         .byte ${op:02X}")
            pc += 1


if __name__ == '__main__':
    main()

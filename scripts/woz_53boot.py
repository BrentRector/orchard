#!/usr/bin/env python3
"""
Load all 5-and-3 decoded sectors from T0 and analyze the boot flow.
The P5A (13-sector) boot ROM loads S0 into $0800, uses byte 0 as sector count,
loads sectors into $0800+N*$100, then JMP $0801.
"""
import struct

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def read_woz_nibbles(woz_path, track_num):
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


def decode_53_sector(nibbles, idx):
    """Decode 5-and-3 data field (410 + 1 checksum nibbles)."""
    GRP = 51

    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DECODE_53:
            return None
        translated.append(DECODE_53[nib])

    # XOR chain
    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]
    cksum_ok = (prev == translated[410])

    # P5A ROM byte reconstruction
    # decoded[0..153] = secondary (stored reversed on disk)
    # decoded[154..409] = primary
    thr = [decoded[153 - j] for j in range(154)]
    top = [decoded[154 + j] for j in range(256)]

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

    result = bytearray(256)
    for i in range(256):
        result[i] = output[i] if i < len(output) else 0
    return bytes(result), cksum_ok


def decode_44(b1, b2):
    return ((b1 << 1) | 1) & b2


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    nibbles = read_woz_nibbles(woz_path, 0)
    nib = nibbles + nibbles[:2000]

    # Find all D5 AA B5 address fields
    sectors = {}
    i = 0
    while i < len(nibbles):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            vol = decode_44(nib[idx], nib[idx+1])
            trk = decode_44(nib[idx+2], nib[idx+3])
            sec = decode_44(nib[idx+4], nib[idx+5])
            ck = decode_44(nib[idx+6], nib[idx+7])

            # Find D5 AA AD data field
            search = idx + 8
            for j in range(search, search + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    didx = j + 3
                    result = decode_53_sector(nib, didx)
                    if result:
                        data, ck_ok = result
                        sectors[sec] = data
                        nz = sum(1 for b in data if b != 0)
                        ff = sum(1 for b in data if b == 0xFF)
                        print(f"  S{sec:2d}: ck={'OK' if ck_ok else 'BAD'}"
                              f"  nz={nz:3d} ff={ff:2d}"
                              f"  first8={' '.join(f'{b:02X}' for b in data[:8])}")
                    break
            i = j + 412 if 'j' in dir() else i + 1
        else:
            i += 1

    # The P5A boot ROM loads sector 0 first
    if 0 in sectors:
        s0 = sectors[0]
        print(f"\n=== Sector 0 analysis ===")
        print(f"  Byte 0 (sector count): ${s0[0]:02X} ({s0[0]})")
        print(f"  Non-zero bytes: {sum(1 for b in s0 if b != 0)}")
        print(f"  $FF bytes: {sum(1 for b in s0 if b == 0xFF)}")

        # Show full hex dump
        for row in range(16):
            off = row * 16
            h = ' '.join(f'{s0[off+c]:02X}' for c in range(16))
            print(f"  ${0x0800+off:04X}: {h}")

    # Show what memory looks like with all sectors loaded
    print(f"\n=== Memory map (all 5-and-3 sectors) ===")
    mem = bytearray(65536)
    for sec in sorted(sectors):
        base = 0x0800 + sec * 0x100
        for i, b in enumerate(sectors[sec]):
            mem[base + i] = b
        nz = sum(1 for b in sectors[sec] if b != 0)
        print(f"  ${base:04X}-${base+0xFF:04X}: S{sec:2d} ({nz} non-zero)")

    # Try to disassemble from $0801 (P5A ROM entry)
    if 0 in sectors:
        print(f"\n=== Disassembly from $0801 (S0) ===")
        s0 = sectors[0]
        pc = 1  # relative to $0800
        for line_num in range(20):
            if pc >= 256:
                break
            op = s0[pc]
            # Simple opcode decoder
            opcodes = {
                0xA0: ('LDY', 2), 0xA2: ('LDX', 2), 0xA9: ('LDA', 2),
                0x85: ('STA zp', 2), 0xA5: ('LDA zp', 2), 0x86: ('STX zp', 2),
                0xA6: ('LDX zp', 2), 0x84: ('STY zp', 2), 0xA4: ('LDY zp', 2),
                0x4C: ('JMP', 3), 0x20: ('JSR', 3),
                0xAD: ('LDA abs', 3), 0x8D: ('STA abs', 3),
                0xBD: ('LDA abs,X', 3), 0x9D: ('STA abs,X', 3),
                0xB9: ('LDA abs,Y', 3), 0x99: ('STA abs,Y', 3),
                0xBC: ('LDY abs,X', 3), 0xBE: ('LDX abs,Y', 3),
                0xE8: ('INX', 1), 0xC8: ('INY', 1),
                0xCA: ('DEX', 1), 0x88: ('DEY', 1),
                0x18: ('CLC', 1), 0x38: ('SEC', 1),
                0x60: ('RTS', 1), 0xEA: ('NOP', 1),
                0xD0: ('BNE', 2), 0xF0: ('BEQ', 2),
                0x90: ('BCC', 2), 0xB0: ('BCS', 2),
                0x10: ('BPL', 2), 0x30: ('BMI', 2),
                0x29: ('AND', 2), 0x09: ('ORA', 2), 0x49: ('EOR', 2),
                0xC9: ('CMP', 2), 0xE0: ('CPX', 2), 0xC0: ('CPY', 2),
                0x48: ('PHA', 1), 0x68: ('PLA', 1),
                0x08: ('PHP', 1), 0x28: ('PLP', 1),
                0x0A: ('ASL', 1), 0x4A: ('LSR', 1),
                0x2A: ('ROL', 1), 0x6A: ('ROR', 1),
                0xAA: ('TAX', 1), 0xA8: ('TAY', 1),
                0x8A: ('TXA', 1), 0x98: ('TYA', 1),
                0x9A: ('TXS', 1), 0xBA: ('TSX', 1),
                0x00: ('BRK', 1), 0x40: ('RTI', 1),
                0x78: ('SEI', 1), 0x58: ('CLI', 1),
                0xD8: ('CLD', 1), 0xF8: ('SED', 1),
                0xB8: ('CLV', 1),
                0x69: ('ADC', 2), 0xE9: ('SBC', 2),
                0xE6: ('INC zp', 2), 0xC6: ('DEC zp', 2),
                0xEE: ('INC abs', 3), 0xCE: ('DEC abs', 3),
                0x91: ('STA (zp),Y', 2), 0xB1: ('LDA (zp),Y', 2),
                0x81: ('STA (zp,X)', 2), 0xA1: ('LDA (zp,X)', 2),
                0x6C: ('JMP (abs)', 3),
            }
            if op in opcodes:
                name, size = opcodes[op]
                raw = ' '.join(f'{s0[pc+k]:02X}' for k in range(min(size, 256-pc)))
                if size == 1:
                    print(f"  ${0x0800+pc:04X}: {raw:8s}  {name}")
                elif size == 2:
                    if 'rel' in name or name.startswith('B'):
                        off_val = s0[pc+1]
                        if off_val >= 0x80:
                            off_val -= 256
                        target = 0x0800 + pc + 2 + off_val
                        print(f"  ${0x0800+pc:04X}: {raw:8s}  {name} ${target:04X}")
                    else:
                        print(f"  ${0x0800+pc:04X}: {raw:8s}  {name} #${s0[pc+1]:02X}")
                elif size == 3:
                    addr = s0[pc+1] | (s0[pc+2] << 8)
                    print(f"  ${0x0800+pc:04X}: {raw:8s}  {name} ${addr:04X}")
                pc += size
            else:
                print(f"  ${0x0800+pc:04X}: {op:02X}         .byte ${op:02X} (unknown)")
                pc += 1

    # Also compare S0 with the cracked runtime at appropriate offset
    with open("E:/Apple/ApplePanic_runtime.bin", 'rb') as f:
        runtime = f.read()

    print(f"\n=== Comparing sectors with cracked runtime ===")
    print(f"  Runtime size: {len(runtime)} bytes (${len(runtime):04X})")
    for sec in sorted(sectors):
        data = sectors[sec]
        best_match = 0
        best_offset = 0
        # Search runtime for best match
        for off in range(0, len(runtime) - 256, 256):
            match = sum(1 for k in range(256) if data[k] == runtime[off + k])
            if match > best_match:
                best_match = match
                best_offset = off
        pct = best_match * 100 // 256
        print(f"  S{sec:2d}: best match {best_match}/256 ({pct}%)"
              f" at runtime offset ${best_offset:04X}")


if __name__ == '__main__':
    main()

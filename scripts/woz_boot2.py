#!/usr/bin/env python3
"""
Decode the REAL boot sector from the D5 AA B5 address field (sector 0).

The D5 AA 96 sector 0 on this disk is a dummy trap for 16-sector copiers.
This script finds the 13-sector D5 AA B5 address fields on track 0, decodes
their data using both 6-and-2 and 5-and-3 encoding, and disassembles the real
boot code. Also decodes and displays the dummy D5 AA 96 boot sector for
comparison.

Usage:
    python woz_boot2.py

    Default path:
        Reads apple-panic/Apple Panic - Disk 1, Side A.woz (repo-relative).

Output:
    Lists all D5 AA B5 sectors on track 0, shows 6-and-2 and 5-and-3 nibble
    validity counts, decoded sector hex previews, the dummy boot sector dump,
    and a full hex dump + disassembly of the real boot sector starting at $0801.
"""
import struct
from pathlib import Path

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}

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

# 6502 opcode table (minimal)
OPCODES = {
    0x00: ('BRK', 1), 0x01: ('ORA (zp,X)', 2), 0x05: ('ORA zp', 2),
    0x06: ('ASL zp', 2), 0x08: ('PHP', 1), 0x09: ('ORA #', 2),
    0x0A: ('ASL A', 1), 0x10: ('BPL rel', 2), 0x18: ('CLC', 1),
    0x20: ('JSR abs', 3), 0x24: ('BIT zp', 2), 0x25: ('AND zp', 2),
    0x26: ('ROL zp', 2), 0x28: ('PLP', 1), 0x29: ('AND #', 2),
    0x2A: ('ROL A', 1), 0x2C: ('BIT abs', 3), 0x30: ('BMI rel', 2),
    0x38: ('SEC', 1), 0x40: ('RTI', 1), 0x45: ('EOR zp', 2),
    0x46: ('LSR zp', 2), 0x48: ('PHA', 1), 0x49: ('EOR #', 2),
    0x4A: ('LSR A', 1), 0x4C: ('JMP abs', 3), 0x50: ('BVC rel', 2),
    0x58: ('CLI', 1), 0x60: ('RTS', 1), 0x65: ('ADC zp', 2),
    0x66: ('ROR zp', 2), 0x68: ('PLA', 1), 0x69: ('ADC #', 2),
    0x6A: ('ROR A', 1), 0x6C: ('JMP (abs)', 3),
    0x78: ('SEI', 1), 0x84: ('STY zp', 2), 0x85: ('STA zp', 2),
    0x86: ('STX zp', 2), 0x88: ('DEY', 1), 0x8A: ('TXA', 1),
    0x8C: ('STY abs', 3), 0x8D: ('STA abs', 3), 0x8E: ('STX abs', 3),
    0x90: ('BCC rel', 2), 0x91: ('STA (zp),Y', 2), 0x95: ('STA zp,X', 2),
    0x98: ('TYA', 1), 0x99: ('STA abs,Y', 3), 0x9A: ('TXS', 1),
    0x9D: ('STA abs,X', 3),
    0xA0: ('LDY #', 2), 0xA2: ('LDX #', 2), 0xA4: ('LDY zp', 2),
    0xA5: ('LDA zp', 2), 0xA6: ('LDX zp', 2), 0xA8: ('TAY', 1),
    0xA9: ('LDA #', 2), 0xAA: ('TAX', 1), 0xAD: ('LDA abs', 3),
    0xAE: ('LDX abs', 3),
    0xB0: ('BCS rel', 2), 0xB1: ('LDA (zp),Y', 2), 0xB5: ('LDA zp,X', 2),
    0xB9: ('LDA abs,Y', 3), 0xBA: ('TSX', 1), 0xBD: ('LDA abs,X', 3),
    0xC0: ('CPY #', 2), 0xC5: ('CMP zp', 2), 0xC6: ('DEC zp', 2),
    0xC8: ('INY', 1), 0xC9: ('CMP #', 2), 0xCA: ('DEX', 1),
    0xCC: ('CPY abs', 3), 0xCD: ('CMP abs', 3), 0xCE: ('DEC abs', 3),
    0xD0: ('BNE rel', 2), 0xD8: ('CLD', 1), 0xDE: ('DEC abs,X', 3),
    0xE0: ('CPX #', 2), 0xE5: ('SBC zp', 2), 0xE6: ('INC zp', 2),
    0xE8: ('INX', 1), 0xE9: ('SBC #', 2), 0xEA: ('NOP', 1),
    0xEE: ('INC abs', 3),
    0xF0: ('BEQ rel', 2), 0xF8: ('SED', 1), 0xFE: ('INC abs,X', 3),
    0xBC: ('LDY abs,X', 3), 0x81: ('STA (zp,X)', 2),
    0xA1: ('LDA (zp,X)', 2), 0x96: ('STX zp,Y', 2),
    0xB4: ('LDY zp,X', 2), 0xB6: ('LDX zp,Y', 2),
    0x16: ('ASL zp,X', 2), 0x36: ('ROL zp,X', 2),
    0x56: ('LSR zp,X', 2), 0x76: ('ROR zp,X', 2),
    0xD6: ('DEC zp,X', 2), 0xF6: ('INC zp,X', 2),
    0x0E: ('ASL abs', 3), 0x2E: ('ROL abs', 3),
    0x4E: ('LSR abs', 3), 0x6E: ('ROR abs', 3),
    0xBE: ('LDX abs,Y', 3), 0xC4: ('CPY zp', 2),
    0x11: ('ORA (zp),Y', 2), 0x31: ('AND (zp),Y', 2),
    0x51: ('EOR (zp),Y', 2), 0x71: ('ADC (zp),Y', 2),
    0xD1: ('CMP (zp),Y', 2), 0xF1: ('SBC (zp),Y', 2),
    0x19: ('ORA abs,Y', 3), 0x39: ('AND abs,Y', 3),
    0x59: ('EOR abs,Y', 3), 0x79: ('ADC abs,Y', 3),
    0xD9: ('CMP abs,Y', 3), 0xF9: ('SBC abs,Y', 3),
    0x0D: ('ORA abs', 3), 0x2D: ('AND abs', 3),
    0x4D: ('EOR abs', 3), 0x6D: ('ADC abs', 3),
    0xED: ('SBC abs', 3),
    0x15: ('ORA zp,X', 2), 0x35: ('AND zp,X', 2),
    0x55: ('EOR zp,X', 2), 0x75: ('ADC zp,X', 2),
    0xD5: ('CMP zp,X', 2), 0xF5: ('SBC zp,X', 2),
    0x1D: ('ORA abs,X', 3), 0x3D: ('AND abs,X', 3),
    0x5D: ('EOR abs,X', 3), 0x7D: ('ADC abs,X', 3),
    0xDD: ('CMP abs,X', 3), 0xFD: ('SBC abs,X', 3),
    0x1E: ('ASL abs,X', 3), 0x3E: ('ROL abs,X', 3),
    0x5E: ('LSR abs,X', 3), 0x7E: ('ROR abs,X', 3),
    0x9C: ('SHY abs,X', 3),  # undocumented
    0x9E: ('SHX abs,Y', 3),  # undocumented
}


def disasm(data, base, count=40):
    """Simple linear 6502 disassembly. Returns a list of formatted instruction strings."""
    addr = 0
    lines = []
    while addr < len(data) and len(lines) < count:
        opc = data[addr]
        if opc in OPCODES:
            name, size = OPCODES[opc]
            if addr + size > len(data):
                break
            if size == 1:
                lines.append(f'${base+addr:04X}: {opc:02X}         {name}')
            elif size == 2:
                op1 = data[addr+1]
                if 'rel' in name:
                    offset_val = op1 if op1 < 128 else op1 - 256
                    target = base + addr + 2 + offset_val
                    lines.append(f'${base+addr:04X}: {opc:02X} {op1:02X}      '
                                 f'{name.split()[0]} ${target:04X}')
                else:
                    lines.append(f'${base+addr:04X}: {opc:02X} {op1:02X}      '
                                 f'{name} ${op1:02X}')
            elif size == 3:
                op1 = data[addr+1]
                op2 = data[addr+2]
                val = op1 | (op2 << 8)
                lines.append(f'${base+addr:04X}: {opc:02X} {op1:02X} {op2:02X}   '
                             f'{name.split()[0]} ${val:04X}')
            addr += size
        else:
            lines.append(f'${base+addr:04X}: {opc:02X}         .byte ${opc:02X}')
            addr += 1
    return lines


def main():
    """Find and decode the real 13-sector boot sector from track 0."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88+160]
    tidx = tmap[0]
    offset = 256 + tidx * 8
    sb = struct.unpack_from('<H', data, offset)[0]
    bc = struct.unpack_from('<H', data, offset + 2)[0]
    bits_count = struct.unpack_from('<I', data, offset + 4)[0]
    track_data = data[sb*512:sb*512 + bc*512]

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
    nib2 = nibbles + nibbles[:1000]

    # Find D5 AA B5 S=0 data field (at position ~4123)
    b5_sectors = {}
    for i in range(len(nibbles)):
        if nib2[i] == 0xD5 and nib2[i+1] == 0xAA and nib2[i+2] == 0xB5:
            idx = i + 3
            vol = ((nib2[idx] << 1) | 1) & nib2[idx+1]
            trk = ((nib2[idx+2] << 1) | 1) & nib2[idx+3]
            sec = ((nib2[idx+4] << 1) | 1) & nib2[idx+5]
            # Find following D5 AA AD
            for j in range(idx+8, idx+80):
                if nib2[j] == 0xD5 and nib2[j+1] == 0xAA and nib2[j+2] == 0xAD:
                    b5_sectors[sec] = j + 3  # data nibble start
                    break

    print(f"Found {len(b5_sectors)} D5 AA B5 sectors on track 0")
    print(f"Sector numbers: {sorted(b5_sectors.keys())}")

    # Decode each sector with 6-and-2 and check checksums
    print("\n=== 6-and-2 decode of D5 AA B5 sectors ===")
    decoded_sectors = {}
    for sec_num in sorted(b5_sectors.keys()):
        didx = b5_sectors[sec_num]

        # Count valid nibbles
        valid_62 = 0
        for j in range(500):
            if nib2[didx+j] in DECODE_62:
                valid_62 += 1
            else:
                break

        valid_53 = 0
        for j in range(500):
            if nib2[didx+j] in DECODE_53:
                valid_53 += 1
            else:
                break

        # 6-and-2 decode
        encoded = []
        ok = True
        for j in range(342):
            n = nib2[didx+j]
            if n in DECODE_62:
                encoded.append(DECODE_62[n])
            else:
                ok = False
                break

        if ok:
            cksum_nib = nib2[didx+342]
            cksum_val = DECODE_62.get(cksum_nib, -1)
            decoded = [0] * 342
            prev = 0
            for j in range(342):
                decoded[j] = encoded[j] ^ prev
                prev = decoded[j]
            cksum_ok = (prev == cksum_val)

            result = bytearray(256)
            for j in range(256):
                upper = decoded[86+j] << 2
                aux_idx = 85 - (j % 86)
                shift = (j // 86) * 2
                lower = (decoded[aux_idx] >> shift) & 0x03
                result[j] = (upper | lower) & 0xFF

            decoded_sectors[sec_num] = bytes(result)
            first8 = ' '.join(f'{b:02X}' for b in result[:8])
            print(f"  S{sec_num:2d}: {first8}... ck={'OK' if cksum_ok else 'BAD'} "
                  f"valid: 6&2={valid_62} 5&3={valid_53}")
        else:
            print(f"  S{sec_num:2d}: 6-and-2 decode FAILED (valid: 6&2={valid_62} 5&3={valid_53})")

    # Also show the D5 AA 96 boot sector
    print("\n=== D5 AA 96 boot sector (dummy) ===")
    for i in range(len(nibbles)):
        if nib2[i] == 0xD5 and nib2[i+1] == 0xAA and nib2[i+2] == 0x96:
            idx = i + 3
            sec = ((nib2[idx+4] << 1) | 1) & nib2[idx+5]
            # Find data field
            for j in range(idx+8, idx+80):
                if nib2[j] == 0xD5 and nib2[j+1] == 0xAA and nib2[j+2] == 0xAD:
                    didx = j + 3
                    encoded = []
                    for k in range(342):
                        n = nib2[didx+k]
                        if n in DECODE_62:
                            encoded.append(DECODE_62[n])
                    if len(encoded) == 342:
                        cksum_nib = nib2[didx+342]
                        cksum_val = DECODE_62.get(cksum_nib, -1)
                        d = [0] * 342
                        prev = 0
                        for k in range(342):
                            d[k] = encoded[k] ^ prev
                            prev = d[k]
                        cksum_ok = (prev == cksum_val)
                        result = bytearray(256)
                        for k in range(256):
                            upper = d[86+k] << 2
                            aux_idx = 85 - (k % 86)
                            shift = (k // 86) * 2
                            lower = (d[aux_idx] >> shift) & 0x03
                            result[k] = (upper | lower) & 0xFF
                        first8 = ' '.join(f'{b:02X}' for b in result[:8])
                        print(f"  S{sec} (D5 AA 96): {first8}... ck={'OK' if cksum_ok else 'BAD'}")
                        print(f"  Byte 0 = ${result[0]:02X}")
                    break

    # Now look at D5 AA B5 sector 0 boot code
    if 0 in decoded_sectors:
        boot = decoded_sectors[0]
        print(f"\n=== D5 AA B5 Sector 0 (potential real boot sector) ===")
        print(f"Byte 0 (sector count): ${boot[0]:02X} = {boot[0]}")
        print(f"\nHex dump:")
        for row in range(16):
            off = row * 16
            h = ' '.join(f'{boot[off+c]:02X}' for c in range(16))
            a = ''.join(chr(boot[off+c]) if 32 <= boot[off+c] < 127 else '.'
                        for c in range(16))
            print(f"  ${0x0800+off:04X}: {h}  {a}")

        print(f"\nDisassembly from $0801:")
        for line in disasm(boot[1:], 0x0801, 60):
            print(f"  {line}")

    # Also look at sector 1 if it exists
    if 1 in decoded_sectors:
        s1 = decoded_sectors[1]
        print(f"\n=== D5 AA B5 Sector 1 ===")
        print(f"First 32: {' '.join(f'{b:02X}' for b in s1[:32])}")
        print(f"Disassembly from $0900:")
        for line in disasm(s1, 0x0900, 30):
            print(f"  {line}")


if __name__ == '__main__':
    main()

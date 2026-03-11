#!/usr/bin/env python3
"""Test correct 6-and-2 decode using the EXACT boot ROM algorithm."""
import struct

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


def read_nibbles(woz_path, track_num):
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
    if tidx == 0xFF:
        return None
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


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    nibbles = read_nibbles(woz_path, 0)
    nib = nibbles + nibbles[:2000]

    # Find D5 AA 96 address field
    i = 0
    while i < len(nibbles):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0x96:
            idx = i + 3
            vol = ((nib[idx] << 1) | 1) & nib[idx+1]
            trk = ((nib[idx+2] << 1) | 1) & nib[idx+3]
            sec = ((nib[idx+4] << 1) | 1) & nib[idx+5]
            ck = ((nib[idx+6] << 1) | 1) & nib[idx+7]
            print(f"D5 AA 96: vol={vol} trk={trk} sec={sec} ck={ck:02X}")

            # Find D5 AA AD data prolog
            search_start = i + 11
            for j in range(search_start, search_start + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    didx = j + 3
                    print(f"Data field at nibble {j}, data starts at {didx}")

                    # Read 343 raw disk nibbles, GCR decode each
                    raw_nibs = nib[didx:didx+343]
                    encoded = []
                    all_valid = True
                    for k, n in enumerate(raw_nibs):
                        if n in DECODE_62:
                            encoded.append(DECODE_62[n])
                        else:
                            print(f"  Invalid nibble at offset {k}: ${n:02X}")
                            all_valid = False
                            encoded.append(0)

                    print(f"  All nibbles valid: {all_valid}")
                    print(f"  First 16 encoded (6-bit): {' '.join(f'{v:02X}' for v in encoded[:16])}")
                    print(f"  Encoded[86:102] (main):   {' '.join(f'{v:02X}' for v in encoded[86:102])}")

                    # XOR chain decode
                    decoded = [0] * 342
                    prev = 0
                    for k in range(342):
                        decoded[k] = encoded[k] ^ prev
                        prev = decoded[k]
                    cksum_ok = (prev == encoded[342])
                    print(f"  Checksum: {'OK' if cksum_ok else 'BAD'} (prev={prev:02X}, ck={encoded[342]:02X})")

                    print(f"  Decoded aux[0:16]:  {' '.join(f'{v:02X}' for v in decoded[0:16])}")
                    print(f"  Decoded main[86:102]: {' '.join(f'{v:02X}' for v in decoded[86:102])}")

                    # === METHOD A: Boot ROM exact algorithm ===
                    # output[Y] = (decoded[86+Y] << 2) | (decoded[Y] & 0x03)
                    result_a = bytearray(256)
                    for y in range(256):
                        upper = decoded[86 + y] << 2
                        lower = decoded[y] & 0x03
                        result_a[y] = (upper | lower) & 0xFF

                    print(f"\n  METHOD A (Boot ROM exact: decoded[86+Y]<<2 | decoded[Y]&3):")
                    print(f"    byte0=${result_a[0]:02X} ({result_a[0]})")
                    print(f"    First 32: {' '.join(f'{v:02X}' for v in result_a[:32])}")

                    # === METHOD B: Old wrong formula ===
                    result_b = bytearray(256)
                    for k in range(256):
                        upper = decoded[86 + k] << 2
                        aux_idx = 85 - (k % 86)
                        shift = (k // 86) * 2
                        lower = (decoded[aux_idx] >> shift) & 0x03
                        result_b[k] = (upper | lower) & 0xFF

                    print(f"\n  METHOD B (Old formula with reversed aux + shift):")
                    print(f"    byte0=${result_b[0]:02X} ({result_b[0]})")
                    print(f"    First 32: {' '.join(f'{v:02X}' for v in result_b[:32])}")

                    # === METHOD C: Standard DOS 3.3 RWTS formula ===
                    # In standard DOS, aux bytes are stored in reverse
                    # aux[0] has bits for bytes 255,169,83; aux[85] has bits for 170,84,0 (approx)
                    # The decode: for byte k:
                    #   aux_byte_idx = (255 - k) % 86  -- but wait, maybe not
                    # Actually the standard formula in real RWTS (not boot ROM) typically does:
                    # auxiliary[85-i] contains: bit1-0 for output[i], bit3-2 for output[i+86], bit5-4 for output[i+172]
                    result_c = bytearray(256)
                    for i in range(86):
                        aux_val = decoded[85 - i]  # aux stored in reverse
                        for g in range(3):
                            out_idx = i + g * 86
                            if out_idx < 256:
                                upper = decoded[86 + out_idx] << 2
                                lower = (aux_val >> (g * 2)) & 0x03
                                result_c[out_idx] = (upper | lower) & 0xFF

                    print(f"\n  METHOD C (Reversed aux, group of 3):")
                    print(f"    byte0=${result_c[0]:02X} ({result_c[0]})")
                    print(f"    First 32: {' '.join(f'{v:02X}' for v in result_c[:32])}")

                    # === METHOD D: Forward aux, group of 3 ===
                    result_d = bytearray(256)
                    for i in range(86):
                        aux_val = decoded[i]
                        for g in range(3):
                            out_idx = i + g * 86
                            if out_idx < 256:
                                upper = decoded[86 + out_idx] << 2
                                lower = (aux_val >> (g * 2)) & 0x03
                                result_d[out_idx] = (upper | lower) & 0xFF

                    print(f"\n  METHOD D (Forward aux, group of 3):")
                    print(f"    byte0=${result_d[0]:02X} ({result_d[0]})")
                    print(f"    First 32: {' '.join(f'{v:02X}' for v in result_d[:32])}")

                    # === METHOD E: What if XOR chain is wrong? Try no XOR ===
                    result_e = bytearray(256)
                    for y in range(256):
                        upper = encoded[86 + y] << 2
                        lower = encoded[y] & 0x03
                        result_e[y] = (upper | lower) & 0xFF

                    print(f"\n  METHOD E (No XOR chain, boot ROM formula):")
                    print(f"    byte0=${result_e[0]:02X} ({result_e[0]})")
                    print(f"    First 32: {' '.join(f'{v:02X}' for v in result_e[:32])}")

                    # Show which methods produce valid 6502 first byte
                    # Byte 0 at $0800 - for boot sector, often the sector count (1-13)
                    # or a valid opcode if the ROM jumps directly to $0800
                    # Valid first opcodes: LDA=A9, LDX=A2, LDY=A0, JMP=4C, JSR=20,
                    # SEI=78, CLD=D8, CLC=18, SEC=38, etc.
                    print("\n  === Checking for valid boot code ===")
                    for name, result in [("A", result_a), ("B", result_b),
                                          ("C", result_c), ("D", result_d), ("E", result_e)]:
                        b0 = result[0]
                        # Check if byte 0 is a sector count (1-13) or valid opcode
                        opcodes = {0x01:'ORA(ind,X)', 0x4C:'JMP', 0x20:'JSR', 0xA9:'LDA#',
                                   0xA2:'LDX#', 0xA0:'LDY#', 0x78:'SEI', 0xD8:'CLD',
                                   0x18:'CLC', 0x38:'SEC', 0x8D:'STA abs', 0xAD:'LDA abs',
                                   0xEA:'NOP', 0x00:'BRK', 0xA5:'LDA zp', 0x85:'STA zp',
                                   0xC9:'CMP#', 0xE8:'INX', 0xC8:'INY', 0xCA:'DEX',
                                   0x88:'DEY', 0x60:'RTS', 0x48:'PHA', 0x68:'PLA',
                                   0x29:'AND#', 0x09:'ORA#', 0x49:'EOR#', 0xBD:'LDA abs,X'}
                        desc = opcodes.get(b0, f'unknown opcode ${b0:02X}')
                        print(f"    {name}: byte0=${b0:02X} -> {desc}")

                    # Full hex dump for method A
                    print(f"\n  === Full hex dump METHOD A ===")
                    for row in range(16):
                        off = row * 16
                        hexvals = ' '.join(f'{result_a[off+c]:02X}' for c in range(16))
                        ascii_repr = ''.join(
                            chr(result_a[off+c]) if 32 <= result_a[off+c] < 127 else '.'
                            for c in range(16)
                        )
                        print(f"    ${0x0800+off:04X}: {hexvals}  {ascii_repr}")

                    break
            break
        i += 1


if __name__ == '__main__':
    main()

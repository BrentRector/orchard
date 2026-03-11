#!/usr/bin/env python3
"""Deep debug of 6-and-2 decode from WOZ file."""
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


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    with open(woz_path, 'rb') as f:
        data = f.read()

    # Check WOZ header
    magic = data[0:4]
    print(f"Magic: {magic} ({magic.hex()})")
    version = data[4]
    print(f"Version: WOZ{version}")

    # TMAP
    tmap_hdr = data[80:88]
    print(f"TMAP chunk header: {tmap_hdr[:4]} size={struct.unpack_from('<I', tmap_hdr, 4)[0]}")
    tmap = data[88:88 + 160]
    print(f"TMAP[0] (track 0, qt 0): {tmap[0]}")

    # TRKS
    trks_hdr = data[248:256]
    print(f"TRKS chunk header: {trks_hdr[:4]} size={struct.unpack_from('<I', trks_hdr, 4)[0]}")

    tidx = tmap[0]  # track 0
    if tidx == 0xFF:
        print("Track 0 not present!")
        return

    # In WOZ2, TRKS entries are at offset 256, each 8 bytes
    # But WOZ2 TRKS entries contain: starting_block (2), block_count (2), bit_count (4)
    trks_entry_offset = 256 + tidx * 8
    sb = struct.unpack_from('<H', data, trks_entry_offset)[0]
    bc = struct.unpack_from('<H', data, trks_entry_offset + 2)[0]
    bits = struct.unpack_from('<I', data, trks_entry_offset + 4)[0]
    print(f"\nTrack 0 TRKS entry (index {tidx}):")
    print(f"  starting_block={sb}, block_count={bc}, bit_count={bits}")
    print(f"  Track data at file offset {sb * 512}, length {bc * 512} bytes")

    track_data = data[sb * 512:sb * 512 + bc * 512]

    # Convert bits to nibbles
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

    print(f"  Total nibbles from track 0: {len(nibbles)}")
    nib = nibbles + nibbles[:2000]

    # Find D5 AA 96
    for i in range(len(nibbles)):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0x96:
            print(f"\n=== D5 AA 96 at nibble {i} ===")

            # Show address field
            idx = i + 3
            raw_addr = [nib[idx+k] for k in range(8)]
            print(f"  Address raw: {' '.join(f'{b:02X}' for b in raw_addr)}")
            vol = ((raw_addr[0] << 1) | 1) & raw_addr[1]
            trk = ((raw_addr[2] << 1) | 1) & raw_addr[3]
            sec = ((raw_addr[4] << 1) | 1) & raw_addr[5]
            ck = ((raw_addr[6] << 1) | 1) & raw_addr[7]
            print(f"  vol={vol} trk={trk} sec={sec} ck={ck:02X}")
            ck_calc = vol ^ trk ^ sec
            print(f"  ck_calc={ck_calc:02X} match={ck == ck_calc}")

            # Show epilog
            epi = [nib[idx+8+k] for k in range(2)]
            print(f"  Epilog: {' '.join(f'{b:02X}' for b in epi)}")

            # Find D5 AA AD data prolog
            gap = idx + 10
            print(f"\n  Gap nibbles (looking for D5 AA AD):")
            gap_nibs = [nib[gap+k] for k in range(30)]
            print(f"    {' '.join(f'{b:02X}' for b in gap_nibs)}")

            for j in range(gap, gap + 100):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    didx = j + 3
                    print(f"\n  D5 AA AD found at nibble {j}, data starts at {didx}")
                    print(f"  Gap between addr and data: {j - i} nibbles")

                    # Read 343 raw disk nibbles
                    raw = [nib[didx+k] for k in range(343)]
                    print(f"\n  First 20 raw disk nibbles: {' '.join(f'{b:02X}' for b in raw[:20])}")
                    print(f"  Raw[86:92]:  {' '.join(f'{b:02X}' for b in raw[86:92])}")
                    print(f"  Raw[342]:    {raw[342]:02X} (checksum nibble)")

                    # GCR decode all 343
                    encoded = [DECODE_62.get(n, -1) for n in raw]
                    bad = [k for k, v in enumerate(encoded) if v == -1]
                    if bad:
                        print(f"  BAD nibbles at positions: {bad}")
                        return

                    print(f"\n  First 20 GCR-decoded: {' '.join(f'{v:02X}' for v in encoded[:20])}")

                    # XOR chain
                    decoded = [0] * 342
                    prev = 0
                    for k in range(342):
                        decoded[k] = encoded[k] ^ prev
                        prev = decoded[k]

                    cksum_val = prev ^ encoded[342]
                    print(f"  XOR chain checksum: {cksum_val:02X} ({'OK' if cksum_val == 0 else 'BAD'})")

                    print(f"\n  Decoded aux[0:20]:    {' '.join(f'{v:02X}' for v in decoded[0:20])}")
                    print(f"  Decoded main[86:106]: {' '.join(f'{v:02X}' for v in decoded[86:106])}")
                    print(f"  Decoded[256:272]:     {' '.join(f'{v:02X}' for v in decoded[256:272])}")

                    # Boot ROM exact algorithm
                    result = bytearray(256)
                    for y in range(256):
                        upper = decoded[86 + y] << 2
                        lower = decoded[y] & 0x03
                        result[y] = (upper | lower) & 0xFF

                    print(f"\n  === Boot ROM decode result ===")
                    print(f"  Byte0=${result[0]:02X} ({result[0]})")
                    for row in range(16):
                        off = row * 16
                        h = ' '.join(f'{result[off+c]:02X}' for c in range(16))
                        a = ''.join(chr(result[off+c]) if 32 <= result[off+c] < 127 else '.'
                                    for c in range(16))
                        print(f"  ${0x0800+off:04X}: {h}  {a}")

                    # Try reverse XOR chain
                    decoded_rev = [0] * 342
                    prev = 0
                    for k in range(341, -1, -1):
                        decoded_rev[k] = encoded[k] ^ prev
                        prev = decoded_rev[k]

                    result_rev = bytearray(256)
                    for y in range(256):
                        upper = decoded_rev[86 + y] << 2
                        lower = decoded_rev[y] & 0x03
                        result_rev[y] = (upper | lower) & 0xFF

                    print(f"\n  === Reverse XOR chain result ===")
                    print(f"  Byte0=${result_rev[0]:02X}")
                    print(f"  First 32: {' '.join(f'{v:02X}' for v in result_rev[:32])}")

                    # Try: no XOR chain at all (raw GCR values)
                    result_raw = bytearray(256)
                    for y in range(256):
                        upper = encoded[86 + y] << 2
                        lower = encoded[y] & 0x03
                        result_raw[y] = (upper | lower) & 0xFF

                    print(f"\n  === No XOR chain result ===")
                    print(f"  Byte0=${result_raw[0]:02X}")
                    print(f"  First 32: {' '.join(f'{v:02X}' for v in result_raw[:32])}")

                    # Also try: maybe bytes 0-85 use bits 5:4, 3:2, 1:0 for 3 groups
                    # This is the "proper" 6-and-2 where each aux byte packs 3 pairs
                    result_packed = bytearray(256)
                    for i in range(86):
                        aux = decoded[i]
                        # Group 0: bits 1:0 -> output[i]
                        # Group 1: bits 3:2 -> output[i + 86]
                        # Group 2: bits 5:4 -> output[i + 172]
                        for g in range(3):
                            out_idx = i + g * 86
                            if out_idx < 256:
                                upper = decoded[86 + out_idx] << 2
                                lower = (aux >> (g * 2)) & 0x03
                                result_packed[out_idx] = (upper | lower) & 0xFF

                    print(f"\n  === Packed aux (3 groups, forward) ===")
                    print(f"  Byte0=${result_packed[0]:02X}")
                    print(f"  First 32: {' '.join(f'{v:02X}' for v in result_packed[:32])}")

                    # Try reverse aux index AND packed
                    result_rpacked = bytearray(256)
                    for i in range(86):
                        aux = decoded[85 - i]
                        for g in range(3):
                            out_idx = i + g * 86
                            if out_idx < 256:
                                upper = decoded[86 + out_idx] << 2
                                lower = (aux >> (g * 2)) & 0x03
                                result_rpacked[out_idx] = (upper | lower) & 0xFF

                    print(f"\n  === Packed aux (3 groups, reversed) ===")
                    print(f"  Byte0=${result_rpacked[0]:02X}")
                    print(f"  First 32: {' '.join(f'{v:02X}' for v in result_rpacked[:32])}")

                    # What if the boot ROM decode on this disk is correct but byte 0 really IS 2?
                    # In real Apple II boot, byte 0 = sector count, execution starts at $0801
                    # Let's try disassembling from $0801 for all methods
                    print(f"\n  === Quick disasm from $0801 ===")
                    for name, res in [("BootROM", result), ("Packed", result_packed),
                                       ("RPacked", result_rpacked)]:
                        print(f"  {name}: ", end='')
                        pos = 1
                        for _ in range(8):
                            if pos >= 256:
                                break
                            op = res[pos]
                            # Simple opcode length map
                            lengths = {
                                0xA0: 2, 0xA2: 2, 0xA9: 2, 0x85: 2, 0xA5: 2,
                                0x4C: 3, 0x20: 3, 0xAD: 3, 0x8D: 3, 0xBD: 3,
                                0xB9: 3, 0xBC: 3, 0xBE: 3, 0x2C: 3,
                                0xE8: 1, 0xC8: 1, 0xCA: 1, 0x88: 1,
                                0x18: 1, 0x38: 1, 0x78: 1, 0xD8: 1,
                                0x60: 1, 0xEA: 1, 0x48: 1, 0x68: 1,
                                0xD0: 2, 0xF0: 2, 0x90: 2, 0xB0: 2,
                                0x10: 2, 0x30: 2, 0x29: 2, 0x09: 2,
                                0x49: 2, 0xC9: 2, 0xE0: 2, 0xC0: 2,
                                0x0A: 1, 0x2A: 1, 0x4A: 1, 0x6A: 1,
                                0x00: 1, 0x86: 2, 0x84: 2, 0xA6: 2,
                                0xA4: 2, 0xC6: 2, 0xE6: 2,
                                0x99: 3, 0x9D: 3, 0x91: 2, 0x81: 2,
                                0xB1: 2, 0xA1: 2, 0x01: 2, 0x21: 2,
                                0x41: 2, 0x61: 2,
                            }
                            l = lengths.get(op, 0)
                            if l == 1:
                                print(f"${op:02X} ", end='')
                            elif l == 2 and pos + 1 < 256:
                                print(f"${op:02X} ${res[pos+1]:02X}  ", end='')
                            elif l == 3 and pos + 2 < 256:
                                addr = res[pos+1] | (res[pos+2] << 8)
                                print(f"${op:02X} ${addr:04X}  ", end='')
                            else:
                                print(f"[${op:02X}?] ", end='')
                                l = 1
                            pos += l
                        print()

                    break
            break


if __name__ == '__main__':
    main()

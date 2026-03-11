#!/usr/bin/env python3
"""
Decode ALL 5-and-3 sectors from the Apple Panic WOZ disk image.
Applies the stage 2 post-decode ($0346) to reconstruct full 256-byte sectors.
Produces hex dumps and disassembly for each sector.

Memory map from stage 2 code:
  Sector 0 → $B600  (also stage 2 code at $0300)
  Sector 1 → $B700  (entry point after all sectors loaded)
  Sector 2 → $B800
  ...
  Sector 9 → $BF00
  Sectors 10-12: loaded by later code (different tracks?)
"""
import struct, sys, os
sys.path.insert(0, 'E:/Apple')
from disasm_rwts import OPCODES, disasm


def read_woz_nibbles(woz_path, track_num):
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
    if tidx == 0xFF:
        return []
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


def build_53_gcr_table():
    """Build the 5-and-3 GCR decode table exactly as boot code does."""
    table = [0] * 256
    x = 0
    for y in range(0xAB, 0x100):
        a = y
        zp3c = a
        a = (a >> 1) & 0x7F
        a = a | zp3c
        if a != 0xFF:
            continue
        if y == 0xD5:
            continue
        table[y] = x
        x += 1
    return table


def corrupt_gcr_table(table):
    """Apply the ASL x3 corruption from stage 2 ($0301-$030B)."""
    t = list(table)
    for i in range(256):
        t[i] = (t[i] << 3) & 0xFF
    return t


def decode_44(b1, b2):
    return ((b1 << 1) | 1) & b2


def rwts_read_sector(nibbles, data_idx, gcr_table):
    """Simulate the RWTS read at $02A1-$02CE.

    Phase 1: Read 154 secondary nibbles into $0800 (reversed), XOR chain
    Phase 2: Read 256 primary nibbles into $0900, XOR chain
    Phase 3: Checksum

    Returns (secondary[0:154], primary[0:256], checksum_ok)
    """
    mem = list(gcr_table)  # $0800
    a = 0
    nib_idx = data_idx

    # Phase 1: 154 secondary nibbles, stored reversed
    y_counter = 0x9A  # 154
    while y_counter > 0:
        disk_nib = nibbles[nib_idx]; nib_idx += 1
        a ^= mem[disk_nib]
        y_counter -= 1
        mem[y_counter] = a

    # Phase 2: 256 primary nibbles
    pri_buf = [0] * 256
    for k in range(256):
        disk_nib = nibbles[nib_idx]; nib_idx += 1
        a ^= mem[disk_nib]
        pri_buf[k] = a

    # Phase 3: Checksum
    disk_nib = nibbles[nib_idx]; nib_idx += 1
    a ^= mem[disk_nib]

    return mem[:154], pri_buf, (a == 0)


def post_decode_0346(secondary, primary):
    """Simulate the stage 2 post-decode at $0346-$03A4.

    This is the 5-and-3 reconstruction that combines secondary (at $0800)
    and primary (at $0900) into 256 output bytes.

    Secondary: 51 entries at $0800, 51 at $0833, 51 at $0866 = 153 total
               Plus 1 extra at $0899
    Primary:   51 entries at $0900, 51 at $0933, 51 at $0966,
               51 at $0999, 51 at $09CC = 255 total
               Plus 1 extra at $09FF

    Output: 256 bytes (5 per iteration * 51 iterations + 1 final = 256)
    """
    output = [0] * 256
    y = 0  # output index

    for x in range(0x32, -1, -1):  # X = 50 down to 0
        # --- First group: sec[X] ($0800,X) ---
        # LDA; LSR; LSR; LSR → STA $3C; LSR → STA $2A; LSR → ORA pri
        a = secondary[x]
        a >>= 1; a >>= 1; a >>= 1          # 3 LSRs
        zp3c = a                             # STA $3C
        a >>= 1                              # 4th LSR
        zp2a = a                             # STA $2A
        a >>= 1                              # 5th LSR
        output[y] = a | primary[x]           # ORA $0900,X
        y += 1

        # --- Second group: sec[X+$33] ($0833,X) ---
        # LDA; LSR x3; then: LSR → carry → ROL $3C; LSR → carry → ROL $2A; ORA pri
        a = secondary[x + 0x33]
        a >>= 1; a >>= 1; a >>= 1           # 3 LSRs
        carry = a & 1; a >>= 1              # 4th LSR, carry = bit shifted out
        zp3c = ((zp3c << 1) | carry) & 0xFF # ROL $3C
        carry = a & 1; a >>= 1              # 5th LSR
        zp2a = ((zp2a << 1) | carry) & 0xFF # ROL $2A
        output[y] = a | primary[x + 0x33]
        y += 1

        # --- Third group: sec[X+$66] ($0866,X) ---
        a = secondary[x + 0x66]
        a >>= 1; a >>= 1; a >>= 1           # 3 LSRs
        carry = a & 1; a >>= 1              # 4th LSR
        zp3c = ((zp3c << 1) | carry) & 0xFF # ROL $3C
        carry = a & 1; a >>= 1              # 5th LSR
        zp2a = ((zp2a << 1) | carry) & 0xFF # ROL $2A
        output[y] = a | primary[x + 0x66]
        y += 1

        # Fourth byte: $2A AND #$07 | $0999,X
        output[y] = (zp2a & 0x07) | primary[x + 0x99]
        y += 1

        # Fifth byte: $3C AND #$07 | $09CC,X
        output[y] = (zp3c & 0x07) | primary[x + 0xCC]
        y += 1

    # Final byte (after loop): LDA $0899; LSR; LSR; LSR; ORA $09FF
    a = secondary[0x99]
    a >>= 1; a >>= 1; a >>= 1
    output[y] = a | primary[0xFF]

    return bytes(output)


def post_decode_02D1(secondary, primary):
    """Simulate the boot post-decode at $02D1-$02F9.

    This is used only for sector 0 during initial boot.
    Groups of 51 bytes, 3 groups. Each iteration:
    - LSR secondary[Y] → carry → ROL primary[0xCC+X]
    - LSR secondary[Y] → carry → ROL primary[0x99+X]
    - STA $3C (remaining bits)
    - LDA primary[Y], ASL x3, ORA $3C → store back
    """
    mem_0300 = list(primary)  # primary data is at $0300 (($26)=$0300)
    mem_0800 = list(secondary) + [0] * (256 - len(secondary))

    y = 0
    for group in range(3):  # $2A = 3, 2, 1
        for x in range(0x33):  # 51 iterations
            sec_val = mem_0800[y]

            # LSR → carry → ROL $03CC,X
            carry = sec_val & 1
            sec_val >>= 1
            cc_idx = 0xCC + x
            if cc_idx < 256:
                mem_0300[cc_idx] = ((mem_0300[cc_idx] << 1) | carry) & 0xFF

            # LSR → carry → ROL $0399,X
            carry2 = sec_val & 1
            sec_val >>= 1
            n9_idx = 0x99 + x
            if n9_idx < 256:
                mem_0300[n9_idx] = ((mem_0300[n9_idx] << 1) | carry2) & 0xFF

            # STA $3C
            zp3c = sec_val

            # LDA ($26),Y = primary[Y], ASL x3, ORA $3C
            pri_val = mem_0300[y]
            pri_val = (pri_val << 3) & 0xFF
            pri_val |= zp3c
            mem_0300[y] = pri_val

            y += 1

    return bytes(mem_0300)


def find_all_53_sectors(nibbles):
    """Find all 5-and-3 sectors (D5 AA B5 address, D5 AA AD data) on a track."""
    nib = nibbles + nibbles[:5000]
    sectors = {}
    i = 0
    while i < len(nibbles):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0xB5:
            idx = i + 3
            vol = decode_44(nib[idx], nib[idx+1])
            trk = decode_44(nib[idx+2], nib[idx+3])
            sec = decode_44(nib[idx+4], nib[idx+5])

            # Find data field
            for j in range(idx + 8, idx + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    data_idx = j + 3
                    sectors[sec] = {
                        'vol': vol, 'trk': trk, 'sec': sec,
                        'addr_offset': i, 'data_offset': data_idx,
                    }
                    i = j + 412
                    break
            else:
                i += 1
        else:
            i += 1
    return sectors


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    nibbles = read_woz_nibbles(woz_path, 0)
    nib = nibbles + nibbles[:5000]

    orig_table = build_53_gcr_table()
    corr_table = corrupt_gcr_table(orig_table)

    sectors = find_all_53_sectors(nibbles)

    print(f"Track 0: Found {len(sectors)} 5-and-3 sectors")
    print(f"Sector numbers: {sorted(sectors.keys())}")
    print()

    # The stage 2 loads sectors 0-9 into $B600-$BF00
    # using the corrupted GCR table and $0346 post-decode

    decoded_sectors = {}

    for sec_num in sorted(sectors.keys()):
        info = sectors[sec_num]

        # Decode with corrupted table (as stage 2 does)
        secondary, primary, cksum_ok = rwts_read_sector(
            nib, info['data_offset'], corr_table)

        # Apply stage 2 post-decode ($0346)
        decoded = post_decode_0346(secondary, primary)
        decoded_sectors[sec_num] = decoded

        # Also decode with original table for comparison
        secondary_orig, primary_orig, cksum_ok_orig = rwts_read_sector(
            nib, info['data_offset'], orig_table)

        if sec_num <= 9:
            dest = 0xB600 + sec_num * 0x100
        else:
            dest = None

        status = "PASS" if cksum_ok else "FAIL"
        status_o = "PASS" if cksum_ok_orig else "FAIL"
        dest_str = f"${dest:04X}" if dest else "????"

        print(f"=== Sector {sec_num:2d} (V:{info['vol']:3d} T:{info['trk']:2d}) "
              f"-> {dest_str}  cksum: orig={status_o} corr={status} ===")

        # Hex dump
        for row in range(16):
            off = row * 16
            h = ' '.join(f'{decoded[off+c]:02X}' for c in range(16))
            a = ''.join(chr(decoded[off+c]) if 32 <= decoded[off+c] < 127 else '.'
                       for c in range(16))
            addr = dest + off if dest else off
            print(f"  ${addr:04X}: {h}  {a}")

        # Check if it looks like code (has valid opcodes in first bytes)
        code_like = sum(1 for b in decoded[:32] if b in OPCODES) / 32
        if code_like > 0.3 and dest:
            print(f"\n  --- Disassembly (first 128 bytes) ---")
            disasm(decoded, dest, dest, min(dest + 128, dest + 256))

        print()

    # Save all decoded sectors as binary
    out_dir = "E:/Apple/decoded_sectors"
    os.makedirs(out_dir, exist_ok=True)

    for sec_num, data in sorted(decoded_sectors.items()):
        fname = os.path.join(out_dir, f"track00_sector{sec_num:02d}.bin")
        with open(fname, 'wb') as f:
            f.write(data)

    # Build the full memory image ($B600-$BFFF)
    memory = bytearray(0x0A00)  # 10 pages
    for sec_num in range(10):
        if sec_num in decoded_sectors:
            off = sec_num * 256
            memory[off:off+256] = decoded_sectors[sec_num]

    mem_path = "E:/Apple/decoded_sectors/stage2_memory_B600.bin"
    with open(mem_path, 'wb') as f:
        f.write(memory)

    print(f"\nSaved {len(decoded_sectors)} sectors to {out_dir}/")
    print(f"Memory image ($B600-$BFFF) saved to {mem_path}")

    # Summary: what does the code do after loading?
    print("\n=== Boot chain summary ===")
    print("  P6 ROM: 6-and-2 sector 0 -> $0800, JMP $0801")
    print("  $0801: Copy $0800->$0200, JMP $020F")
    print("  $020F: Build 5-and-3 GCR table, read sector 0 -> $0300")
    print("  $0237: Patch $031F (ORA #$C0 -> LDA #$02)")
    print("  $0241: JMP $0301 (stage 2)")
    print("  $0301: Corrupt GCR table (ASL x3)")
    print("  $030D: Load sectors 0-9 -> $B600-$BF00")
    print("  $033A: JMP ($003E) where $3E/$3F=$00/$B7 -> JMP $B700")
    print(f"  Entry: $B700 (sector 1 data)")


if __name__ == '__main__':
    main()

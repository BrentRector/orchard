#!/usr/bin/env python3
"""Analyze the .dsk file to understand its format and bootability."""

def main():
    with open("E:/Apple/ApplePanic_original.dsk", 'rb') as f:
        dsk = f.read()

    print(f"File size: {len(dsk)} bytes ({len(dsk)//256} sectors)")

    # Check how many sectors are all zeros
    zero_sectors = 0
    for s in range(len(dsk) // 256):
        sector = dsk[s*256:(s+1)*256]
        if all(b == 0 for b in sector):
            zero_sectors += 1
    print(f"Zero sectors: {zero_sectors}/{len(dsk)//256}")

    # Check VTOC at T17S0 (DOS 3.3)
    vtoc_offset = 17 * 16 * 256  # T17S0
    vtoc = dsk[vtoc_offset:vtoc_offset + 256]
    print(f"\n=== VTOC at T17S0 (offset {vtoc_offset}) ===")
    print(f"  First 32 bytes: {' '.join(f'{b:02X}' for b in vtoc[:32])}")
    print(f"  Catalog track/sector: T{vtoc[1]:d} S{vtoc[2]:d}")
    print(f"  DOS version: {vtoc[3]:d}")
    print(f"  Volume: {vtoc[6]:d}")
    print(f"  Max T/S pairs: {vtoc[0x27]:d}")
    print(f"  Last alloc track: {vtoc[0x30]:d}")
    print(f"  Alloc direction: {vtoc[0x31]:d}")
    print(f"  Tracks per disk: {vtoc[0x34]:d}")
    print(f"  Sectors per track: {vtoc[0x35]:d}")
    print(f"  Bytes per sector: {vtoc[0x36] | (vtoc[0x37] << 8)}")

    # Check if VTOC looks valid
    is_dos33 = (vtoc[0x34] == 35 and vtoc[0x35] == 16 and
                (vtoc[0x36] | (vtoc[0x37] << 8)) == 256)
    print(f"  Looks like DOS 3.3: {is_dos33}")

    # Check catalog
    cat_trk = vtoc[1]
    cat_sec = vtoc[2]
    if cat_trk < 35 and cat_sec < 16:
        cat_offset = (cat_trk * 16 + cat_sec) * 256
        cat = dsk[cat_offset:cat_offset + 256]
        print(f"\n=== Catalog at T{cat_trk}S{cat_sec} ===")
        print(f"  First 16 bytes: {' '.join(f'{b:02X}' for b in cat[:16])}")
        # Parse file entries (start at offset $0B, every 35 bytes)
        for i in range(7):  # 7 entries per catalog sector
            entry_off = 0x0B + i * 0x23
            if entry_off + 0x23 > 256:
                break
            t_s = cat[entry_off]
            if t_s == 0:
                continue
            file_type = cat[entry_off + 2]
            name = bytes(cat[entry_off + 3:entry_off + 3 + 30])
            name_str = ''.join(chr(b & 0x7F) for b in name).rstrip()
            size = cat[entry_off + 0x21] | (cat[entry_off + 0x22] << 8)
            ft_map = {0x00: 'T', 0x01: 'I', 0x02: 'A', 0x04: 'B',
                       0x08: 'S', 0x10: 'R', 0x20: 'a', 0x40: 'b'}
            ft_name = ft_map.get(file_type & 0x7F, f'${file_type:02X}')
            locked = '*' if file_type & 0x80 else ' '
            print(f"  {locked}{ft_name} {size:3d} {name_str}")

    # Show T0 sector summary
    print(f"\n=== Track 0 sectors ===")
    for s in range(16):
        sector = dsk[s * 256:(s+1) * 256]
        nz = sum(1 for b in sector if b != 0)
        first8 = ' '.join(f'{b:02X}' for b in sector[:8])
        print(f"  S{s:2d}: {nz:3d} non-zero bytes  {first8}...")

    # Check if T0S0 has the boot sector signature
    t0s0 = dsk[0:256]
    print(f"\n=== T0S0 analysis ===")
    print(f"  Byte 0 (sector count): ${t0s0[0]:02X} ({t0s0[0]})")
    print(f"  Last 4 bytes: {' '.join(f'{b:02X}' for b in t0s0[252:256])}")
    if t0s0[252] == 0x4C:  # JMP
        addr = t0s0[253] | (t0s0[254] << 8)
        print(f"  $08FC: JMP ${addr:04X}")


if __name__ == '__main__':
    main()

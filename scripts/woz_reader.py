#!/usr/bin/env python3
"""
WOZ2 disk image reader for Apple II
Decodes flux-level WOZ2 images into raw sector data.
Supports standard DOS 3.3 6-and-2 encoding.
"""

import struct
import sys

# DOS 3.3 6-and-2 decode table
# Maps disk nibble bytes to 6-bit values
DECODE_62 = {}
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
for i, v in enumerate(ENCODE_62):
    DECODE_62[v] = i

# DOS 3.3 logical-to-physical sector interleave
DOS33_INTERLEAVE = [0x0, 0x7, 0xE, 0x6, 0xD, 0x5, 0xC, 0x4,
                    0xB, 0x3, 0xA, 0x2, 0x9, 0x1, 0x8, 0xF]

# ProDOS interleave (different from DOS 3.3)
PRODOS_INTERLEAVE = [0x0, 0x8, 0x1, 0x9, 0x2, 0xA, 0x3, 0xB,
                     0x4, 0xC, 0x5, 0xD, 0x6, 0xE, 0x7, 0xF]


def read_woz2(path):
    """Parse a WOZ2 file and return track bit streams."""
    with open(path, 'rb') as f:
        data = f.read()

    # Verify header
    magic = data[0:4]
    if magic != b'WOZ2':
        raise ValueError(f"Not a WOZ2 file (magic: {magic})")

    ff_byte = data[4]
    if ff_byte != 0xFF:
        raise ValueError(f"Expected 0xFF at byte 4, got 0x{ff_byte:02X}")

    print(f"WOZ2 file: {len(data)} bytes")

    # Parse INFO chunk
    info_id = data[12:16]
    info_size = struct.unpack_from('<I', data, 16)[0]
    info_version = data[20]
    disk_type = data[21]  # 1=5.25", 2=3.5"
    write_protected = data[22]
    synchronized = data[23]
    cleaned = data[24]
    creator = data[25:57].decode('ascii', errors='replace').strip()
    print(f"INFO: version={info_version}, disk_type={'5.25\"' if disk_type==1 else '3.5\"'}, "
          f"creator='{creator}', synced={synchronized}, cleaned={cleaned}")

    # Parse TMAP chunk
    tmap_offset = 12 + 4 + 4 + info_size  # after INFO chunk header + data
    # Actually, chunks are at fixed positions in WOZ2:
    # INFO starts at offset 12
    # TMAP starts at offset 80 (12 + 8 + 60)
    # TRKS starts at offset 248 (80 + 8 + 160)
    tmap_id = data[80:84]
    assert tmap_id == b'TMAP', f"Expected TMAP at offset 80, got {tmap_id}"
    tmap_size = struct.unpack_from('<I', data, 84)[0]
    tmap = data[88:88+160]  # 160 quarter-track entries

    # Parse TRKS chunk
    trks_id = data[248:252]
    assert trks_id == b'TRKS', f"Expected TRKS at offset 248, got {trks_id}"
    trks_size = struct.unpack_from('<I', data, 252)[0]

    # Track entries start at offset 256, 8 bytes each, up to 160 entries
    tracks = {}
    for i in range(160):
        offset = 256 + i * 8
        start_block = struct.unpack_from('<H', data, offset)[0]
        block_count = struct.unpack_from('<H', data, offset + 2)[0]
        bit_count = struct.unpack_from('<I', data, offset + 4)[0]

        if start_block == 0 and block_count == 0:
            continue

        byte_offset = start_block * 512
        byte_count = block_count * 512
        track_data = data[byte_offset:byte_offset + byte_count]

        tracks[i] = {
            'start_block': start_block,
            'block_count': block_count,
            'bit_count': bit_count,
            'data': track_data,
        }

    # Map quarter tracks to track indices via TMAP
    print(f"\nTMAP -> Track mapping:")
    for qt in range(160):
        tidx = tmap[qt]
        if tidx != 0xFF:
            track_num = qt / 4.0
            if tidx in tracks:
                t = tracks[tidx]
                print(f"  Quarter-track {qt:3d} (track {track_num:5.2f}) -> "
                      f"index {tidx:2d}, {t['bit_count']} bits, "
                      f"blocks {t['start_block']}-{t['start_block']+t['block_count']-1}")

    return tracks, tmap


def extract_bits(track_data, bit_count):
    """Convert byte array to bit stream."""
    bits = []
    for byte_idx in range(len(track_data)):
        for bit_idx in range(7, -1, -1):
            bits.append((track_data[byte_idx] >> bit_idx) & 1)
            if len(bits) >= bit_count:
                return bits
    return bits


def find_nibbles(bits):
    """Convert bit stream to nibble stream (bytes with high bit set).
    Apple II disk controller shifts bits in from the right,
    and a byte is complete when bit 7 is set."""
    nibbles = []
    current = 0
    for b in bits:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles


def decode_44(byte1, byte2):
    """Decode 4-and-4 encoded byte (used in address fields)."""
    return ((byte1 << 1) | 0x01) & byte2


def decode_sector_data(nibbles, start_idx):
    """Decode 6-and-2 encoded sector data starting at given nibble index.
    Returns 256-byte sector or None on error."""
    idx = start_idx

    # Read 342 encoded bytes (86 + 256)
    encoded = []
    for i in range(342):
        if idx + i >= len(nibbles):
            return None, start_idx
        nib = nibbles[idx + i]
        if nib not in DECODE_62:
            return None, start_idx
        encoded.append(DECODE_62[nib])
    idx += 342

    # Read checksum byte
    if idx >= len(nibbles):
        return None, start_idx
    if nibbles[idx] not in DECODE_62:
        return None, start_idx
    checksum_byte = DECODE_62[nibbles[idx]]
    idx += 1

    # XOR-decode the encoded stream
    decoded = [0] * 342
    prev = 0
    for i in range(342):
        decoded[i] = encoded[i] ^ prev
        prev = decoded[i]

    # Verify checksum
    if prev != checksum_byte:
        # Checksum mismatch - try anyway but flag it
        pass

    # Reconstruct 256 bytes from 6-and-2 encoding
    # First 86 bytes contain the lower 2 bits, next 256 have upper 6 bits
    result = bytearray(256)
    for i in range(256):
        # Upper 6 bits from decoded[86+i]
        upper = decoded[86 + i] << 2

        # Lower 2 bits from the first 86 bytes
        # The mapping is reversed: byte 0's bits come from decoded[85],
        # byte 1's from decoded[84], etc.
        aux_idx = 85 - (i % 86)
        shift = (i // 86) * 2
        lower = (decoded[aux_idx] >> shift) & 0x03

        result[i] = (upper | lower) & 0xFF

    return bytes(result), idx


def decode_track(track_info):
    """Decode all sectors from a track's bit stream."""
    bits = extract_bits(track_info['data'], track_info['bit_count'])
    nibbles = find_nibbles(bits)

    # Double the nibble stream to handle wrap-around
    nibbles_ext = nibbles + nibbles

    sectors = {}
    idx = 0

    while idx < len(nibbles):
        # Search for address field prologue: D5 AA 96
        found = False
        for search_idx in range(idx, min(idx + 600, len(nibbles_ext) - 20)):
            if (nibbles_ext[search_idx] == 0xD5 and
                nibbles_ext[search_idx + 1] == 0xAA and
                nibbles_ext[search_idx + 2] == 0x96):
                idx = search_idx + 3
                found = True
                break
        if not found:
            break

        # Read address field: volume, track, sector, checksum (4-and-4 encoded)
        if idx + 8 > len(nibbles_ext):
            break
        volume = decode_44(nibbles_ext[idx], nibbles_ext[idx + 1])
        track = decode_44(nibbles_ext[idx + 2], nibbles_ext[idx + 3])
        sector = decode_44(nibbles_ext[idx + 4], nibbles_ext[idx + 5])
        cksum = decode_44(nibbles_ext[idx + 6], nibbles_ext[idx + 7])
        idx += 8

        # Verify address checksum
        addr_ok = (volume ^ track ^ sector ^ cksum) == 0

        # Skip address epilogue (DE AA EB)
        # Search for data field prologue: D5 AA AD
        data_found = False
        for search_idx in range(idx, min(idx + 100, len(nibbles_ext) - 350)):
            if (nibbles_ext[search_idx] == 0xD5 and
                nibbles_ext[search_idx + 1] == 0xAA and
                nibbles_ext[search_idx + 2] == 0xAD):
                idx = search_idx + 3
                data_found = True
                break

        if not data_found:
            continue

        # Decode sector data
        sector_data, idx = decode_sector_data(nibbles_ext, idx)

        if sector_data and addr_ok:
            if sector not in sectors:
                sectors[sector] = {
                    'volume': volume,
                    'track': track,
                    'sector': sector,
                    'data': sector_data,
                }

    return sectors


def build_dos33_image(all_tracks, tmap):
    """Build a standard 140K DOS 3.3 disk image from decoded tracks."""
    # 35 tracks x 16 sectors x 256 bytes = 143,360 bytes
    image = bytearray(35 * 16 * 256)

    total_sectors = 0
    missing_sectors = []

    for track_num in range(35):
        # Look up quarter-track in TMAP
        qt = track_num * 4
        tidx = tmap[qt]
        if tidx == 0xFF:
            print(f"  Track {track_num:2d}: not in TMAP")
            missing_sectors.extend([(track_num, s) for s in range(16)])
            continue

        if tidx not in all_tracks:
            print(f"  Track {track_num:2d}: TMAP index {tidx} but no track data")
            missing_sectors.extend([(track_num, s) for s in range(16)])
            continue

        sectors = decode_track(all_tracks[tidx])

        found = sorted(sectors.keys())
        if len(found) < 16:
            missing = [s for s in range(16) if s not in sectors]
            print(f"  Track {track_num:2d}: {len(found)}/16 sectors (missing: {missing})")
            missing_sectors.extend([(track_num, s) for s in missing])
        else:
            vol = sectors[found[0]]['volume']
            print(f"  Track {track_num:2d}: 16/16 sectors, volume={vol}")

        for phys_sector, info in sectors.items():
            # DOS 3.3 sector interleave: physical -> logical
            logical_sector = DOS33_INTERLEAVE[phys_sector]
            offset = (track_num * 16 + logical_sector) * 256
            image[offset:offset + 256] = info['data']
            total_sectors += 1

    print(f"\nTotal sectors decoded: {total_sectors}/{35*16}")
    if missing_sectors:
        print(f"Missing sectors: {len(missing_sectors)}")

    return bytes(image), missing_sectors


def read_vtoc(image):
    """Read the DOS 3.3 VTOC (Volume Table of Contents) from track 17, sector 0."""
    offset = 17 * 16 * 256  # Track 17, sector 0
    vtoc = image[offset:offset + 256]

    catalog_track = vtoc[1]
    catalog_sector = vtoc[2]
    dos_version = vtoc[3]
    volume_number = vtoc[6]
    max_pairs = vtoc[0x27]
    last_track = vtoc[0x34]
    dir_format = vtoc[0x35]
    tracks_per_disk = vtoc[0x36]
    sectors_per_track = vtoc[0x37]
    bytes_per_sector = struct.unpack_from('<H', vtoc, 0x38)[0]

    print(f"\n=== VTOC ===")
    print(f"DOS version: {dos_version}")
    print(f"Volume: {volume_number}")
    print(f"Catalog: track {catalog_track}, sector {catalog_sector}")
    print(f"Tracks/disk: {tracks_per_disk}, Sectors/track: {sectors_per_track}")
    print(f"Bytes/sector: {bytes_per_sector}")

    return {
        'catalog_track': catalog_track,
        'catalog_sector': catalog_sector,
        'volume': volume_number,
        'dos_version': dos_version,
    }


def read_catalog(image, vtoc):
    """Read the DOS 3.3 catalog chain."""
    files = []
    track = vtoc['catalog_track']
    sector = vtoc['catalog_sector']
    visited = set()

    while track != 0 or sector != 0:
        if (track, sector) in visited:
            print(f"  Catalog chain loop at T{track}S{sector}")
            break
        visited.add((track, sector))

        offset = (track * 16 + sector) * 256
        cat_sector = image[offset:offset + 256]

        next_track = cat_sector[1]
        next_sector = cat_sector[2]

        # Each catalog sector has 7 file entries, each 35 bytes, starting at byte 11
        for i in range(7):
            entry_offset = 0x0B + i * 0x23
            entry = cat_sector[entry_offset:entry_offset + 0x23]

            ts_list_track = entry[0]
            ts_list_sector = entry[1]

            if ts_list_track == 0:
                continue  # empty entry
            if ts_list_track == 0xFF:
                continue  # deleted entry

            file_type = entry[2]
            file_name = entry[3:33].decode('ascii', errors='replace')
            # Strip high bit from file name characters
            clean_name = ''.join(chr(c & 0x7F) for c in entry[3:33]).rstrip()
            file_size = struct.unpack_from('<H', entry, 33)[0]  # in sectors

            type_names = {
                0x00: 'T', 0x01: 'I', 0x02: 'A', 0x04: 'B',
                0x08: 'S', 0x10: 'R', 0x20: 'a', 0x40: 'b',
            }
            locked = '*' if file_type & 0x80 else ' '
            ftype = type_names.get(file_type & 0x7F, '?')

            files.append({
                'name': clean_name,
                'type': ftype,
                'locked': locked,
                'type_byte': file_type,
                'size_sectors': file_size,
                'ts_list_track': ts_list_track,
                'ts_list_sector': ts_list_sector,
            })

        track = next_track
        sector = next_sector

    return files


def read_file_data(image, file_info):
    """Read a file's data by following its T/S list chain."""
    data = bytearray()
    track = file_info['ts_list_track']
    sector = file_info['ts_list_sector']
    visited = set()
    ts_pairs = []

    while track != 0 or sector != 0:
        if (track, sector) in visited:
            break
        visited.add((track, sector))

        offset = (track * 16 + sector) * 256
        ts_list = image[offset:offset + 256]

        next_track = ts_list[1]
        next_sector = ts_list[2]

        # T/S pairs start at byte 12, each is 2 bytes (track, sector)
        for i in range(122):
            pair_offset = 0x0C + i * 2
            dt = ts_list[pair_offset]
            ds = ts_list[pair_offset + 1]

            if dt == 0 and ds == 0:
                # End of file or sparse sector
                continue

            ts_pairs.append((dt, ds))
            data_offset = (dt * 16 + ds) * 256
            data.extend(image[data_offset:data_offset + 256])

        track = next_track
        sector = next_sector

    return bytes(data), ts_pairs


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"

    print("=== Reading WOZ2 file ===")
    tracks, tmap = read_woz2(woz_path)

    print(f"\n=== Building DOS 3.3 disk image ===")
    image, missing = build_dos33_image(tracks, tmap)

    # Save raw disk image
    dsk_path = "E:/Apple/ApplePanic_original.dsk"
    with open(dsk_path, 'wb') as f:
        f.write(image)
    print(f"\nDisk image saved: {dsk_path} ({len(image)} bytes)")

    # Read catalog
    vtoc = read_vtoc(image)
    files = read_catalog(image, vtoc)

    print(f"\n=== Disk Catalog ===")
    print(f"{'L':1s} {'T':1s} {'Size':>4s}  {'Name'}")
    print(f"{'-':1s} {'-':1s} {'----':>4s}  {'----'}")
    for f_info in files:
        print(f"{f_info['locked']}{f_info['type']} {f_info['size_sectors']:4d}  {f_info['name']}")

    # Extract binary files
    for f_info in files:
        name = f_info['name'].strip()
        print(f"\n--- Extracting: {name} (type {f_info['type']}) ---")
        data, ts_pairs = read_file_data(image, f_info)
        print(f"  Raw data: {len(data)} bytes from {len(ts_pairs)} sectors")

        if f_info['type'] == 'B':  # Binary file
            # Binary files have a 4-byte header: 2-byte load address, 2-byte length
            if len(data) >= 4:
                load_addr = struct.unpack_from('<H', data, 0)[0]
                file_len = struct.unpack_from('<H', data, 2)[0]
                print(f"  Binary: load=${load_addr:04X}, length=${file_len:04X} ({file_len} bytes)")

                actual_data = data[4:4 + file_len]
                safe_name = name.replace(' ', '_')
                out_path = f"E:/Apple/original_{safe_name}.bin"
                with open(out_path, 'wb') as f:
                    f.write(actual_data)
                print(f"  Saved: {out_path} ({len(actual_data)} bytes)")
        elif f_info['type'] == 'A':  # Applesoft BASIC
            if len(data) >= 4:
                load_addr = struct.unpack_from('<H', data, 0)[0]
                file_len = struct.unpack_from('<H', data, 2)[0]
                print(f"  Applesoft: load=${load_addr:04X}, length=${file_len:04X}")
        elif f_info['type'] == 'I':  # Integer BASIC
            if len(data) >= 4:
                load_addr = struct.unpack_from('<H', data, 0)[0]
                file_len = struct.unpack_from('<H', data, 2)[0]
                print(f"  Integer BASIC: load=${load_addr:04X}, length=${file_len:04X}")


if __name__ == '__main__':
    main()

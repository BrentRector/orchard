"""
DSK disk image reading, writing, and creation.

Handles standard 140K DOS 3.3 disk images (35 tracks x 16 sectors x 256 bytes).
Can convert WOZ images to DSK and create bootable DSK images from binaries.
"""

import struct
from .gcr import DOS33_INTERLEAVE, find_sectors_62


def woz_to_dsk(woz, interleave=None):
    """Convert a WOZ file's 6-and-2 tracks to a standard 140K DSK image.

    Args:
        woz: WOZFile object
        interleave: sector interleave table (default: DOS33_INTERLEAVE)

    Returns:
        (image_bytes, missing_sectors_list)
    """
    if interleave is None:
        interleave = DOS33_INTERLEAVE

    image = bytearray(35 * 16 * 256)
    total = 0
    missing = []

    for track_num in range(35):
        if not woz.track_exists(track_num):
            missing.extend([(track_num, s) for s in range(16)])
            continue

        nibbles = woz.get_track_nibbles(track_num, bit_double=True)
        sectors = find_sectors_62(nibbles)

        for phys_sector, sd in sectors.items():
            logical = interleave[phys_sector]
            offset = (track_num * 16 + logical) * 256
            image[offset:offset + 256] = sd.data
            total += 1

        found = set(sectors.keys())
        for s in range(16):
            if s not in found:
                missing.append((track_num, s))

    return bytes(image), missing


def read_dsk(path):
    """Read a raw 140K DSK image file."""
    with open(path, 'rb') as f:
        return bytearray(f.read())


def write_dsk(path, image):
    """Write a raw 140K DSK image file."""
    with open(path, 'wb') as f:
        f.write(image)


def read_vtoc(image):
    """Read the DOS 3.3 VTOC from track 17, sector 0."""
    offset = 17 * 16 * 256
    vtoc = image[offset:offset + 256]

    return {
        'catalog_track': vtoc[1],
        'catalog_sector': vtoc[2],
        'dos_version': vtoc[3],
        'volume': vtoc[6],
        'max_pairs': vtoc[0x27],
        'tracks_per_disk': vtoc[0x34] if vtoc[0x34] else 35,
        'sectors_per_track': vtoc[0x35] if vtoc[0x35] else 16,
        'bytes_per_sector': struct.unpack_from('<H', vtoc, 0x38)[0] or 256,
    }


def read_catalog(image, vtoc=None):
    """Read the DOS 3.3 catalog chain. Returns list of file info dicts."""
    if vtoc is None:
        vtoc = read_vtoc(image)

    files = []
    track = vtoc['catalog_track']
    sector = vtoc['catalog_sector']
    visited = set()

    while track != 0 or sector != 0:
        if (track, sector) in visited:
            break
        visited.add((track, sector))

        offset = (track * 16 + sector) * 256
        cat = image[offset:offset + 256]

        next_track = cat[1]
        next_sector = cat[2]

        for i in range(7):
            entry_offset = 0x0B + i * 0x23
            entry = cat[entry_offset:entry_offset + 0x23]

            ts_track = entry[0]
            ts_sector = entry[1]
            if ts_track == 0 or ts_track == 0xFF:
                continue

            file_type = entry[2]
            clean_name = ''.join(chr(c & 0x7F) for c in entry[3:33]).rstrip()
            file_size = struct.unpack_from('<H', entry, 33)[0]

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
                'ts_list_track': ts_track,
                'ts_list_sector': ts_sector,
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

    while track != 0 or sector != 0:
        if (track, sector) in visited:
            break
        visited.add((track, sector))

        offset = (track * 16 + sector) * 256
        ts_list = image[offset:offset + 256]

        next_track = ts_list[1]
        next_sector = ts_list[2]

        for i in range(122):
            pair_offset = 0x0C + i * 2
            dt = ts_list[pair_offset]
            ds = ts_list[pair_offset + 1]
            if dt == 0 and ds == 0:
                continue
            data_offset = (dt * 16 + ds) * 256
            data.extend(image[data_offset:data_offset + 256])

        track = next_track
        sector = next_sector

    return bytes(data)


def create_bootable_dsk(binary, load_addr, entry_addr=None, volume=254):
    """Create a minimal bootable DOS 3.3 DSK with a BRUN-able binary.

    The binary is stored as a type-B file that can be loaded with BRUN.
    A minimal boot sector, VTOC, and catalog are created.

    Args:
        binary: bytes of the program
        load_addr: 16-bit load address
        entry_addr: 16-bit entry address (default: load_addr)
        volume: disk volume number (default: 254)

    Returns:
        140K DSK image as bytes
    """
    if entry_addr is None:
        entry_addr = load_addr

    image = bytearray(35 * 16 * 256)

    # Binary file data: 4-byte header (load addr + length) + data
    file_data = bytearray()
    file_data += struct.pack('<H', load_addr)
    file_data += struct.pack('<H', len(binary))
    file_data += binary

    # Calculate sectors needed
    data_sectors_needed = (len(file_data) + 255) // 256
    ts_lists_needed = (data_sectors_needed + 121) // 122

    # Allocate sectors: avoid track 0 (boot) and track 17 (VTOC/catalog)
    # Use tracks 1-16 and 18-34
    available = []
    for t in range(1, 35):
        if t == 17:
            continue
        for s in range(15, -1, -1):
            available.append((t, s))

    # Allocate: T/S list sectors first, then data sectors
    ts_sectors = []
    for _ in range(ts_lists_needed):
        ts_sectors.append(available.pop(0))

    data_ts_pairs = []
    for _ in range(data_sectors_needed):
        data_ts_pairs.append(available.pop(0))

    # Write data sectors
    for i, (dt, ds) in enumerate(data_ts_pairs):
        offset = (dt * 16 + ds) * 256
        chunk_start = i * 256
        chunk = file_data[chunk_start:chunk_start + 256]
        image[offset:offset + len(chunk)] = chunk

    # Write T/S list sectors
    pair_idx = 0
    for ts_idx, (tst, tss) in enumerate(ts_sectors):
        offset = (tst * 16 + tss) * 256
        ts_list = bytearray(256)

        # Link to next T/S list
        if ts_idx + 1 < len(ts_sectors):
            ts_list[1] = ts_sectors[ts_idx + 1][0]
            ts_list[2] = ts_sectors[ts_idx + 1][1]

        # T/S pairs start at byte 12
        for j in range(122):
            if pair_idx >= len(data_ts_pairs):
                break
            ts_list[0x0C + j * 2] = data_ts_pairs[pair_idx][0]
            ts_list[0x0C + j * 2 + 1] = data_ts_pairs[pair_idx][1]
            pair_idx += 1

        image[offset:offset + 256] = ts_list

    # Write VTOC at track 17, sector 0
    vtoc_offset = 17 * 16 * 256
    vtoc = bytearray(256)
    vtoc[1] = 17   # catalog track
    vtoc[2] = 15   # catalog sector
    vtoc[3] = 3    # DOS version
    vtoc[6] = volume
    vtoc[0x27] = 122  # max T/S pairs
    vtoc[0x34] = 35   # tracks per disk
    vtoc[0x35] = 16   # sectors per track
    struct.pack_into('<H', vtoc, 0x38, 256)  # bytes per sector

    # Free sector bitmap (mark used sectors)
    used_sectors = set()
    used_sectors.add((0, 0))   # boot sector
    used_sectors.add((17, 0))  # VTOC
    used_sectors.add((17, 15)) # catalog
    for t, s in ts_sectors:
        used_sectors.add((t, s))
    for t, s in data_ts_pairs:
        used_sectors.add((t, s))

    for t in range(35):
        bitmap_offset = 0x38 + t * 4
        bits = 0xFFFF  # all free
        for s in range(16):
            if (t, s) in used_sectors:
                bits &= ~(1 << s)
        struct.pack_into('<H', vtoc, bitmap_offset, bits)

    image[vtoc_offset:vtoc_offset + 256] = vtoc

    # Write catalog at track 17, sector 15
    cat_offset = (17 * 16 + 15) * 256
    catalog = bytearray(256)
    # First entry at byte 0x0B
    entry = bytearray(0x23)
    entry[0] = ts_sectors[0][0]  # T/S list track
    entry[1] = ts_sectors[0][1]  # T/S list sector
    entry[2] = 0x84  # type B (binary), locked
    # File name: "PROGRAM" padded to 30 bytes with spaces, high bit set
    name = "PROGRAM"
    for i, ch in enumerate(name.ljust(30)):
        entry[3 + i] = ord(ch) | 0x80
    struct.pack_into('<H', entry, 33, data_sectors_needed + ts_lists_needed)
    catalog[0x0B:0x0B + 0x23] = entry

    image[cat_offset:cat_offset + 256] = catalog

    return bytes(image)

"""
DSK disk image reading, writing, and creation.

Handles standard 140K DOS 3.3 disk images (35 tracks x 16 sectors x 256 bytes).
Can convert WOZ images to DSK and create bootable DSK images from binaries.

Overview
--------
The DSK format is a raw sector dump of an Apple II floppy disk. A standard
DOS 3.3 disk has 35 tracks, 16 sectors per track, and 256 bytes per sector,
for a total of 35 * 16 * 256 = 143,360 bytes (140K).

The byte ordering in a DSK file is: track 0 sector 0, track 0 sector 1, ...,
track 0 sector 15, track 1 sector 0, ..., track 34 sector 15. Sectors are
stored in logical (interleaved) order, so the physical-to-logical sector
mapping must be applied when converting from a raw disk (WOZ) to DSK format.

DOS 3.3 Disk Structure
----------------------
  - **Track 0**: Boot sector (sector 0) and DOS boot code.
  - **Track 17**: The "directory track" — contains the VTOC (sector 0) and
    the catalog chain (starting at the sector specified in the VTOC).
  - **All other tracks**: File data and T/S (track/sector) lists.

Usage
-----
    from nibbler.dsk import read_dsk, read_vtoc, read_catalog, read_file_data

    image = read_dsk("game.dsk")
    vtoc = read_vtoc(image)
    files = read_catalog(image)
    for f in files:
        print(f"{f['locked']}{f['type']} {f['size_sectors']:03d} {f['name']}")
        data = read_file_data(image, f)
"""

import struct
from .gcr import DOS33_INTERLEAVE, find_sectors_62


def woz_to_dsk(woz, interleave=None):
    """Convert a WOZ file's 6-and-2 tracks to a standard 140K DSK image.

    Reads each track's nibble stream from the WOZ object, decodes the
    6-and-2 GCR-encoded sectors, and places the 256-byte sector data
    into the correct position in the flat DSK image using the interleave
    table to map physical sector numbers to logical positions.

    Args:
        woz: WOZFile object (must support track_exists() and
            get_track_nibbles() methods).
        interleave: Sector interleave table mapping physical sector number
            (index) to logical sector number (value). Default: DOS33_INTERLEAVE.

    Returns:
        (image_bytes, missing_sectors_list): A tuple of the 140K DSK image
        as bytes and a list of (track, sector) tuples for any sectors that
        could not be decoded.
    """
    if interleave is None:
        interleave = DOS33_INTERLEAVE

    image = bytearray(35 * 16 * 256)  # 140K = 143,360 bytes
    total = 0
    missing = []

    for track_num in range(35):
        if not woz.track_exists(track_num):
            missing.extend([(track_num, s) for s in range(16)])
            continue

        # Bit-doubling the nibble stream ensures we can read sectors that
        # straddle the track's wrap-around point.
        nibbles = woz.get_track_nibbles(track_num, bit_double=True)
        sectors = find_sectors_62(nibbles)

        for phys_sector, sd in sectors.items():
            # Map physical sector to logical sector using the interleave table.
            # DOS 3.3 interleave spaces logical sectors around the track so the
            # CPU has time to process each sector before the next one arrives
            # under the read head. Physical sector 0 -> logical 0, physical 1
            # -> logical 7, physical 2 -> logical 14, etc.
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
    """Read a raw 140K DSK image file.

    Args:
        path: Path to the .dsk file.

    Returns:
        bytearray of the 140K disk image (143,360 bytes for a standard disk).
    """
    with open(path, 'rb') as f:
        return bytearray(f.read())


def write_dsk(path, image):
    """Write a raw 140K DSK image file.

    Args:
        path: Path to write the .dsk file.
        image: bytes/bytearray of the disk image to write.
    """
    with open(path, 'wb') as f:
        f.write(image)


def read_vtoc(image):
    """Read the DOS 3.3 VTOC (Volume Table of Contents) from track 17, sector 0.

    The VTOC is a 256-byte structure that describes the disk's format and
    points to the first catalog sector. It also contains the free sector
    bitmap for the entire disk.

    VTOC structure (selected fields):
      Offset  Size  Description
      ------  ----  -----------
      $01     1     Track number of first catalog sector
      $02     1     Sector number of first catalog sector
      $03     1     DOS version (3 for DOS 3.3)
      $06     1     Disk volume number (1-254)
      $27     1     Max number of T/S pairs per T/S list sector (122)
      $34     1     Tracks per disk (35)
      $35     1     Sectors per track (16)
      $38     2     Bytes per sector (256, little-endian)
      $38+    4*35  Free sector bitmaps: 4 bytes per track, where each bit
                    represents one sector (1 = free, 0 = used)

    Args:
        image: bytearray of the DSK image.

    Returns:
        Dict with keys: catalog_track, catalog_sector, dos_version, volume,
        max_pairs, tracks_per_disk, sectors_per_track, bytes_per_sector.
    """
    # Track 17, sector 0 is at byte offset 17*16*256 = 69,632
    offset = 17 * 16 * 256
    vtoc = image[offset:offset + 256]

    return {
        'catalog_track': vtoc[1],       # Track of first catalog sector
        'catalog_sector': vtoc[2],      # Sector of first catalog sector
        'dos_version': vtoc[3],         # Should be 3 for DOS 3.3
        'volume': vtoc[6],              # Disk volume number (1-254)
        'max_pairs': vtoc[0x27],        # Max T/S pairs per T/S list (normally 122)
        'tracks_per_disk': vtoc[0x34] if vtoc[0x34] else 35,     # Default 35
        'sectors_per_track': vtoc[0x35] if vtoc[0x35] else 16,   # Default 16
        'bytes_per_sector': struct.unpack_from('<H', vtoc, 0x38)[0] or 256,
    }


def read_catalog(image, vtoc=None):
    """Read the DOS 3.3 catalog chain. Returns list of file info dicts.

    The catalog is a linked list of sectors, each containing up to 7 file
    entries. The chain starts at the sector specified in the VTOC and
    follows next-track/next-sector pointers until a (0, 0) link is found.

    Catalog sector structure:
      Offset  Size  Description
      ------  ----  -----------
      $01     1     Track of next catalog sector (0 = end of chain)
      $02     1     Sector of next catalog sector
      $0B     35    First file entry (7 entries at $0B, $2E, $51, $74, $97, $BA, $DD)

    Each file entry is 35 ($23) bytes:
      Offset  Size  Description
      ------  ----  -----------
      $00     1     Track of first T/S list sector (0 = deleted, $FF = never used)
      $01     1     Sector of first T/S list sector
      $02     1     File type + lock bit: bit 7 = locked, bits 0-6 = type
                    Types: 0=T(ext), 1=I(nteger BASIC), 2=A(pplesoft),
                           4=B(inary), 8=S(pecial), 16=R(elocatable),
                           32=a(new A), 64=b(new B)
      $03-$20 30    File name (high-ASCII, padded with spaces)
      $21-$22 2     File size in sectors (little-endian)

    Args:
        image: bytearray of the DSK image.
        vtoc: Pre-read VTOC dict (optional; will read from image if not provided).

    Returns:
        List of dicts, each with keys: name, type, locked, type_byte,
        size_sectors, ts_list_track, ts_list_sector.
    """
    if vtoc is None:
        vtoc = read_vtoc(image)

    files = []
    track = vtoc['catalog_track']
    sector = vtoc['catalog_sector']
    visited = set()  # Detect circular chains (corrupt disk protection)

    while track != 0 or sector != 0:
        # Guard against infinite loops from circular sector chains
        if (track, sector) in visited:
            break
        visited.add((track, sector))

        offset = (track * 16 + sector) * 256
        cat = image[offset:offset + 256]

        # Next catalog sector link (bytes 1-2)
        next_track = cat[1]
        next_sector = cat[2]

        # Each catalog sector holds 7 file entries, starting at offset $0B,
        # spaced $23 (35) bytes apart.
        for i in range(7):
            entry_offset = 0x0B + i * 0x23  # $0B, $2E, $51, $74, $97, $BA, $DD
            entry = cat[entry_offset:entry_offset + 0x23]

            ts_track = entry[0]   # Track of T/S list
            ts_sector = entry[1]  # Sector of T/S list
            # Track 0 = deleted file, $FF = never-used slot
            if ts_track == 0 or ts_track == 0xFF:
                continue

            file_type = entry[2]  # Bit 7 = locked, bits 0-6 = type code
            # File names are stored in high-ASCII (bit 7 set); strip it
            clean_name = ''.join(chr(c & 0x7F) for c in entry[3:33]).rstrip()
            file_size = struct.unpack_from('<H', entry, 33)[0]  # Sector count

            # Map type code to single-character abbreviation
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
    """Read a file's data by following its T/S (Track/Sector) list chain.

    Each file in DOS 3.3 has one or more T/S list sectors that contain an
    ordered list of (track, sector) pairs pointing to the file's data sectors.

    T/S list sector structure:
      Offset  Size  Description
      ------  ----  -----------
      $01     1     Track of next T/S list sector (0 = last)
      $02     1     Sector of next T/S list sector
      $0C-$FF 244   Up to 122 pairs of (track, sector) bytes, 2 bytes each.
                    A (0, 0) pair means "no data" (sparse file or end of file).

    Each T/S list can reference up to 122 data sectors (122 * 256 = 31,232
    bytes). Files larger than this require a chain of T/S list sectors.

    Args:
        image: bytearray of the DSK image.
        file_info: Dict from read_catalog() with ts_list_track and
            ts_list_sector keys.

    Returns:
        bytes containing the concatenated file data (may include trailing
        padding from the last partial sector).
    """
    data = bytearray()
    track = file_info['ts_list_track']
    sector = file_info['ts_list_sector']
    visited = set()  # Detect circular T/S list chains

    while track != 0 or sector != 0:
        if (track, sector) in visited:
            break
        visited.add((track, sector))

        offset = (track * 16 + sector) * 256
        ts_list = image[offset:offset + 256]

        # Link to next T/S list sector
        next_track = ts_list[1]
        next_sector = ts_list[2]

        # Read up to 122 T/S pairs starting at byte $0C
        for i in range(122):
            pair_offset = 0x0C + i * 2
            dt = ts_list[pair_offset]       # Data sector track
            ds = ts_list[pair_offset + 1]   # Data sector sector
            if dt == 0 and ds == 0:
                continue  # Empty slot (sparse file or end)
            data_offset = (dt * 16 + ds) * 256
            data.extend(image[data_offset:data_offset + 256])

        track = next_track
        sector = next_sector

    return bytes(data)


def create_bootable_dsk(binary, load_addr, entry_addr=None, volume=254):
    """Create a minimal bootable DOS 3.3 DSK with a BRUN-able binary.

    The binary is stored as a type-B (binary) file that can be loaded with
    BRUN from the DOS 3.3 command prompt. A minimal boot sector, VTOC,
    and catalog are created. The file is named "PROGRAM".

    The disk layout is:
      - Track 0, sector 0: Boot sector (left empty here; a real bootable
        disk would need DOS boot code).
      - Track 17, sector 0: VTOC
      - Track 17, sector 15: First (and only) catalog sector
      - Remaining sectors: T/S list(s) and file data, allocated from
        tracks 1-16 and 18-34 (avoiding track 0 and track 17).

    Binary file format (type B):
      The first 4 bytes of the file data are a header:
        Bytes 0-1: Load address (little-endian 16-bit)
        Bytes 2-3: Data length (little-endian 16-bit)
      Followed by the raw binary data.

    Args:
        binary: bytes of the program to store.
        load_addr: 16-bit memory address where the binary should be loaded.
        entry_addr: 16-bit entry point address (default: load_addr).
            Note: DOS 3.3 BRUN always enters at load_addr; this parameter
            is informational.
        volume: Disk volume number (default: 254, the standard default).

    Returns:
        140K DSK image as bytes (143,360 bytes).
    """
    if entry_addr is None:
        entry_addr = load_addr

    image = bytearray(35 * 16 * 256)  # 140K blank disk image

    # Build the binary file data: 4-byte header + raw binary
    file_data = bytearray()
    file_data += struct.pack('<H', load_addr)    # Load address
    file_data += struct.pack('<H', len(binary))  # Data length
    file_data += binary

    # Calculate how many sectors we need for the file data
    data_sectors_needed = (len(file_data) + 255) // 256
    # Each T/S list holds up to 122 data sector references
    ts_lists_needed = (data_sectors_needed + 121) // 122

    # Build list of available sectors, skipping track 0 (boot) and track 17
    # (VTOC/catalog). Sectors are allocated in descending order within each
    # track, matching DOS 3.3's allocation pattern.
    available = []
    for t in range(1, 35):
        if t == 17:
            continue  # Reserved for VTOC and catalog
        for s in range(15, -1, -1):
            available.append((t, s))

    # Allocate T/S list sectors first (they must be known before writing data)
    ts_sectors = []
    for _ in range(ts_lists_needed):
        ts_sectors.append(available.pop(0))

    # Then allocate data sectors
    data_ts_pairs = []
    for _ in range(data_sectors_needed):
        data_ts_pairs.append(available.pop(0))

    # Write file data into the allocated data sectors
    for i, (dt, ds) in enumerate(data_ts_pairs):
        offset = (dt * 16 + ds) * 256
        chunk_start = i * 256
        chunk = file_data[chunk_start:chunk_start + 256]
        image[offset:offset + len(chunk)] = chunk

    # Write T/S list sectors (each references up to 122 data sectors)
    pair_idx = 0
    for ts_idx, (tst, tss) in enumerate(ts_sectors):
        offset = (tst * 16 + tss) * 256
        ts_list = bytearray(256)

        # Link to next T/S list sector (if there is one)
        if ts_idx + 1 < len(ts_sectors):
            ts_list[1] = ts_sectors[ts_idx + 1][0]  # Next T/S list track
            ts_list[2] = ts_sectors[ts_idx + 1][1]  # Next T/S list sector

        # Fill in T/S pairs starting at byte $0C (12)
        for j in range(122):
            if pair_idx >= len(data_ts_pairs):
                break
            ts_list[0x0C + j * 2] = data_ts_pairs[pair_idx][0]      # Track
            ts_list[0x0C + j * 2 + 1] = data_ts_pairs[pair_idx][1]  # Sector
            pair_idx += 1

        image[offset:offset + 256] = ts_list

    # Write VTOC at track 17, sector 0
    vtoc_offset = 17 * 16 * 256  # Byte offset 69,632
    vtoc = bytearray(256)
    vtoc[1] = 17   # Catalog starts on track 17
    vtoc[2] = 15   # Catalog starts on sector 15
    vtoc[3] = 3    # DOS version 3 (for DOS 3.3)
    vtoc[6] = volume
    vtoc[0x27] = 122  # Max T/S pairs per T/S list sector
    vtoc[0x34] = 35   # 35 tracks per disk
    vtoc[0x35] = 16   # 16 sectors per track
    struct.pack_into('<H', vtoc, 0x38, 256)  # 256 bytes per sector

    # Build free sector bitmap in the VTOC.
    # The bitmap starts at offset $38 and has 4 bytes per track (35 tracks).
    # Each bit represents one sector: 1 = free, 0 = used.
    used_sectors = set()
    used_sectors.add((0, 0))   # Boot sector
    used_sectors.add((17, 0))  # VTOC
    used_sectors.add((17, 15)) # Catalog
    for t, s in ts_sectors:
        used_sectors.add((t, s))
    for t, s in data_ts_pairs:
        used_sectors.add((t, s))

    for t in range(35):
        bitmap_offset = 0x38 + t * 4
        bits = 0xFFFF  # Start with all 16 sectors free
        for s in range(16):
            if (t, s) in used_sectors:
                bits &= ~(1 << s)  # Clear bit to mark sector as used
        struct.pack_into('<H', vtoc, bitmap_offset, bits)

    image[vtoc_offset:vtoc_offset + 256] = vtoc

    # Write catalog sector at track 17, sector 15
    cat_offset = (17 * 16 + 15) * 256
    catalog = bytearray(256)
    # First (and only) file entry starts at byte $0B
    entry = bytearray(0x23)  # 35 bytes per entry
    entry[0] = ts_sectors[0][0]  # T/S list track
    entry[1] = ts_sectors[0][1]  # T/S list sector
    entry[2] = 0x84  # Type B (binary) + locked bit ($80)
    # File name: "PROGRAM" padded to 30 bytes with spaces, high-ASCII
    name = "PROGRAM"
    for i, ch in enumerate(name.ljust(30)):
        entry[3 + i] = ord(ch) | 0x80  # Set high bit for Apple II character set
    # File size in sectors (data sectors + T/S list sectors)
    struct.pack_into('<H', entry, 33, data_sectors_needed + ts_lists_needed)
    catalog[0x0B:0x0B + 0x23] = entry

    image[cat_offset:cat_offset + 256] = catalog

    return bytes(image)

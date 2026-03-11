"""
WOZ2 disk image parser.

Reads WOZ2 files and provides access to track bit streams and nibble data.
Handles bit-doubling for correct nibble conversion across track boundaries.
"""

import struct


class WOZFile:
    """Parse and access a WOZ2 disk image file."""

    def __init__(self, path):
        self.path = path
        self.info = {}
        self.tmap = None        # 160-byte quarter-track map
        self.track_entries = {}  # index -> {start_block, block_count, bit_count}
        self._data = None       # raw file bytes

        self._parse(path)

    def _parse(self, path):
        with open(path, 'rb') as f:
            self._data = f.read()

        data = self._data

        # Verify header
        magic = data[0:4]
        if magic != b'WOZ2':
            if data[0:4] == b'WOZ1':
                raise ValueError("WOZ1 format is not supported, only WOZ2")
            raise ValueError(f"Not a WOZ2 file (magic: {magic!r})")

        if data[4] != 0xFF:
            raise ValueError(f"Expected 0xFF at byte 4, got 0x{data[4]:02X}")

        # Parse INFO chunk (starts at offset 12)
        self.info = {
            'version': data[20],
            'disk_type': data[21],  # 1=5.25", 2=3.5"
            'write_protected': data[22],
            'synchronized': data[23],
            'cleaned': data[24],
            'creator': data[25:57].decode('ascii', errors='replace').strip(),
        }

        # Parse TMAP chunk (starts at offset 80)
        tmap_id = data[80:84]
        if tmap_id != b'TMAP':
            raise ValueError(f"Expected TMAP at offset 80, got {tmap_id!r}")
        self.tmap = data[88:88 + 160]

        # Parse TRKS chunk (starts at offset 248)
        trks_id = data[248:252]
        if trks_id != b'TRKS':
            raise ValueError(f"Expected TRKS at offset 248, got {trks_id!r}")

        # Track entries: 160 entries of 8 bytes each starting at offset 256
        for i in range(160):
            offset = 256 + i * 8
            sb = struct.unpack_from('<H', data, offset)[0]
            bc = struct.unpack_from('<H', data, offset + 2)[0]
            bit_count = struct.unpack_from('<I', data, offset + 4)[0]
            if sb == 0 and bc == 0:
                continue
            self.track_entries[i] = {
                'start_block': sb,
                'block_count': bc,
                'bit_count': bit_count,
            }

    @property
    def disk_type_str(self):
        return '5.25"' if self.info.get('disk_type') == 1 else '3.5"'

    def track_exists(self, track):
        """Check if a whole track number has data in the TMAP."""
        qt = track * 4
        if qt >= 160:
            return False
        tidx = self.tmap[qt]
        return tidx != 0xFF and tidx in self.track_entries

    def get_track_index(self, track):
        """Get the TRKS entry index for a whole track number."""
        qt = track * 4
        if qt >= 160:
            return None
        tidx = self.tmap[qt]
        if tidx == 0xFF or tidx not in self.track_entries:
            return None
        return tidx

    def get_track_data(self, track):
        """Get raw track bytes and bit count for a whole track number."""
        tidx = self.get_track_index(track)
        if tidx is None:
            return None, 0
        entry = self.track_entries[tidx]
        byte_offset = entry['start_block'] * 512
        byte_count = entry['block_count'] * 512
        return self._data[byte_offset:byte_offset + byte_count], entry['bit_count']

    def get_track_bits(self, track):
        """Get the raw bit stream for a track as a list of 0/1 values."""
        track_data, bit_count = self.get_track_data(track)
        if track_data is None:
            return []
        return _bytes_to_bits(track_data, bit_count)

    def get_track_nibbles(self, track, bit_double=True):
        """Convert a track's bit stream to nibbles.

        If bit_double is True (default), the bit stream is doubled before
        nibble conversion to correctly handle sectors that span the track
        boundary. This is essential for any WOZ file since the physical disk
        is circular but the bit stream has an arbitrary start point.
        """
        bits = self.get_track_bits(track)
        if not bits:
            return []
        if bit_double:
            bits = bits + bits
        return _bits_to_nibbles(bits)

    def get_qtrack_data(self, qtrack):
        """Get raw track bytes and bit count for a quarter-track."""
        if qtrack >= 160:
            return None, 0
        tidx = self.tmap[qtrack]
        if tidx == 0xFF or tidx not in self.track_entries:
            return None, 0
        entry = self.track_entries[tidx]
        byte_offset = entry['start_block'] * 512
        byte_count = entry['block_count'] * 512
        return self._data[byte_offset:byte_offset + byte_count], entry['bit_count']

    def track_count(self):
        """Return number of whole tracks that have data."""
        count = 0
        for t in range(40):
            if self.track_exists(t):
                count += 1
        return count

    def summary(self):
        """Return a multi-line summary string of the WOZ file."""
        lines = [
            f"WOZ2 file: {self.path}",
            f"  Disk type: {self.disk_type_str}",
            f"  Creator: {self.info.get('creator', 'unknown')}",
            f"  Version: {self.info.get('version', '?')}",
            f"  Synchronized: {self.info.get('synchronized', '?')}",
            f"  Write protected: {self.info.get('write_protected', '?')}",
            f"  Tracks with data: {self.track_count()}",
        ]
        return '\n'.join(lines)


def _bytes_to_bits(track_data, bit_count):
    """Convert byte array to bit stream, limited to bit_count bits."""
    bits = []
    for b in track_data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
            if len(bits) >= bit_count:
                return bits
    return bits


def _bits_to_nibbles(bits):
    """Convert bit stream to nibble stream.

    Apple II disk controller shifts bits in from the left,
    and a byte is complete when bit 7 is set.
    """
    nibbles = []
    current = 0
    for b in bits:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles

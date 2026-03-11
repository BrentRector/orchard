"""
WOZ disk nibble streaming for emulated disk I/O.

Provides the WOZDisk class that simulates the Disk II controller's
stepper motor and nibble read mechanism, suitable for use with the
CPU6502 emulator.
"""

from .woz import WOZFile, _bytes_to_bits, _bits_to_nibbles


class WOZDisk:
    """WOZ2 disk image with nibble streaming for emulated disk I/O.

    Converts track data to nibbles (with bit-doubling) and provides
    sequential nibble reads and stepper motor phase simulation.
    """

    def __init__(self, woz_or_path):
        """Initialize from a WOZFile object or a path string."""
        self.nibble_tracks = {}  # quarter-track -> [nibbles]
        self.current_qtrack = 0
        self.nibble_pos = 0
        self.motor_on = True
        self.phases = [False] * 4  # stepper motor phases
        self.data_latch = 0
        self.q6 = False   # Q6 state (False = data latch read)
        self.q7 = False   # Q7 state (False = read mode)

        if isinstance(woz_or_path, WOZFile):
            self._load_from_wozfile(woz_or_path)
        else:
            self._load_from_path(woz_or_path)

    def _load_from_path(self, path):
        """Parse WOZ file and build nibble tracks."""
        woz = WOZFile(path)
        self._load_from_wozfile(woz)

    def _load_from_wozfile(self, woz):
        """Build nibble tracks from a parsed WOZFile."""
        self.woz = woz
        for qt in range(160):
            tidx = woz.tmap[qt]
            if tidx == 0xFF or tidx not in woz.track_entries:
                continue
            track_data, bit_count = woz.get_qtrack_data(qt)
            if track_data is None:
                continue
            bits = _bytes_to_bits(track_data, bit_count)
            # Double the bit stream to handle sectors spanning the boundary
            double_bits = bits + bits
            self.nibble_tracks[qt] = _bits_to_nibbles(double_bits)

    def read_nibble(self):
        """Return next nibble from current track (called on Q6L read)."""
        if not self.motor_on:
            return 0x00
        qt = self.current_qtrack
        track = self.nibble_tracks.get(qt)
        if not track or len(track) == 0:
            return 0xFF
        nib = track[self.nibble_pos % len(track)]
        self.nibble_pos = (self.nibble_pos + 1) % len(track)
        return nib

    def step_phase(self, phase, on):
        """Handle stepper motor phase switch. Phases 0-3 control head position."""
        self.phases[phase] = on
        if not on:
            return
        # Determine direction based on which phase turned on relative to current
        current_phase = (self.current_qtrack // 2) % 4
        diff = (phase - current_phase + 4) % 4
        if diff == 1:
            self.current_qtrack = min(self.current_qtrack + 2, 159)
        elif diff == 3:
            self.current_qtrack = max(self.current_qtrack - 2, 0)
        elif diff == 2:
            pass  # half-track: don't move for now
        self.nibble_pos = 0  # reset position on track change

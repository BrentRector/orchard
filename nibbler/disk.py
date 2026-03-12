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
        self.trace_callback = None  # optional callback for I/O tracing
        self._recent_nibbles = []   # ring buffer for prolog detection

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

        # --- Prolog detection state machine (trace mode only) ---
        # Maintains a 3-nibble sliding window (_recent_nibbles) to detect
        # address and data field prologs in the stream as they pass.
        # This mirrors how the real Apple II boot ROM finds sectors:
        # it reads nibbles sequentially until a 3-byte prolog appears.
        #
        # Address prolog:  xx $AA $96  (6-and-2)  or  xx $AA $B5  (5+3)
        #   - First byte varies per protection scheme ($D5 is standard)
        # Data prolog:     $D5 $AA $AD  (both formats)
        if self.trace_callback:
            self._recent_nibbles.append(nib)
            if len(self._recent_nibbles) > 3:
                self._recent_nibbles.pop(0)
            if len(self._recent_nibbles) == 3:
                b0, b1, b2 = self._recent_nibbles
                # Detect known address prologs
                if b1 == 0xAA and b2 in (0x96, 0xB5):
                    self.trace_callback(
                        f"ADDR PROLOG ${b0:02X} ${b1:02X} ${b2:02X} "
                        f"at nibble {self.nibble_pos - 3} on track {qt // 4}")
                # Detect data prolog
                elif b0 == 0xD5 and b1 == 0xAA and b2 == 0xAD:
                    self.trace_callback(
                        f"DATA PROLOG $D5 $AA $AD "
                        f"at nibble {self.nibble_pos - 3} on track {qt // 4}")

        return nib

    def step_phase(self, phase, on):
        """Handle stepper motor phase switch. Phases 0-3 control head position."""
        self.phases[phase] = on
        if not on:
            return
        # --- Stepper motor phase calculation ---
        # The Disk II uses a 4-phase stepper motor.  Each whole track
        # corresponds to 4 quarter-track positions, and each phase
        # transition moves the head by 2 quarter-tracks (= one half-track).
        #
        # current_phase maps the current quarter-track position to the
        # expected active phase (0-3).  The diff tells us the relationship
        # between the newly activated phase and the current one:
        #
        #   diff == 1  ->  next phase in sequence  ->  step INWARD  (+2 qtracks)
        #   diff == 3  ->  previous phase          ->  step OUTWARD (-2 qtracks)
        #   diff == 2  ->  opposite phase          ->  half-track boundary, ignore
        #   diff == 0  ->  same phase re-activated ->  no movement (handled by
        #                  the early return above when on==False)
        old_qtrack = self.current_qtrack
        current_phase = (self.current_qtrack // 2) % 4
        diff = (phase - current_phase + 4) % 4
        if diff == 1:
            self.current_qtrack = min(self.current_qtrack + 2, 159)
        elif diff == 3:
            self.current_qtrack = max(self.current_qtrack - 2, 0)
        elif diff == 2:
            pass  # half-track: don't move for now

        if self.current_qtrack != old_qtrack:
            # Reset nibble position on track change so the controller starts
            # reading from the beginning of the new track's nibble stream.
            # This matches real hardware behavior where the head lands at an
            # arbitrary position, but for emulation starting at 0 is simplest.
            self.nibble_pos = 0
            self._recent_nibbles.clear()
            if self.trace_callback:
                self.trace_callback(
                    f"SEEK track {old_qtrack // 4} -> {self.current_qtrack // 4} "
                    f"(qtrack {old_qtrack} -> {self.current_qtrack})")

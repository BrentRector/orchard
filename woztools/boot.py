"""
Boot emulation framework for Apple II WOZ disk images.

Provides BootAnalyzer that sets up the standard P6 ROM boot environment,
runs the emulated CPU, and captures memory at configurable stop points.
"""

from .cpu import CPU6502
from .disk import WOZDisk
from .woz import WOZFile
from .gcr import ENCODE_62, DECODE_62


class BootAnalyzer:
    """Emulate the Apple II boot process from a WOZ disk image.

    Sets up the standard P6 Boot ROM environment:
    - Decodes the 6-and-2 boot sector from track 0
    - Loads it at $0800
    - Sets PC=$0801, X=slot*16, SP=$FD
    - Installs Monitor ROM stubs (RTS at IORTS, WAIT, etc.)
    - Runs the CPU with configurable stop conditions

    Usage:
        ba = BootAnalyzer("disk.woz")
        ba.setup_boot()
        result = ba.run(stop_at=0x4000)
        ba.save_snapshot("game.bin", 0x4000, 0xA800)
    """

    def __init__(self, woz_path, slot=6):
        self.woz_path = woz_path
        self.slot = slot
        self.woz = WOZFile(woz_path)
        self.disk = WOZDisk(self.woz)
        self.cpu = CPU6502(slot=slot)
        self.cpu.disk = self.disk
        self.event_log = []  # list of (exec_count, event_str)

    def setup_boot(self):
        """Set up the standard P6 ROM boot environment.

        Decodes the 6-and-2 boot sector, loads at $0800, and configures
        the CPU state as if the P6 Boot ROM just completed.
        """
        # Decode the 6-and-2 boot sector from track 0
        boot_data = self._decode_boot_sector()
        if boot_data is None:
            raise RuntimeError("Could not decode 6-and-2 boot sector from track 0")

        # Load at $0800
        for i, b in enumerate(boot_data):
            self.cpu.mem[0x0800 + i] = b

        # Monitor ROM stubs
        self.cpu.mem[0xFF58] = 0x60  # RTS (IORTS)
        self.cpu.mem[0xFCA8] = 0x60  # RTS (WAIT)
        self.cpu.mem[0xFF2D] = 0x60  # RTS (used by some boot code)

        # BRK/IRQ handler — halt at $0002
        self.cpu.mem[0xFFFE] = 0x02
        self.cpu.mem[0xFFFF] = 0x00
        self.cpu.mem[0x0002] = 0x02  # KIL

        # CPU state after P6 ROM boot
        self.cpu.pc = 0x0801
        self.cpu.x = self.slot * 16
        self.cpu.sp = 0xFD
        self.cpu.a = 0
        self.cpu.y = 0
        self.cpu.mem[0x2B] = self.slot * 16

        # Disk state
        self.disk.motor_on = True
        self.disk.current_qtrack = 0

        self._log(f"Boot setup complete, PC=$0801, X=${self.slot * 16:02X}")

    def run(self, max_instructions=200_000_000, stop_at=None,
            progress_interval=5_000_000):
        """Run the boot emulation.

        Args:
            max_instructions: limit on instructions to execute
            stop_at: PC address to stop at (e.g., 0x4000 for game entry)
            progress_interval: print progress every N instructions (0=quiet)

        Returns:
            str: reason for stopping ('stop_at', 'halt', 'breakpoint', 'limit')
        """
        return self.cpu.run(
            max_instructions=max_instructions,
            stop_at=stop_at,
            progress_interval=progress_interval
        )

    def dump_memory(self, start, end):
        """Return a bytes copy of memory from start to end."""
        return bytes(self.cpu.mem[start:end])

    def save_snapshot(self, path, start=0, end=65536):
        """Save a memory region to a binary file."""
        with open(path, 'wb') as f:
            f.write(self.cpu.mem[start:end])
        self._log(f"Saved ${start:04X}-${end - 1:04X} to {path}")

    def save_full_memory(self, path):
        """Save the entire 64K memory to a file."""
        self.save_snapshot(path, 0, 65536)

    def memory_summary(self):
        """Return a summary of non-zero memory pages."""
        lines = []
        for page in range(256):
            data = bytes(self.cpu.mem[page * 256:(page + 1) * 256])
            nonzero = sum(1 for b in data if b != 0)
            if nonzero > 16:
                lines.append(f"  ${page:02X}00: {nonzero:3d} non-zero bytes")
        return '\n'.join(lines)

    def _log(self, msg):
        self.event_log.append((self.cpu.exec_count, msg))

    def _decode_boot_sector(self):
        """Decode the 6-and-2 boot sector (sector 0) from track 0."""
        nibbles = self.woz.get_track_nibbles(0, bit_double=True)
        if not nibbles:
            return None

        # Search limit: first revolution only
        search_limit = len(nibbles) // 2 + 1000

        i = 0
        while i < search_limit - 20:
            if (nibbles[i] == 0xD5 and nibbles[i + 1] == 0xAA and
                    nibbles[i + 2] == 0x96):
                idx = i + 3
                if idx + 8 > len(nibbles):
                    break

                # Decode address field
                sec = ((nibbles[idx + 4] << 1) | 1) & nibbles[idx + 5]

                # Find data field
                for j in range(idx + 8, min(idx + 200, len(nibbles) - 350)):
                    if (nibbles[j] == 0xD5 and nibbles[j + 1] == 0xAA and
                            nibbles[j + 2] == 0xAD):
                        didx = j + 3

                        # Decode 6-and-2 data (342 encoded bytes)
                        encoded = []
                        valid = True
                        for k in range(342):
                            n = nibbles[didx + k]
                            if n not in DECODE_62:
                                valid = False
                                break
                            encoded.append(DECODE_62[n])

                        if not valid:
                            break

                        # ROM-exact decode
                        aux_buf = [0] * 86
                        xor_acc = 0
                        for k in range(86):
                            xor_acc ^= encoded[k]
                            aux_buf[85 - k] = xor_acc

                        pri_buf = [0] * 256
                        for k in range(256):
                            xor_acc ^= encoded[86 + k]
                            pri_buf[k] = xor_acc

                        # Post-decode with destructive LSR/ROL
                        result = bytearray(256)
                        x = 0x56
                        for y in range(256):
                            x -= 1
                            if x < 0:
                                x = 0x55
                            a = pri_buf[y]
                            carry = aux_buf[x] & 1
                            aux_buf[x] >>= 1
                            a = ((a << 1) | carry) & 0xFF
                            carry2 = aux_buf[x] & 1
                            aux_buf[x] >>= 1
                            a = ((a << 1) | carry2) & 0xFF
                            result[y] = a

                        if sec == 0:
                            return bytes(result)
                        break
                i += 1
            else:
                i += 1

        return None

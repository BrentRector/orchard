# nibbler Usage Guide

A Python toolkit for analyzing Apple II WOZ disk images. Scans for copy protection, emulates the boot process, extracts runtime binaries, decodes individual sectors, converts to DSK format, and disassembles 6502 code.

```
python -m nibbler <command> [arguments]
```

---

## Commands at a Glance

| Command   | Purpose                                           |
|-----------|---------------------------------------------------|
| `info`    | Show WOZ metadata, track map, half-track data     |
| `scan`    | Scan all tracks for encoding type and checksums    |
| `protect` | Detect copy protection techniques, generate report |
| `boot`    | Emulate boot process, capture memory at stop point |
| `decode`  | Decode a specific track/sector to hex dump or file |
| `dsk`     | Convert WOZ to standard 140K DSK image             |
| `disasm`  | Disassemble a binary file or memory dump           |

---

## info — WOZ Metadata

Shows the WOZ2 file header, disk type, creator tool, track bit counts, and any half/quarter-track data.

```
python -m nibbler info <woz_file>
```

**Example:**

```
$ python -m nibbler info "Apple Panic - Disk 1, Side A.woz"

WOZ2 file: Apple Panic - Disk 1, Side A.woz
  Disk type: 5.25"
  Creator: Applesauce v1.56.1
  Version: 2
  Synchronized: 1
  Write protected: 1
  Tracks with data: 14

Track map:
  Track  0:  51107 bits (13 blocks)
  Track  1:  51125 bits (13 blocks)
  ...
  Track 13:  51056 bits (13 blocks)

Half/quarter tracks: [1, 5, 6, 7, 9, ...]
```

**What to look for:**
- **Tracks with data** — standard DOS 3.3 uses 35 tracks; fewer tracks may indicate a custom loader
- **Half/quarter tracks** — data at non-standard positions is a copy protection indicator
- **Synchronized** — whether the WOZ capture was synchronized to the index hole

---

## scan — Track Encoding Scan

Scans each track for 6-and-2 (16-sector) and 5-and-3 (13-sector) encoded sectors. Reports encoding type, sector counts, and address/data checksum status. Automatically tries non-standard address prologs ($DE instead of $D5).

```
python -m nibbler scan <woz_file>
```

**Example:**

```
$ python -m nibbler scan "Apple Panic - Disk 1, Side A.woz"

Track    Encoding   6+2   5+3   Addr CK   Data CK  Notes
---------------------------------------------------------------------------
    0        dual     1    12     14/17        OK
    1         5+3     0     3       3/5        OK  addr=$DE,5+3
    7         5+3     0    15     16/17        OK  addr=$DE,5+3
```

**Columns:**
- **Encoding** — `6+2` (DOS 3.3 standard), `5+3` (13-sector), `dual` (both on same track), `???` (unrecognized)
- **6+2 / 5+3** — number of decoded sectors of each type
- **Addr CK** — `OK` if all address field checksums pass; `N/M` means N bad out of M total
- **Data CK** — same for data field checksums
- **Notes** — flags like `addr=$DE,5+3` mean non-standard address prolog was needed

**What to look for:**
- **`dual`** tracks have both formats — a known copy protection technique
- **Bad address checksums** — may be deliberate (protection) or indicate damage
- **Low sector counts** with `addr=$DE` — the disk uses non-standard markers
- **`???` encoding** — no recognizable sectors found; heavily protected or damaged

---

## protect — Copy Protection Analysis

Scans all tracks and generates a markdown report of detected copy protection techniques.

```
python -m nibbler protect <woz_file>
python -m nibbler protect <woz_file> -o report.md
```

**Options:**
- `-o FILE` — save the report to a file instead of printing to stdout

**Detected techniques:**
1. **Dual-Format Tracks** — both 6-and-2 and 5-and-3 on same track
2. **5-and-3 Encoding** — uncommon post-1980, incompatible with DOS 3.3 copiers
3. **Invalid Address Checksums** — deliberately wrong, defeats validating copiers
4. **Invalid Data Checksums** — sectors with bad data checksums
5. **Non-Standard Address Markers** — first byte other than $D5 (e.g., $DE)
6. **Half/Quarter Track Data** — data at non-standard positions
7. **Custom Address Field Third Byte** — per-track variations in prolog bytes
8. **Non-Standard Sector/Track Numbers** — address fields with out-of-range values

---

## boot — Boot Emulation

Emulates the Apple II boot process: loads the 6-and-2 boot sector from track 0, sets up the P6 ROM environment, and runs the 6502 CPU. You specify a stop address (where the game entry point is), and optionally dump or save memory.

```
python -m nibbler boot <woz_file> [options]
```

**Options:**
- `--stop ADDR` — stop when PC reaches this address (hex: `0x4000`, `$4000`, or `4000`)
- `--dump START-END` — hex dump a memory range on stop (e.g., `0x4000-0xA7FF`)
- `--save FILE` — save memory dump (or full 64K if no `--dump`) to binary file
- `--max-instructions N` — instruction limit (default 200,000,000)
- `--slot N` — disk controller slot (default 6)
- `-q` — suppress progress output

**Example — extract a game binary:**

```
$ python -m nibbler boot "disk.woz" --stop 0x4000 --dump 0x4000-0xA7FF --save game.bin

Booting disk.woz...
Will stop at $4000
  5,000,000 instructions, PC=$B97A
  10,000,000 instructions, PC=$B97A
  ...
Stopped: stop_at
Instructions: 69,813,247
Final PC: $4000
State: A=$00 X=$60 Y=$00 SP=$FD P=30 [------]

Memory $4000-$A7FF (26624 bytes):
  $4000: 4C 65 74 ...
Saved to game.bin
```

**How it works:**
1. Decodes the 6-and-2 boot sector (sector 0, track 0) and loads it at $0800
2. Sets PC=$0801, X=slot×16, SP=$FD (standard P6 ROM boot state)
3. Installs ROM stubs (RTS at $FF58/IORTS, $FCA8/WAIT, $FF2D)
4. Runs the CPU until `--stop` address is reached, a KIL opcode is hit, or the instruction limit is exceeded

**Tips:**
- If you don't know the stop address, run without `--stop` and check the non-zero memory summary to find where the game loaded
- The boot emulator handles all standard Disk II soft switches ($C0E0-$C0EF for slot 6)
- All 256 6502 opcodes are implemented, including 29 undocumented NMOS instructions

---

## decode — Decode Track/Sector

Decodes and hex-dumps individual sectors from a specific track. Tries both 6-and-2 and 5-and-3 encoding, including non-standard $DE address prologs.

```
python -m nibbler decode <woz_file> <track> [options]
```

**Options:**
- `--sector N` — decode only sector N (omit for all sectors on the track)
- `-o FILE` — save sector data to a binary file (requires `--sector`)

**Example — hex dump all sectors on track 0:**

```
$ python -m nibbler decode "disk.woz" 0

=== Track 0, Sector 0 (6+2, checksum: OK) ===
  $0000: 01 A5 27 C9 09 D0 ...
  ...

=== Track 0, Sector 1 (5+3, checksum: BAD) ===
  $0000: ...
```

**Example — extract a single sector to a file:**

```
$ python -m nibbler decode "disk.woz" 0 --sector 0 -o boot_sector.bin
```

---

## dsk — Convert to DSK

Converts a standard 6-and-2 encoded WOZ image to a 140K DSK file (the format used by most Apple II emulators). Only works for disks with standard 16-sector formatting.

Can also create a bootable DSK from a raw binary file.

```
python -m nibbler dsk <woz_file> [-o output.dsk]
python -m nibbler dsk --binary game.bin --load-addr 0x4000 --entry-addr 0x4000 [-o output.dsk]
```

**Options:**
- `-o FILE` — output DSK path (default: same name as input with `.dsk` extension)
- `--binary FILE` — create a bootable DSK from a binary file instead of converting WOZ
- `--load-addr ADDR` — load address for the binary (default $0800)
- `--entry-addr ADDR` — entry address / start of execution (default: same as load address)

**Example — convert a WOZ to DSK:**

```
$ python -m nibbler dsk "standard_disk.woz" -o output.dsk

Converting standard_disk.woz to DSK...
DSK image saved: output.dsk (143360 bytes)
```

**Example — create a bootable DSK from an extracted binary:**

```
$ python -m nibbler dsk --binary game.bin --load-addr 0x4000 --entry-addr 0x4000 -o game.dsk

Bootable DSK created: game.dsk
  Load address: $4000
  Entry address: $4000
  Binary size: 26624 bytes
```

**Note:** Copy-protected disks with non-standard encoding (5-and-3, custom markers, etc.) cannot be directly converted to DSK. Use `boot` to emulate the loader and extract the runtime binary, then use `dsk --binary` to create a bootable DSK from the extracted binary.

---

## disasm — 6502 Disassembler

Disassembles a binary file or memory dump as 6502 machine code. Supports both linear (sequential) and recursive descent (follows branches/jumps) modes.

```
python -m nibbler disasm <binary> [options]
```

**Options:**
- `--base ADDR` — base address where the binary loads in memory (default $0000)
- `--start ADDR` — start disassembly at this address (default: base)
- `--end ADDR` — stop disassembly at this address (default: end of file)
- `--entry ADDR` — entry point for recursive descent (default: start)
- `-r` — use recursive descent instead of linear disassembly

**Example — linear disassembly of a boot sector:**

```
$ python -m nibbler disasm boot_sector.bin --base 0x0800

$0800  00        BRK
$0801  A0 00     LDY #$00
$0803  B9 00 08  LDA $0800,Y
...
```

**Example — recursive descent from an entry point:**

```
$ python -m nibbler disasm game.bin --base 0x4000 --entry 0x4000 -r

$4000  L_4000          JMP $4065
...
$4065  ENTRY           LDA #$00
$4067                  STA $C050    ; GR/Text: set graphics mode
```

**Linear vs recursive descent:**
- **Linear** (`default`) — disassembles every byte sequentially. Fast and simple, but can't distinguish code from data. Best for small regions you know are all code.
- **Recursive** (`-r`) — follows execution flow from the entry point, tracing branches and JSR targets. Correctly identifies code vs data regions. Generates labels for branch targets and subroutines. Adds Apple II hardware register comments automatically.

---

## Module Reference

The `nibbler` package can also be used as a Python library:

```python
from nibbler.woz import WOZFile
from nibbler.gcr import find_sectors_62, find_sectors_53, scan_address_fields
from nibbler.cpu import CPU6502
from nibbler.disk import WOZDisk
from nibbler.boot import BootAnalyzer
from nibbler.analyze import CopyProtectionAnalyzer
from nibbler.dsk import woz_to_dsk, create_bootable_dsk
from nibbler.disasm import Disassembler, disassemble_region
```

| Module       | Key Classes / Functions                                      |
|--------------|--------------------------------------------------------------|
| `woz.py`     | `WOZFile` — parse WOZ2 header, TMAP, TRKS; get track nibbles with bit-doubling |
| `gcr.py`     | `find_sectors_62()`, `find_sectors_53()`, `scan_address_fields()`, `decode_sector_62()`, `decode_sector_53()`, GCR encode/decode tables |
| `cpu.py`     | `CPU6502` — full NMOS 6502 emulator (all 256 opcodes), breakpoint system, Disk II soft switch handling |
| `disk.py`    | `WOZDisk` — nibble streaming from WOZ bit streams, stepper motor simulation |
| `boot.py`    | `BootAnalyzer` — P6 ROM boot emulation, memory capture, snapshot saving |
| `analyze.py` | `CopyProtectionAnalyzer` — detect 8 protection techniques, generate markdown report |
| `dsk.py`     | `woz_to_dsk()`, `write_dsk()`, `create_bootable_dsk()`, DOS 3.3 VTOC/catalog reading |
| `disasm.py`  | `Disassembler` (recursive descent), `disassemble_region()` (linear), `OPCODES` table |

---

## Typical Workflow

### Investigating an unknown WOZ disk

```bash
# 1. What's on this disk?
python -m nibbler info disk.woz

# 2. What encoding and how many sectors?
python -m nibbler scan disk.woz

# 3. Any copy protection?
python -m nibbler protect disk.woz -o protection_report.md

# 4. Look at specific sectors
python -m nibbler decode disk.woz 0
python -m nibbler decode disk.woz 0 --sector 0 -o boot_sector.bin

# 5. Disassemble the boot sector
python -m nibbler disasm boot_sector.bin --base 0x0800
```

### Extracting a game binary

```bash
# 1. Boot-trace to find where the game loads
python -m nibbler boot disk.woz --stop 0x4000 --dump 0x4000-0xBFFF --save game.bin

# 2. Disassemble the extracted binary
python -m nibbler disasm game.bin --base 0x4000 --entry 0x4000 -r

# 3. Create a bootable DSK for use in emulators
python -m nibbler dsk --binary game.bin --load-addr 0x4000 --entry-addr 0x4000 -o game.dsk
```

### Converting a standard disk to DSK

```bash
# Only works for standard 6-and-2 (16-sector) disks
python -m nibbler dsk standard_disk.woz -o output.dsk
```

---

## Address Format

All hex address arguments accept three formats:
- `0x4000` (C-style)
- `$4000` (6502-style)
- `4000` (bare hex)

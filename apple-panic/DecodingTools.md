# Apple Panic Disk Decoding Tools

Documentation of all scripts and tools used to decode the Apple Panic disk.

---

## Primary/Active Scripts

### decode_track0.py
**Purpose**: Main decoder for track 0. Uses verified $02D1 algorithm + permutation mapping to correctly decode all 13 five-and-three sectors.
**Invocation**: `python decode_track0.py`
**Output**:
- Individual sector files in `E:/Apple/decoded_sectors/track00_secNN_mem.bin`
- Combined memory image `E:/Apple/decoded_sectors/track0_B600_BFFF.bin` ($B600-$BFFF)
- Hex dumps and disassembly to stdout

**Key functions**: `read_woz_nibbles()`, `build_53_gcr_table()`, `rwts_read()`, `decode_02D1()`, `permute_02D1_to_0346()`

### disasm_rwts.py
**Purpose**: Decodes the 6-and-2 boot sector and disassembles the RWTS code at $0200-$02FF. Also provides `OPCODES` dict and `disasm()` function used by other scripts.
**Invocation**: `python disasm_rwts.py`
**Output**: Hex dump and disassembly of the boot RWTS
**Imported by**: decode_track0.py, disasm_stage2.py

### disasm_stage2.py
**Purpose**: Simulates boot decode of 5-and-3 sector 0 to produce the stage 2 loader code at $0300-$03FF. Disassembles the stage 2 code.
**Invocation**: `python disasm_stage2.py`
**Output**: Hex dump and disassembly of stage 2 loader ($0300-$03FF)

### verify_checksum.py
**Purpose**: Verifies 5-and-3 data checksums using both original and corrupted GCR tables for all sectors.
**Invocation**: `python verify_checksum.py`
**Output**: Pass/fail status for each sector with both table variants

### scan_sector1.py
**Purpose**: Scans track 0 across multiple revolutions to find all address fields and verify sector 1's data consistency.
**Invocation**: `python scan_sector1.py`
**Output**: All D5 AA B5 address fields with vol/trk/sec/checksum, data checksum status for sectors 1 and 11

### compare_decoders.py
**Purpose**: Validates that $02D1+permutation produces the same output as direct $0346 decode for sector 2.
**Invocation**: `python compare_decoders.py`
**Output**: Byte-by-byte comparison showing they match (only byte 255 differs due to bit truncation in $02D1)

### boot_emulate.py
**Purpose**: Emulates the complete Apple Panic boot process using emu6502.py. Traces from boot sector through stage 2 sector loading to JMP $B700.
**Invocation**: `python boot_emulate.py`
**Output**:
- Milestone trace messages showing boot progress
- `E:/Apple/emu_boot_memory.bin` — Full 64K memory dump after boot
- `E:/Apple/emu_B600_BFFF.bin` — $B600-$BFFF region after boot
**Key behavior**: Runs WITHOUT checksum bypass — bit-doubled WOZ reader handles wrap correctly

### boot_emulate_full.py
**Purpose**: Full boot emulation from $0801 through JMP $B700 through all track reads to JMP $4000 (game entry).
**Invocation**: `python boot_emulate_full.py`
**Output**:
- `E:/Apple/emu_full_boot_memory.bin` — Complete 64K memory after boot
- `E:/Apple/emu_game_4000_A7FF.bin` — Game code $4000-$A7FF
- `E:/Apple/emu_full_boot_B600.bin` — $B600-$BFFF after boot
- `E:/Apple/emu_tracks1_5.bin` — $0800-$48FF (intermediate code from tracks 1-5)
- `E:/Apple/emu_0800_3FFF.bin` — $0800-$3FFF after boot
**Runtime**: ~70M instructions, takes a few minutes

### check_wrap.py
**Purpose**: Diagnostic script that proves the bit-doubling fix for sector 1. Compares single-revolution vs doubled-bit-stream nibble conversion.
**Invocation**: `python check_wrap.py`
**Output**: Shows 189/256 bytes differ between methods for sector 1, saves correct decode to `decoded_sectors/track00_sec01_wrap_fixed.bin`

---

## Analysis/Debug Scripts

### debug_decode.py
**Purpose**: Detailed debugging of RWTS intermediate values with both original and corrupted tables.
**Invocation**: `python debug_decode.py`

### decode_all_sectors.py
**Purpose**: Early attempt at direct $0346 decode. Had carry handling bugs. Superseded by decode_track0.py.
**Status**: Historical - do not use

### boot_rom_decode.py
**Purpose**: Analyzes the P6 Boot ROM (Disk II 341-0027) sector read process.
**Invocation**: `python boot_rom_decode.py`

### emu6502.py
**Purpose**: General-purpose 6502 CPU emulator for running Apple II code.
**Invocation**: Imported by other scripts, not typically run standalone.

---

## WOZ Analysis Scripts (earlier exploration)

### WOZ format analysis and boot process
- **woz_analyze.py** — WOZ format analysis
- **woz_analyze_boot.py** — Boot process analysis within WOZ images
- **woz_boot.py** — Boot sequence investigation
- **woz_boot2.py** — Secondary boot sequence investigation
- **woz_boot_check.py** — Boot process verification

### 5-and-3 GCR decoding experiments
- **woz_53boot.py** — 5-and-3 boot sector decoding
- **woz_53brute.py** — Brute-force 5-and-3 GCR table search
- **woz_53calibrate.py** — GCR table calibration
- **woz_53decode.py** — 5-and-3 sector decoding
- **woz_53_variants.py** — GCR table variant exploration
- **woz_p5a_decode.py** — Phase 5A decode experiments
- **woz_p5a_test.py** — Phase 5A decode testing

### 6-and-2 GCR verification
- **woz_62compare.py** — 6-and-2 decode comparison
- **woz_62debug.py** — 6-and-2 decode debugging
- **woz_62fix.py** — 6-and-2 decode fixes
- **woz_62verify.py** — 6-and-2 decode verification

### General WOZ utilities
- **woz_compare.py** — WOZ image comparison
- **woz_decode.py** — General WOZ decoding
- **woz_deep.py** — Deep WOZ format analysis
- **woz_disasm_boot.py** — WOZ boot sector disassembly
- **woz_reader.py** — WOZ file reader
- **woz_sectors.py** — WOZ sector scanning

---

## Other Utilities

### disassemble.py
**Purpose**: General-purpose 6502 disassembler.
**Invocation**: `python disassemble.py <binary_file> [base_address]`

### build_runtime.py
**Purpose**: Builds runtime binary from decoded components.

### check_dsk.py
**Purpose**: DSK image analysis utility.

---

## Key Data Files

- `Apple Panic - Disk 1, Side A.woz` — Original protected WOZ2 disk image
- `ApplePanic_runtime.bin` — Runtime memory image ($0000-$A7FF, 43008 bytes, extracted via boot emulation)
- `DiskII_BootROM.md` — P6 Boot ROM documentation
- `decoded_sectors/` — Decoded binary sector data from track 0

---

## Typical Workflow

1. Start with `disasm_rwts.py` to understand the boot RWTS at $0200
2. Run `disasm_stage2.py` to see the stage 2 loader at $0300
3. Run `verify_checksum.py` to check which sectors have valid checksums
4. Run `decode_track0.py` to decode all sectors and produce the memory image
5. Use `scan_sector1.py` to investigate problematic sectors
6. Use `compare_decoders.py` to validate decode algorithm equivalence

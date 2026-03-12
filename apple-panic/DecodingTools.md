# Apple Panic Disk Decoding Tools

Documentation of all scripts and tools used to decode the Apple Panic disk. For the full script catalog, see [`scripts/README.md`](../scripts/README.md). For a guided walkthrough showing when and why each tool is used, see [Walkthrough.md](Walkthrough.md).

Scripts use repo-relative default paths and work out of the box. Pipeline scripts accept CLI arguments (e.g., `--woz`, `--output-dir`) to override defaults.

---

## Reusable Toolkit: nibbler

The [`nibbler`](../nibbler/) package is the reusable successor to the investigation scripts. It works on any WOZ2 disk image, not just Apple Panic.

```bash
python -m nibbler scan "Apple Panic - Disk 1, Side A.woz"
python -m nibbler protect "Apple Panic - Disk 1, Side A.woz"
python -m nibbler boot "Apple Panic - Disk 1, Side A.woz" --stop 0x4000 --save game.bin
```

See [`nibbler/USAGE.md`](../nibbler/USAGE.md) for full documentation.

---

## Final Pipeline Scripts

These scripts implement the final, verified decode pipeline. Run them in order to reproduce the full reverse engineering result.

### disasm_rwts.py

**Purpose**: Decode the 6-and-2 boot sector from the WOZ image using the ROM-exact algorithm, then disassemble it as RWTS code at $0200-$02FF. The boot sector is initially loaded at $0800 by the P6 ROM, then self-relocates to $0200 where it serves as the disk RWTS for loading subsequent 5-and-3 sectors. Also provides a reusable `disasm()` function and `OPCODES` table imported by other scripts.

**Invocation**: `python scripts/disasm_rwts.py [--woz PATH]`
**Output**: Boot sector hex dump at $0200-$02FF, full 6502 disassembly, and a summary of all JMP/JSR/JMP-indirect targets.
**Imported by**: `decode_track0.py`, `disasm_stage2.py`, `decode_all_sectors.py`, `check_wrap.py`

### disasm_stage2.py

**Purpose**: Simulate the $02D1 post-decode of 5-and-3 sector 0 to produce stage 2 loader code at $0300-$03FF. The RWTS reads sector 0, applies the $02D1 post-decode, then JMPs to $0301. The stage 2 code corrupts the GCR table (ASL x3) and enters a sector-loading loop that reads sectors 0-9 into $B600-$BFFF using the $0346 post-decode.

**Invocation**: `python scripts/disasm_stage2.py [--woz PATH]`
**Output**: Hex dump of $0300-$03FF, disassembly of stage 2 code at $0301-$0345, the $0346 post-decode routine, and the sector loading loop at $0327-$033F.

### decode_track0.py

**Purpose**: Final, correct decoder for Track 0. Decodes all 13 five-and-three sectors using the verified $02D1 algorithm with bit-doubling for proper wrap handling, then applies the $0346 permutation mapping to produce the correct memory layout. The two post-decode routines ($02D1 and $0346) produce the same 256 byte values in different order; the permutation maps between them.

**Invocation**: `python scripts/decode_track0.py [--woz PATH] [--output-dir DIR]`
**Output**:
- Per-sector hex dumps with checksum status and disassembly of code-like sectors
- Individual `.bin` files per sector in the output directory
- Combined `track0_B600_BFFF.bin` memory image ($B600-$BFFF)
- Verification that sector 0 matches known stage 2 code

**Key functions**: `read_woz_nibbles()`, `build_53_gcr_table()`, `rwts_read()`, `decode_02D1()`, `permute_02D1_to_0346()`

### boot_emulate.py

**Purpose**: Emulate the Apple Panic boot process through stage 1 using emu6502.py. Traces from the 6-and-2 boot sector at $0801 through stage 2, loading 5-and-3 sectors 0-9 into $B600-$BFFF, until JMP $B700. Detects key milestones (code relocation, GCR table corruption, sector reads, checksum failures).

**Invocation**: `python scripts/boot_emulate.py [--woz PATH] [--output-dir DIR]`
**Output**:
- Milestone trace messages showing boot progress
- `emu_boot_memory.bin` — Full 64K memory dump
- `emu_B600_BFFF.bin` — $B600-$BFFF region
**Key behavior**: Runs WITHOUT checksum bypass — bit-doubled WOZ reader handles wrap correctly. Stops at JMP $B700 or after 10M instructions / 100 checksum failures.

### boot_emulate_full.py

**Purpose**: Full boot emulation from $0801 through all five boot stages to JMP $4000 (game entry). Traces ~70M instructions through: P6 ROM boot → RWTS relocation → stage 2 → game loader at $B700 → tracks 1-5 → title screen at $1000 → tracks 6-13 → game entry at $4000.

**Invocation**: `python scripts/boot_emulate_full.py [--woz PATH] [--output-dir DIR]`
**Output**:
- `emu_full_boot_memory.bin` — Complete 64K memory at game entry
- `emu_game_4000_A7FF.bin` — Game code ($4000-$A7FF, 26,624 bytes)
- `emu_full_boot_B600.bin` — $B600-$BFFF after boot
- `emu_tracks1_5.bin` — $0800-$48FF (intermediate code from tracks 1-5)
- Detailed milestone trace messages for each boot stage

**Runtime**: ~70M instructions, takes a few minutes.

### build_runtime.py

**Purpose**: Build the clean runtime memory image from the raw boot emulation output. Simulates the relocation copy loops at $1900 that move memory regions to their final runtime locations, then applies cleanups to produce a canonical image.

**Invocation**: `python scripts/build_runtime.py [--input PATH] [--output PATH]`
**Output**: 43,008-byte runtime image ($0000-$A7FF) and a build summary showing copy-loop operations, cleanup regions, and MD5 hash.

### disassemble.py

**Purpose**: Generate a complete Merlin32-syntax assembly source file from the runtime memory image using recursive descent. Includes 200+ descriptive label names, automatic hardware register comments, Apple II ROM call annotations, and sprite/level data table formatting.

**Invocation**: `python scripts/disassemble.py [--input PATH] [--output PATH]`
**Output**: ~8,800-line .asm file with 104 subroutines, organized into sections (pre-game data, main game code, clean loader).

---

## Verification Scripts

These scripts validate specific aspects of the decode process.

### verify_checksum.py

**Purpose**: Test 5-and-3 sector checksums with both the original GCR table and the corrupted table (ASL x3 on entries $99-$FF) to determine which table the disk was written with. Also simulates the exact boot code read algorithm to test self-modifying behavior.

**Invocation**: `python scripts/verify_checksum.py`
**Output**: GCR table comparison, per-sector checksum results with both tables, boot-code-exact simulation results.

### compare_decoders.py

**Purpose**: Verify that applying $02D1 post-decode followed by the permutation mapping produces the same result as the direct $0346 post-decode. Also validates that corrupted GCR table values are exactly the originals shifted left by 3.

**Invocation**: `python scripts/compare_decoders.py`
**Output**: Byte-by-byte comparison (match except byte 255 due to bit truncation in $02D1).

### check_wrap.py

**Purpose**: Prove that sector 1's data spans the track wrap boundary. Compares single-revolution vs bit-doubled nibble extraction, showing exactly how many bytes differ and whether the wrap-fixed version produces valid code.

**Invocation**: `python scripts/check_wrap.py`
**Output**: Diff count (189/256 bytes differ), checksum validation, and saved wrap-fixed decode.

### scan_sector1.py

**Purpose**: Scan Track 0 across 3 revolutions to find ALL occurrences of sector 1 (and sector 11) address/data fields. Checks data consistency across revolutions and checksums with both GCR tables.

**Invocation**: `python scripts/scan_sector1.py`
**Output**: All D5 AA B5 address fields across 3 revolutions, data field checksums, occurrence counts, byte-level cross-revolution comparison.

### woz_62verify.py

**Purpose**: Verify the corrected 6-and-2 decode algorithm (reversed aux, group-of-3 bit packing) against the known-good .dsk file. A 256/256 byte match confirms correctness.

**Invocation**: `python scripts/woz_62verify.py`
**Output**: "PERFECT MATCH!" and hex dump of verified boot sector.

### woz_62compare.py

**Purpose**: Compare naive 6-and-2 decode from WOZ against .dsk file to identify decode errors. Analyzes whether mismatches are in low 2 bits (aux-byte errors) or upper bits.

**Invocation**: `python scripts/woz_62compare.py`
**Output**: Match count, differing byte positions, cross-sector search.

---

## Exploration Scripts

### WOZ Format Analysis

| Script | Purpose |
|--------|---------|
| **woz_reader.py** | WOZ2 reader, 6-and-2 decode, .dsk extraction, DOS 3.3 catalog reading. First tool written. |
| **woz_analyze.py** | Scan tracks for standard/custom prologs, decode address fields, D5-follower frequency analysis. |
| **woz_deep.py** | 8-section deep analysis: disk structure, per-track prologs, boot sector, sync bytes, epilogs, sector ordering. |
| **woz_decode.py** | Decode 14-track/13-sector format with custom D5 xx B5 prologs. Early 6-and-2 attempt (before 5-and-3 was identified). |
| **woz_sectors.py** | Decode ALL address fields across 14 tracks, build ordered image, search for game code (including XOR $24). |
| **woz_compare.py** | Search WOZ data for game patterns: direct match, XOR, short-pattern, per-byte key, sector-level comparison. |
| **check_dsk.py** | Analyze .dsk file: VTOC, catalog, Track 0 layout, boot sector signature analysis. |

### Boot Process Investigation

| Script | Purpose |
|--------|---------|
| **woz_boot.py** | Disassemble boot sector from raw dump, search for game code, per-track byte frequency analysis. |
| **woz_boot2.py** | Find real boot sector (D5 AA B5 not D5 AA 96 trap), decode both 6+2 and 5+3 for comparison. |
| **woz_boot_check.py** | Scan all address fields on Track 0, decode data for both encoding formats. |
| **woz_disasm_boot.py** | Standalone boot sector disassembly (hardcoded bytes, both Autostart and Integer ROM entry points). |
| **woz_analyze_boot.py** | Decode Track 0 sectors, disassemble code sectors, map JMP/JSR cross-references, full RWTS disassembly. |

### 5-and-3 GCR Decoding

| Script | Purpose |
|--------|---------|
| **woz_53decode.py** | Try 3 byte-reconstruction variants (v1, v2, v3) against cracked image. First 5-and-3 attempt. |
| **woz_53calibrate.py** | Systematic: try ALL combinations of buffer direction (fwd/rev) and bit-packing order (MSB/LSB). |
| **woz_53brute.py** | Brute-force: raw bit concatenation, P5A layouts, interleaved secondary, XOR key analysis. |
| **woz_53_variants.py** | Test 8 decode variants: continuous/split XOR × forward/reverse secondary × primary-first layout. |
| **woz_p5a_decode.py** | Correct P5A ROM algorithm (from Apple-II-Disk-Tools source). **This is the one that works.** |
| **woz_p5a_test.py** | Quick comparison of forward vs reversed secondary ordering with P5A algorithm. |
| **woz_53boot.py** | Decode Track 0 with 5-and-3, analyze P5A boot flow (sector count in byte 0), compare against cracked image. |

### 6-and-2 GCR Verification

| Script | Purpose |
|--------|---------|
| **woz_62fix.py** | Compare 5 reconstruction methods to find the correct one. Boot ROM exact vs naive vs 3-group packing. |
| **woz_62debug.py** | Trace every decode step: WOZ2 header, TMAP, nibbles, GCR, XOR chain, multiple reconstruction methods. |
| **boot_rom_decode.py** | Implement 5 methods (A-E) including cycle-accurate P6 ROM simulation. Method E matches. |

### Debug and Diagnostic

| Script | Purpose |
|--------|---------|
| **debug_decode.py** | Inspect intermediate decode values with original vs corrupted GCR tables. Verify $02D1 and $0346 post-decode. |
| **decode_all_sectors.py** | Early $0346 decode attempt (had carry bugs). **Superseded by decode_track0.py.** |
| **emu6502.py** | 6502 CPU emulator + WOZ disk reader. Library imported by boot_emulate scripts. |

---

## Key Data Files

| File | Description |
|------|-------------|
| `Apple Panic - Disk 1, Side A.woz` | Original copy-protected WOZ2 disk image (Applesauce capture) |
| `ApplePanic_runtime.bin` | Runtime memory image ($0000-$A7FF, 43,008 bytes, from boot emulation) |
| `ApplePanic_original.dsk` | Standard .dsk conversion (6-and-2 sectors only) |

---

## Typical Workflow

### Understanding the boot process
1. `disasm_rwts.py` — see the boot RWTS at $0200
2. `disasm_stage2.py` — see the stage 2 loader at $0300
3. `verify_checksum.py` — confirm which sectors have valid checksums and with which GCR table
4. `decode_track0.py` — decode all Track 0 sectors and produce the $B600-$BFFF memory image

### Reproducing the full boot
1. `boot_emulate_full.py` — emulate all ~70M instructions from power-on to game entry
2. `build_runtime.py` — apply relocation copy loops to produce clean runtime image
3. `disassemble.py` — generate full Merlin32 assembly source

### Validating the decode
1. `compare_decoders.py` — verify $02D1+permutation ≡ $0346
2. `check_wrap.py` — verify bit-doubling fix for sector 1
3. `scan_sector1.py` — verify sector data consistency across revolutions
4. `woz_62verify.py` — verify 6-and-2 decode matches .dsk file

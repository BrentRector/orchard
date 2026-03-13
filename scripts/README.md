# Investigation Scripts

The 39 Python scripts in this directory were written during the reverse engineering of the Apple Panic WOZ disk image. Each script represents a specific question that was asked and answered (or abandoned) during the investigation.

The pipeline and verification scripts implement decoders for specific copy protection techniques — GCR table corruption, post-decode permutations, self-modifying boot loaders, per-track prolog variations — that are not unique to Apple Panic. These techniques are characteristic of a protection scheme that may appear on other titles from the same era or publisher. The scripts are reusable against any disk using the same protection techniques.

These are working artifacts, not polished tools. They are preserved to document the investigative process.

For the reusable toolkit, see [`nibbler/`](../nibbler/). For a guided walkthrough showing when and why each script is used, see [`apple-panic/Walkthrough.md`](../apple-panic/Walkthrough.md).

---

## How to Use

All scripts are run with:

```
python scripts/<script_name>.py
```

Scripts use repo-relative default paths (derived from each script's location), so they work out of the box when the WOZ and DSK files are in `apple-panic/`. The 7 pipeline scripts also accept CLI arguments (e.g., `--woz`, `--output-dir`) to override defaults.

Script output goes to `apple-panic/output/` (gitignored), created automatically on first use.

Many scripts import from each other (e.g., `decode_track0.py` imports from `disasm_rwts.py`). These imports use `sys.path` manipulation to find sibling scripts.

---

## Script Categories

### Final Pipeline Scripts

These scripts implement the final, verified decode pipeline for Apple Panic. Run them in order to reproduce the full reverse engineering result.

| Script | Purpose | Output |
|--------|---------|--------|
| **disasm_rwts.py** | Decode 6-and-2 boot sector, disassemble RWTS at $0200-$02FF. Also provides `OPCODES` and `disasm()` used by other scripts. | Boot sector hex dump and disassembly |
| **disasm_stage2.py** | Simulate $02D1 post-decode of sector 0, disassemble stage 2 code at $0300-$03FF. | Stage 2 loader disassembly |
| **decode_track0.py** | Decode all 13 sectors from Track 0 using verified $02D1 + permutation. Final correct decoder. | Per-sector .bin files, combined $B600-$BFFF image |
| **boot_emulate.py** | Emulate boot from $0801 through stage 2 sector loading to JMP $B700. | 64K memory dump, $B600-$BFFF region |
| **boot_emulate_full.py** | Full boot from $0801 through all track reads to JMP $4000 (game entry). ~70M instructions. | 64K memory, game binary $4000-$A7FF, intermediate dumps |
| **build_runtime.py** | Build clean runtime memory image by simulating relocation copy loops. | 43,008-byte runtime image ($0000-$A7FF) |
| **disassemble.py** | Generate full Merlin32-syntax assembly source from runtime image using recursive descent. | .asm file (~8,800 lines, 104 subroutines) |
| **render_sprites.py** | Render player, enemy, font, and platform sprites from runtime image as PNGs. | `apple-panic/assets/*.png` (6 images) |
| **woz_flux_image.py** | Render magnetic flux patterns as a top-down grayscale disk surface image. Wrapper around `nibbler flux`. | `apple-panic/flux_image.png` |

### Verification Scripts

These scripts verify specific aspects of the decode process.

| Script | Purpose | Output |
|--------|---------|--------|
| **verify_checksum.py** | Test checksums with original vs corrupted GCR tables to confirm copy protection nature. | Per-sector pass/fail with both table variants |
| **compare_decoders.py** | Verify $02D1+permutation produces same output as $0346 decode. | Byte-by-byte comparison (match except byte 255) |
| **check_wrap.py** | Prove bit-doubling fix for sector 1 wrap-around. | Diff count between naive and wrap-fixed decodes |
| **scan_sector1.py** | Scan for all sector 1/11 occurrences across revolutions, verify consistency. | Address field list, cross-revolution data comparison |
| **woz_62verify.py** | Verify 6-and-2 decode against .dsk file (correct algorithm: reversed aux, 3-group packing). | PERFECT MATCH or byte-level diff |
| **woz_62compare.py** | Compare WOZ 6-and-2 decode against .dsk file (naive algorithm). | Match count and diff analysis |

### Exploration Scripts — WOZ Format and Boot Process

Early investigation scripts for understanding the disk format and boot sequence.

| Script | Purpose |
|--------|---------|
| **woz_reader.py** | WOZ2 reader, 6-and-2 decode, DOS 3.3 catalog extraction. First tool written. |
| **woz_analyze.py** | Scan tracks for standard/custom prologs, decode address fields, frequency analysis. |
| **woz_deep.py** | 8-section deep analysis: structure, per-track prologs, boot sector, sync bytes, epilogs. |
| **woz_boot.py** | Disassemble boot sector from raw sector dump, search for game code patterns. |
| **woz_boot2.py** | Find the REAL boot sector (D5 AA B5, not D5 AA 96 trap), decode both for comparison. |
| **woz_boot_check.py** | Scan all address fields on Track 0, decode data for both 6+2 and 5+3 formats. |
| **woz_disasm_boot.py** | Standalone disassembly of the boot sector (hardcoded bytes, no WOZ dependency). |
| **woz_sectors.py** | Decode ALL address fields across 14 tracks, build ordered sector image, search for game code. |
| **woz_compare.py** | Search WOZ data for known game patterns: direct, XOR, short-pattern, per-byte key analysis. |
| **woz_decode.py** | Decode the custom 14-track/13-sector format with non-standard prologs (6-and-2 attempt). |
| **woz_analyze_boot.py** | Decode Track 0 sectors, disassemble code-like ones, map JMP/JSR cross-references. Sector 3 = custom RWTS. |
| **check_dsk.py** | Analyze .dsk file: VTOC, catalog, Track 0 layout, boot signature. |

### Exploration Scripts — 5-and-3 GCR Decoding

These scripts systematically worked through the 5-and-3 byte reconstruction problem.

| Script | Purpose |
|--------|---------|
| **woz_53decode.py** | Try 3 byte-reconstruction variants against cracked image. First 5-and-3 attempt. |
| **woz_53calibrate.py** | Try ALL combinations of buffer direction and bit-packing order. Systematic search. |
| **woz_53brute.py** | Brute-force: raw bit concatenation, interleaved secondary, XOR key analysis. |
| **woz_53_variants.py** | Test 8 decode variants (continuous/split XOR, forward/reverse secondary, primary-first layout). |
| **woz_p5a_decode.py** | Correct P5A ROM algorithm (from Apple-II-Disk-Tools source). The one that works. |
| **woz_p5a_test.py** | Quick comparison of forward vs reversed secondary ordering with P5A algorithm. |
| **woz_53boot.py** | Decode Track 0 with 5-and-3, analyze P5A boot flow (sector count in byte 0). |

### Exploration Scripts — 6-and-2 GCR Verification

These scripts debugged the 6-and-2 decode (needed for the boot sector).

| Script | Purpose |
|--------|---------|
| **woz_62fix.py** | Compare 5 different reconstruction methods (A-E) to find the correct one. |
| **woz_62debug.py** | Trace every decode step: header, TMAP, nibbles, GCR, XOR chain, reconstruction. |
| **boot_rom_decode.py** | Implement 5 methods (A-E) including cycle-accurate ROM simulation. Method E matches. |

### Debug and Diagnostic Scripts

| Script | Purpose |
|--------|---------|
| **debug_decode.py** | Inspect intermediate decode values with original vs corrupted GCR tables. |
| **decode_all_sectors.py** | Early $0346 decode attempt (had carry bugs). Superseded by decode_track0.py. |
| **emu6502.py** | General-purpose 6502 emulator + WOZ disk reader. Library used by boot_emulate scripts. |

---

## Dependency Graph

```
disasm_rwts.py  <── decode_track0.py
                <── disasm_stage2.py
                <── decode_all_sectors.py
                <── check_wrap.py

emu6502.py      <── boot_emulate.py
                <── boot_emulate_full.py

build_runtime.py ── (reads boot_emulate_full.py output)
                 └──> disassemble.py (reads build_runtime.py output)
                 └──> render_sprites.py (reads build_runtime.py output)
```

---

## Investigation Timeline

The scripts roughly follow this investigation order:

1. **Format discovery:** `woz_reader.py` → `woz_analyze.py` → `woz_deep.py`
2. **Boot sector:** `woz_boot.py` → `woz_boot2.py` → `woz_disasm_boot.py`
3. **6-and-2 decode:** `woz_62debug.py` → `woz_62fix.py` → `boot_rom_decode.py` → `woz_62verify.py`
4. **5-and-3 decode:** `woz_53decode.py` → `woz_53calibrate.py` → `woz_53brute.py` → `woz_53_variants.py` → `woz_p5a_decode.py`
5. **Sector analysis:** `woz_sectors.py` → `woz_analyze_boot.py` → `disasm_rwts.py` → `disasm_stage2.py`
6. **Checksum/integrity:** `verify_checksum.py` → `scan_sector1.py` → `check_wrap.py`
7. **Final decode:** `decode_track0.py` → `compare_decoders.py`
8. **Boot emulation:** `emu6502.py` → `boot_emulate.py` → `boot_emulate_full.py`
9. **Game extraction:** `build_runtime.py` → `disassemble.py`
10. **Asset rendering:** `render_sprites.py`

# Reverse Engineering a Copy-Protected Apple II Disk

*A step-by-step walkthrough using Apple Panic as the example.*

This walkthrough follows the logical chain of discovery when reverse engineering a copy-protected Apple II floppy disk. Each step starts from what the previous step revealed — nothing is assumed beyond what you've already found. The tools used are [nibbler](../nibbler/) (a general-purpose WOZ2 analysis toolkit) and a set of [investigation scripts](../scripts/) that implement decoders for specific protection techniques. These techniques are not unique to Apple Panic — they are characteristic of a protection scheme that may appear on other titles from the same era or publisher.

For the full narrative of the actual investigation (including dead ends and breakthroughs), see [ReverseEngineeringHistory.md](ReverseEngineeringHistory.md). For the technical reference on each protection layer, see [CopyProtection.md](CopyProtection.md). For detailed per-script documentation, see [DecodingTools.md](DecodingTools.md).

---

## 1. Starting Point

**What you know:** You have a `.woz` file — a flux-level capture of an Apple II floppy disk. The only guaranteed fact about any Apple II disk is that the Disk II controller's P6 Boot ROM reads track 0, sector 0 in 6-and-2 GCR encoding, loads it to `$0800`, and transfers control to `$0801`. Everything after that is up to the software on the disk.

**Goal:** Extract the game as a fully commented assembly source, understanding every byte between the magnetic surface and `JMP $4000`.

---

## 2. Survey the Disk

**What you know so far:** You have a WOZ file and the boot ROM entry point.

**Commands:**

```bash
python -m nibbler info "apple-panic/Apple Panic - Disk 1, Side A.woz"
python -m nibbler scan "apple-panic/Apple Panic - Disk 1, Side A.woz"
```

`nibbler info` shows the WOZ2 metadata and track map — which tracks contain data and how many bits each track holds. `nibbler scan` goes further: it converts each track's bit stream to nibbles, searches for sector markers in both 6-and-2 and 5-and-3 encoding, checks address field and data checksums, and auto-detects non-standard address prologs.

**What you discover:**

```
Track  Encoding   6+2   5+3  Addr CK   Data CK  Notes
    0        dual    1    13    13/14       1/14
    1         5+3    0    13    13/13        0/13  addr=$D5 $BE $B5
    2         5+3    0    13    13/13        0/13  addr=$D5 $BE $B5
    ...
    6         5+3    0    13    13/13        0/13  addr=$DE $FB $B5
    ...
   13         5+3    0    13    13/13        0/13  addr=$DE $BB $B5
```

Key findings:
- **14 tracks** (0-13), not the standard 35. The entire game fits in 40% of the disk.
- **Track 0 is dual-format:** one 6-and-2 sector (the boot sector) and thirteen 5-and-3 sectors coexisting on the same track.
- **5-and-3 encoding** on all tracks — the older, less common 13-sector format that predates DOS 3.3's 6-and-2.
- **Non-standard address prologs** — the second byte varies per track, and tracks 6-13 use `$DE` instead of `$D5` as the first byte.
- **Bad address checksums** across all 5-and-3 sectors on track 0.
- **One bad data checksum** on track 0 (sector 11).

**What this tells you:** This is a custom-loader disk with copy protection, not standard DOS 3.3. Standard tools won't read it.

**What to investigate next:** Catalog the specific protection techniques.

---

## 3. Catalog the Protections

**What you know so far:** The disk uses non-standard encoding, custom markers, and bad checksums — clear signs of copy protection.

**Command:**

```bash
python -m nibbler protect "apple-panic/Apple Panic - Disk 1, Side A.woz"
```

`nibbler protect` runs a comprehensive analysis: it checks for dual-format tracks, non-standard address prologs, invalid checksums, encoding anomalies, and per-track marker variations. It produces a structured report listing each detected technique.

**What you discover:** Eight or more distinct protection techniques operating in layers:

1. Dual-format track 0 (6-and-2 + 5-and-3)
2. Invalid address field checksums on all 5-and-3 sectors
3. Non-standard address prolog bytes varying per track
4. `$DE` first byte on tracks 6-13 (instead of standard `$D5`)
5. Non-standard sector/track numbers in address fields
6. Bad data checksum on sector 11

The remaining techniques (GCR table corruption, self-modifying code, custom post-decode permutation) are invisible to static analysis — they live in the boot code and can only be discovered by reading and tracing it.

**What this tells you:** This disk was designed to defeat copiers at multiple levels. Each layer targets a different class of copy tool. Understanding *how* each layer works requires reading the boot code.

**What to investigate next:** Disassemble the boot sector.

---

## 4. Read the Boot Sector

**What you know so far:** Track 0 has one 6-and-2 boot sector that the P6 ROM loads to `$0800`. Everything else is 5-and-3.

**Commands:**

```bash
# Decode the 6-and-2 boot sector
python -m nibbler decode "apple-panic/Apple Panic - Disk 1, Side A.woz" 0 --sector 0

# Disassemble the RWTS (the boot sector after relocation to $0200)
python scripts/disasm_rwts.py
```

`nibbler decode` extracts the raw 256 bytes of the boot sector. `disasm_rwts.py` goes further — it decodes the sector and disassembles it as RWTS code at its runtime address (`$0200`, where it relocates itself).

**What you discover:**

The boot sector is a compact, self-contained RWTS (Read/Write Track/Sector) routine:

```
$0801: LDX #$00        ; Copy self from $0800 to $0200
$0803: LDA $0800,X
$0806: STA $0200,X
       ...
$020F: [build 5-and-3 GCR decode table at $0800]
       ...
$0231: [read 5-and-3 sector 0 → $0300, post-decode via $02D1]
$0237: LDA #$A9        ; Self-modify: patch $031F from ORA #$C0
$0239: STA $031F       ;   to LDA #$02
$023C: LDA #$02
$023E: STA $0320
$0241: JMP $0301       ; Enter stage 2
```

The code:
1. **Relocates** itself from `$0800` to `$0200` (freeing `$0800` for the GCR table)
2. **Builds** the 5-and-3 GCR decode table at `$0800`
3. **Reads** 5-and-3 sector 0, applies the standard `$02D1` post-decode, loading stage 2 code to `$0300`
4. **Self-modifies** the stage 2 code at `$031F`/`$0320` before entering it

**Protection technique — self-modifying code:** The boot sector patches bytes in the freshly-loaded stage 2 code before jumping to it. On disk, `$031F` contains `$09 $C0` (`ORA #$C0`); at runtime it becomes `$A9 $02` (`LDA #$02`). Static disassembly of the raw sector data shows the wrong instruction. You must trace execution across both the boot sector (`$0200`) and stage 2 (`$0300`) to see the actual runtime behavior. This technique applies to any disk with a custom boot loader that patches subsequently-loaded code.

**What this tells you:** The boot sector *is* the RWTS — it reads the rest of the disk using 5-and-3 encoding. It loads stage 2 to `$0300` and jumps there. Follow the stage 2 code next.

**What to investigate next:** Disassemble the stage 2 loader at `$0300`.

---

## 5. Follow the Boot Code — Stage 2

**What you know so far:** The boot RWTS loads stage 2 code to `$0300` via the standard `$02D1` post-decode, patches it, and jumps to `$0301`.

**Command:**

```bash
python scripts/disasm_stage2.py
```

`disasm_stage2.py` simulates the `$02D1` post-decode of sector 0 to produce the stage 2 code at `$0300`-`$03FF`, then disassembles it.

**What you discover:**

```
$0301: LDA $0800,Y     ; Y enters at $99 (from boot code)
$0304: ASL
$0305: ASL
$0306: ASL
$0307: STA $0800,Y     ; Corrupt GCR table entry
$030A: INY
$030B: BNE $0301       ; Loop Y=$99..$FF
       ...
$0327: [sector loading loop: read sectors 0-9 → $B600-$BFFF]
       [post-decode via $0346 (custom routine)]
       ...
$033F: JMP ($003E)     ; = JMP $B700
```

Stage 2 does three things:
1. **Corrupts the GCR decode table** — applies ASL ×3 (shift left 3 bits) to entries `$0899`-`$08FF`, the upper 103 entries of the 5-and-3 decode table
2. **Reads sectors 0-9** into `$B600`-`$BFFF` using a custom post-decode routine at `$0346`
3. **Jumps to `$B700`** — the game loader

**Protection technique — GCR table corruption:** The stage 2 loader deliberately corrupts the GCR decode table before using it to read sectors. The sectors on disk were *written* with this corrupted table — so only code that performs the same corruption can decode them correctly. A nibble copier that reads the raw disk nibbles and decodes them with a fresh (uncorrupted) table gets garbage. The mathematical insight: `(A<<3) XOR (B<<3) = (A XOR B)<<3`, so XOR-based checksums remain valid despite the corruption. This technique applies to any disk with a custom boot loader that can modify its own decode tables.

**Protection technique — custom post-decode permutation ($0346):** The stage 2 loader uses a non-standard post-decode algorithm at `$0346` instead of the standard `$02D1`. Both produce the same 256 byte values, but in different positions. Even if someone correctly decodes the raw nibbles, applying the standard post-decode produces scrambled output. The `$0346` routine processes data in reverse order (X counting down from `$32`) and interleaves five groups per iteration, while `$02D1` processes sequentially. This technique can be used on any disk with a custom RWTS.

**What this tells you:** You now need to decode all of track 0 using the corrupted GCR table and the correct post-decode to get the `$B600`-`$BFFF` memory image containing the game loader.

**What to investigate next:** Decode track 0 with the correct algorithms.

---

## 6. Decode Track 0

**What you know so far:** Track 0's 5-and-3 sectors must be decoded with the corrupted GCR table (ASL ×3 on entries `$99`-`$FF`) and the `$0346` post-decode permutation.

**Commands:**

```bash
# Final correct decoder for track 0
python scripts/decode_track0.py

# Verification
python scripts/verify_checksum.py
python scripts/compare_decoders.py
python scripts/check_wrap.py
```

`decode_track0.py` is the final, verified decoder. It reads the WOZ bit stream with bit-doubling (see below), applies the corrupted GCR table, uses the `$02D1` post-decode followed by the permutation mapping to `$0346` order, and produces individual sector binaries plus the combined `$B600`-`$BFFF` memory image.

**What you discover:**

Twelve of thirteen sectors decode cleanly. Sector 1 — the critical `$B700` game loader entry point — requires special handling of the track wrap boundary.

**Protection technique — bit-stream wrap boundary:** A WOZ file stores each track as a linear bit stream, but a physical floppy disk track is a continuous circle. Sector 1's 411 data nibbles happen to start near the end of the bit stream and wrap past its boundary. A naive converter that processes one revolution of bits has 1 leftover bit at the boundary — discarding it shifts all subsequent nibbles by one bit, producing 189/256 wrong bytes. The fix is **bit-doubling**: concatenate the bit stream with itself before converting to nibbles, simulating the circular disk. This isn't deliberate copy protection — it's an artifact of how WOZ files represent circular media — but any disk with sectors near the track boundary may exhibit it.

**Protection technique — intentionally bad data checksum:** Sector 11 has data that fails checksum verification with both the original and corrupted GCR tables. Sector 11 is not used by the boot loader (only sectors 0-9 are loaded). This is a trap for copiers that validate all sector checksums — they'll reject the entire track even though the failing sector is unused.

The verification scripts confirm the decode:
- `verify_checksum.py` — confirms which sectors pass with which GCR table variant
- `compare_decoders.py` — confirms `$02D1` + permutation ≡ direct `$0346` decode (byte-for-byte match)
- `check_wrap.py` — confirms bit-doubling produces valid code for sector 1

**What this tells you:** You now have the complete `$B600`-`$BFFF` memory image: the RWTS and game loader. The game loader at `$B700` will read the remaining tracks.

**What to investigate next:** Emulate the full boot to see what the game loader does.

---

## 7. Emulate the Full Boot

**What you know so far:** The game loader at `$B700` reads the remaining tracks. But you've seen that this disk uses self-modifying code and runtime patching — static analysis alone won't reveal the full picture. Time to let the code run.

**Commands:**

```bash
# Full boot emulation: P6 ROM → RWTS → boot loader stage 2 → game loader → game entry
python -m nibbler boot "apple-panic/Apple Panic - Disk 1, Side A.woz" \
    --stop 0x4000 --dump 0x4000-0xA7FF --save game.bin

# Detailed trace with milestone detection (~70M instructions)
python scripts/boot_emulate_full.py
```

`nibbler boot` runs the 6502 emulator from the P6 ROM boot through the entire boot sequence, stopping at the specified address. `boot_emulate_full.py` provides a more detailed trace with milestone detection at each boot stage, outputting intermediate memory dumps at key points.

**What you discover:**

The boot sequence has five stages:

1. **P6 ROM → Boot sector** — loads 6-and-2 sector 0 to `$0800`, jumps to `$0801`
2. **Boot RWTS → Stage 2** — relocates to `$0200`, builds GCR table, reads sector 0 to `$0300`, self-modifies, jumps to `$0301`
3. **Boot loader stage 2 → Game loader** — corrupts GCR table, loads sectors 0-9 to `$B600`-`$BFFF`, jumps to `$B700`
4. **Game loader → Tracks 1-5** — reads 65 sectors to `$0800`-`$48FF`, then calls `$1000`
5. **`$1000` patches RWTS, displays title screen → Tracks 6-13** — reads 104 sectors to `$4000`-`$A7FF`, then `JMP $4000`

**Protection technique — runtime prolog patching:** The code at `$1000` runs *after* tracks 1-5 are loaded but *before* tracks 6-13 are read. It patches the RWTS's address prolog search from `$D5` to `$DE`:

```
$1015: LDA #$DE
$1017: STA $B8F6,Y    ; patches $B976: CMP #$D5 → CMP #$DE
$101A: STA $BE75,Y    ; patches $BEF5: LDA #$D5 → LDA #$DE
```

This means tracks 6-13 use `$DE` as the address prolog first byte — they literally cannot be read without first executing the code from tracks 1-5. A static analysis of the boot code or RWTS would never reveal this patch. Combined with the per-track second-byte variations (a lookup table at `$0400` patches `$B980` before each track read), every track on the disk has a unique address prolog. This technique applies to any disk where the RWTS is loaded into RAM and can be patched at runtime.

**Per-track address prolog table:**

```
Track:   0   1   2   3   4   5   6   7   8   9  10  11  12  13
First:  D5  D5  D5  D5  D5  D5  DE  DE  DE  DE  DE  DE  DE  DE
Second: AA  BE  BE  AB  BF  EB  FB  AA  FA  AA  AB  EA  EF  BB
Third:  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5
```

The full boot takes approximately **69.8 million emulated 6502 instructions**. The game entry point is `$4000`, with game code occupying `$4000`-`$A7FF` (26,624 bytes).

**What this tells you:** You now have the complete memory state at game entry. But the boot code includes relocation copy loops that move memory regions — the raw memory dump may not reflect the final runtime layout.

**What to investigate next:** Build the canonical runtime memory image.

---

## 8. Build the Runtime Image

**What you know so far:** The boot emulation produced a 64K memory dump at the moment of `JMP $4000`. The boot code at `$1900` contains relocation copy loops that rearrange memory regions to their final positions.

**Command:**

```bash
python scripts/build_runtime.py
```

`build_runtime.py` reads the boot emulation output, simulates the relocation copy loops at `$1900` that move memory regions to their final runtime locations, and applies cleanups to produce a canonical image.

**What you discover:**

The runtime image is 43,008 bytes (`$0000`-`$A7FF`). Key regions:

- `$0000`-`$07FF`: Zero page, stack, RWTS at `$0200`
- `$0800`-`$1FFF`: Sprite data, lookup tables, title screen routines
- `$4000`-`$A7FF`: Game code and data (26,624 bytes)

**What this tells you:** The memory is now in its final runtime configuration, ready for disassembly.

**What to investigate next:** Generate the assembly source.

---

## 9. Generate the Assembly Source

**What you know so far:** You have a 43,008-byte runtime memory image with the game code at `$4000`-`$A7FF`.

**Commands:**

```bash
# Recursive descent disassembly
python -m nibbler disasm ApplePanic_runtime.bin --base 0x0000 --entry 0x4000 -r

# Full disassembly with labels, annotations, and data formatting
python scripts/disassemble.py
```

`nibbler disasm -r` performs recursive descent disassembly — it traces execution paths from the entry point, following branches and jumps to classify each byte as code or data. `disassemble.py` adds a layer on top: 200+ descriptive label names, hardware register comments (`$C050`-`$C057` for graphics, `$C000`/`$C010` for keyboard, `$C030` for speaker), Apple II ROM call annotations, and formatted sprite/level data tables.

**What you discover:**

The output is an ~8,800-line Merlin32-syntax assembly source with 104 identified subroutines. Key structures:

- **Entry point:** `$4000` → `JMP $4065` (initialization)
- **Main loop:** `$74E9` — dispatches enemy updates + player input per frame
- **Graphics:** HGR page-flipping (page 1 display, page 2 as XOR sprite background)
- **Score:** 6 BCD digits at `$70BB`-`$70C0`
- **Enemies:** 10 slots, state tables at `$8581`-`$85FF`
- **Levels:** Difficulty data caps at level 7; victory at level 49
- **No undocumented opcodes** anywhere — neither in the boot loader nor in the game code

**What this tells you:** You now have a fully commented, readable assembly source for the entire game.

**What to investigate next:** Verify the result.

---

## 10. Verify the Result

**What you know so far:** You have the full disassembly. But the decode pipeline has many stages — WOZ bit-stream parsing, GCR decoding with a corrupted table, custom post-decode permutation, 6502 emulation, relocation simulation — and any error in any stage would propagate silently.

**Commands:**

```bash
# Verify $02D1+permutation ≡ $0346 (decoder equivalence)
python scripts/compare_decoders.py

# Verify bit-doubling fix for sector 1 (wrap handling)
python scripts/check_wrap.py

# Verify 6-and-2 boot sector matches .dsk file
python scripts/woz_62verify.py

# Scan sector data consistency across revolutions
python scripts/scan_sector1.py
```

**What you discover:**

- `compare_decoders.py`: byte-for-byte match between `$02D1`+permutation and direct `$0346` decode (except byte 255, a known bit-truncation difference)
- `check_wrap.py`: 189/256 bytes differ between naive and bit-doubled decode of sector 1; bit-doubled version passes checksum and produces valid code
- `woz_62verify.py`: 256/256 byte match between WOZ 6-and-2 decode and the `.dsk` file — "PERFECT MATCH!"
- `scan_sector1.py`: sector data is consistent across multiple revolutions of the disk

**What this confirms:** The extraction is byte-perfect. Every stage of the pipeline produces correct output.

---

## Summary: The Chain of Discovery

| Step | Tool | Discovery | Protection Defeated |
|------|------|-----------|-------------------|
| 2 | `nibbler scan` | 14 tracks, dual-format, 5-and-3, non-standard prologs | — |
| 3 | `nibbler protect` | 8+ protection techniques cataloged | — |
| 4 | `nibbler decode` + `disasm_rwts.py` | Boot sector = RWTS, self-modifying code | Self-modifying code |
| 5 | `disasm_stage2.py` | GCR table corruption, custom post-decode | GCR corruption, custom permutation |
| 6 | `decode_track0.py` + verification | Bit-stream wrap, bad sector 11 checksum | Wrap boundary, decoy checksum |
| 7 | `nibbler boot` + `boot_emulate_full.py` | Runtime prolog patching, per-track markers | `$DE` patch, per-track second byte |
| 8 | `build_runtime.py` | Relocation copy loops, final memory layout | — |
| 9 | `nibbler disasm -r` + `disassemble.py` | 104 subroutines, 8,800-line source | — |
| 10 | Verification scripts | Byte-perfect extraction confirmed | — |

Each step reveals what the next step must address. The protections are layered so that defeating one exposes the next — dual-format leads to the boot sector, which reveals GCR corruption, which requires the custom post-decode, which produces the game loader, which contains the runtime prolog patches. No single tool defeats all layers; the chain of discovery is the methodology.

# Cracking Open Apple Panic: Reverse Engineering a 1981 Copy-Protected Disk

*A chronicle of exploring, decoding, and understanding the copy protection on an Apple II floppy disk image — one byte at a time.*

---

## Why the Apple II Disk Drive Was Special

To understand why Apple II copy protection was so varied and so devious, you first have to understand what made the Disk II drive unusual.

Most floppy disk controllers of the late 1970s were complex hardware systems. They handled encoding, decoding, sector formatting, and error detection in dedicated circuitry. The operating system asked the controller for "sector 5 on track 12" and got back 256 bytes. The software never touched the raw bit stream.

The Disk II was Steve Wozniak's answer to that. Instead of a complex controller, the Disk II used a handful of TTL chips and a small state machine. The controller did almost nothing — it could shift bits in and out, and it could move the head. Everything else was done in software. The P6 ROM (a 256-byte PROM soldered to the controller card) contained just enough code to read a single sector in one specific format: 6-and-2 GCR encoding with `D5 AA 96` address markers. That was the boot ROM. After that single sector loaded, the software on the disk was in charge.

This design made the Disk II astonishingly cheap — Wozniak famously reduced the chip count from around 50 (in competing designs) to 8. But it had a profound unintended consequence: **because the software controlled the bit stream directly, the software could write anything it wanted.**

The controller's write mode worked by toggling a latch at precise intervals. If the software could time its writes correctly, it could lay down any bit pattern: standard 6-and-2 sectors, 5-and-3 sectors, sectors with non-standard markers, sectors with no markers at all, half-tracks, quarter-tracks, spiral tracks, varying bit timing, nibble counts that changed per revolution — anything the magnetic medium could physically represent. There was no hardware enforcing a format. The bits on the disk were whatever the last piece of software to write them decided they should be.

The only constraint was bootstrap: **track 0, sector 0 had to be in the format the P6 Boot ROM expected** — 6-and-2 encoding, `D5 AA 96` address prolog, `D5 AA AD` data prolog — because that 256-byte ROM was the only fixed point in the system. It would find sector 0, load 256 bytes to `$0800`, and jump to `$0801`. After that, the code at `$0801` could reprogram the disk I/O from scratch. It could build its own GCR tables, search for its own marker bytes, decode sectors in its own format, and lay out data in ways no standard tool would recognize.

This is why Apple II copy protection became an arms race that lasted a decade. The disk format wasn't a hardware standard — it was a software convention. And conventions can be broken by anyone with access to the write circuitry, which on the Apple II was everyone.

---

## What Is a WOZ File?

Standard Apple II disk images — `.dsk` and `.do` files — store 140 kilobytes of decoded sector data: 35 tracks × 16 sectors × 256 bytes. They throw away everything about *how* that data was encoded on disk: the marker bytes, the sync gaps, the GCR encoding, the bit timing. For a standard DOS 3.3 disk, this is fine. For a copy-protected disk, it's catastrophic. The protection *is* the encoding.

A `.woz` file is different. Created by the [Applesauce](https://applesaucefdc.com/) hardware — a modern device that connects to real Apple II drives — a WOZ file captures the actual magnetic flux transitions on the disk surface. It stores each track as a circular bit stream: the raw sequence of 0s and 1s that the drive head would see spinning past it. The WOZ2 format records:

- **The exact bit stream** for each track — not decoded bytes, not nibbles, but the individual flux transitions
- **The bit count** — how many bits are on the track (typically ~51,000 for a 5.25" disk at standard speed)
- **Quarter-track resolution** — data can exist at positions 0, 0.25, 0.5, and 0.75 between integer tracks
- **Timing metadata** — whether the capture was synchronized to the index hole

This means a WOZ file preserves everything: non-standard markers, custom GCR tables, half-track data, sectors that span the track's physical wrap point, and bit patterns that no standard format anticipated. Reading a WOZ file is like putting the original floppy in a drive — you see exactly what the drive head would see, and you have to make sense of it the same way the original software did, one bit at a time.

The process of going from a WOZ bit stream to usable data is what this entire project is about.

---

## The Starting Point

It begins with a single file: `Apple Panic - Disk 1, Side A.woz` — a WOZ2 disk image captured by Applesauce. The game is *Apple Panic* by Ben Serki, published by Broderbund in 1981 — a platformer where you dig holes to trap monsters, inspired by the arcade game *Space Panic*.

The goal: understand exactly how this disk boots, what copy protection mechanisms are at work, and extract a clean game binary. We also have a cracked version (`ApplePanic_runtime.bin`, 43,008 bytes) to compare against — extracted years ago by a cracking group called "RIP_EM_OFF SOFTWARE" — but the point is not just to get the game running. The point is to *understand*.

---

## Phase 1: Reading the WOZ File

### First Contact with woz_reader.py

The first tool written was `woz_reader.py` — a straightforward WOZ2 format parser. The WOZ2 file format stores each track as a circular bit stream with metadata: the number of valid bits, the bit timing, and a `TMAP` (track map) that maps quarter-tracks to physical data chunks.

The first surprise came immediately. A standard Apple II DOS 3.3 disk has 35 tracks (0 through 34). This disk has only **14 tracks** (0 through 13). Tracks 14-34 are empty. The entire game — code, graphics, title screen, everything — fits in 14 tracks. That's only 40% of the disk's capacity.

This was the first hint that something unusual was going on. DOS 3.3 needs a catalog track, VTOC, and a filesystem. This disk has none of that. It's a raw boot disk with its own custom loader.

### woz_analyze.py: The Nibble Landscape

The next step was `woz_analyze.py`, which converts each track's raw bit stream into nibbles (valid disk bytes are $96-$FF on the Apple II — any byte with the high bit set and specific bit patterns) and scans for known marker sequences.

On a standard 16-sector disk, you expect to see `D5 AA 96` (address field prolog) and `D5 AA AD` (data field prolog) markers. On a 13-sector disk (the older format used by DOS 3.2), you'd see `D5 AA B5` address fields.

Track 0 had **both**.

---

## Phase 2: The Dual-Format Track

This was the first real discovery. Track 0 contains sectors in *two different encoding formats* on the same physical track:

- **One** sector using 6-and-2 encoding (16-sector format, `D5 AA 96` address prolog)
- **Thirteen** sectors using 5-and-3 encoding (13-sector format, `D5 AA B5` address prolog)

This is a deliberate copy protection choice. The Apple II's Disk II P6 Boot ROM (the 341-0027 PROM) always boots using the 6-and-2 format. It looks for `D5 AA 96` address markers, reads sector 0, and loads it to `$0800`. Standard DOS 3.3 copiers work only with 6-and-2 sectors. So the boot ROM can find and load the single 6-and-2 sector, but a copier trying to read "all the sectors" would only find one sector on track 0 instead of 16.

The boot sector, once loaded at `$0800`, contains code that switches to reading the 5-and-3 sectors. The remaining 13 sectors carry the actual boot loader and RWTS (Read/Write Track/Sector) routines.

**Why 5-and-3?** The 5-and-3 encoding format predates 6-and-2. It was used by DOS 3.2 and stores only 256 bytes per sector (vs. 256 for 6-and-2, but using 410 GCR nibbles instead of 342). Fewer copy tools support it, and mixing it with 6-and-2 on the same track is virtually unheard of. It's an obscure enough format that many copiers simply don't handle it.

---

## Phase 3: Disassembling the Boot Code

### The Boot Sector ($0800)

The 6-and-2 boot sector loads at `$0800`. Disassembling it with `disasm_rwts.py` revealed a compact piece of code that:

1. Relocates itself from `$0800` to `$0200`
2. Jumps to `$020F`
3. Builds the 5-and-3 GCR decode table at `$0800`
4. Begins reading 5-and-3 sectors

The relocation is clever — the code needs the `$0800` region for the GCR table, so it copies itself out of the way first. The GCR (Group Coded Recording) decode table maps the 32 valid 5-and-3 disk nibble values back to 5-bit data values. Building this table programmatically (rather than storing it as a literal table) saves precious boot sector space.

### Self-Modifying Code at $031B

One of the more devious tricks lives in the RWTS code at `$0200`. At address `$031B`, the code patches its own instructions:

```
$031B: LDA #$02
$031D: STA $0320
$0320: ORA #$C0    ; <-- this gets patched to "LDA #$02"
```

Before the patch, `$031F`/`$0320` contain `ORA #$C0`. After the self-modification, they become `LDA #$02`. This changes the behavior of the RWTS between the initial boot read and all subsequent sector reads. If you're doing static disassembly — just reading the bytes on disk — you see the `ORA #$C0` and get a misleading picture of what the code actually does at runtime.

This is the kind of trick that makes a reverse engineer's life difficult: the code on disk is not the code that runs.

---

## Phase 4: The 6502 Emulator

### Why Emulation?

At some point, static analysis hits a wall. The boot code is self-modifying, the GCR table gets built and then corrupted at runtime, and the post-decode algorithms are complex enough that hand-tracing is error-prone. The solution: build an emulator.

`emu6502.py` is a cycle-level 6502 CPU emulator written in Python. It implements all 256 opcodes — including the **29 undocumented NMOS 6502 opcodes** that "officially" don't exist but that real hardware executes in well-known (if bizarre) ways.

This turned out to be prescient. The boot code uses `SHY` (opcode `$9C`), one of the undocumented instructions. `SHY` stores `Y AND (high_byte_of_address + 1)` to the target address. It's an unstable opcode — its behavior depends on page-crossing conditions — but the boot code uses it in a context where the behavior is deterministic. Without implementing `$9C` correctly, the emulator would hang or produce wrong results.

### Disk I/O Soft Switches

A CPU emulator alone isn't enough. The boot code reads the disk by accessing Apple II soft switches — memory-mapped I/O addresses in the `$C0Ex` range. The Disk II controller uses:

- `$C08C` (with slot offset): read data latch
- `$C08E`: set read mode
- `$C08A`: select drive 1

The emulator needed to simulate these soft switches by feeding nibbles from the WOZ bit stream whenever the emulated CPU reads from `$C0EC` (slot 6 data latch). This meant implementing a virtual Disk II controller that converts the WOZ bit stream into the sequence of nibbles the CPU would see on real hardware.

---

## Phase 5: The GCR Table Corruption

With the emulator running, we could watch the boot process unfold step by step. After the RWTS builds the standard 5-and-3 GCR decode table at `$0800`, the stage 2 loader at `$0301` does something unexpected:

```
$0301: LDX #$32
$0303: ASL $0899,X
$0306: ASL $0899,X
$0309: ASL $0899,X
$030C: DEX
$030D: BPL $0303
```

This loop applies `ASL` (Arithmetic Shift Left) **three times** to every byte in the GCR table from offset `$99` through `$FF` — the upper 103 entries. Each ASL shifts the byte left by one bit, so three ASLs effectively multiply by 8 and zero out the low 3 bits. The upper portion of the GCR table, which should contain values like `$00` through `$1F`, now contains values like `$00`, `$08`, `$10`, `$18`, etc.

**Why does this work?** The key mathematical insight is that XOR distributes over bit shifts:

```
(A << 3) XOR (B << 3) = (A XOR B) << 3
```

The 5-and-3 data checksum is computed by XORing all decoded values together. If every value in the affected range is shifted left by 3, the XOR checksum is also shifted left by 3 — it's still zero if the original checksum was zero. So checksums still pass, but the *values* are wrong if you use a standard, uncorrupted table.

This is the copy protection trap: if a nibble copier reads the raw disk nibbles perfectly, then decodes them with a freshly-built GCR table, it gets corrupted data. The Apple Panic loader *expects* the corrupted table and its post-decode algorithm is designed to work with the corrupted values. A copier doesn't know about the corruption step and produces garbage.

---

## Phase 6: The $0346 Post-Decode Permutation

Standard 5-and-3 encoding stores 256 bytes as 410 GCR nibbles: 154 "secondary" nibbles (carrying the low bits) and 256 "primary" nibbles (carrying the high bits). The standard Apple II post-decode routine at `$02D1` reassembles these into 256 output bytes in a specific order.

Apple Panic doesn't use `$02D1`. It uses a custom post-decode routine at `$0346` that produces bytes in a **different order**. The same 256 values come out, but they're permuted — placed in different positions in the output buffer.

Working out this permutation was one of the more tedious analytical challenges. The `$0346` routine processes data in reverse order (X counting down from `$32`) and interleaves five groups per iteration, while `$02D1` processes sequentially. After significant analysis and verification with `compare_decoders.py`, the mapping was determined:

```
$0346 output[5k + n] = $02D1 output[offset - k]
  where offsets = [50, 101, 152, 203, 254] for n = [0, 1, 2, 3, 4]
```

Byte 255 is a special case: `$0346` reconstructs all 8 bits from `secondary[153]` and `primary[255]`, while `$02D1` loses the high bits.

The practical approach was to implement the standard `$02D1` decode (which is well-documented and easier to verify) and then apply the permutation mapping. This was validated by `compare_decoders.py`, which confirmed byte-for-byte equivalence.

---

## Phase 7: The Sector 1 Crisis

This was the lowest point of the project — a problem that consumed hours of debugging and led down multiple dead ends before the real cause was found.

### The Symptom

After implementing the GCR table corruption and the `$0346` permutation, we could decode 12 of the 13 five-and-three sectors on track 0. Sector 1 — the one that loads to `$B700`, the critical secondary loader entry point — failed its data checksum every time.

### Dead End #1: Wrong GCR Table

The first theory: maybe the GCR table corruption was implemented incorrectly. Hours were spent reviewing the ASL loop, double-checking table offsets, trying different corruption ranges. Nothing helped. All other sectors decoded fine with the corrupted table.

### Dead End #2: Deliberate Bad Checksum

The second theory: maybe sector 1 has a deliberately bad checksum, like sector 11 (which genuinely does — sector 11 is unused by the boot loader and appears to be a decoy). The stage 2 loader doesn't verify data checksums, so a bad checksum wouldn't prevent booting. But this felt wrong — sector 1 contains actual code that must be correct.

### Dead End #3: Brute-Force GCR Table Variants

The third theory: maybe the GCR table has additional modifications we haven't discovered. `woz_53brute.py` was written to try thousands of GCR table variants, looking for one that produced a valid checksum for sector 1. None worked.

### The Breakthrough: Bit-Doubling

The real problem had nothing to do with copy protection at all.

A WOZ file stores each track as a linear array of bits with a defined bit count. But a physical floppy disk track is a **circle** — there is no start or end. The Applesauce hardware picks an arbitrary point (based on the index pulse) as "bit 0" and captures one revolution of data.

When converting the bit stream to nibbles, you scan for valid disk bytes (high bit set, no more than one consecutive pair of zero bits). At the end of the bit stream, you might have leftover bits that don't form a complete nibble. A naive implementation discards these leftovers and starts fresh from the beginning of the stream for a second revolution.

But those leftover bits are *part of a nibble that spans the boundary*. Sector 1's 411 data nibbles happen to start near the end of the bit stream and wrap past its edge. With the naive approach, there's **1 leftover bit** at the wrap point. Discarding it shifts every subsequent nibble by one bit position, producing completely wrong values.

The fix is what we called **bit-doubling**: concatenate the bit stream with itself before converting to nibbles. This simulates the continuous circular nature of the physical disk. The nibble converter sees a continuous stream of bits with no artificial boundary, and all nibbles — including those that span the original wrap point — are decoded correctly.

```python
# WRONG: convert one revolution, then try to wrap nibbles
nibbles = bits_to_nibbles(track_bits)
wrapped = nibbles + nibbles[:extra]  # nibble boundaries are wrong!

# RIGHT: double the bits, then convert
doubled = track_bits + track_bits
nibbles = bits_to_nibbles(doubled)  # correct nibble boundaries everywhere
```

The `check_wrap.py` diagnostic script proved the fix: **189 out of 256 bytes** differ between the two methods for sector 1. With bit-doubling, the checksum passes and the decoded data is valid 6502 machine code.

This wasn't copy protection — it's an artifact of how WOZ files represent circular media in a linear format. But it was the hardest bug to find in the entire project, precisely because we kept looking for clever tricks in the copy protection when the real problem was in our own tooling.

---

## Phase 8: The Full Boot

With bit-doubling in place, the emulator could finally complete the entire boot sequence. `boot_emulate_full.py` traces from power-on through to game start:

### Stage 1: Track 0 ($0801 to JMP $B700)

The P6 Boot ROM loads the 6-and-2 boot sector to `$0800` and jumps to `$0801`. The boot code relocates to `$0200`, builds the GCR table, corrupts it, reads sectors 0-9 to `$B600`-`$BFFF`, and jumps to `$B700`.

Memory map after stage 1:
```
$0200-$03FF  Boot RWTS (relocated boot sector + stage 2 loader)
$0800-$08FF  5-and-3 GCR decode table (corrupted)
$B600-$BFFF  Track 0 sectors 0-9 (RWTS + secondary loader)
```

### Stage 2: Tracks 1-5 to $0800-$48FF

The secondary loader at `$B700` reads tracks 1-5 (65 sectors at 13 sectors per track) into `$0800`-`$48FF`. This region contains:

- `$1000`: Intermediate code that displays the title screen and patches the RWTS
- `$1200`: Display and sound routines
- HGR bitmap data for the title screen

Then comes the marker patch — code at `$1000` rewrites the RWTS to search for `$DE` instead of `$D5` as the first byte of address field prologs:

```
$1015: LDA #$DE
$1017: STA $B8F6,Y    ; patches CMP #$D5 → CMP #$DE at $B976
$101A: STA $BE75,Y    ; patches LDA #$D5 → LDA #$DE at $BEF5
```

After this patch, tracks 1 and above use `DE AA xx` address markers instead of `D5 AA xx`. The third byte (`xx`) varies per track via a lookup table:

```
Track:  0   1   2   3   4   5   6   7   8   9  10  11  12  13
Value: AA  BE  BE  AB  BF  EB  FB  AA  FA  AA  AB  EA  EF  BB
```

This is another layer of copy protection: a copier scanning for standard `D5 AA B5` address fields on tracks 1+ finds nothing. Even knowing to look for `$DE` isn't enough — you also need the per-track third-byte table.

### Stage 3: Tracks 6-13 to $4000-$A7FF

After the title screen displays and the player presses a key, the loader reads tracks 6-13 (104 sectors) into `$4000`-`$A7FF` — approximately 27KB of game code and data. Then: `JMP $4000`. The game begins.

The full boot took approximately **69.8 million emulated 6502 instructions** — a testament to how many times the RWTS loops waiting for the right sector to come around under the read head.

---

## Phase 9: Verification Against the Cracked Version

With the emulated memory dump in hand, we could compare it against `ApplePanic_runtime.bin` — the cracked version extracted years earlier. Initial comparison at `$4000`-`$5FFF` showed only a 69.5% match, which was alarming.

Investigation revealed the discrepancy wasn't a decode error — the cracked version had **reorganized memory**. The cracking group relocated code during the crack:

- Emulated `$8000`-`$9FFF` corresponds to cracked `$4000`-`$5FFF`
- Pages `$6000`-`$A7FF` match at **99.6%**

The remaining 0.4% differences were in regions that the cracker had modified: removing the copy protection loader, replacing it with a standard DOS 3.3 `BRUN` stub, and zeroing out the relocation machinery.

This verification gave high confidence that our decode pipeline — WOZ reader, bit-doubling, GCR table corruption, custom post-decode permutation, 6502 emulation — was correct.

---

## Phase 10: The Disassembler

With the game binary extracted and verified, the next step was understanding what the code actually does. `disassemble.py` is a recursive-descent 6502 disassembler that:

1. **Seeds** from known entry points (like `$4000`, `$7000`, and every `JSR` target)
2. **Traces** execution paths, following branches and jumps
3. **Classifies** every byte as code or data
4. **Multi-pass gap-fills**: after the initial trace, it scans for untouched regions that look like valid code (e.g., subroutines reached via indirect `JMP ($xxxx)` that the tracer couldn't follow)

The result: a fully annotated assembly source with named subroutines, branch labels, and hardware register comments. The recursive descent tracer classifies code vs data, while multi-pass gap-filling catches subroutines reached via indirect jumps that single-pass tracing misses.

Notable findings:
- The game uses HGR page-flipping: page 1 for display, page 2 as a background snapshot for XOR-based sprite rendering
- Score is stored as 6 BCD digits at `$70BB`-`$70C0`
- There are 10 enemy slots with state tables at `$8581`-`$85FF`
- Victory is at level 49 (though the difficulty data table caps at level 7)
- An identity table at `$1800`-`$18FF` (256 bytes where `table[n] = n`) is used for memory operations
- No undocumented 6502 opcodes in the game code itself — only the boot loader uses them

---

## Phase 11: Packaging as woztools

The final step was consolidating the ~38 individual scripts into a reusable Python package called `woztools`. The package provides:

- **10 modules** covering WOZ file I/O, bit-stream handling, GCR decoding (both 5-and-3 and 6-and-2), 6502 emulation, and disassembly
- **7 CLI subcommands**: `info`, `scan`, `protect`, `boot`, `decode`, `dsk`, `disasm`
- Works on any WOZ file, not just Apple Panic

The journey from `woz_reader.py` (a quick script to dump WOZ headers) to `woztools` (a general-purpose WOZ analysis toolkit) mirrors the project itself: each new challenge required a new tool, and eventually there were enough tools that a package structure made sense.

---

## The Nine Layers of Protection

Looking back, Apple Panic's copy protection operates in nine distinct layers:

| # | Mechanism | Defeats |
|---|-----------|---------|
| 1 | Dual-format track 0 (6-and-2 + 5-and-3) | Standard DOS 3.3 copy utilities |
| 2 | Invalid address field checksums (all 13 sectors) | Nibble copiers that validate headers |
| 3 | GCR table corruption (ASL x3 on upper entries) | Raw nibble copies decoded with fresh tables |
| 4 | Intentionally bad checksum on sector 11 | Copiers that validate all sector checksums |
| 5 | Custom post-decode permutation ($0346 vs $02D1) | Manual analysis with standard decode assumptions |
| 6 | Self-modifying code | Static disassembly |
| 7 | Non-standard $DE address markers on tracks 1+ | Copiers looking for standard $D5 prologs |
| 8 | Per-track third-byte variations | Copiers that handle $DE but assume fixed prologs |
| 9 | Non-standard sector/track numbers in address fields | Copiers expecting sector 0-12 / track matching physical position |

Layer 9 was discovered late in the analysis. On corrupted tracks (1-6, 8, 10-13), the address fields contain deliberately non-standard values — sector numbers like 215, 253, and 255, and track numbers that don't correspond to the physical track position. The boot code's custom RWTS knows exactly which non-standard sector numbers to look for on each track. A standard copier expecting sector numbers 0-12 (for 13-sector format) would never find these sectors, even if it handled every other protection layer correctly.

The bit-stream wrap issue was excluded from this list — it's a WOZ capture artifact, not a deliberate protection. But it was, paradoxically, the hardest problem to solve.

---

## Reflections

### The Detective Nature of Reverse Engineering

Reverse engineering a copy-protected disk is detective work. You start with raw evidence (the bit stream), form hypotheses about what the code is doing, test those hypotheses, and iterate. Many hypotheses are wrong. The GCR table corruption was discovered not by reading the code (which is obfuscated by self-modification) but by watching the emulator modify memory at runtime.

The sector 1 crisis is the best example. The symptom (bad checksum) was real. The first three theories were all plausible and internally consistent — they just happened to be wrong. The real cause (bit-stream wrap) was in a completely different part of the system, in code we'd written ourselves. It's a reminder that when debugging, the bug is always in the last place you look, and it's often in your own assumptions rather than in the system you're studying.

### The Craft of 1981

The copy protection on Apple Panic is remarkably sophisticated for 1981. Mixing two encoding formats on one track, corrupting lookup tables while preserving checksum invariants, using per-track marker variations — this is the work of someone who understood the Disk II hardware at a deep level. The `(A<<3) XOR (B<<3) = (A XOR B)<<3` property that keeps checksums valid despite table corruption is particularly elegant.

The game itself fits in 14 tracks — about 45KB of disk space. The boot loader, RWTS, copy protection, title screen, and complete game with all its graphics and logic. Every byte earned its place.

### The Tools

Over the course of this project, approximately 38 Python scripts were written. Many were throwaway experiments (`woz_53brute.py` — the failed brute-force GCR search), others became essential (`emu6502.py`, `decode_track0.py`, `boot_emulate_full.py`). The timeline of script creation mirrors the investigation itself:

1. `woz_reader.py`, `woz_analyze.py` — "What's on this disk?"
2. `disasm_rwts.py`, `disasm_stage2.py` — "What does the boot code do?"
3. `woz_53decode.py`, `woz_53brute.py`, `woz_53_variants.py` — "Why can't I decode sector 1?"
4. `emu6502.py`, `boot_emulate.py` — "Let's just run the code and watch what happens"
5. `check_wrap.py` — "Oh. *Oh.* It's the bit stream boundary."
6. `boot_emulate_full.py` — "Now let's boot the whole thing"
7. `disassemble.py` — "Now let's understand what the game actually does"

Each script is a fossil of a question that was asked and answered — or asked and abandoned. That's what a real investigation looks like.

---

## Complete Boot Flow Reference

```
Power On
  │
  ▼
P6 Boot ROM (341-0027)
  │  Reads 6-and-2 sector 0 → $0800
  │
  ▼
$0801: Boot Sector
  │  Relocate self to $0200
  │  Build 5-and-3 GCR table at $0800
  │  JMP $020F
  │
  ▼
$0200: Boot RWTS
  │  Read sector 0 (stage 2 code)
  │  Self-modify: patch $031F/$0320
  │
  ▼
$0301: Stage 2 Loader
  │  Corrupt GCR table (ASL x3 on $0899-$08FF)
  │  Load sectors 0-9 → $B600-$BFFF
  │  JMP ($003E) = JMP $B700
  │
  ▼
$B700: Secondary Loader
  │  Read tracks 1-5 → $0800-$48FF
  │  JSR $1000:
  │    Display title screen
  │    Patch RWTS: $D5 → $DE for tracks 1+
  │  JSR $1290: Display routine
  │  Read tracks 6-13 → $4000-$A7FF
  │
  ▼
$4000: GAME START
  (69.8M emulated instructions from power-on)
```

---

*Total tools written: ~38 Python scripts. Total emulated instructions: 69.8 million. Total layers of copy protection: 9. Total hours lost to the bit-doubling bug: too many.*

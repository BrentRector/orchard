# Cracking Open Apple Panic: Reverse Engineering a 1981 Copy-Protected Disk

*A chronicle of exploring, decoding, and understanding the copy protection on an Apple II floppy disk image — one byte at a time.*

> For the logical step-by-step walkthrough (what to do, in what order, what each step reveals), see [Walkthrough.md](Walkthrough.md). This document tells the full story of the investigation, including dead ends and breakthroughs.

---

## Why the Apple II Disk Drive Was Special

To understand why Apple II copy protection was so varied and so devious, you first have to understand what made the Disk II drive unusual.

Most floppy disk controllers of the late 1970s were complex hardware systems. They handled encoding, decoding, sector formatting, and error detection in dedicated circuitry. The operating system asked the controller for "sector 5 on track 12" and got back 256 bytes. The software never touched the raw bit stream.

The Disk II was Steve Wozniak's answer to that. Instead of a complex controller, the Disk II used a handful of TTL chips and a small state machine. The controller did almost nothing — it could shift bits in and out, and it could move the head. Everything else was done in software. A 256-byte boot ROM (the "P6 ROM," a PROM soldered to the controller card) contained just enough code to read a single sector from track 0 and jump to it. After that, the software on the disk was in charge.

This design made the Disk II astonishingly cheap — Wozniak famously reduced the chip count from around 50 (in competing designs) to 8. But it had a profound unintended consequence: **because the software controlled the bit stream directly, the software could write anything it wanted.**

The controller's write mode worked by toggling a latch at precise intervals. If the software could time its writes correctly, it could imprint practically any magnetic flux pattern on any track. The stepper motor had four phases and the software controlled each phase individually, giving quarter-track resolution — the head could be positioned at track 0, 0.25, 0.5, 0.75, 1.0, and so on. The only physical constraint was the width of the read/write head: at the Disk II's 48 tracks per inch, the head was wide enough that writing on adjacent quarter-tracks would destroy neighboring data. Half-track spacing (every other quarter-track) was the practical minimum. But that still meant a protection scheme could write data at track 1, track 2.25, track 3.5 — whatever positions it chose. A standard copier that only looked at integer tracks would miss half the data, and a copier that tried to copy all half-tracks would need to know which positions actually had data.

Standard 16-sector-per-track formats, standard 13-sector-per-track formats, sectors with non-standard markers, sectors with no markers at all, spiral tracks, varying bit timing, nibble counts that changed per revolution — anything the magnetic medium could physically represent. There was no hardware enforcing a format. The bits on the disk were whatever the last piece of software to write them decided they should be.

The one hardware constraint was on the *read* side. The Disk II's shift register was self-clocking — it used the 1-bits in the data stream to maintain timing synchronization. Too many consecutive 0-bits and the hardware would lose sync. The original 13-sector controller (the P5A boot ROM, used by DOS 3.2) required that no two adjacent bits could both be zero — at most one consecutive zero bit. The later 16-sector controller (the P6 boot ROM, used by DOS 3.3) relaxed this to allow one pair of adjacent zero bits — at most two consecutive zeros. The controller board hardware was the same in both cases; the difference was in the boot PROM and the encoding scheme it implemented.

This constraint meant you couldn't store arbitrary byte values directly on disk. A byte like `$08` (`00001000`) has long runs of zeros that would desynchronize the read hardware. Of the 256 possible byte values, only a subset had bit patterns dense enough in 1-bits to be read back reliably — and those byte values all had to have the high bit set (the shift register used bit 7 as its "data ready" signal). Under the stricter 13-sector constraint, the Disk II could only read and write **32** different byte values. Under the relaxed 16-sector constraint, it could handle **64**. These valid byte values were called "disk nibbles."

But a program needs to store all 256 possible byte values — arbitrary code and data. How do you write 256 values using an alphabet of only 32 or 64? The answer was GCR — Group Code Recording — an encoding algorithm that disassembles each 8-bit data byte into smaller groups of bits and maps each group to one of the permitted nibble values. With 32 nibbles available, each nibble can represent 5 bits of data (2⁵ = 32). So GCR takes each data byte, extracts 5 bits into one nibble and the remaining 3 bits into another — this is "5-and-3" encoding. With 64 nibbles available, each can represent 6 bits (2⁶ = 64), so GCR extracts 6 bits and 2 bits — "6-and-2" encoding. In practice, the leftover bits (the 3s or the 2s) from several consecutive bytes are packed together into shared nibbles rather than wasting a full nibble on just 2 or 3 bits.

The result is that each 256-byte sector becomes 411 nibbles on disk under 5-and-3, or 342 nibbles under 6-and-2. Because the 6-and-2 scheme encodes more data in fewer flux transitions, the same physical disk — the same magnetic medium, the same number of tracks, the same rotation speed — could hold more data simply by reformatting it. No hardware changes, just a more efficient encoding.

This is why Apple II copy protection became an arms race that lasted a decade. The disk format wasn't a hardware standard — it was a software convention. And conventions can be broken by anyone with access to the write circuitry, which on the Apple II was everyone.

---

## Standard Disk Formats and Disk Images

A standard Apple II floppy disk has 35 tracks. Under DOS 3.2's 5-and-3 encoding, each track held 13 sectors of 256 bytes — 35 × 13 × 256 = **113,750 bytes** (~111 KB). Under DOS 3.3's more efficient 6-and-2 encoding, each track held 16 sectors — 35 × 16 × 256 = **143,360 bytes** (140 KB). The transition wasn't tied to a specific computer model; any Apple II could use either format by swapping the boot PROM on the controller card. But by the early 1980s, the 16-sector format had become the standard and DOS 3.2 was largely forgotten.

Standard Apple II disk images — `.dsk` and `.do` files — are straightforward copies of the decoded sector data from a 16-sector disk: 140 KB laid out sequentially, track by track, sector by sector. They throw away everything about *how* that data was encoded on disk: the marker bytes, the sync gaps, the GCR encoding, the bit timing. For a standard DOS 3.3 disk, this is fine — the encoding is uniform and predictable, so the sector data is all you need. For a copy-protected disk, it's catastrophic. The protection *is* the encoding.

## What Is a WOZ File?

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

The goal: understand exactly how this disk boots, what copy protection mechanisms are at work, and extract a clean game binary — not just get the game running, but understand every byte between the magnetic surface and `JMP $4000`.

The one thing we know for certain is where to start. No matter what else the disk does, **track 0, sector 0 must be in the format the P6 Boot ROM expects** — 6-and-2 encoding, `D5 AA 96` address prolog, `D5 AA AD` data prolog — because that 256-byte ROM is the only fixed point in the system. It finds sector 0, loads 256 bytes to `$0800`, and jumps to `$0801`. After that, the code at `$0801` is in charge. It can build its own GCR tables, search for its own marker bytes, decode sectors in its own format, and lay out data in ways no standard tool would recognize. But that first sector must play by the rules — and that's where the analysis begins.

---

## Phase 1: Reading the WOZ File

### First Contact with woz_reader.py

The first tool written was `woz_reader.py` — a straightforward WOZ2 format parser. The WOZ2 file format stores each track as a circular bit stream with metadata: the number of valid bits, the bit timing, and a `TMAP` (track map) that maps quarter-tracks to physical data chunks.

The first surprise came immediately. A standard Apple II DOS 3.3 disk has 35 tracks (0 through 34). This disk has only **14 tracks** (0 through 13). Tracks 14-34 are empty. The entire game — code, graphics, title screen, everything — fits in 14 tracks. That's only 40% of the disk's capacity.

This was the first hint that something unusual was going on. DOS 3.3 needs a catalog track, VTOC, and a filesystem. This disk has none of that. It's a raw boot disk with its own custom loader.

### woz_analyze.py: The Nibble Landscape

The next step was `woz_analyze.py`, which converts each track's raw bit stream into nibbles (valid disk bytes are $96-$FF on the Apple II — any byte with the high bit set and specific bit patterns) and scans for known marker sequences.

Each sector on a track is laid out as two fields separated by gaps of sync bytes (self-clocking byte patterns that let the hardware regain bit synchronization). The **address field** comes first — it identifies which sector this is (volume, track number, sector number, and a checksum). The **data field** follows — it carries the 256 bytes of actual content, plus its own checksum. Each field has its own three-byte **prolog** that marks the beginning and its own three-byte **epilog** (typically `DE AA EB`) that marks the end. So a complete sector on the nibble stream looks like:

```
[sync bytes] [address prolog] [address data] [address epilog]
[sync bytes] [data prolog]    [sector data]  [data epilog]
```

The RWTS (Read/Write Track/Sector — the disk I/O routine) finds sectors by scanning the nibble stream for an address field prolog, reading the sector number from the address data, then scanning forward for the data field prolog to read the payload.

On a standard 16-sector disk, you expect to see `D5 AA 96` as the address field prolog and `D5 AA AD` as the data field prolog. On a 13-sector disk (the older format used by DOS 3.2), the address field prolog is `D5 AA B5`. These three-byte sequences were chosen because no valid GCR-encoded data can accidentally produce them — the value `$D5` is deliberately excluded from the GCR encoding tables, so `$D5` appearing in the nibble stream can only be a marker.

Track 0 had markers from **both** formats.

---

## Phase 2: The Dual-Format Track

A standard Apple II disk uses a single encoding format — every track is either 13-sector (5-and-3) or 16-sector (6-and-2), never a mix. The first real discovery was that this disk breaks that rule. Track 0 contains sectors in *two different encoding formats* on the same physical track:

- **One** sector using 6-and-2 encoding (16-sector format, `D5 AA 96` address prolog)
- **Thirteen** sectors using 5-and-3 encoding (13-sector format, `D5 AA B5` address prolog)

That's 14 sectors total — neither the 13 nor 16 that any standard format would produce. But the sector counts 13 and 16 were only conventions of the standard operating systems; custom code could write whatever it wanted up to the track's physical capacity. Note that both formats have their own sector 0: the 6-and-2 sector 0 (the boot sector) and a separate 5-and-3 sector 0. They coexist on the same track because their address field prologs are different (`D5 AA 96` vs `D5 AA B5`) — the RWTS searching for one format simply skips over sectors in the other. `nibbler decode 0` confirms this, showing both a 6-and-2 sector 0 and 5-and-3 sectors 0 through 12.

This is a deliberate copy protection choice. As described above, the boot ROM only reads the one 6-and-2 sector — that works fine. But a DOS 3.3 copier expecting 16 sectors of 6-and-2 would only find one sector on track 0 instead of 16.

The boot sector, once loaded at `$0800`, contains code that switches to reading the 5-and-3 sectors. The remaining 13 sectors (including that second sector 0) carry the actual boot loader and RWTS routines.

**Why 5-and-3?** By 1981, the 5-and-3 format was obsolete — replaced by 6-and-2 years earlier. Fewer copy tools supported it, and mixing it with 6-and-2 on the same track was virtually unheard of. It's an obscure enough format that many copiers simply couldn't handle it.

---

## Phase 3: Disassembling the Boot Code

### The Boot Sector ($0800)

The 6-and-2 boot sector loads at `$0800`. Disassembling it with `disasm_rwts.py` revealed a compact piece of code that:

1. Relocates itself from `$0800` to `$0200`
2. Jumps to `$020F`
3. Builds the 5-and-3 GCR decode table at `$0800`
4. Begins reading 5-and-3 sectors

The relocation is clever — the code needs the `$0800` region for the GCR table, so it copies itself out of the way first. The GCR (Group Coded Recording) decode table maps the 32 valid 5-and-3 disk nibble values back to 5-bit data values. Building this table programmatically (rather than storing it as a literal table) saves precious boot sector space.

### Self-Modifying Code at $0237

One of the more devious tricks lives in the boot code. After the GCR table is built and the first 5-and-3 sector is read and decoded (loading stage 2 code to `$0300`-`$03FF`), the boot code at `$0237` patches two bytes in the freshly loaded stage 2:

```
$0237: LDA #$A9       ; opcode for LDA immediate
$0239: STA $031F      ; patch first byte
$023C: LDA #$02
$023E: STA $0320      ; patch second byte
$0241: JMP $0301      ; enter stage 2
```

Before the patch, `$031F`/`$0320` contain `09 C0` (`ORA #$C0`). After the self-modification, they become `A9 02` (`LDA #$02`). In context, the code at `$031A` does `TXA; LSR; LSR; LSR; LSR` to compute the slot number from `X` (slot × 16). The unpatched `ORA #$C0` combines this with `$C0` to form a Disk II I/O page address. The patched `LDA #$02` discards the computation and hardcodes `$02`. This changes how the RWTS sets up its indirect jump target between the initial boot read (which needs the slot-based address) and all subsequent sector reads (which use the fixed stage 2 entry point).

If you're doing static disassembly — just reading the bytes on disk — you see `ORA #$C0` and get a misleading picture of what the code actually does at runtime. The patching code at `$0237` is in the boot sector (relocated to `$0200`), while the patched bytes at `$031F`/`$0320` are in the first 5-and-3 sector (loaded to `$0300` as stage 2). You have to trace the execution across both regions to see the full picture.

This is the kind of trick that makes a reverse engineer's life difficult: the code on disk is not the code that runs.

---

## Phase 4: The 6502 Emulator

### Why Emulation?

At some point, static analysis hits a wall. The boot code is self-modifying, the GCR decode table gets deliberately modified at runtime as a copy protection measure (the details of how and why are the subject of Phase 5), and the post-decode algorithms are complex enough that hand-tracing is error-prone. The solution: build an emulator.

`emu6502.py` is a cycle-level 6502 CPU emulator written in Python. It implements all 256 opcodes — including the **29 undocumented NMOS 6502 opcodes** that "officially" don't exist but that real hardware executes in well-known (if bizarre) ways.

Implementing all 256 opcodes was a deliberate choice for correctness: since the emulator would be running arbitrary code loaded from disk, any unimplemented opcode would silently produce wrong results. As it turned out, the Apple Panic boot code does not use any undocumented opcodes — but we couldn't have known that before running it. The game code itself (`$4000`-`$A7FF`) also uses only documented instructions.

### Disk I/O Soft Switches

A CPU emulator alone isn't enough. The boot code reads the disk by accessing Apple II soft switches — memory-mapped I/O addresses in the `$C0Ex` range. The Disk II controller uses:

- `$C08C` (with slot offset): read data latch
- `$C08E`: set read mode
- `$C08A`: select drive 1

The emulator needed to simulate these soft switches by feeding nibbles from the WOZ bit stream whenever the emulated CPU reads from `$C0EC` (slot 6 data latch). This meant implementing a virtual Disk II controller that converts the WOZ bit stream into the sequence of nibbles the CPU would see on real hardware.

---

## Phase 5: The GCR Table Corruption

With the emulator running, we could watch the boot process unfold step by step. After the RWTS builds the standard 5-and-3 GCR decode table at `$0800` and uses it to read the very first 5-and-3 sector (stage 2 at `$0300`), the stage 2 loader at `$0301` does something unexpected — it modifies the GCR table before reading anything else:

```
$0301: LDA $0800,Y    ; load GCR table entry (Y starts at $99)
$0304: ASL            ; shift left
$0305: ASL            ; shift left
$0306: ASL            ; shift left
$0307: STA $0800,Y    ; store back
$030A: INY            ; next entry
$030B: BNE $0301      ; loop until Y wraps to 0
```

The `Y` register enters this loop at `$99` (carried over from the preceding boot code). The loop applies `ASL` (Arithmetic Shift Left) **three times** to every byte in the GCR table from `$0899` through `$08FF` — the upper 103 entries. Each ASL shifts the byte left by one bit, so three ASLs effectively multiply by 8 and zero out the low 3 bits. The upper portion of the GCR table, which should contain values like `$00` through `$1F`, now contains values like `$00`, `$08`, `$10`, `$18`, etc.

**Why does this work?** The key mathematical insight is that XOR distributes over bit shifts:

```
(A << 3) XOR (B << 3) = (A XOR B) << 3
```

The 5-and-3 data checksum is computed by XORing all decoded values together. If every value in the affected range is shifted left by 3, the XOR checksum is also shifted left by 3 — it's still zero if the original checksum was zero. So checksums still pass, but the *values* are wrong if you use a standard, uncorrupted table.

This is the copy protection trap: every sector after that first 5-and-3 read — the rest of track 0 and all of tracks 1 through 13 — was written on the original disk using this modified GCR table. The boot code must apply the same modification before reading those sectors, and its post-decode algorithm is designed to work with the modified values. A copier that reads the raw disk nibbles perfectly but decodes them with a fresh, standard table gets garbage for every sector on the disk.

---

## Phase 6: The $0346 Post-Decode Permutation

Standard 5-and-3 encoding stores 256 bytes as 411 GCR nibbles: 154 "secondary" nibbles (carrying the low bits) and 256 "primary" nibbles (carrying the high bits). The standard Apple II post-decode routine at `$02D1` reassembles these into 256 output bytes in a specific order.

Apple Panic uses `$02D1` exactly once — for the very first sector read (5-and-3 sector 0 into `$0300`-`$03FF`, the stage 2 loader code). After that first read, the self-modifying code at `$0237` patches the RWTS call vector, and all subsequent sectors are decoded through a custom post-decode routine at `$0346` that produces bytes in a **different order**. The same 256 values come out, but they're permuted — placed in different positions in the output buffer.

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

After implementing the GCR table corruption and the `$0346` permutation, we could decode 12 of the 13 five-and-three sectors on track 0. Sector 1 — the one that loads to `$B700`, the critical game loader entry point — failed its data checksum every time.

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

The P6 Boot ROM loads the 6-and-2 boot sector to `$0800` and jumps to `$0801`. The boot code relocates to `$0200`, builds the standard GCR table, and reads one 5-and-3 sector using that standard table — loading the stage 2 code to `$0300`. After self-modifying stage 2, it jumps to `$0301`. Stage 2 then modifies the GCR table, reads sectors 0-9 to `$B600`-`$BFFF` using the modified table, and jumps to `$B700`.

A small puzzle here: the loading loop re-reads sector 0 (the same sector already decoded to `$0300`), this time using the modified GCR table and the `$0346` post-decode, storing the result at `$B600`. Since sector 0 was originally written with the standard GCR table, decoding it with the modified table produces garbled data — 227 of 256 bytes differ from the correct decode at `$0300`. This turns out to be harmless: the game loader enters at `$B700` (sector 1), and no code ever references the `$B600` page. The RWTS loaded at `$B800`-`$BFFF` does include write routines that reference `$B600` as a GCR encode table, but the game never writes to disk — after booting, it's purely RAM-resident. The loop simply starts at sector 0 because that's the simplest counter; skipping sector 0 would have required extra code with no benefit.

Memory map after stage 1:
```
$0200-$03FF  Boot RWTS (relocated boot sector + stage 2 loader)
$0800-$08FF  5-and-3 GCR decode table (corrupted)
$B600-$B6FF  Sector 0 (garbled re-read — not used)
$B700-$BFFF  Track 0 sectors 1-9 (game loader + RWTS)
```

### Stage 2: Tracks 1-5 to $0800-$48FF

The game loader at `$B700` reads tracks 1-5 (65 sectors at 13 sectors per track) into `$0800`-`$48FF`. This region contains:

- `$1000`-`$1027`: RWTS patcher — patches `$D5` to `$DE` in address field search, sets graphics mode, then jumps to `$1200`
- `$1100`-`$11C0`: HGR shape rendering engine — an XOR sprite blitter with pixel-level horizontal shifting. Supports three entry points: row address lookup (`$1100`), shape pointer lookup (`$1115`), and full shape draw with shift (`$112D`). The XOR blit means calling it twice at the same position erases the shape, enabling animation without redrawing the background.
- `$1200`-`$1261`: Sound effects (descending tone, rising tone, chirp) and a general-purpose delay routine
- `$1262`-`$12AA`: Display sequence player — a command interpreter that reads 3-byte entries (row, shape index, shift parameter) and animates shapes sliding across the HGR screen
- `$12AB`-`$1366`: Title screen setup — draws the apple logo, animated title text, character sprites, and decorative elements using the XOR blitter
- `$1367`-`$17FF`: Shape coordinate and timing data tables for the animation sequences
- `$1800`-`$19FF`: Pre-computed HGR row address lookup table (192 entries — needed because Apple II HGR memory layout is notoriously non-linear)
- `$1A00`-`$1DFF`: Shape and sprite pointer tables
- `$1E00`-`$1FFF`: Pixel shift tables (7 positions) — pre-shifted shape data for smooth horizontal animation without per-pixel rotation at draw time
- HGR bitmap data for the title screen apple shape and text

Then comes the marker patch — code at `$1000` sets the Apple II soft switches for hi-res graphics display, then rewrites the RWTS to search for `$DE` instead of `$D5` as the first byte of address field prologs, then jumps to `$1200` for the title screen display:

```
$1000: LDA $C057       ; HGR mode on
$1003: LDA $C054       ; page 1
$1006: LDA $C052       ; full screen
$1009: LDA $C050       ; graphics mode
       ...
$1015: LDA #$DE
$1017: STA $B8F6,Y    ; patches CMP #$D5 → CMP #$DE at $B976
$101A: STA $BE75,Y    ; patches LDA #$D5 → LDA #$DE at $BEF5
       ...
$1027: JMP $1200       ; title screen display
```

Note the order: the RWTS patch happens *before* the title screen is displayed, not after. This matters because the patch only affects tracks 6-13 — tracks 1-5 have already been loaded using the unpatched RWTS (which still searches for `$D5`).

The address prolog structure across all tracks is a three-byte sequence where the **second byte** varies per track. The game loader patches `$B980` (the second-byte comparison operand) before reading each track, using a lookup table stored at `$0400`:

```
Address prolog format:  [first] [second] B5

Track:   0   1   2   3   4   5   6   7   8   9  10  11  12  13
First:  D5  D5  D5  D5  D5  D5  DE  DE  DE  DE  DE  DE  DE  DE
Second: AA  BE  BE  AB  BF  EB  FB  AA  FA  AA  AB  EA  EF  BB
Third:  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5  B5
```

Track 0 uses the standard `D5 AA B5` prolog (readable by the boot RWTS at `$0200`). Tracks 1-5 keep `D5` as the first byte but vary the second byte — a copier scanning for the standard `D5 AA B5` finds nothing. Tracks 6-13 additionally change the first byte to `DE` (after the `$1000` patch), adding a second layer of obfuscation. The third byte is always `B5` (the 5-and-3 format identifier).

This is one of the most layered protections on the disk: even a copier that knows to handle `$DE` and non-standard second bytes would need the complete per-track lookup table to find any sectors.

### Stage 3: Tracks 6-13 to $4000-$A7FF

After the title screen displays and the player presses a key, the loader reads tracks 6-13 (104 sectors) into `$4000`-`$A7FF` — approximately 27KB of game code and data. During this read, the game loader calls the title screen animation routine (`JSR $1290`) three times between each track's sector reads, keeping the title screen visually active while the disk loads. This interleaving of disk I/O and animation is a polished touch — the player sees a living title screen rather than a frozen display during the ~10 seconds of game loading. Then: `JMP $4000`. The game begins.

The full boot took approximately **69.8 million emulated 6502 instructions** — a testament to how many times the RWTS loops waiting for the right sector to come around under the read head.

---

## Phase 9: Verification

With the emulated memory dump in hand, we needed to verify that the decode pipeline — WOZ reader, bit-doubling, GCR table corruption, custom post-decode permutation, 6502 emulation — had produced correct results.

The verification was multi-pronged:

- **Structural validation**: The extracted binary at `$4000`-`$A7FF` disassembles cleanly as 6502 code. The recursive-descent disassembler found 104 well-formed subroutines with consistent calling conventions, proper stack discipline, and no orphaned code paths.
- **Behavioral validation**: The relocation routine at `$4000` correctly copies sprite data from `$4800`-`$5FFF` to `$0800`-`$1FFF`, builds an identity table at `$4400`, and transfers control to the game entry point at `$7000`.
- **Cross-reference validation**: Hardware register accesses (`$C050`-`$C057` for graphics mode, `$C000`/`$C010` for keyboard, `$C030` for speaker) are all consistent with a legitimate Apple II game.
- **Data validation**: Sprite bitmaps at `$6000`-`$6EFF` render correctly as 7-pixel-wide HGR frames when interpreted as pre-shifted Apple II hi-res data.

Every layer of the decode pipeline was confirmed: the WOZ bit stream produces valid nibbles, the GCR decode produces valid bytes, the post-decode permutation produces valid code, and the emulated boot sequence loads a functional game.

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
- Two identity tables (256 bytes where `table[n] = n`): one at `$4400` (built explicitly by the relocation routine at `$4000`) and one at `$1800` (copied from `$5800` during relocation of sprite data from `$4800`-`$5FFF` to `$0800`-`$1FFF`)
- No undocumented 6502 opcodes anywhere — neither in the boot loader nor in the game code

---

## Phase 11: Packaging as nibbler

The final step was consolidating the ~38 individual scripts into a reusable Python package called `nibbler`. The package provides:

- **10 modules** covering WOZ file I/O, bit-stream handling, GCR decoding (both 5-and-3 and 6-and-2), 6502 emulation, and disassembly
- **7 CLI subcommands**: `info`, `scan`, `protect`, `boot`, `decode`, `dsk`, `disasm`
- Works on any WOZ file, not just Apple Panic

The journey from `woz_reader.py` (a quick script to dump WOZ headers) to `nibbler` (a general-purpose WOZ analysis toolkit) mirrors the project itself: each new challenge required a new tool, and eventually there were enough tools that a package structure made sense.

---

## The Nine Layers of Protection

Looking back, Apple Panic's copy protection operates in nine distinct layers:

| # | Mechanism | Defeats |
|---|-----------|---------|
| 1 | Dual-format track 0 (6-and-2 + 5-and-3) | Standard DOS 3.3 copy utilities |
| 2 | Invalid address field checksums (all 13 sectors) | Nibble copiers that validate headers |
| 3 | GCR table corruption (ASL ×3 on upper entries) | Raw nibble copies decoded with fresh tables |
| 4 | Intentionally bad checksum on sector 11 | Copiers that validate all sector checksums |
| 5 | Custom post-decode permutation ($0346 vs $02D1) | Manual analysis with standard decode assumptions |
| 6 | Self-modifying code | Static disassembly |
| 7 | Per-track second-byte variations in address prologs | Copiers expecting standard `D5 AA B5` address markers |
| 8 | Non-standard `$DE` first byte on tracks 6-13 | Copiers looking for `$D5` as address prolog first byte |
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
$020F: Boot RWTS
  │  Read 5-and-3 sector 0 → $0300 (stage 2 code)
  │  Post-decode via $02D1 (standard, one-time use)
  │  Self-modify at $0237: patch $031F/$0320
  │
  ▼
$0301: Stage 2 Loader
  │  Corrupt GCR table (ASL ×3 on $0899-$08FF)
  │  Load sectors 0-9 → $B600-$BFFF (post-decode via $0346)
  │  JMP ($003E) = JMP $B700
  │
  ▼
$B700: Game Loader
  │  Copy per-track lookup table to $0400
  │  Read tracks 1-5 → $0800-$48FF (address prolog: D5 [per-track] B5)
  │  JSR $1000:
  │    Set HGR mode
  │    Patch RWTS: $D5 → $DE at $B976 (address prolog first byte)
  │    JMP $1200: Title screen display
  │  JSR $1290: Animation routine
  │  Read tracks 6-13 → $4000-$A7FF (address prolog: DE [per-track] B5)
  │    (3× JSR $B7DA animation calls between each track, tracks ≥ 6 only)
  │
  ▼
$4000: GAME START
  (69.8M emulated instructions from power-on)
```

---

## Final Memory Map

After all 14 tracks are loaded and the relocation routine at $4000 completes, the game's memory layout is:

### Boot Infrastructure (Track 0)

| Address | Size | Contents |
|---------|------|----------|
| `$0200-$02FF` | 256 | Boot RWTS (relocated from $0800 boot sector) |
| `$0300-$03FF` | 256 | Stage 2 loader (loaded from 5-and-3 sector 0, post-decoded via $02D1) |
| `$B600-$B6FF` | 256 | Garbled data (sector 0 re-read with corrupted GCR table, unused) |
| `$B700-$BFFF` | 2,304 | Game loader + RWTS (sectors 1-9 from track 0) |

### Tracks 1-5 → $0800-$48FF (Overwritten by Relocation)

The game loader reads 65 sectors from tracks 1-5 into $0800-$48FF. This region initially contains the title screen code ($1000-$1FFF), but the $4000 relocation routine copies most of it to lower memory, overwriting the title screen. What survives:

| Address | Source | Contents |
|---------|--------|----------|
| `$0400-$04FF` | $4400 | Game loop dispatcher + per-track address prolog table |
| `$0500-$07FF` | $4500 | Text page blanks / screen holes |
| `$0800-$097F` | $4800 | Platform tile bitmaps (8 shift variants, 3×16 each) |
| `$0980-$09FF` | $4980 | Loader artifact ("EDASM.OBJ" string) + padding |
| `$0A00-$0BFF` | $4A00 | Character sprite source frames (7 frames × 64 bytes) |
| `$0C00-$0D7C` | $4C00 | Background theme tile patterns (4 themes + 4 duplicates) |
| `$0D7D-$0FFF` | $4D7D | Runtime scratch / enemy spawn tables |
| `$1000-$15FF` | $5000 | Enemy sprite data (Apple, Butterfly, Mask × 8 shifts × 2 frames) |
| `$1600-$16FF` | $5600 | Sprite transparency masks |
| `$1700-$17FF` | $5700 | Solid fill pattern |
| `$1800-$18FF` | $5800 | Identity table ($00-$FF) |
| `$1900-$1FFF` | $5900 | Game state variables |

### Tracks 6-13 → $4000-$A7FF (Game Code)

104 sectors from tracks 6-13 load directly to $4000-$A7FF (26,624 bytes). After the relocation routine runs, the layout is:

| Address | Size | Contents |
|---------|------|----------|
| `$4000-$4024` | 37 | Relocation routine (runs once, then dead code) |
| `$4025-$402A` | 6 | Game startup bridge: `JMP $7000` |
| `$402B-$43FF` | 981 | Game subroutines (sprite animation, player helpers) |
| `$4400-$5FFF` | 7,168 | Source data for relocation (overwritten: now contains identity table remnant at $4400) |
| `$6000-$6EFF` | 3,840 | Pre-shifted player sprites (5 animations × 7 shifts × 48 bytes) |
| `$6F00-$6FFF` | 256 | Platform tile patterns (mask/top/bottom × 8 shifts) |
| `$7000-$70BA` | 187 | Game initialization (`GAME_START` entry point) |
| `$70BB-$70C0` | 6 | Score (6 BCD digits) |
| `$70C1-$74E8` | 1,064 | Game state, input handling, screen management |
| `$74E9-$7FFF` | 2,839 | Main game loop, graphics engine, level drawing |
| `$8000-$85FF` | 1,536 | Enemy state tables (10 slots) and sprite management |
| `$8600-$A7FF` | 8,704 | Enemy AI, collision detection, scoring, sound |

### HGR Screen Pages (Not Loaded — Drawn at Runtime)

| Address | Size | Contents |
|---------|------|----------|
| `$2000-$3FFF` | 8,192 | HGR Page 1 (display) |
| `$4000-$5FFF` | 8,192 | HGR Page 2 (background snapshot for XOR sprite restore) |

Note: HGR Page 2 overlaps the game code region $4000-$5FFF. The game uses page flipping — page 1 for display, page 2 as a background buffer. The relocation routine copies sprite/tile data out of $4400-$5FFF before the game begins drawing, so the overlap is intentional.

### Summary

| Region | Size | Purpose |
|--------|------|---------|
| Boot infrastructure | ~3 KB | RWTS + loaders (track 0) |
| Relocated game data | ~7 KB | Sprites, tiles, tables ($0400-$1FFF) |
| Game code + data | ~27 KB | Everything at $4000-$A7FF |
| **Total unique data** | **~37 KB** | From 14 tracks of a 5.25" floppy |

---

*Total tools written: ~39 Python scripts. Total emulated instructions: 69.8 million. Total layers of copy protection: 9. Total hours lost to the bit-doubling bug: too many.*

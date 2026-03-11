# Copy Protection Mechanisms: Apple Panic - Disk 1, Side A

Analysis of copy protection techniques discovered on Track 0 of the WOZ disk image.

---

## 1. Dual-Format Track 0

Track 0 contains **both** 6-and-2 (16-sector) and 5-and-3 (13-sector) format data on the same track. The Disk II P6 Boot ROM (341-0027) reads the single 6-and-2 boot sector at `$0800` using standard 16-sector `D5 AA 96` / `D5 AA AD` markers. The boot sector code at `$0800` then switches to reading 5-and-3 encoded sectors (`D5 AA B5` address / `D5 AA AD` data markers) for the remaining 13 sectors. This means a standard DOS 3.3 copy utility would fail because it only expects one format.

**Details:**

- 6-and-2 boot sector: address prolog `D5 AA 96`, data prolog `D5 AA AD`, 342 GCR bytes
- 5-and-3 sectors: address prolog `D5 AA B5`, data prolog `D5 AA AD`, 411 GCR bytes (154 secondary + 256 primary + 1 checksum)
- Track physical sector order: S11, S8, S5, S2, S12, S9, S6, S3, S0, S10, S7, S4, S1

---

## 2. Invalid Address Field Checksums

**All 13** five-and-three sector address fields have deliberately wrong checksums. The standard RWTS address verification code would reject every sector. The custom boot RWTS at `$0200` simply skips address checksum verification entirely.

**Details:**

- Standard check: `Volume XOR Track XOR Sector` should equal the checksum byte
- All 13 sectors fail this check
- The boot RWTS code reads vol/track/sector fields but never verifies the checksum
- A nibble copier that validates address checksums would reject all sectors

---

## 3. GCR Translation Table Corruption (Self-Modifying Code)

The stage 2 loader at `$0300` deliberately corrupts the 5-and-3 GCR translation table at `$0800` before using it. After the boot RWTS builds the standard table, the stage 2 code applies ASL x3 (shift left 3 times) to entries `$0899`-`$08FF` (positions `$99`-`$FF` in the table).

**Details:**

- Code at `$0301`-`$030C`: `LDX #$32`, loop: `ASL $0899,X` / `ASL $0899,X` / `ASL $0899,X` / `DEX` / `BPL` loop
- This shifts the upper 103 table entries left by 3 bits, zeroing the low 3 bits
- Mathematical property preserved: XOR of `(val<<3)` = `(XOR of val)<<3`, so data checksums still work
- The `$0346` post-decode routine is designed to work with these corrupted values
- A copier that builds its own fresh GCR table would decode data incorrectly

---

## 4. Intentionally Bad Data Checksum on Sector 11

Sector 11 has data that fails checksum verification with both the original and corrupted GCR tables. All other sectors (0-10, 12) pass with the original table when using proper bit-level wrap handling.

**Details:**

- Sector 11 fails: original = `$09`, corrupted = `$48`
- Sector 11 is not used by the boot loader (sectors 0-9 map to `$B600`-`$BFFF`)
- Sector 1 (`$B700`) was previously thought to have a bad checksum, but this was caused by the track boundary wrap issue (see section 7). With proper bit-doubling, sector 1's checksum passes correctly
- The stage 2 loader code does **not** verify data checksums -- it reads and decodes without checking

---

## 5. Custom Post-Decode Algorithm ($0346)

The stage 2 loader uses a non-standard post-decode algorithm at `$0346` that produces bytes in a different order than the standard `$02D1` algorithm. Even if someone managed to read the raw nibbles correctly, applying the standard 5-and-3 post-decode would produce scrambled output.

**Details:**

- Standard `$02D1`: processes `secondary[0..153]` sequentially, building output in primary order
- Custom `$0346`: processes in reverse (X from `$32` downward), interleaving 5 groups per iteration
- Permutation mapping: `$0346 output[5k+n]` = `$02D1 output[offset-k]` where offsets are `[50, 101, 152, 203, 254]` for `n=[0,1,2,3,4]`
- Byte 255 is special: `$0346` reconstructs full 8 bits from `secondary[153]` and `primary[255]`
- The two algorithms are mathematically equivalent permutations -- they produce the same 256 byte values in different positions

---

## 6. Self-Modifying Boot Code

The boot RWTS (`$0200`) contains self-modifying code that patches its own instructions during execution.

**Details:**

- At `$031B`-`$0320`: patches bytes at `$031F`/`$0320` from `ORA #$C0` to `LDA #$02`
- This redirects the RWTS read vector, changing behavior between the initial boot read and subsequent sector reads
- Makes static analysis of the code misleading

---

## 7. Bit-Stream Wrap-Around Handling

Sector 1's data field on track 0 happens to span the WOZ bit-stream boundary. The WOZ file stores each track as a linear bit stream with a defined bit count, but physically a floppy disk track is a continuous circle with no start or end. Sector 1's 411 data nibbles start near the end of the bit stream and wrap past its boundary.

When converting bits to nibbles, there is 1 leftover bit at the boundary. A naive converter that processes one revolution of bits, then appends nibbles from a second pass, will misalign all nibbles after the wrap point because that leftover bit is discarded. The fix is to double the bit stream before nibble conversion ("bit-doubling"), which correctly simulates the continuous circular nature of the physical disk.

**Note:** The sector placement at the wrap boundary may not be deliberate copy protection -- it could simply be an artifact of how the WOZ file was created (the physical disk has no inherent start/end point, so whichever index pulse position was chosen as bit 0 determines which sectors span the boundary). Regardless, correct handling requires bit-level wrap, not nibble-level wrap.

**Effect:** A naive WOZ reader that converts bits to nibbles for a single revolution produces 6273 nibbles with incorrect data for sector 1. With proper bit-doubling, the checksum passes and the decoded data is valid 6502 code.

**Technical detail:** The standard approach of wrapping nibble arrays (`nib + nib[:N]`) does NOT fix the problem because the nibble boundaries themselves are wrong -- the leftover bit at the wrap point means all subsequent nibbles are shifted by 1 bit

---

## 8. Non-Standard Address Field Markers on Tracks 1+ ($DE instead of $D5)

The intermediate code loaded from tracks 1-5 at `$1000` patches the RWTS at runtime to use `$DE` instead of the standard `$D5` as the first byte of address field prologs on subsequent tracks.

**Details:**

- Code at `$1000`: `LDA $C057` / `LDA $C054` / etc. (set up display), then:
- `$1015: LDA #$DE`
- `$1017: STA $B8F6,Y` (Y=$80) → patches `$B976` from `$D5` to `$DE`. This is the operand of `CMP #$D5` in the address field search routine at `$B975`, changing it to `CMP #$DE`
- `$101A: STA $BE75,Y` (Y=$80) → patches `$BEF5` from `$D5` to `$DE`. This is the operand of `LDA #$D5` in the address field write routine at `$BEF4`
- After patching, the code zeroes itself at `$1080` and jumps to `$1200` (title screen display)

**Address field markers by track:**
- Track 0: Standard `D5 AA xx` (where `xx` varies per track via `$B7CB` patching)
- Tracks 1+: `DE AA xx` (first byte changed from `$D5` to `$DE`)

**Per-track third marker byte:** The `$B7CB` routine also patches the third address field byte on a per-track basis using a lookup table originally at `$B7E2` (24 bytes, copied to `$0400` at boot):
```
Track:  0   1   2   3   4   5   6   7   8   9  10  11  12  13
Table: 00  14  14  21  35  61  73  20  50  82  23  60  67  91
Value: AA  BE  BE  AB  BF  EB  FB  AA  FA  AA  AB  EA  EF  BB
```
(Value = Table[track] | $AA, stored at $B980 as the `CMP` operand)

**Effect:** A copier that searches for standard `D5 AA B5` address fields on tracks 1+ will find nothing. Even a copier that knows about `DE` must also handle the per-track third byte variations.

---

## Memory Map

```
Track 0 Sectors -> Memory Layout:
  Sector 0  -> $B600  (stage 2 loader code)
  Sector 1  -> $B700  (secondary loader entry point)
  Sector 2  -> $B800  (5-and-3 encoder)
  Sector 3  -> $B900  (address field reader + post-decode)
  Sector 4  -> $BA00  (track seek + timing + GCR encode table)
  Sector 5  -> $BB00  (buffer/table data)
  Sector 6  -> $BC00  (RWTS routines)
  Sector 7  -> $BD00  (RWTS entry: disk controller I/O)
  Sector 8  -> $BE00  (seek + format routines)
  Sector 9  -> $BF00  (address/data field writer)
  Sectors 10-12 -> unused by boot loader

Tracks 1-5 (65 sectors) -> $0800-$48FF:
  $1000: Intermediate code (title screen, RWTS patching)
  $1200: Display/sound routines
  (remaining: HGR title screen bitmap + tables)

Tracks 6-13 (104 sectors) -> $4000-$A7FF:
  $4000: Game entry point (JMP $4000)
  $4000-$5FFF: Game initialization + screen setup
  $6000-$A7FF: Main game code + data
```

---

## 9. Non-Standard Sector/Track Numbers in Address Fields

On tracks 1-6, 8, and 10-13, the address fields contain deliberately non-standard sector and track numbers. Instead of sector numbers 0-12 (the valid range for 13-sector format) and track numbers matching the physical track position, these fields use values like sector 215, 253, 255 and track numbers in the 200+ range.

**Details:**

- The boot code's custom RWTS knows exactly which non-standard sector numbers to search for on each track
- A standard copier expecting sector numbers 0-12 would never find these sectors
- Even a copier that handles all other protection layers (dual format, $DE markers, per-track third bytes) would fail if it validates sector/track number ranges
- Tracks 7 and 9 retain standard sector numbers (0-12) alongside additional non-standard "decoy" address fields with garbage values
- The non-standard values arise from the GCR corruption applied to the address field data — the ASL×3 shifts corrupt the sector/track/volume bytes, but the custom RWTS is designed to work with these corrupted values

**Effect:** This is an additional layer on top of the per-track third-byte variations. Even if a copier handles $DE markers and variable third bytes, it must also accept arbitrary sector/track numbers in address fields rather than rejecting them as invalid.

---

## Effectiveness Assessment

These protections work in layers:

1. **Dual format** prevents standard DOS copy utilities
2. **Bad address checksums** prevent nibble copiers that validate headers
3. **GCR table corruption** means raw nibble copies decoded with fresh tables get wrong data
4. **Bad data checksum on sector 11** prevents copiers that validate data on all sectors
5. **Custom post-decode** means even manual analysis requires understanding the permutation
6. **Self-modifying code** makes static disassembly unreliable
7. **Bit-stream wrap** requires correct bit-level handling when converting WOZ tracks to nibbles
8. **Non-standard $DE markers** on tracks 1+ prevents copiers looking for standard $D5 address fields, with per-track third-byte variations adding further complexity
9. **Non-standard sector/track numbers** in address fields prevent copiers that validate sector ranges

## Full Boot Flow

```
P6 ROM -> $0801 (boot sector at $0800)
  -> relocate to $0200, JMP $020F
  -> build 5-and-3 GCR table at $0800
  -> RWTS reads sector 0 (stage 2 code)
  -> patch $031F/$0320 (self-modifying)
  -> $0301: corrupt GCR table (ASL x3)
  -> load sectors 0-9 to $B600-$BFFF
  -> JMP ($003E) = JMP $B700

$B700 (secondary loader):
  -> read tracks 1-5 to $0800-$48FF (5 tracks x 13 sectors)
  -> JSR $1000 (title screen + patch RWTS: $D5->$DE)
  -> patch $129D with RTS, set up JMP at $0000
  -> JSR $1290 (display routine)
  -> read tracks 6-13 to $4000-$A7FF (8 tracks x 13 sectors, ~27KB game code)
  -> JMP $4000 (GAME START)
```

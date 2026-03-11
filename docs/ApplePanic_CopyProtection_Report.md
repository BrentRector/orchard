# Apple Panic Copy Protection & Disk Format Analysis

> **Note:** This was the initial analysis report, written before the full boot
> emulation was completed. Some early conclusions (particularly about "encryption"
> and "missing address fields") were later corrected through 6502 emulation.
> See `CopyProtection.md` for the definitive analysis, and
> `ReverseEngineeringHistory.md` for the full narrative of the investigation.

## Overview

Apple Panic (Broderbund, 1981) shipped on a custom-formatted 5.25" floppy disk
with **nine layers** of copy protection. This report documents the protection
scheme as preserved in the WOZ2 disk image `Apple Panic - Disk 1, Side A.woz`.

The game uses only **14 of 35 tracks** with **13 sectors per track** (5-and-3
encoding, not 6-and-2), employs **per-track custom address prologues**, **GCR
table corruption**, **a custom post-decode permutation**, **non-standard sector
numbers in address fields**, and **self-modifying boot code**.

---

## 1. Disk Physical Format

### 1.1 Track Layout

| Parameter          | Apple Panic       | Standard DOS 3.3   |
|--------------------|-------------------|---------------------|
| Tracks used        | 14 (0-13)         | 35 (0-34)           |
| Sectors per track  | 13                | 16                  |
| Bytes per sector   | 256               | 256                 |
| Total capacity     | ~46,592 bytes     | 143,360 bytes       |
| Boot format        | Custom (type 3)   | DOS 3.3 (type 1)    |

The WOZ2 INFO chunk identifies the disk as boot format type 3 (custom), meaning
no standard operating system (DOS 3.3 or ProDOS) is present. The game implements
its own complete disk I/O routines.

### 1.2 Nibble Counts

Each track contains approximately 6,270-6,300 nibbles when decoded from the
flux-level WOZ bit stream. Sync byte ($FF) density varies significantly:

- **Track 0**: 792 sync nibbles (12.6%) -- standard gap density
- **Track 1**: 709 sync nibbles (11.3%) -- slightly reduced
- **Track 6**: 279 sync nibbles (4.4%) -- dramatically reduced

The reduction in sync bytes on later tracks is a copy protection measure: bit
copiers that rely on sync byte detection to find sector boundaries will fail on
tracks with minimal sync gaps.

---

## 2. Address Field Protection

### 2.1 Standard vs Custom Prologues

The Apple II disk system identifies sectors using **address fields** that precede
each data field. Standard DOS 3.3 uses the prologue bytes `D5 AA 96`. Apple
Panic uses a different scheme for each track group:

| Track | Address Prologue | Notes                          |
|-------|------------------|--------------------------------|
| 0     | D5 AA 96         | Standard (compatible with ROM) |
| 0     | D5 AA B5         | Additional custom markers       |
| 1     | D5 BE B5         | Custom second byte              |
| 2     | D5 BE B5         | Custom second byte              |
| 3     | D5 AB B5         | Custom second byte              |
| 4     | D5 BF B5         | Custom second byte              |
| 5     | D5 EB B5         | Custom second byte              |
| 6-13  | **NONE**          | No address fields at all        |

**Key observations:**

- Track 0 retains the standard `D5 AA 96` prologue because the Apple II boot
  ROM's sector-read routine at `$C600` only recognizes this pattern. The boot
  sector *must* be readable by the ROM to bootstrap the custom loader.

- Tracks 1-5 replace the second prologue byte with a **track-specific value**
  (`$BE`, `$AB`, `$BF`, `$EB`). This means the disk I/O code must be
  reprogrammed for each track -- a nibble copier using fixed prologue bytes will
  miss these sectors entirely.

- The third byte is always `$B5` instead of the standard `$96`, further
  defeating copiers that search for `D5 AA 96`.

- Tracks 6-13 have **no address markers whatsoever**. The custom loader must
  identify sectors purely by position on the track (sequential read from the
  index hole equivalent, or by counting from a known sync pattern). This is one
  of the most aggressive anti-copy measures possible -- without address fields,
  there is no way for standard disk utilities to identify or reorder sectors.

### 2.2 Address Field Encoding

Where address fields exist (tracks 0-5), they use standard **4-and-4 encoding**
for the volume, track, sector, and checksum bytes:

```
D5 xx B5  [vol_odd] [vol_even] [trk_odd] [trk_even] [sec_odd] [sec_even] [cksum_odd] [cksum_even]  DE AA
```

Each value byte is split into two disk nibbles using the formula:
```
odd_nibble  = (value >> 1) | 0xAA
even_nibble = value | 0xAA
decoded     = ((odd << 1) | 0x01) & even
```

Decoded address field values:

| Track | Volume | Track | First Sector | Checksum |
|-------|--------|-------|--------------|----------|
| 1     | $FE    | $01   | $06          | $E9      |
| 2     | $FE    | $02   | $01          | $EE      |
| 3     | $FE    | $03   | $09          | $E6      |
| 4     | $FE    | $04   | $01          | $EE      |
| 5     | $FE    | $05   | $09          | $E6      |

Volume $FE (254) is used throughout, matching a common Broderbund convention.

### 2.3 Sector Interleave

The sector ordering revealed by address field decoding shows a **custom
interleave pattern** that differs from DOS 3.3's standard skew:

- **Track 0**: 0, 8, 5, 2, 12, 9, 6, 3, [0], 10, 7, 4, 1, 13
- **Track 1**: 6, 3, 0, 10, 7, 4, 1, 11, 8, 5, 2, 12, 13
- **Track 2**: 1, 11, 8, 5, 2, 12, 9, 6, 3, 0, 10, 7, 4, 13
- **Track 3**: 9, 6, 3, 0, 10, 7, 4, 1, 11, 8, 5, 2, 12, 13
- **Track 4**: 1, 11, 8, 5, 2, 12, 9, 6, 3, 0, 10, 7, 4, 13
- **Track 5**: 9, 6, 3, 0, 10, 7, 4, 1, 11, 8, 5, 2, 13

This is a **3-sector skew** pattern (each successive logical sector is 3
physical positions later), optimized for the game's custom loader timing. The
skew allows the loader to process one sector and be ready to read the next
without waiting a full disk rotation.

Note: Sector 13 consistently appears last with volume=0, suggesting it may be a
marker/sentinel sector rather than data.

---

## 3. Data Field Format

### 3.1 Data Prologue

All tracks use the standard data prologue `D5 AA AD`. This is the one invariant
across the entire disk -- the 6-and-2 data encoding mechanism itself is not
modified.

### 3.2 6-and-2 Encoding

The data nibbles within each sector use the **standard 6-and-2 translation
table**. Verification shows 100% valid 6-and-2 nibbles across all tracks:

- Track 0: 100.0% valid
- Track 1: 100.0% valid
- Track 6: 100.0% valid
- Track 13: 100.0% valid

This means the low-level nibble encoding is standard -- the protection and
encryption operate at the byte level *after* 6-and-2 decoding, not at the
nibble level.

Each sector encodes 256 data bytes as:
1. 86 auxiliary nibbles (2-bit fragments, XOR-chained)
2. 256 primary nibbles (upper 6 bits, XOR-chained)
3. 1 checksum nibble

### 3.3 Data Epilogue

The data epilogue is **non-standard** and varies by track:

| Track | Data Epilogue    | Standard? |
|-------|------------------|-----------|
| 0     | DE AA EB         | YES       |
| 1     | AB AB AB AB AB   | NO        |
| 6     | AF DA DD EA DF   | NO        |

Track 0 again uses standard epilogues for boot ROM compatibility. All other
tracks use non-standard epilogue bytes. This serves two purposes:

1. **Copy protection**: Nibble copiers that verify `DE AA EB` epilogues will
   report errors on tracks 1+, potentially aborting the copy.
2. **Anti-analysis**: The varying epilogues make it harder to determine where
   one sector ends and the next begins without the custom loader code.

### 3.4 Checksum Anomaly

The 6-and-2 XOR checksum fails on virtually all sectors except Track 0,
Sector 0 (the boot sector):

- Track 0, Sector 0: Checksum **OK**
- All other sectors: Checksum **BAD**

This is consistent with **post-encoding data modification** -- the sector data
was written with intentionally incorrect checksums, or the data was encrypted
after the standard 6-and-2 checksum was computed. The custom loader presumably
either ignores checksums entirely or computes its own validation after
decryption.

---

## 4. Data Encryption

### 4.1 Evidence of Encryption

The decoded sector data (after standard 6-and-2 decoding) does not contain any
recognizable game code, despite the game being a 43KB 6502 program that should
span most of the disk's 46KB capacity. Specifically:

- **Zero matches** for any of 12 known 16-byte game code patterns
- **Zero matches** for 5-byte pattern fragments
- **Zero matches** with single-byte XOR keys ($01-$FF)
- **Zero sector-level matches** with common XOR keys ($24, $01, $8E, $AA, $AB)
- No recognizable 6502 instruction sequences (JMP, JSR, LDA targets in the
  $6000-$A800 game code range show random distribution)

### 4.2 Encryption Characteristics

The encryption is NOT a simple single-byte or two-byte XOR cipher. Evidence:

- The byte `$24` and `$01` appear with extremely high frequency in tracks 2-5,
  often as repeating `24 01` pairs. This pattern likely represents encrypted
  zero-fill regions (the game has large empty areas in HGR page buffers).

- The "key" varies between tracks and possibly between sectors. Track 2's
  most common byte pair is `24 01`, while track 1 shows `AB 8E` repeating
  in some sectors.

- Some tracks show clear repeating patterns within sectors (e.g., `7E 5B 7E 5B`
  on track 2, `AB 8E AB 8E` on tracks 1 and 3), suggesting the plaintext
  contains repeating data (like sprite shift tables or fill patterns) that is
  XOR'd with a relatively short key.

### 4.3 Likely Encryption Method

Based on the patterns observed, the encryption is most likely a **multi-byte
XOR with a key derived from track and/or sector number**, possibly combined with
a running cipher (where each byte's decryption depends on the previous byte).
The boot code's self-modifying nature (see Section 5) suggests the decryption
routine is constructed dynamically at runtime, making static analysis infeasible.

Common Apple II copy protection encryption techniques from this era include:

- **EOR with track/sector-derived key**: Each sector XOR'd with a value
  computed from its track and sector number
- **Running XOR**: Each byte XOR'd with the previous decrypted byte
- **Table-driven substitution**: A 256-byte substitution table loaded from
  the boot sector or constructed at runtime
- **Multi-stage decryption**: Boot code decrypts a small loader, which
  decrypts the actual game data

---

## 5. Boot Code Obfuscation

### 5.1 Boot Sector Structure

The boot sector (Track 0, Sector 0) loads at address `$0800`. The Apple II boot
ROM reads this single sector and jumps to `$0801`.

```
$0800: $00       ; Sector count = 0 (non-standard; normally 1-15)
$0801: LDY #$00  ; Begin boot code
$0803: LDY $0800,X
$0806: $9C       ; Undocumented opcode (SHY abs,X on NMOS 6502)
...
$080C: JMP $000C ; Jump to zero page!
```

### 5.2 Self-Modifying Code

The boot code exhibits several hallmarks of deliberate obfuscation:

1. **Sector count of $00**: Normally this tells the boot ROM how many additional
   sectors to load. A value of $00 means "load no additional sectors" -- the
   boot code must load everything itself using direct disk I/O.

2. **Undocumented opcodes**: The byte `$9C` at `$0806` is `SHY abs,X` on NMOS
   6502 processors. This instruction has unpredictable behavior and may be used
   as an anti-debugger measure (it behaves differently on 65C02/65816).

3. **Zero page execution**: `JMP $000C` at `$080C` transfers execution to zero
   page. This means the boot code copies a routine to zero page addresses
   $000C+ before jumping there. Zero page code is harder to trace with monitors
   because it conflicts with system variables.

4. **Mixed hardware addresses**: The disassembled code references both correct
   (`$C08C`) and incorrect (`$C28C`, `$C18E`) disk controller addresses. The
   correct base is `$C0nC` where n=slot (typically 6, giving `$C06C`). The
   incorrect addresses suggest either:
   - Code that self-modifies these addresses at runtime (patching the high byte)
   - Encrypted instruction operands that resolve correctly after decryption

5. **Interleave table at $0840**: Bytes $0840-$005B contain a suspicious table
   of small values (0-3) that may serve as a sector translation/interleave map,
   telling the loader which physical sector corresponds to each logical sector.

### 5.3 Anti-Debugging Features

The boot code design actively resists analysis:

- **No standard DOS**: Without DOS 3.3 or ProDOS, there are no file catalog
  entries, no VTOC, and no standard entry points for disk utilities.
- **Zero page execution**: Most monitors and debuggers use zero page variables;
  the boot code's zero page routine overwrites these.
- **Timing-sensitive I/O**: Direct disk controller access (`LDA $C08C,X`) with
  tight timing loops means the code cannot be single-stepped without losing
  sync with the disk.

---

## 6. Track-by-Track Summary

### Tracks 0-5 (Address Fields Present)

These tracks have custom address prologues that allow sector identification.
The custom loader knows each track's specific prologue byte and reprograms
its sector-search routine accordingly.

- **Track 0**: Boot sector + initial loader. Standard `D5 AA 96` address
  prologues for ROM compatibility. Standard `DE AA EB` epilogues.
- **Tracks 1-2**: Address prologue `D5 BE B5`. Track 1 starts at logical
  sector 6; Track 2 starts at logical sector 1.
- **Track 3**: Address prologue `D5 AB B5`. Starts at logical sector 9.
- **Track 4**: Address prologue `D5 BF B5`. Starts at logical sector 1.
- **Track 5**: Address prologue `D5 EB B5`. Starts at logical sector 9.

### Tracks 6-13 (No Address Fields)

These tracks contain **only data fields** (`D5 AA AD` prologues) with no
preceding address markers. The loader must read sectors sequentially and
trust their physical order on disk. This is the strongest anti-copy measure:

- Standard disk copy utilities cannot identify individual sectors
- Bit copiers must achieve exact timing reproduction
- Even if the nibble stream is perfectly copied, the lack of address fields
  means the copy's sector alignment may differ from the original
- Any track-to-track speed variation during copying will corrupt the sector
  boundaries

---

## 7. Comparison: Protected vs Cracked Versions

### 7.1 Known Cracked Version

The cracked version (`ApplePanic_runtime.bin`, 43,008 bytes) is a clean memory
image loadable at `$0000-$A7FF` with:

- Game code at `$7000-$A800` (entry point `JMP $7465`)
- Sprite data at `$0800-$1FFF` and `$6000-$6FFF`
- HGR page buffers at `$2000-$5FFF` (zeroed at runtime)

### 7.2 Data Size Comparison

- Protected disk: ~46,592 bytes of sector data (182 sectors x 256 bytes,
  excluding duplicate/sentinel sectors)
- Cracked binary: 43,008 bytes

The ~3.5KB difference accounts for the boot loader code, disk I/O routines,
decryption code, and sector interleave tables that are present on the original
disk but unnecessary in the cracked version.

### 7.3 What Crackers Had to Do

To produce the cracked version, the crackers would have needed to:

1. **Boot-trace** the original disk using a modified monitor to capture the
   decryption routine as it executes
2. **Identify the decryption key(s)** and memory load addresses for each
   track/sector
3. **Capture the fully decrypted game** from memory after the loader completes
4. **Create a standard DOS 3.3 loader** (BRUN) to replace the custom boot chain
5. **Remove or neutralize** any runtime copy-protection checks (disk access
   during gameplay, nibble count checks, etc.)

---

## 8. Protection Effectiveness Assessment

> **Updated:** Full emulation revealed **nine distinct layers**, correcting the
> earlier five-layer analysis. What appeared to be "encryption" is actually GCR
> table corruption + custom post-decode permutation. Tracks 6-13 DO have address
> fields — they use `$DE` markers with non-standard sector/track numbers.

Apple Panic's copy protection employs **nine distinct layers**:

| # | Technique                                          | Difficulty to Bypass |
|---|----------------------------------------------------|----------------------|
| 1 | Dual-format track 0 (6-and-2 + 5-and-3)           | High                 |
| 2 | Invalid address field checksums (all 13 sectors)   | Medium               |
| 3 | GCR table corruption (ASL x3 on upper entries)     | High                 |
| 4 | Intentionally bad checksum on sector 11            | Low                  |
| 5 | Custom post-decode permutation ($0346 vs $02D1)    | High                 |
| 6 | Self-modifying code                                | Medium               |
| 7 | Non-standard $DE address markers on tracks 1+      | Medium               |
| 8 | Per-track third-byte variations in address prologs | Medium               |
| 9 | Non-standard sector/track numbers in address fields| High                 |

For 1981, this was a **remarkably sophisticated protection scheme**. The
combination of dual-format encoding, GCR table corruption that preserves
checksum invariants, per-track marker variations, and non-standard sector
numbering would have defeated virtually all automated copy programs of the era
(Locksmith, Copy II Plus, EDD).

The protection was ultimately defeated -- cracked versions exist -- but it
required skilled crackers with boot-tracing capability to capture the decrypted
game from memory rather than from disk.

---

## 9. Tools and Methodology

This analysis was performed using custom Python scripts that:

1. **Parse the WOZ2 container** to extract raw bit streams per track
2. **Convert bits to nibbles** using standard Apple II nibble framing
3. **Search for prologue patterns** (`D5 AA 96`, `D5 xx B5`, `D5 AA AD`)
4. **Decode 4-and-4 address fields** to extract volume/track/sector/checksum
5. **Decode 6-and-2 data fields** to extract 256-byte sector data
6. **Attempt decryption** using single-byte XOR, multi-byte XOR, and
   sector-level pattern matching against the known cracked version

Scripts used: `woz_reader.py`, `woz_analyze.py`, `woz_decode.py`,
`woz_deep.py`, `woz_sectors.py`, `woz_boot.py`, `woz_compare.py`

---

## 10. Conclusion

The Apple Panic WOZ disk image preserves a well-engineered copy protection
system from the early days of commercial software distribution on the Apple II.
While the 6-and-2 nibble encoding is standard, every other aspect of the disk
format has been customized: address prologues vary by track, epilogues are
non-standard, half the tracks lack address fields entirely, and all sector data
(except the boot sector) is encrypted with a cipher that cannot be broken
through simple static analysis.

Full extraction of the original game code from this disk would require either:
- **Emulator-based boot tracing** to capture the decrypted game from memory
- **Reverse engineering the boot code** starting from the obfuscated zero-page
  routine to reconstruct the decryption algorithm

The WOZ2 format faithfully preserves these protection mechanisms at the flux
level, ensuring that the full complexity of the original disk can be studied
and, potentially, the protection can be traced to completion.

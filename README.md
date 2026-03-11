# Apple Panic Reverse Engineering & woztools

Reverse engineering the copy protection on *Apple Panic* (Broderbund, 1981) — an Apple II game shipped on a custom-formatted 5.25" floppy disk with nine layers of copy protection. The project produced **woztools**, a reusable Python toolkit for analyzing any WOZ disk image.

![Apple Panic Instructions](docs/ApplePanicInstructions.png)

## What's Here

### [`woztools/`](woztools/) — WOZ Disk Analysis Toolkit

A Python package for analyzing Apple II WOZ disk images. Works on any WOZ2 file, not just Apple Panic.

```
python -m woztools <command> <woz_file> [options]
```

| Command   | Purpose                                            |
|-----------|----------------------------------------------------|
| `info`    | Show WOZ metadata, track map, half-track data      |
| `scan`    | Scan tracks for encoding type, sector counts, checksums |
| `protect` | Detect copy protection techniques, generate report |
| `boot`    | Emulate 6502 boot process, capture memory at stop point |
| `decode`  | Decode specific track/sector to hex dump or binary |
| `dsk`     | Convert WOZ to standard 140K DSK image             |
| `disasm`  | Disassemble 6502 binary (linear or recursive descent) |

**10 modules:** WOZ2 parser, GCR 6-and-2 / 5-and-3 codec, full NMOS 6502 emulator (all 256 opcodes including 29 undocumented), Disk II controller simulation, boot emulation framework, copy protection analyzer, DSK converter, and 6502 disassembler.

See [`woztools/USAGE.md`](woztools/USAGE.md) for detailed usage with examples.

### [`scripts/`](scripts/) — Investigation Scripts

The ~38 Python scripts written during the reverse engineering investigation. Each one represents a question that was asked — and answered or abandoned. They are preserved as-is: working artifacts of the investigation, not polished tools. Key scripts:

| Script | Purpose |
|--------|---------|
| `emu6502.py` | The original 6502 emulator + Disk II simulation |
| `boot_emulate_full.py` | Full boot trace: power-on through game start (69.8M instructions) |
| `decode_track0.py` | Track 0 decoder: 5-and-3 GCR with corrupted table + custom permutation |
| `disassemble.py` | Recursive descent disassembler that produced the full game assembly |
| `check_wrap.py` | The script that diagnosed the bit-doubling crisis |
| `woz_53brute.py` | Failed brute-force GCR table search (a productive dead end) |
| `build_runtime.py` | Builds the clean 43K runtime image from the cracked binary |

### [`docs/`](docs/) — Documentation

| Document | Description |
|----------|-------------|
| [`ReverseEngineeringHistory.md`](docs/ReverseEngineeringHistory.md) | **The full narrative** — a blog-post-ready account of the entire investigation, from first contact with the WOZ file through all the dead ends and breakthroughs |
| [`CopyProtection.md`](docs/CopyProtection.md) | Definitive analysis of all 9 copy protection layers |
| [`ApplePanic_CopyProtection_Report.md`](docs/ApplePanic_CopyProtection_Report.md) | Earlier analysis report (annotated with corrections) |
| [`DiskII_BootROM.md`](docs/DiskII_BootROM.md) | Apple II Disk II P6 Boot ROM documentation |
| [`DiskII_BootROM.asm`](docs/DiskII_BootROM.asm) | Fully disassembled and commented P6 Boot ROM |
| [`ApplePanic.asm`](docs/ApplePanic.asm) | Complete disassembly of the game (8,378 lines, 104 named subroutines) |
| [`ApplePanic_Boot_T0.asm`](docs/ApplePanic_Boot_T0.asm) | Annotated disassembly of the boot sector and RWTS |
| [`DecodingTools.md`](docs/DecodingTools.md) | Guide to all the investigation scripts |
| [`PLAN.md`](docs/PLAN.md) | The original reconstruction plan |
| [`subroutine_analysis.txt`](docs/subroutine_analysis.txt) | Analysis of all 104 game subroutines |

### [`disks/`](disks/) — Disk Images and Binaries

| File | Description |
|------|-------------|
| `Apple Panic - Disk 1, Side A.woz` | Original WOZ2 flux-level disk image (Applesauce capture) |
| `ApplePanic` | Cracked binary (26,640 bytes, by "RIP_EM_OFF SOFTWARE") |
| `ApplePanic_runtime.bin` | Clean runtime image (43,008 bytes, $0000-$A7FF) |
| `ApplePanic_original.dsk` | Standard DSK conversion of the WOZ image |

## The Nine Layers of Copy Protection

Apple Panic's copy protection is remarkably sophisticated for 1981:

| # | Mechanism | What It Defeats |
|---|-----------|-----------------|
| 1 | Dual-format track 0 (6-and-2 + 5-and-3) | Standard DOS 3.3 copy utilities |
| 2 | Invalid address field checksums | Nibble copiers that validate headers |
| 3 | GCR table corruption (ASL x3) | Raw nibble copies decoded with fresh tables |
| 4 | Intentionally bad checksum on sector 11 | Copiers that validate all sector checksums |
| 5 | Custom post-decode permutation ($0346) | Manual analysis with standard decode assumptions |
| 6 | Self-modifying code | Static disassembly |
| 7 | Non-standard $DE address markers (tracks 1+) | Copiers looking for standard $D5 prologs |
| 8 | Per-track third-byte variations | Copiers that handle $DE but assume fixed prologs |
| 9 | Non-standard sector/track numbers | Copiers expecting sector 0-12 and matching track numbers |

Read the full story in [`docs/ReverseEngineeringHistory.md`](docs/ReverseEngineeringHistory.md).

## Quick Start

**Requirements:** Python 3.10+. No external dependencies.

```bash
# What's on this disk?
python -m woztools info "disks/Apple Panic - Disk 1, Side A.woz"

# Scan for encoding and checksums
python -m woztools scan "disks/Apple Panic - Disk 1, Side A.woz"

# Detect all copy protection techniques
python -m woztools protect "disks/Apple Panic - Disk 1, Side A.woz"

# Boot-trace and extract the game binary
python -m woztools boot "disks/Apple Panic - Disk 1, Side A.woz" \
    --stop 0x4000 --dump 0x4000-0xA7FF --save game.bin

# Disassemble the extracted binary
python -m woztools disasm game.bin --base 0x4000 --entry 0x4000 -r
```

## Project History

This project started as "what's on this disk?" and grew into a full reverse engineering effort:

1. **WOZ parsing** — reading the raw bit stream, finding markers, discovering the dual-format track
2. **GCR decoding** — implementing both 5-and-3 and 6-and-2 codecs, discovering the table corruption
3. **6502 emulation** — building a full CPU emulator when static analysis hit a wall
4. **The bit-doubling crisis** — the hardest bug, caused by WOZ's linear representation of circular media
5. **Full boot emulation** — 69.8 million instructions from power-on to game start
6. **Verification** — byte-for-byte comparison against the known cracked version
7. **Packaging** — consolidating ~38 scripts into the reusable `woztools` toolkit

## License

The investigation scripts, woztools package, documentation, and analysis are original work.

*Apple Panic* is (c) 1981 Broderbund Software / Ben Serki. The WOZ disk image and game binaries are included for research and preservation purposes.

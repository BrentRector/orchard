# Orchard

Apple II reverse engineering: copy protection analysis, boot tracing, and binary extraction.

Each game gets its own folder with disk images, analysis documents, and disassembled source. The **nibbler** toolkit provides the tools to analyze any WOZ disk image.

## Games

### [Apple Panic](apple-panic/) (Broderbund, 1981)

![Apple Panic Instructions](apple-panic/ApplePanicInstructions.png)

A platformer with **nine layers of copy protection** — dual-format tracks, GCR table corruption, self-modifying code, non-standard address markers, and more. Fully reverse engineered: boot traced, all protection defeated, game binary extracted and disassembled.

## nibbler — WOZ Disk Analysis Toolkit

[`nibbler/`](nibbler/) is a reusable Python package for analyzing Apple II WOZ disk images. Works on any WOZ2 file.

```
python -m nibbler <command> <woz_file> [options]
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

No external dependencies. Python 3.10+.

See [`nibbler/USAGE.md`](nibbler/USAGE.md) for detailed usage with examples.

### Quick Start

```bash
# What's on a disk?
python -m nibbler info "apple-panic/Apple Panic - Disk 1, Side A.woz"

# Scan for encoding and checksums
python -m nibbler scan "apple-panic/Apple Panic - Disk 1, Side A.woz"

# Detect copy protection techniques
python -m nibbler protect "apple-panic/Apple Panic - Disk 1, Side A.woz"

# Boot-trace and extract the game binary
python -m nibbler boot "apple-panic/Apple Panic - Disk 1, Side A.woz" \
    --stop 0x4000 --dump 0x4000-0xA7FF --save game.bin

# Disassemble the extracted binary
python -m nibbler disasm game.bin --base 0x4000 --entry 0x4000 -r
```

## Other Resources

### [`scripts/`](scripts/) — Investigation Scripts

The ~38 Python scripts written during the Apple Panic investigation. Each one represents a question that was asked — and answered or abandoned. Preserved as-is: working artifacts, not polished tools.

### [`docs/`](docs/) — Apple II Reference

| Document | Description |
|----------|-------------|
| [DiskII_BootROM.md](docs/DiskII_BootROM.md) | Apple II Disk II P6 Boot ROM documentation |
| [DiskII_BootROM.asm](docs/DiskII_BootROM.asm) | Fully disassembled and commented P6 Boot ROM |

## License

The investigation scripts, nibbler package, documentation, and analysis are original work.

Game disk images and binaries are included for research and preservation purposes. All game copyrights belong to their respective owners.

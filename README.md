# Orchard

I always wanted to know how Apple II copy protection actually worked.

Back in the day, I knew certain disks couldn't be copied — you'd run COPYA or Locksmith and the copy would just fail, or worse, it would seem to work and then crash on boot. The protection was down in the disk format itself, in the way bits were laid down on the magnetic surface, but I never understood the specifics. What exactly was different about those bits? What did the boot code do that was so clever? Why couldn't the copiers handle it?

Recently, after restoring a vintage Apple ][+ to better-than-original condition, I found a [WOZ file](https://applesaucefdc.com/woz/) of *Apple Panic* — one of my favorite idle timewasters from back in the day — captured at the magnetic flux level by modern hardware. A WOZ file preserves everything about the original disk: every bit pattern, every non-standard marker, every copy protection trick, exactly as it existed on the physical media. Unlike a `.dsk` image, which stores only the decoded sector data, a WOZ file gives you the raw magnetic flux stream that the drive read head would actually detect.

I started poking at it. How does this disk boot? What format are the sectors in? Why does it look so weird compared to a standard DOS 3.3 disk?

One thing led to another. I built a WOZ parser, then a GCR decoder, then a full 6502 CPU emulator, then a Disk II disk drive emulator, then a boot tracer. I hit dead ends — spent hours debugging a checksum failure that turned out to be in my own tooling, not the disk. I discovered nine distinct layers of copy protection, each one defeating a different class of copy tool. I traced 69.8 million emulated CPU instructions from power-on to game start.

I wanted to understand *why* the disk couldn't be copied, not just play the game. This repo is the result. Start to finish, with the assistence of Claude Code, the reverse engineering was complete in one day. It took another couple of days to document all the work.

## Games

### [Apple Panic](apple-panic/) (Broderbund, 1981)

![Apple Panic Instructions](apple-panic/ApplePanicInstructions.png)

A platformer with **nine layers of copy protection** — dual-format tracks, GCR table corruption, self-modifying code, non-standard address markers, and more. Fully reverse engineered: boot traced, all protection defeated, game binary extracted and disassembled into ~8,800 lines of commented assembly.

The reverse engineering follows a chain of discovery: each protection layer, once defeated, reveals what to investigate next. The Disk II P6 ROM loads one standard boot sector — after that, the software on the disk is in charge, and the nine protection layers activate one by one as the boot progresses through five stages and ~70 million emulated instructions.

- **[Walkthrough](apple-panic/Walkthrough.md)** — Step-by-step guide: what to do, in what order, what each step reveals, and what protection technique each step defeats
- **[The Full Story](apple-panic/ReverseEngineeringHistory.md)** — The investigation narrative, including dead ends and breakthroughs
- **[Copy Protection Reference](apple-panic/CopyProtection.md)** — Technical analysis of all 9 protection layers

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
| `nibbles` | Dump raw nibbles for a track with optional byte highlighting |
| `boot`    | Emulate 6502 boot process, capture memory at stop point |
| `decode`  | Decode specific track/sector to hex dump or binary |
| `dsk`     | Convert WOZ to standard 140K DSK image             |
| `disasm`  | Disassemble 6502 binary (linear or recursive descent) |

**11 modules:** WOZ2 parser, GCR 6-and-2 / 5-and-3 codec with auto-detection of non-standard address prologs, full NMOS 6502 emulator (all 256 opcodes including 29 undocumented), Disk II controller simulation with stepper motor and I/O tracing, boot emulation framework, copy protection analyzer, DSK converter, and 6502 disassembler with recursive descent.

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

The ~38 Python scripts written during the Apple Panic investigation. Each one represents a question that was asked — and answered or abandoned. Preserved as-is: working artifacts, not polished tools. See [`scripts/README.md`](scripts/README.md) for a complete guide.

### [`docs/`](docs/) — Apple II Reference

| Document | Description |
|----------|-------------|
| [DiskII_BootROM.md](docs/DiskII_BootROM.md) | Apple II Disk II P6 Boot ROM documentation |
| [DiskII_BootROM.asm](docs/DiskII_BootROM.asm) | Fully disassembled and commented P6 Boot ROM |

## License

The investigation scripts, nibbler package, documentation, and analysis are original work.

Game disk images and binaries are included for research and preservation purposes. All game copyrights belong to their respective owners.

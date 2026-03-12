"""
Command-line interface for nibbler.

Defines the argparse-based CLI that dispatches to per-command handler
functions (``cmd_info``, ``cmd_scan``, ``cmd_boot``, etc.).

Usage::

    python -m nibbler <command> <woz_file> [options]

Expected output varies by command.  ``info`` prints WOZ metadata;
``scan`` prints a table of track encodings and checksums; ``boot``
runs the 6502 emulator and optionally dumps memory; etc.
"""

import argparse
import os
import sys


def parse_addr(s):
    """Parse a user-supplied hexadecimal address string.

    Accepts common Apple II / Python hex notations::

        '0x4000'  ->  0x4000
        '$4000'   ->  0x4000
        '4000'    ->  0x4000

    Args:
        s: Address string in any of the above forms.

    Returns:
        int: The parsed 16-bit address value.
    """
    # Strip leading whitespace and common hex prefixes ('$' for 6502
    # convention, '0x'/'0X' for Python/C convention).
    s = s.strip().lstrip('$').lstrip('0x').lstrip('0X')
    return int(s, 16)


def cmd_info(args):
    """Show WOZ metadata and track map."""
    from .woz import WOZFile

    woz = WOZFile(args.woz_file)
    print(woz.summary())

    print(f"\nTrack map:")
    for track in range(40):
        if woz.track_exists(track):
            data, bits = woz.get_track_data(track)
            tidx = woz.get_track_index(track)
            entry = woz.track_entries[tidx]
            print(f"  Track {track:2d}: {entry['bit_count']:6d} bits "
                  f"({entry['block_count']} blocks)")

    # Check for half/quarter tracks
    halfs = []
    for qt in range(160):
        if qt % 4 != 0:
            tidx = woz.tmap[qt]
            if tidx != 0xFF and tidx in woz.track_entries:
                halfs.append(qt)
    if halfs:
        print(f"\nHalf/quarter tracks: {halfs}")


def cmd_scan(args):
    """Scan tracks for encoding type, sector count, checksums."""
    from .woz import WOZFile
    from .gcr import (find_sectors_62, find_sectors_53, scan_address_fields,
                      auto_detect_address_prologs)

    woz = WOZFile(args.woz_file)

    print(f"Scanning {args.woz_file}...")
    print(f"{'Track':>5s}  {'Encoding':>10s}  {'6+2':>4s}  {'5+3':>4s}  "
          f"{'Addr CK':>8s}  {'Data CK':>8s}  {'Notes'}")
    print("-" * 75)

    for track in range(35):
        if not woz.track_exists(track):
            continue

        nibbles = woz.get_track_nibbles(track, bit_double=True)

        sec_62 = find_sectors_62(nibbles)
        sec_53 = find_sectors_53(nibbles)

        # --- Auto-detect non-standard address prologs ---
        # Copy-protected disks often change the three-byte address field
        # prolog (normally $D5 $AA $96 for 6+2 or $D5 $AA $B5 for 5+3).
        # If standard prologs found nothing we scan for alternate patterns.
        notes = []
        if not sec_62 or not sec_53:
            detected = auto_detect_address_prologs(nibbles)
            for prolog in detected:
                p_str = ' '.join(f'${b:02X}' for b in prolog)
                # The third byte of the address prolog identifies the GCR
                # encoding scheme used for the data field that follows:
                #   $96 = 6-and-2  (16 sectors per track, 256 bytes each)
                #   $B5 = 5-and-3  (13 sectors per track, 256 bytes each)
                if prolog[2] == 0x96 and not sec_62:
                    alt = find_sectors_62(nibbles, addr_prolog=prolog)
                    # Require >= 3 sectors to avoid false positives: a random
                    # byte sequence might match a prolog once or twice, but
                    # successfully decoding 3+ full sectors is strong evidence.
                    if len(alt) >= 3:
                        sec_62 = alt
                        notes.append(f"addr={p_str}")
                elif prolog[2] == 0xB5 and not sec_53:
                    alt = find_sectors_53(nibbles, addr_prolog=prolog)
                    if len(alt) >= 3:
                        sec_53 = alt
                        notes.append(f"addr={p_str}")

        addr_fields = scan_address_fields(nibbles)
        bad_addr = sum(1 for af in addr_fields if not af['checksum_ok'])
        bad_data = 0
        for sd in list(sec_62.values()) + list(sec_53.values()):
            if sd.data_checksum_ok is False:
                bad_data += 1

        enc = 'dual' if sec_62 and sec_53 else ('6+2' if sec_62 else ('5+3' if sec_53 else '???'))

        addr_str = f"{bad_addr}/{len(addr_fields)}" if bad_addr else "OK"
        total_sec = len(sec_62) + len(sec_53)
        data_str = f"{bad_data}/{total_sec}" if bad_data else "OK"

        print(f"  {track:3d}  {enc:>10s}  {len(sec_62):4d}  {len(sec_53):4d}  "
              f"{addr_str:>8s}  {data_str:>8s}  {' '.join(notes)}")


def cmd_protect(args):
    """Detect copy protection techniques and generate report."""
    from .analyze import CopyProtectionAnalyzer

    analyzer = CopyProtectionAnalyzer(args.woz_file)
    report = analyzer.analyze_all()
    markdown = analyzer.generate_report(report)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(markdown)
        print(f"Report saved to {args.output}")
    else:
        print(markdown)


def cmd_nibbles(args):
    """Dump raw nibbles for a track."""
    from .woz import WOZFile

    woz = WOZFile(args.woz_file)
    track = args.track

    if not woz.track_exists(track):
        print(f"Track {track} does not exist")
        return

    # Single revolution (no bit-doubling) for raw dump
    nibbles = woz.get_track_nibbles(track, bit_double=False)

    # Parse highlight bytes if specified
    highlight = set()
    if args.highlight:
        for h in args.highlight.split(','):
            highlight.add(int(h.strip(), 16))

    print(f"Track {track}: {len(nibbles)} nibbles")
    print()

    # Print hex dump, 32 nibbles per line
    for row in range(0, len(nibbles), 32):
        end = min(row + 32, len(nibbles))
        parts = []
        for i in range(row, end):
            nib = nibbles[i]
            s = f'{nib:02X}'
            if highlight and nib in highlight:
                s = f'[{s}]'
            parts.append(s)
        print(f"  {row:5d}: {' '.join(parts)}")


def cmd_boot(args):
    """Emulate boot process and capture memory."""
    from .boot import BootAnalyzer

    stop_addr = parse_addr(args.stop) if args.stop else None
    max_instr = args.max_instructions or 200_000_000

    print(f"Booting {args.woz_file}...")
    if stop_addr:
        print(f"Will stop at ${stop_addr:04X}")

    ba = BootAnalyzer(args.woz_file, slot=args.slot)
    ba.setup_boot()

    # Set up boot trace logging if requested
    if args.trace:
        ba.enable_trace()

    progress = 5_000_000 if not args.quiet else 0
    result = ba.run(max_instructions=max_instr, stop_at=stop_addr,
                    progress_interval=progress)

    print(f"\nStopped: {result}")
    print(f"Instructions: {ba.cpu.exec_count:,}")
    print(f"Final PC: ${ba.cpu.pc:04X}")
    print(f"State: {ba.cpu.format_state()}")

    if args.dump:
        parts = args.dump.split('-')
        start = parse_addr(parts[0])
        end = (parse_addr(parts[1]) + 1) if len(parts) > 1 else start + 256
        data = ba.dump_memory(start, end)
        print(f"\nMemory ${start:04X}-${end - 1:04X} ({len(data)} bytes):")
        for row in range(0, len(data), 16):
            addr = start + row
            h = ' '.join(f'{data[row + c]:02X}' for c in range(min(16, len(data) - row)))
            print(f"  ${addr:04X}: {h}")

    if args.save:
        if args.dump:
            parts = args.dump.split('-')
            start = parse_addr(parts[0])
            end = (parse_addr(parts[1]) + 1) if len(parts) > 1 else start + 256
            ba.save_snapshot(args.save, start, end)
        else:
            ba.save_full_memory(args.save)
        print(f"Saved to {args.save}")

    # Show non-zero memory summary
    if not args.quiet:
        print(f"\nNon-zero memory pages:")
        print(ba.memory_summary())


def cmd_decode(args):
    """Decode specific track/sector to hex dump or binary."""
    from .woz import WOZFile
    from .gcr import find_sectors_62, find_sectors_53, auto_detect_address_prologs

    woz = WOZFile(args.woz_file)
    track = args.track

    if not woz.track_exists(track):
        print(f"Track {track} does not exist")
        return

    nibbles = woz.get_track_nibbles(track, bit_double=True)

    # Try both encodings
    sec_62 = find_sectors_62(nibbles)
    sec_53 = find_sectors_53(nibbles)

    # Auto-detect non-standard prologs if standard search found nothing.
    # Same pattern as cmd_scan: third byte picks decoder, >= 3 sectors
    # threshold guards against false positives.
    if not sec_62 or not sec_53:
        detected = auto_detect_address_prologs(nibbles)
        for prolog in detected:
            if prolog[2] == 0x96 and not sec_62:
                alt = find_sectors_62(nibbles, addr_prolog=prolog)
                if len(alt) >= 3:
                    sec_62 = alt
            elif prolog[2] == 0xB5 and not sec_53:
                alt = find_sectors_53(nibbles, addr_prolog=prolog)
                if len(alt) >= 3:
                    sec_53 = alt

    all_sectors = {}
    for s, sd in sec_62.items():
        all_sectors[s] = ('6+2', sd)
    for s, sd in sec_53.items():
        all_sectors[s] = ('5+3', sd)

    if args.sector is not None:
        if args.sector not in all_sectors:
            print(f"Sector {args.sector} not found on track {track}")
            print(f"Available: {sorted(all_sectors.keys())}")
            return
        sectors_to_show = {args.sector: all_sectors[args.sector]}
    else:
        sectors_to_show = all_sectors

    for sec_num in sorted(sectors_to_show.keys()):
        enc, sd = sectors_to_show[sec_num]
        ck = "OK" if sd.data_checksum_ok else "BAD"
        print(f"\n=== Track {track}, Sector {sec_num} ({enc}, checksum: {ck}) ===")

        if args.output and args.sector is not None:
            with open(args.output, 'wb') as f:
                f.write(sd.data)
            print(f"  Saved to {args.output}")
        else:
            # Hex dump: 16 rows x 16 bytes = 256-byte sector.
            # Each line shows the offset, hex bytes, and an ASCII sidebar
            # where non-printable characters are replaced with '.'.
            for row in range(16):
                off = row * 16
                h = ' '.join(f'{sd.data[off + c]:02X}' for c in range(16))
                a = ''.join(chr(sd.data[off + c]) if 32 <= sd.data[off + c] < 127 else '.'
                            for c in range(16))
                print(f"  ${off:04X}: {h}  {a}")


def cmd_dsk(args):
    """Convert WOZ to standard DSK image."""
    from .woz import WOZFile
    from .dsk import woz_to_dsk, write_dsk, create_bootable_dsk

    if args.binary:
        # Create bootable DSK from binary file
        with open(args.binary, 'rb') as f:
            binary_data = f.read()
        load_addr = parse_addr(args.load_addr) if args.load_addr else 0x0800
        entry_addr = parse_addr(args.entry_addr) if args.entry_addr else load_addr

        output = args.output or args.binary.rsplit('.', 1)[0] + '.dsk'
        image = create_bootable_dsk(binary_data, load_addr, entry_addr)
        write_dsk(output, image)
        print(f"Bootable DSK created: {output}")
        print(f"  Load address: ${load_addr:04X}")
        print(f"  Entry address: ${entry_addr:04X}")
        print(f"  Binary size: {len(binary_data)} bytes")
        return

    woz = WOZFile(args.woz_file)
    output = args.output or args.woz_file.rsplit('.', 1)[0] + '.dsk'

    print(f"Converting {args.woz_file} to DSK...")
    image, missing = woz_to_dsk(woz)

    write_dsk(output, image)
    print(f"DSK image saved: {output} ({len(image)} bytes)")

    if missing:
        print(f"Missing sectors: {len(missing)}")
        # Group by track
        by_track = {}
        for t, s in missing:
            by_track.setdefault(t, []).append(s)
        for t in sorted(by_track.keys()):
            print(f"  Track {t}: sectors {by_track[t]}")


def cmd_disasm(args):
    """Disassemble a binary file or memory dump."""
    from .disasm import disassemble_region, Disassembler, add_hardware_comments, OPCODES

    with open(args.binary, 'rb') as f:
        data = bytearray(f.read())

    base = parse_addr(args.base) if args.base else 0x0000
    start = parse_addr(args.start) if args.start else base
    end = parse_addr(args.end) if args.end else base + len(data)

    if args.recursive:
        # Recursive descent disassembly
        mem = bytearray(65536)
        mem[base:base + len(data)] = data
        dis = Disassembler(mem, base, base + len(data))

        entry = parse_addr(args.entry) if args.entry else start
        dis.trace(entry)
        dis.name_labels()
        add_hardware_comments(dis, mem)

        lines = dis.disassemble_range(start, end)
        for addr, label, instr, comment in lines:
            prefix = f"{label:16s}" if label else " " * 16
            suffix = f"  ; {comment}" if comment else ""
            print(f"${addr:04X}  {prefix} {instr}{suffix}")
    else:
        # Linear disassembly
        lines = disassemble_region(data, base, start, end)
        for line in lines:
            print(line)


def main():
    """Parse command-line arguments and dispatch to the appropriate handler.

    Uses argparse subcommands so each command (info, scan, boot, etc.)
    has its own set of arguments.  If no command is given, prints usage
    help and exits.
    """
    parser = argparse.ArgumentParser(
        prog='nibbler',
        description='WOZ disk image analysis toolkit for Apple II'
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # info
    p_info = subparsers.add_parser('info', help='Show WOZ metadata and track map')
    p_info.add_argument('woz_file', help='Path to WOZ2 disk image')

    # scan
    p_scan = subparsers.add_parser('scan', help='Scan tracks for encoding and checksums')
    p_scan.add_argument('woz_file', help='Path to WOZ2 disk image')

    # protect
    p_protect = subparsers.add_parser('protect', help='Detect copy protection techniques')
    p_protect.add_argument('woz_file', help='Path to WOZ2 disk image')
    p_protect.add_argument('-o', '--output', help='Save report to file (markdown)')

    # nibbles
    p_nibbles = subparsers.add_parser('nibbles', help='Dump raw nibbles for a track')
    p_nibbles.add_argument('woz_file', help='Path to WOZ2 disk image')
    p_nibbles.add_argument('track', type=int, help='Track number')
    p_nibbles.add_argument('--highlight', help='Comma-separated hex bytes to highlight (e.g. D5,AA,96)')

    # boot
    p_boot = subparsers.add_parser('boot', help='Emulate boot process')
    p_boot.add_argument('woz_file', help='Path to WOZ2 disk image')
    p_boot.add_argument('--stop', help='Stop at PC address (hex, e.g. 0x4000)')
    p_boot.add_argument('--dump', help='Dump memory range (e.g. 0x4000-0xA7FF)')
    p_boot.add_argument('--save', help='Save memory dump to file')
    p_boot.add_argument('--max-instructions', type=int, help='Max instructions (default 200M)')
    p_boot.add_argument('--slot', type=int, default=6, help='Disk controller slot (default 6)')
    p_boot.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    p_boot.add_argument('--trace', action='store_true', help='Log disk I/O operations (seeks, sector reads)')

    # decode
    p_decode = subparsers.add_parser('decode', help='Decode track/sector data')
    p_decode.add_argument('woz_file', help='Path to WOZ2 disk image')
    p_decode.add_argument('track', type=int, help='Track number')
    p_decode.add_argument('--sector', type=int, help='Sector number (omit for all)')
    p_decode.add_argument('-o', '--output', help='Save sector data to binary file')

    # dsk
    p_dsk = subparsers.add_parser('dsk', help='Convert to DSK or create bootable DSK')
    p_dsk.add_argument('woz_file', nargs='?', help='Path to WOZ2 disk image')
    p_dsk.add_argument('-o', '--output', help='Output DSK path')
    p_dsk.add_argument('--binary', help='Create bootable DSK from binary file')
    p_dsk.add_argument('--load-addr', help='Load address for binary (hex)')
    p_dsk.add_argument('--entry-addr', help='Entry address for binary (hex)')

    # disasm
    p_disasm = subparsers.add_parser('disasm', help='Disassemble binary')
    p_disasm.add_argument('binary', help='Binary file to disassemble')
    p_disasm.add_argument('--base', help='Base address (hex, default 0x0000)')
    p_disasm.add_argument('--start', help='Start address (hex)')
    p_disasm.add_argument('--end', help='End address (hex)')
    p_disasm.add_argument('--entry', help='Entry point for recursive descent (hex)')
    p_disasm.add_argument('-r', '--recursive', action='store_true',
                          help='Use recursive descent (vs linear)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Dispatch table mapping subcommand name to handler function.
    commands = {
        'info': cmd_info,
        'scan': cmd_scan,
        'protect': cmd_protect,
        'nibbles': cmd_nibbles,
        'boot': cmd_boot,
        'decode': cmd_decode,
        'dsk': cmd_dsk,
        'disasm': cmd_disasm,
    }

    commands[args.command](args)

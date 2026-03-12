#!/usr/bin/env python3
"""
Full boot emulation of Apple Panic from WOZ disk image through game entry.

Traces through the entire multi-stage boot process:
  1. P6 ROM -> $0801: 6-and-2 boot sector self-relocates to $0200
  2. $0200 RWTS reads 5-and-3 sector 0 -> $0300 (stage 2)
  3. Stage 2 loads sectors 0-9 to $B600-$BFFF, JMP $B700
  4. $B700 game loader reads tracks 1-5 to $0800+, JSR $1000
  5. $1000 intermediate code reads tracks 6-13 to $4000+, JMP $4000
  6. $4000 is the game entry point

Saves complete memory dumps at each milestone: stage 1 output ($B600-$BFFF),
tracks 1-5 data ($0800-$48FF), full 64K memory at game entry, and the game
code region ($4000-$A7FF).

Usage:
    python boot_emulate_full.py [--woz PATH] [--output-dir DIR]

    Defaults use repo-relative paths; override with CLI arguments.

Expected output:
    Detailed milestone trace messages for each boot stage, track reading
    progress, memory dump saves at each stage, and a summary of non-zero
    memory pages. Runs up to 200M instructions or until JMP $4000 is reached.
"""
import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from emu6502 import CPU6502, WOZDisk, decode_boot_sector_from_woz


def main():
    """Run the full boot emulation from $0801 through JMP $4000 (game entry)."""
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Full boot emulation of Apple Panic through game entry.")
    parser.add_argument("--woz", default=str(repo_root / "apple-panic" / "Apple Panic - Disk 1, Side A.woz"),
                        help="Path to the WOZ disk image")
    parser.add_argument("--output-dir", default=str(repo_root / "apple-panic" / "output"),
                        help="Directory for output files")
    args = parser.parse_args()

    woz_path = args.woz
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    # Load WOZ disk
    disk = WOZDisk(woz_path)

    # Decode 6-and-2 boot sector
    sectors_62 = decode_boot_sector_from_woz(woz_path)
    boot = sectors_62[0]
    print(f"Boot sector loaded, byte 0 = ${boot[0]:02X}")

    # Create CPU
    cpu = CPU6502()
    cpu.disk = disk

    # Load boot sector at $0800
    for i, b in enumerate(boot):
        cpu.mem[0x0800 + i] = b

    # Monitor ROM stubs
    cpu.mem[0xFF58] = 0x60  # RTS (IORTS)
    cpu.mem[0xFCA8] = 0x60  # RTS (WAIT)
    cpu.mem[0xFF2D] = 0x60  # RTS (for JMP $FF2D at $02FC)

    # BRK/IRQ handler
    cpu.mem[0xFFFE] = 0x02  # KIL at $0002
    cpu.mem[0xFFFF] = 0x00
    cpu.mem[0x0002] = 0x02  # KIL

    # Soft switch stubs - text/graphics mode switches (read-activated)
    # These are at $C050-$C057, $C000, $C010 etc.
    # The emulator's read() already handles $C000/$C010 and disk I/O
    # For $C050-$C057 (text/graphics), just return 0 from memory

    # Initial state (after P6 boot ROM)
    cpu.pc = 0x0801
    cpu.x = 0x60  # slot 6
    cpu.sp = 0xFD
    cpu.mem[0x2B] = 0x60
    disk.motor_on = True
    disk.current_qtrack = 0

    print("Starting full boot emulation...")
    print("=" * 60)

    # Milestone tracking
    reached_B700 = False
    reached_1000 = False
    reached_4000 = False
    track_reads = {}
    current_track_read = None

    max_instr = 200_000_000  # 200M instructions should be plenty
    checksum_fail_count = 0

    for i in range(max_instr):
        pc = cpu.pc

        # ---- Stage 1: Boot sector milestones ----
        if pc == 0x020F and cpu.exec_count < 1000:
            print(f"[{cpu.exec_count:9d}] Boot code relocated to $0200, JMP $020F")

        if pc == 0x0241 and cpu.exec_count < 50000:
            print(f"[{cpu.exec_count:9d}] JMP $0301 - entering stage 2")

        if pc == 0x0301 and cpu.exec_count < 50000:
            print(f"[{cpu.exec_count:9d}] Stage 2: GCR table corruption loop")

        # Detect sector loading (stage 1 loader)
        if pc == 0x0327 and not reached_B700:
            expected_sec = cpu.mem[0x3D]
            target_page = cpu.mem[0x41]
            if expected_sec == 0:
                print(f"[{cpu.exec_count:9d}] Loading sector {expected_sec} -> ${target_page:02X}00")

        # ---- JMP ($003E) = JMP $B700 ----
        if pc == 0x0343 and cpu.mem[0x3E] == 0x00 and cpu.mem[0x3F] == 0xB7:
            print(f"\n[{cpu.exec_count:9d}] *** JMP ($003E) = JMP $B700 - Stage 1 COMPLETE ***")
            print(f"  $B600-$BFFF loaded successfully")
            # Save stage 1 output
            with open(os.path.join(output_dir, "emu_stage1_B600.bin"), 'wb') as f:
                f.write(cpu.mem[0xB600:0xC000])

        # ---- Reached $B700 ----
        if pc == 0xB700 and not reached_B700:
            reached_B700 = True
            print(f"[{cpu.exec_count:9d}] *** Reached $B700 - Game loader ***")
            print(f"  Disk qtrack={disk.current_qtrack}, motor={'ON' if disk.motor_on else 'OFF'}")

        # ---- Track reading setup at $B789 ----
        if pc == 0xB789 and reached_B700:
            start_track = cpu.mem[0x3E] if hasattr(cpu, '_b789_first') else cpu.a
            num_tracks = cpu.mem[0x42]
            dest_hi = cpu.mem[0xB77D] if 0xB77D < len(cpu.mem) else 0
            dest_lo = cpu.mem[0xB77C] if 0xB77C < len(cpu.mem) else 0
            print(f"\n[{cpu.exec_count:9d}] $B789: Reading {num_tracks} tracks starting at track {cpu.mem[0x3E]}")
            print(f"  Destination: ${cpu.mem[0xB77D]:02X}{cpu.mem[0xB77C]:02X}")

        # ---- Track seek at $BA1E ----
        if pc == 0xBA1E:
            target = cpu.a
            current = cpu.mem[0x0478]
            if target != current:
                pass  # Track seeking

        # ---- RWTS entry at $BD00 ----
        if pc == 0xBD00 and reached_B700:
            pass  # Don't spam

        # ---- Sector read complete (address field found at $B9C0 RTS) ----
        if pc == 0xB9C0 and reached_B700:
            sec_found = cpu.mem[0x2D]
            trk_found = cpu.mem[0x2C]
            if trk_found not in track_reads:
                track_reads[trk_found] = set()
                print(f"[{cpu.exec_count:9d}]   Track {trk_found}: reading sectors...")
            track_reads[trk_found].add(sec_found)

        # ---- Sector data page increment at $B7B0 ----
        if pc == 0xB7B0 and reached_B700:
            dest_page = cpu.mem[0xB77D]
            sec_count = cpu.mem[0xB779]
            # Only print first and last sector per track
            if sec_count == 0 or sec_count == 12:
                qtrack = disk.current_qtrack
                track = qtrack // 8 if qtrack > 0 else 0
                pass

        # ---- Track count at $B7C6 (DEC $42) ----
        if pc == 0xB7C6 and reached_B700:
            tracks_remaining = cpu.mem[0x42]
            current_dest = cpu.mem[0xB77D]
            current_track = cpu.mem[0xB778]
            print(f"[{cpu.exec_count:9d}]   Track {current_track} complete -> ${current_dest:02X}00, {tracks_remaining} tracks remaining")

        # ---- Motor off at $B742 ----
        if pc == 0xB742 and reached_B700 and not reached_1000:
            print(f"\n[{cpu.exec_count:9d}] Motor off after reading tracks 1-5")
            print(f"  Destination ended at ${cpu.mem[0xB77D]:02X}00")

        # ---- JSR $1000 ----
        if pc == 0x1000 and reached_B700 and not reached_1000:
            reached_1000 = True
            print(f"\n[{cpu.exec_count:9d}] *** Reached $1000 - Intermediate code ***")
            # Save tracks 1-5 data
            with open(os.path.join(output_dir, "emu_tracks1_5.bin"), 'wb') as f:
                f.write(cpu.mem[0x0800:0x4900])
            print(f"  Saved $0800-$48FF to emu_tracks1_5.bin")

        # ---- JMP $4000 ----
        if pc == 0x4000 and reached_B700:
            if not reached_4000:
                reached_4000 = True
                print(f"\n[{cpu.exec_count:9d}] *** JMP $4000 - GAME ENTRY POINT ***")
                print(f"  Full boot complete!")

                # Save complete memory dump
                with open(os.path.join(output_dir, "emu_full_boot_memory.bin"), 'wb') as f:
                    f.write(cpu.mem)
                print(f"  Full 64K memory saved to emu_full_boot_memory.bin")

                # Save game area
                with open(os.path.join(output_dir, "emu_game_4000_A7FF.bin"), 'wb') as f:
                    f.write(cpu.mem[0x4000:0xA800])
                print(f"  Game code $4000-$A7FF saved to emu_game_4000_A7FF.bin")

                # Save B600-BFFF (may have been modified)
                with open(os.path.join(output_dir, "emu_full_boot_B600.bin"), 'wb') as f:
                    f.write(cpu.mem[0xB600:0xC000])
                print(f"  $B600-$BFFF saved to emu_full_boot_B600.bin")

                # Save intermediate code area
                with open(os.path.join(output_dir, "emu_0800_3FFF.bin"), 'wb') as f:
                    f.write(cpu.mem[0x0800:0x4000])
                print(f"  $0800-$3FFF saved to emu_0800_3FFF.bin")

                # Summary
                print(f"\n  Memory regions loaded:")
                print(f"    $0800-$48FF: Tracks 1-5 (intermediate/setup code)")
                print(f"    $4000-$A7FF: Tracks 6-13 (game code)")
                print(f"    $B600-$BFFF: Track 0 sectors 0-9 (boot/RWTS)")

                # Show non-zero memory regions
                print(f"\n  Non-zero memory pages:")
                for page in range(256):
                    data = bytes(cpu.mem[page*256:(page+1)*256])
                    nonzero = sum(1 for b in data if b != 0)
                    if nonzero > 16:
                        print(f"    ${page:02X}00: {nonzero:3d} non-zero bytes")

                break

        # ---- Detect halt/KIL ----
        if cpu.halted:
            print(f"\n[{cpu.exec_count:9d}] CPU HALTED at ${pc:04X}")
            print(f"  State: {cpu.format_state()}")
            # Dump context
            for addr in range(max(0, pc-8), min(0xFFFF, pc+8)):
                print(f"  ${addr:04X}: ${cpu.mem[addr]:02X}")
            break

        if not cpu.step():
            print(f"CPU stopped at ${pc:04X}")
            break

        if cpu.exec_count % 5_000_000 == 0:
            qt = disk.current_qtrack
            print(f"  ... {cpu.exec_count:,} instructions, PC=${cpu.pc:04X}, qtrack={qt}, motor={'ON' if disk.motor_on else 'OFF'}")

    else:
        print(f"\nReached {max_instr:,} instruction limit at PC=${cpu.pc:04X}")

    print(f"\nTotal instructions: {cpu.exec_count:,}")
    print(f"Final PC: ${cpu.pc:04X}")
    print(f"Final state: {cpu.format_state()}")
    print(f"Disk qtrack: {disk.current_qtrack} (track {disk.current_qtrack // 8})")
    print(f"Tracks read: {sorted(track_reads.keys()) if track_reads else 'none after B700'}")


if __name__ == '__main__':
    main()

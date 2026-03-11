#!/usr/bin/env python3
"""
Emulate the complete Apple Panic boot process using emu6502.py.
Traces through boot sector → stage 2 → sector loading → JMP $B700.
"""
import sys
sys.path.insert(0, 'E:/Apple')
from emu6502 import CPU6502, WOZDisk

def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"

    # Load WOZ disk
    disk = WOZDisk(woz_path)

    # Decode 6-and-2 boot sector
    from emu6502 import decode_boot_sector_from_woz
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

    # Initial state (after P6 boot ROM)
    cpu.pc = 0x0801
    cpu.x = 0x60  # slot 6
    cpu.sp = 0xFD
    cpu.mem[0x2B] = 0x60
    disk.motor_on = True
    disk.current_qtrack = 0

    # No checksum bypass needed - bit-doubled WOZ reader handles wrap
    print("Using bit-doubled WOZ reader (no checksum bypass needed)")

    # Track key events
    sector_reads = []
    sector_read_count = 0
    last_sector_match = None

    # Run with milestone detection
    max_instr = 10_000_000
    checksum_fail_count = 0

    for i in range(max_instr):
        pc = cpu.pc

        # Detect key milestones
        if pc == 0x020F and cpu.exec_count < 1000:
            print(f"[{cpu.exec_count:7d}] Boot code relocated to $0200, JMP $020F")

        if pc == 0x0231 and cpu.exec_count < 5000:
            print(f"[{cpu.exec_count:7d}] JSR $025D - reading first 5-and-3 sector (sector 0)")

        if pc == 0x0234 and cpu.exec_count < 50000:
            print(f"[{cpu.exec_count:7d}] JSR $02D1 - post-decode sector 0")

        if pc == 0x0241 and cpu.exec_count < 50000:
            print(f"[{cpu.exec_count:7d}] JMP $0301 - entering stage 2")
            print(f"  $031F=${cpu.mem[0x031F]:02X} $0320=${cpu.mem[0x0320]:02X} (patched to LDA #$02)")

        if pc == 0x0301 and cpu.exec_count < 50000:
            print(f"[{cpu.exec_count:7d}] Stage 2: GCR table corruption loop")

        # Detect sector loading loop iterations
        if pc == 0x0327:
            expected_sec = cpu.mem[0x3D]
            target_page = cpu.mem[0x41]
            print(f"[{cpu.exec_count:7d}] Loading sector {expected_sec} -> ${target_page:02X}00")

        # Detect RWTS sector match
        if pc == 0x029B:  # CMP $3D
            expected = cpu.mem[0x3D]
            found = cpu.a
            if found == expected:
                last_sector_match = found

        # Detect RWTS data read complete
        if pc == 0x02D0:  # RTS after data read
            if last_sector_match is not None:
                print(f"[{cpu.exec_count:7d}]   RWTS read complete for sector {last_sector_match}, checksum A=${cpu.a:02X}")
                last_sector_match = None

        # Detect checksum failure
        if pc == 0x02CE:  # BNE after checksum XOR
            if cpu.a != 0:
                checksum_fail_count += 1
                # print(f"[{cpu.exec_count:7d}]   Checksum FAIL A=${cpu.a:02X}, retrying... (fail #{checksum_fail_count})")
                if checksum_fail_count > 100:
                    print(f"\n*** Checksum failures exceeded 100 for sector {cpu.mem[0x3D]}!")
                    print(f"*** The RWTS is stuck in an infinite retry loop.")
                    print(f"*** This confirms sector {cpu.mem[0x3D]} has a deliberately bad checksum.")
                    break

        # Detect $0346 post-decode entry
        if pc == 0x0346 and cpu.exec_count > 1000:
            pass  # Post-decode running

        # Detect jump to $B700
        if pc == 0x0343 and cpu.mem[0x3E] == 0x00 and cpu.mem[0x3F] == 0xB7:
            print(f"\n[{cpu.exec_count:7d}] *** JMP ($003E) = JMP $B700 - BOOT COMPLETE! ***")
            print(f"  Dumping $B600-$BFFF memory:")
            for page in range(0xB6, 0xC0):
                data = bytes(cpu.mem[page*256:(page+1)*256])
                nonzero = sum(1 for b in data if b != 0)
                if nonzero > 0:
                    print(f"  ${page:02X}00: {' '.join(f'{data[j]:02X}' for j in range(16))}  ({nonzero} non-zero bytes)")

            # Save full memory dump
            with open("E:/Apple/emu_boot_memory.bin", 'wb') as f:
                f.write(cpu.mem)
            print(f"\n  Memory dump saved to emu_boot_memory.bin")

            # Save $B600-$BFFF
            with open("E:/Apple/emu_B600_BFFF.bin", 'wb') as f:
                f.write(cpu.mem[0xB600:0xC000])
            print(f"  $B600-$BFFF saved to emu_B600_BFFF.bin")
            break

        # Also check if we JMP to $B700 directly
        if pc == 0xB700:
            print(f"\n[{cpu.exec_count:7d}] *** Reached $B700! ***")
            # Dump key memory regions
            for page in range(0xB6, 0xC0):
                data = bytes(cpu.mem[page*256:(page+1)*256])
                nonzero = sum(1 for b in data if b != 0)
                if nonzero > 0:
                    first16 = ' '.join(f'{data[j]:02X}' for j in range(16))
                    print(f"  ${page:02X}00: {first16}")

            with open("E:/Apple/emu_boot_memory.bin", 'wb') as f:
                f.write(cpu.mem)
            with open("E:/Apple/emu_B600_BFFF.bin", 'wb') as f:
                f.write(cpu.mem[0xB600:0xC000])
            print(f"  Memory saved.")
            break

        # Detect halt/KIL
        if cpu.halted:
            print(f"\n[{cpu.exec_count:7d}] CPU HALTED at ${pc:04X}")
            print(f"  State: {cpu.format_state()}")
            break

        if not cpu.step():
            print(f"CPU stopped at ${pc:04X}")
            break

        if cpu.exec_count % 1_000_000 == 0:
            print(f"  ... {cpu.exec_count:,} instructions, PC=${cpu.pc:04X}")
    else:
        print(f"\nReached {max_instr:,} instruction limit at PC=${cpu.pc:04X}")

    print(f"\nTotal instructions: {cpu.exec_count:,}")
    print(f"Checksum failures: {checksum_fail_count}")
    print(f"Final PC: ${cpu.pc:04X}")
    print(f"Final state: {cpu.format_state()}")

    # Show zero page
    print(f"\nKey zero-page values:")
    for addr in [0x26, 0x27, 0x2A, 0x2B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41]:
        print(f"  ${addr:02X} = ${cpu.mem[addr]:02X}")

if __name__ == '__main__':
    main()

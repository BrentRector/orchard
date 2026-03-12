#!/usr/bin/env python3
"""
Build the clean runtime memory image for Apple Panic.

The original binary loads at $07FD and contains a relocation routine at $1900
that copies memory regions to their final runtime locations. This script
simulates those copy loops and applies cleanups to produce a canonical image.

Usage:
    python build_runtime.py [--input PATH] [--output PATH]

    Defaults use repo-relative paths; override with CLI arguments.

Output:
    Prints a build summary showing copy-loop operations, cleanup regions, and
    an MD5 hash of the game code region ($6000-$A7FF). Writes the runtime
    image to OUTPUT_FILE.
"""

import argparse
import hashlib
import os
import struct
import sys
from pathlib import Path

EXPECTED_INPUT_SIZE = 26640
BASE_ADDR = 0x07FD          # Load address (raw binary, no header)
IMAGE_SIZE = 0xA800          # $0000-$A7FF = 43008 bytes


def file_offset(mem_addr):
    """Convert a memory address to a file offset."""
    return mem_addr - BASE_ADDR


def main():
    """Simulate the Apple Panic relocation routine and produce a clean runtime image."""
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Build the clean runtime memory image for Apple Panic.")
    parser.add_argument("--input", default=str(repo_root / "apple-panic" / "ApplePanic"),
                        help="Path to the raw Apple Panic binary")
    parser.add_argument("--output", default=str(repo_root / "apple-panic" / "ApplePanic_runtime.bin"),
                        help="Path for the runtime image output")
    args = parser.parse_args()

    INPUT_FILE = args.input
    OUTPUT_FILE = args.output
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_FILE)), exist_ok=True)

    # --- Read input ---
    with open(INPUT_FILE, "rb") as f:
        raw = f.read()

    if len(raw) != EXPECTED_INPUT_SIZE:
        print(f"WARNING: Expected {EXPECTED_INPUT_SIZE} bytes, got {len(raw)}")

    # Create a 64K memory image to work in, initialized to zero
    mem = bytearray(0x10000)

    # --- Load the file into memory at its load address ---
    # Raw binary, no header — entire file loads at $07FD
    data_len = len(raw)
    load_start = BASE_ADDR
    mem[load_start:load_start + data_len] = raw[0:data_len]

    print(f"Loaded {data_len} bytes at ${load_start:04X}-${load_start + data_len - 1:04X}")

    # --- Loop 1 (ascending): Copy $6800-$6FFF -> $0000-$07FF (8 pages) ---
    src1_start = 0x6800
    dst1_start = 0x0000
    copy1_len = 0x0800  # 8 pages * 256
    mem[dst1_start:dst1_start + copy1_len] = mem[src1_start:src1_start + copy1_len]
    print(f"Loop 1: Copied ${src1_start:04X}-${src1_start + copy1_len - 1:04X} -> "
          f"${dst1_start:04X}-${dst1_start + copy1_len - 1:04X} ({copy1_len} bytes)")

    # --- Loop 2 (descending): Copy pages $20-$67 -> pages $60-$A7 (72 pages) ---
    src2_start = 0x2000
    dst2_start = 0x6000
    copy2_len = 0x4800  # 72 pages * 256
    # Use a temporary copy since source and destination overlap
    block = bytes(mem[src2_start:src2_start + copy2_len])
    mem[dst2_start:dst2_start + copy2_len] = block
    print(f"Loop 2: Copied ${src2_start:04X}-${src2_start + copy2_len - 1:04X} -> "
          f"${dst2_start:04X}-${dst2_start + copy2_len - 1:04X} ({copy2_len} bytes)")

    # --- Resident area $0800-$1FFF stays in place (already there from load) ---
    print(f"Resident: ${0x0800:04X}-${0x1FFF:04X} (already at loaded position)")

    # --- Extract the runtime image $0000-$A7FF ---
    image = bytearray(mem[0x0000:0x0000 + IMAGE_SIZE])
    print(f"\nRuntime image: ${0x0000:04X}-${IMAGE_SIZE - 1:04X} ({IMAGE_SIZE} bytes, {IMAGE_SIZE:#x})")

    # === Cleanups ===
    cleanups = []

    # 1. Zero out EDASM dead code region $0D7D-$0FFC (640 bytes)
    clean_start = 0x0D7D
    clean_end = 0x0FFC
    clean_len = clean_end - clean_start + 1
    image[clean_start:clean_end + 1] = b'\x00' * clean_len
    cleanups.append(f"  Zeroed ${clean_start:04X}-${clean_end:04X} ({clean_len} bytes) - EDASM dead code")

    # 2. Replace credit text at $05D0-$05F8 with $A0 spaces
    credit_start = 0x05D0
    credit_end = 0x05F8
    credit_len = credit_end - credit_start + 1
    # Show what we're replacing for reference
    old_credit = image[credit_start:credit_end + 1]
    credit_text = "".join(chr(b & 0x7F) for b in old_credit if 0xA1 <= b <= 0xDA)
    print(f"\n  Credit text found: \"{credit_text}\"")
    image[credit_start:credit_end + 1] = b'\xa0' * credit_len
    cleanups.append(f"  Blanked ${credit_start:04X}-${credit_end:04X} ({credit_len} bytes) - credit text")

    # 3. Replace $1900-$1939 with clean minimal loader + zero fill
    loader_start = 0x1900
    loader_end = 0x1939
    loader_len = loader_end - loader_start + 1  # 58 bytes

    # Build the clean loader
    loader = bytearray()
    loader += b'\xAD\x50\xC0'   # LDA $C050 - graphics mode
    loader += b'\xAD\x52\xC0'   # LDA $C052 - full screen
    loader += b'\xAD\x57\xC0'   # LDA $C057 - hi-res
    loader += b'\x4C\x00\x70'   # JMP $7000  - start game
    # Pad with zeros
    loader += b'\x00' * (loader_len - len(loader))

    image[loader_start:loader_end + 1] = loader
    cleanups.append(f"  Patched ${loader_start:04X}-${loader_end:04X} ({loader_len} bytes) - clean loader")

    # --- Save ---
    with open(OUTPUT_FILE, "wb") as f:
        f.write(image)

    # --- Summary ---
    print(f"\n=== Build Summary ===")
    print(f"Input:  {INPUT_FILE} ({len(raw)} bytes)")
    print(f"Output: {OUTPUT_FILE} ({len(image)} bytes)")
    print(f"\nRegions cleaned:")
    for c in cleanups:
        print(c)

    # MD5 of game code region $6000-$A7FF
    game_region = image[0x6000:0xA800]
    md5 = hashlib.md5(game_region).hexdigest()
    print(f"\nMD5 of game code $6000-$A7FF ({len(game_region)} bytes): {md5}")

    print(f"\nDone. Runtime image written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

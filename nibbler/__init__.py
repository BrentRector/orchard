"""
nibbler — WOZ disk image analysis toolkit for Apple II

Analyze copy-protected WOZ disk images, emulate boot processes,
extract runtime binaries, and convert to standard DSK format.

Usage:
    python -m nibbler <command> <woz_file> [options]

Commands:
    info      Show WOZ metadata and track map
    scan      Scan tracks for encoding type, sector count, checksums
    protect   Detect copy protection techniques
    boot      Emulate boot process and capture memory
    decode    Decode specific track/sector data
    dsk       Convert to standard DOS 3.3 DSK image
    disasm    Disassemble a binary or memory dump
"""

__version__ = "0.1.0"

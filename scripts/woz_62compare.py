#!/usr/bin/env python3
"""
Compare 6-and-2 GCR decoded sector data from a WOZ disk image against the
corresponding sector in a .dsk file to validate the decoding algorithm.

Reads Track 0, Sector 0 from both an Apple Panic WOZ image and a .dsk image,
decodes the WOZ nibble data using the boot ROM's 6-and-2 GCR algorithm, and
performs a byte-by-byte comparison. Reports any differences, analyzing whether
mismatches are confined to the low 2 bits (which would indicate an aux-byte
decoding error).

Usage:
    python woz_62compare.py

    Default paths (override by editing APPLE_PANIC):
        - .dsk file: apple-panic/ApplePanic_original.dsk
        - .woz file: apple-panic/Apple Panic - Disk 1, Side A.woz

Expected output:
    Hex dumps of T0S0 from both .dsk and WOZ sources, a match count out of 256,
    details of any differing bytes, and a search across all 16 .dsk T0 sectors
    for potential matches.
"""
import struct
from pathlib import Path

# 6-and-2 GCR encoding table: maps 6-bit values (0-63) to disk nibbles.
# Only nibbles with the high bit set and no more than one consecutive zero bit
# are valid on the Disk II hardware.
ENCODE_62 = [
    0x96, 0x97, 0x9A, 0x9B, 0x9D, 0x9E, 0x9F, 0xA6,
    0xA7, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF, 0xB2, 0xB3,
    0xB4, 0xB5, 0xB6, 0xB7, 0xB9, 0xBA, 0xBB, 0xBC,
    0xBD, 0xBE, 0xBF, 0xCB, 0xCD, 0xCE, 0xCF, 0xD3,
    0xD6, 0xD7, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE,
    0xDF, 0xE5, 0xE6, 0xE7, 0xE9, 0xEA, 0xEB, 0xEC,
    0xED, 0xEE, 0xEF, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6,
    0xF7, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF,
]
# Reverse lookup: disk nibble -> 6-bit decoded value
DECODE_62 = {v: i for i, v in enumerate(ENCODE_62)}


def read_woz_nibbles(woz_path, track_num):
    """Read a WOZ2 disk image and extract the nibble stream for a given track.

    Parses the WOZ2 TMAP and TRKS chunks to locate the track's bit stream,
    converts it to a list of 8-bit nibbles (each starting with a 1-bit).

    Args:
        woz_path: Path to the WOZ2 disk image file.
        track_num: Logical track number (0-34).

    Returns:
        A list of nibble bytes for the track, or None if the track is empty.
    """
    with open(woz_path, 'rb') as f:
        data = f.read()
    # WOZ2 TMAP starts at offset 88: 160 entries mapping quarter-tracks to TRKS indices
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]  # Quarter-track index (each track = 4 quarter-tracks)
    if tidx == 0xFF:
        return None
    # TRKS chunk entries: 8 bytes each starting at offset 256
    offset = 256 + tidx * 8
    sb = struct.unpack_from('<H', data, offset)[0]       # Starting block (512-byte units)
    bc = struct.unpack_from('<H', data, offset + 2)[0]   # Block count
    bits = struct.unpack_from('<I', data, offset + 4)[0]  # Number of valid bits
    track_data = data[sb * 512:sb * 512 + bc * 512]
    # Unpack individual bits from the track data, MSB first
    bit_list = []
    for b in track_data:
        for i in range(7, -1, -1):
            bit_list.append((b >> i) & 1)
            if len(bit_list) >= bits:
                break
        if len(bit_list) >= bits:
            break
    # Convert bit stream to nibbles: accumulate bits until high bit is set,
    # which marks the start of a valid disk nibble
    nibbles = []
    current = 0
    for b in bit_list:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles


def decode_62_bootrom(encoded_342):
    """Decode 342 GCR-translated values using the boot ROM's 6-and-2 algorithm.

    This is the naive/simplified interpretation: upper 6 bits from decoded[86+Y],
    lower 2 bits from decoded[Y]. This does NOT match the actual P6 ROM behavior
    (which uses reversed aux order and destructive LSR), so it may produce
    incorrect low-2-bit values. See boot_rom_decode.py for the ROM-exact version.

    Args:
        encoded_342: List of 342 GCR-decoded 6-bit values.

    Returns:
        Tuple of (result_bytearray_256, decoded_list_342).
    """
    # XOR chain: each value is XORed with the previous to undo the disk encoding
    decoded = [0] * 342
    prev = 0
    for k in range(342):
        decoded[k] = encoded_342[k] ^ prev
        prev = decoded[k]
    # Reconstruct 256 output bytes from 86 aux + 256 primary decoded values
    # decoded[0..85] = aux (low 2 bits), decoded[86..341] = primary (upper 6 bits)
    result = bytearray(256)
    for y in range(256):
        upper = decoded[86 + y] << 2
        lower = decoded[y] & 0x03
        result[y] = (upper | lower) & 0xFF
    return result, decoded


def main():
    """Compare WOZ 6-and-2 decode of T0S0 against the .dsk file version."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    # Read T0S0 from .dsk file
    dsk_path = str(APPLE_PANIC / "ApplePanic_original.dsk")
    with open(dsk_path, 'rb') as f:
        dsk_data = f.read()

    print(f".dsk file size: {len(dsk_data)} bytes ({len(dsk_data) // 256} sectors)")

    # .dsk files: 35 tracks * 16 sectors * 256 bytes = 143360
    # Sector ordering in .dsk: DOS 3.3 logical order
    # T0S0 is at offset 0
    dsk_t0s0 = dsk_data[0:256]
    print(f"\n=== .dsk T0S0 (first 256 bytes of .dsk file) ===")
    for row in range(16):
        off = row * 16
        h = ' '.join(f'{dsk_t0s0[off+c]:02X}' for c in range(16))
        a = ''.join(chr(dsk_t0s0[off+c]) if 32 <= dsk_t0s0[off+c] < 127 else '.'
                    for c in range(16))
        print(f"  ${0x0800+off:04X}: {h}  {a}")

    # Now decode from WOZ
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    nibbles = read_woz_nibbles(woz_path, 0)
    # Extend nibble stream to handle data fields that wrap around the track end
    nib = nibbles + nibbles[:2000]

    # Find D5 AA 96 sector 0 (6-and-2 address field prologue)
    for i in range(len(nibbles)):
        if nib[i] == 0xD5 and nib[i+1] == 0xAA and nib[i+2] == 0x96:
            # Find data field
            for j in range(i + 11, i + 200):
                if nib[j] == 0xD5 and nib[j+1] == 0xAA and nib[j+2] == 0xAD:
                    didx = j + 3
                    # GCR decode 343 nibbles
                    encoded = [DECODE_62[nib[didx+k]] for k in range(343)]
                    woz_result, decoded = decode_62_bootrom(encoded[:342])

                    print(f"\n=== WOZ decode (boot ROM algorithm) ===")
                    for row in range(16):
                        off = row * 16
                        h = ' '.join(f'{woz_result[off+c]:02X}' for c in range(16))
                        print(f"  ${0x0800+off:04X}: {h}")

                    # Compare byte by byte
                    match_count = sum(1 for k in range(256) if woz_result[k] == dsk_t0s0[k])
                    print(f"\n=== Comparison ===")
                    print(f"  Matching bytes: {match_count}/256")

                    if match_count < 256:
                        print(f"\n  Differences (first 20):")
                        diffs = 0
                        for k in range(256):
                            if woz_result[k] != dsk_t0s0[k]:
                                # Check which bits differ
                                xor = woz_result[k] ^ dsk_t0s0[k]
                                print(f"    [{k:3d}] WOZ=${woz_result[k]:02X} DSK=${dsk_t0s0[k]:02X} XOR=${xor:02X} (bits {xor:08b})")
                                diffs += 1
                                if diffs >= 20:
                                    break

                        # Analyze: are differences only in low 2 bits?
                        only_low2 = True
                        for k in range(256):
                            if woz_result[k] != dsk_t0s0[k]:
                                xor = woz_result[k] ^ dsk_t0s0[k]
                                if xor & 0xFC:
                                    only_low2 = False
                                    break
                        print(f"\n  Differences only in low 2 bits: {only_low2}")

                        # If only low bits differ, the aux decode is wrong
                        # Let's figure out what the correct aux values should be
                        if only_low2:
                            print(f"\n  === Reconstructing correct aux values ===")
                            correct_aux = [0] * 256
                            for k in range(256):
                                correct_aux[k] = dsk_t0s0[k] & 0x03
                                current_aux = decoded[k] & 0x03

                            # Show what decoded[0..85] should be (low 2 bits)
                            print(f"  Current decoded aux[0:20]: {' '.join(f'{decoded[k] & 0x03}' for k in range(20))}")
                            print(f"  Needed  aux bits[0:20]:    {' '.join(f'{dsk_t0s0[k] & 0x03}' for k in range(20))}")

                            # For bytes 86-255, the "aux" comes from decoded[86..255]
                            # (which are main bytes). Check if those also differ
                            print(f"\n  Current decoded[86:106] low2: {' '.join(f'{decoded[k] & 0x03}' for k in range(86, 106))}")
                            print(f"  Needed  aux bits[86:106]:     {' '.join(f'{dsk_t0s0[k] & 0x03}' for k in range(86, 106))}")

                    # Also try: maybe .dsk uses different sector ordering
                    # DOS 3.3 physical-to-logical: 0,7,14,6,13,5,12,4,11,3,10,2,9,1,8,15
                    # .dsk stores in LOGICAL order. The WOZ has PHYSICAL sectors.
                    # So WOZ physical sector 0 = .dsk logical sector 0 (for T0S0 they're the same)
                    # Actually, physical sector 0 maps to logical sector 0 in DOS 3.3 interleave

                    break
            break

    # Also try all 16 .dsk sectors of track 0 to see if any match
    print(f"\n=== Searching all .dsk T0 sectors for match ===")
    for s in range(16):
        offset = s * 256  # T0 sectors
        sector = dsk_data[offset:offset + 256]
        match = sum(1 for k in range(256) if woz_result[k] == sector[k])
        if match > 200:
            print(f"  .dsk T0S{s:2d} (offset {offset:5d}): {match}/256 match")
        # Also check upper 6 bits only
        match6 = sum(1 for k in range(256) if (woz_result[k] & 0xFC) == (sector[k] & 0xFC))
        if match6 > 200:
            print(f"  .dsk T0S{s:2d} upper-6-bits: {match6}/256 match")


if __name__ == '__main__':
    main()

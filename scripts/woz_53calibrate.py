#!/usr/bin/env python3
"""
Calibrate 5-and-3 byte reconstruction by trying ALL plausible packing variants.

Systematically tries every combination of primary buffer direction (forward/
reverse), secondary buffer direction (forward/reverse), and bit-packing order
(MSB/LSB) against the boot sector from Track 0. Also tries swapped region
layouts (primary at [0:256] vs. [154:410]). For each "reasonable" variant
(byte 0 between 1 and 13, which is a valid sector count), decodes all Track 0
sectors and checks for matches against the cracked runtime image.

Usage:
    python woz_53calibrate.py

    Default paths (override by editing APPLE_PANIC):
        woz_path - apple-panic/Apple Panic - Disk 1, Side A.woz
        Also reads apple-panic/ApplePanic_runtime.bin for comparison

Output:
    A table of all reconstruction variants showing byte 0 and first 8 bytes,
    followed by detailed match results for promising variants (exact sector
    matches and short pattern searches against the cracked version).
"""
import struct
from pathlib import Path

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def read_track0_nibbles(woz_path):
    """Read a WOZ2 file and return the nibble stream for track 0."""
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[0]
    offset = 256 + tidx * 8
    sb = struct.unpack_from('<H', data, offset)[0]
    bc = struct.unpack_from('<H', data, offset + 2)[0]
    bits = struct.unpack_from('<I', data, offset + 4)[0]
    track_data = data[sb * 512:sb * 512 + bc * 512]

    bit_list = []
    for b in track_data:
        for i in range(7, -1, -1):
            bit_list.append((b >> i) & 1)
            if len(bit_list) >= bits:
                break
        if len(bit_list) >= bits:
            break
    nibbles = []
    current = 0
    for b in bit_list:
        current = ((current << 1) | b) & 0xFF
        if current & 0x80:
            nibbles.append(current)
            current = 0
    return nibbles


def decode_44(b1, b2):
    """Decode a 4-and-4 encoded byte pair (used in address field headers)."""
    return ((b1 << 1) | 0x01) & b2


def get_53_raw(nibbles, idx):
    """Get raw 5-bit XOR-decoded values from 410+1 data nibbles."""
    translated = []
    for i in range(411):
        nib = nibbles[idx + i]
        if nib not in DECODE_53:
            return None
        translated.append(DECODE_53[nib])

    decoded = [0] * 410
    prev = 0
    for i in range(410):
        decoded[i] = translated[i] ^ prev
        prev = decoded[i]

    cksum_val = translated[410]
    cksum_ok = (prev == cksum_val)
    return decoded, cksum_ok


def reconstruct_bytes(decoded, primary_start, primary_dir, sec_start, sec_dir,
                      pack_order):
    """Try to reconstruct 256 bytes from 410 5-bit values.

    primary_start: start index for primary values (154 or 0)
    primary_dir: +1 (forward) or -1 (reverse)
    sec_start: start index for secondary values
    sec_dir: +1 or -1
    pack_order: 'msb' or 'lsb' (which end of 15 bits gets byte 0)
    """
    result = bytearray(256)

    # Primary values (upper 5 bits)
    for i in range(256):
        p_idx = primary_start + i * primary_dir
        if 0 <= p_idx < 410:
            result[i] = (decoded[p_idx] & 0x1F) << 3

    # Secondary values (lower 3 bits, packed 5 per 3 nibbles)
    sec_len = 410 - 256  # = 154
    for i in range(256):
        group = i // 5
        pos = i % 5

        # Get the 3 nibbles for this group
        g_base = sec_start + group * 3 * sec_dir
        if sec_dir == 1:
            n0_idx = g_base
            n1_idx = g_base + 1
            n2_idx = g_base + 2
        else:
            n0_idx = g_base
            n1_idx = g_base - 1
            n2_idx = g_base - 2

        if not (0 <= n0_idx < 410 and 0 <= n1_idx < 410 and 0 <= n2_idx < 410):
            continue

        n0 = decoded[n0_idx] & 0x1F
        n1 = decoded[n1_idx] & 0x1F
        n2 = decoded[n2_idx] & 0x1F

        combined = (n0 << 10) | (n1 << 5) | n2

        if pack_order == 'msb':
            lower3 = (combined >> (12 - pos * 3)) & 7
        else:  # lsb
            lower3 = (combined >> (pos * 3)) & 7

        result[i] |= lower3

    return bytes(result)


def main():
    """Try all 5-and-3 reconstruction variants and report matches against cracked image."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    APPLE_PANIC = REPO_ROOT / "apple-panic"
    woz_path = str(APPLE_PANIC / "Apple Panic - Disk 1, Side A.woz")
    nibbles = read_track0_nibbles(woz_path)
    nib2 = nibbles + nibbles[:1000]

    # Find D5 AA B5 sector 0 data field
    b5_s0_data_idx = None
    for i in range(len(nibbles)):
        if nib2[i] == 0xD5 and nib2[i + 1] == 0xAA and nib2[i + 2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib2[idx + 4], nib2[idx + 5])
            if sec == 0:
                # Find following D5 AA AD
                for j in range(idx + 8, idx + 80):
                    if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                        b5_s0_data_idx = j + 3
                        break
                break

    if not b5_s0_data_idx:
        print("Could not find D5 AA B5 S0 data field!")
        return

    # Get raw 5-bit decoded values
    raw = get_53_raw(nib2, b5_s0_data_idx)
    if not raw:
        print("Failed to decode 5-and-3 nibbles!")
        return

    decoded, cksum_ok = raw
    print(f"Raw decoded: {len(decoded)} values, checksum {'OK' if cksum_ok else 'BAD'}")

    # Print full decoded buffer
    print("\nFull decoded 5-bit values:")
    for row in range(26):
        off = row * 16
        vals = ' '.join(f'{decoded[off + c]:02X}' for c in range(min(16, 410 - off)))
        label = "SEC" if off < 154 else "PRI"
        print(f"  [{off:3d}] ({label}): {vals}")

    # Try systematic reconstruction variants
    print("\n=== Trying all reconstruction variants ===")

    cracked = open(str(APPLE_PANIC / "ApplePanic_runtime.bin"), 'rb').read()

    # For each variant, decode all T0 sectors and check for matches
    variants = []

    for p_start, p_dir, p_name in [(154, 1, "fwd"), (409, -1, "rev")]:
        for s_start, s_dir, s_name in [(0, 1, "fwd"), (153, -1, "rev")]:
            for pack in ['msb', 'lsb']:
                name = f"P:{p_name} S:{s_name} Pack:{pack}"
                result = reconstruct_bytes(decoded, p_start, p_dir,
                                           s_start, s_dir, pack)
                byte0 = result[0]
                first8 = ' '.join(f'{b:02X}' for b in result[:8])
                variants.append((name, byte0, first8, result))

    # Also try: primary at [0:256], secondary at [256:410] (swapped regions)
    for p_start, p_dir, p_name in [(0, 1, "fwd0"), (255, -1, "rev0")]:
        for s_start, s_dir, s_name in [(256, 1, "fwd256"), (409, -1, "rev409")]:
            for pack in ['msb', 'lsb']:
                name = f"P:{p_name} S:{s_name} Pack:{pack}"
                result = reconstruct_bytes(decoded, p_start, p_dir,
                                           s_start, s_dir, pack)
                byte0 = result[0]
                first8 = ' '.join(f'{b:02X}' for b in result[:8])
                variants.append((name, byte0, first8, result))

    # Show all variants
    print(f"\n{'Name':35s} Byte0  First 8 bytes")
    print("-" * 80)
    for name, byte0, first8, _ in variants:
        marker = " <-- REASONABLE" if 0 < byte0 <= 13 else ""
        print(f"{name:35s} ${byte0:02X}    {first8}{marker}")

    # For promising variants (byte0 1-13), try loading all T0 sectors
    # and searching for game patterns
    print("\n=== Checking promising variants against cracked version ===")

    # First, get ALL T0 sector data fields
    all_t0_sectors = {}  # sec_num -> data_idx
    for i in range(len(nibbles)):
        if nib2[i] == 0xD5 and nib2[i + 1] == 0xAA and nib2[i + 2] == 0xB5:
            idx = i + 3
            sec = decode_44(nib2[idx + 4], nib2[idx + 5])
            if sec not in all_t0_sectors:
                for j in range(idx + 8, idx + 80):
                    if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                        didx = j + 3
                        # Check it's 5-and-3 (not 6-and-2)
                        valid53 = 0
                        for k in range(411):
                            if nib2[didx + k] in DECODE_53:
                                valid53 += 1
                            else:
                                break
                        if valid53 >= 410:
                            all_t0_sectors[sec] = didx
                        break

    print(f"Track 0 sectors with 5&3 data: {sorted(all_t0_sectors.keys())}")

    for name, byte0, first8, boot in variants:
        if not (0 < byte0 <= 13):
            continue

        # Decode all T0 sectors with this variant's parameters
        # Extract the variant parameters
        parts = name.split()
        p_part = parts[0].split(':')[1]  # fwd, rev, fwd0, rev0
        s_part = parts[1].split(':')[1]  # fwd, rev, fwd256, rev409
        pack = parts[2].split(':')[1]  # msb, lsb

        if p_part == "fwd":
            p_start, p_dir = 154, 1
        elif p_part == "rev":
            p_start, p_dir = 409, -1
        elif p_part == "fwd0":
            p_start, p_dir = 0, 1
        else:
            p_start, p_dir = 255, -1

        if s_part == "fwd":
            s_start, s_dir = 0, 1
        elif s_part == "rev":
            s_start, s_dir = 153, -1
        elif s_part == "fwd256":
            s_start, s_dir = 256, 1
        else:
            s_start, s_dir = 409, -1

        # Build a concatenation of all T0 sectors
        all_data = bytearray()
        for sec_num in range(13):
            if sec_num in all_t0_sectors:
                raw = get_53_raw(nib2, all_t0_sectors[sec_num])
                if raw:
                    dec, _ = raw
                    sector = reconstruct_bytes(dec, p_start, p_dir,
                                               s_start, s_dir, pack)
                    all_data.extend(sector)
                else:
                    all_data.extend(bytes(256))
            else:
                all_data.extend(bytes(256))

        # Count non-zero sector matches with cracked version
        matches = 0
        nz_matches = 0
        for off in range(0, len(all_data) - 256, 256):
            sector = all_data[off:off + 256]
            if all(b == 0 for b in sector):
                continue  # skip zero sectors
            for game_start in range(0, len(cracked) - 256, 256):
                if cracked[game_start:game_start + 256] == sector:
                    nz_matches += 1
                    if nz_matches <= 3:
                        print(f"  {name}: NON-ZERO match woz[${off:04X}] = "
                              f"cracked[${game_start:04X}]")

        # Search for 4-byte patterns
        patterns = {
            "JMP $7465": bytes([0x4C, 0x65, 0x74]),
            "LDA $C08C": bytes([0xBD, 0x8C, 0xC0]),
            "STA $C0": bytes([0x8D, 0x54, 0xC0]),
        }
        found_any = False
        for pname, pat in patterns.items():
            for i in range(len(all_data) - len(pat)):
                if all_data[i:i + len(pat)] == pat:
                    found_any = True
                    print(f"  {name}: FOUND {pname} at ${i:04X}")
                    break

        if not found_any and nz_matches == 0:
            print(f"  {name}: no matches")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Brute-force 5-and-3 byte reconstruction calibration.
Try raw bit concatenation and various unusual packing schemes.
"""
import struct

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}


def read_track_nibbles(woz_path, track_num):
    with open(woz_path, 'rb') as f:
        data = f.read()
    tmap = data[88:88 + 160]
    tidx = tmap[track_num * 4]
    if tidx == 0xFF:
        return None
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
    return ((b1 << 1) | 0x01) & b2


def get_sector_data_positions(nibbles, prologue_byte=0xAA):
    """Find D5 xx B5 sectors and their data field positions."""
    nib2 = nibbles + nibbles[:1000]
    sectors = {}
    for i in range(len(nibbles)):
        if (nib2[i] == 0xD5 and i + 2 < len(nib2) and nib2[i + 2] == 0xB5):
            idx = i + 3
            if idx + 8 < len(nib2):
                sec = decode_44(nib2[idx + 4], nib2[idx + 5])
                for j in range(idx + 8, idx + 80):
                    if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                        didx = j + 3
                        valid = sum(1 for k in range(411)
                                    if nib2[didx + k] in DECODE_53)
                        if valid >= 410 and sec not in sectors:
                            sectors[sec] = didx
                        break
    return sectors, nib2


def get_53_raw(nib2, idx):
    translated = []
    for i in range(411):
        nib = nib2[idx + i]
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


def reconstruct_bitstream(decoded, msb_first=True):
    """Concatenate all 5-bit values into a bitstream, then read 8-bit bytes."""
    bits = []
    for val in decoded:
        if msb_first:
            for i in range(4, -1, -1):
                bits.append((val >> i) & 1)
        else:
            for i in range(5):
                bits.append((val >> i) & 1)

    # Read 256 bytes (2048 bits) from the bitstream
    result = bytearray(256)
    for i in range(256):
        byte_val = 0
        for b in range(8):
            bit_idx = i * 8 + b
            if bit_idx < len(bits):
                if msb_first:
                    byte_val = (byte_val << 1) | bits[bit_idx]
                else:
                    byte_val |= bits[bit_idx] << b
        result[i] = byte_val
    return bytes(result)


def reconstruct_p5a(decoded):
    """Standard P5A ROM reconstruction.

    Based on actual P5A ROM disassembly from 'Beneath Apple DOS':
    - Buffer holds 410 five-bit values
    - First 256 values (indices 0-255) = primary (upper 5 bits)
    - Next 154 values (indices 256-409) = secondary (packed lower 3 bits)
    - Primary: byte[i] upper = decoded[i] << 3
    - Secondary: interleaved 3-bit extraction from decoded[256+]

    P5A ROM secondary packing:
    The ROM reads nibbles into the buffer with Y going from 0 upward.
    The first 154 nibbles go to buffer[0-153] (these become secondary).
    The next 256 nibbles go to buffer[154-409] (these become primary).
    Wait, that's the other way... let me try both.
    """
    # Try standard layout: primary at [0:256], secondary at [256:410]
    result = bytearray(256)
    for i in range(256):
        result[i] = (decoded[i] & 0x1F) << 3

    # Secondary: 154 values at [256:410]
    # Each group of 3 nibbles encodes 5 three-bit values
    # Mapping: byte i -> secondary position
    # The P5A ROM processes bytes in REVERSE (Y counts down from 255 to 0)
    # For each group of 5 consecutive bytes, their 3-bit values come from
    # 3 consecutive secondary nibbles.
    #
    # Standard mapping:
    # Bytes 0-4 -> secondary [0,1,2]
    # Bytes 5-9 -> secondary [3,4,5]
    # Bytes 10-14 -> secondary [6,7,8]
    # ...
    # Bytes 250-254 -> secondary [150,151,152]
    # Byte 255 -> secondary [153]

    for group in range(51):
        si = 256 + group * 3
        if si + 2 >= 410:
            break
        n0 = decoded[si] & 0x1F
        n1 = decoded[si + 1] & 0x1F
        n2 = decoded[si + 2] & 0x1F
        combined = (n0 << 10) | (n1 << 5) | n2

        base = group * 5
        # Extract 5 three-bit values (MSB order)
        for pos in range(5):
            if base + pos < 256:
                lower3 = (combined >> (12 - pos * 3)) & 7
                result[base + pos] |= lower3

    # Last byte (255)
    if 256 + 153 < 410:
        n = decoded[256 + 153] & 0x1F
        result[255] |= (n >> 2) & 7

    return bytes(result)


def reconstruct_p5a_rev(decoded):
    """P5A with reversed byte processing order."""
    result = bytearray(256)
    for i in range(256):
        result[255 - i] = (decoded[i] & 0x1F) << 3

    for group in range(51):
        si = 256 + group * 3
        if si + 2 >= 410:
            break
        n0 = decoded[si] & 0x1F
        n1 = decoded[si + 1] & 0x1F
        n2 = decoded[si + 2] & 0x1F
        combined = (n0 << 10) | (n1 << 5) | n2

        base = group * 5
        for pos in range(5):
            byte_idx = 255 - (base + pos)
            if 0 <= byte_idx < 256:
                lower3 = (combined >> (12 - pos * 3)) & 7
                result[byte_idx] |= lower3

    return bytes(result)


def reconstruct_interleaved(decoded, interleave):
    """Try interleaved secondary mapping.
    interleave: number of groups between consecutive bytes' 3-bit values."""
    result = bytearray(256)
    for i in range(256):
        result[i] = (decoded[154 + i] & 0x1F) << 3

    # Secondary at [0:154]
    # Interleaved mapping: byte i corresponds to:
    # sec_group = (i * interleave) % 51 (approximately)
    for i in range(256):
        group = (i * interleave) % 51
        pos = ((i * interleave) // 51) % 5
        si = group * 3
        if si + 2 >= 154:
            continue
        n0 = decoded[si] & 0x1F
        n1 = decoded[si + 1] & 0x1F
        n2 = decoded[si + 2] & 0x1F
        combined = (n0 << 10) | (n1 << 5) | n2
        lower3 = (combined >> (12 - pos * 3)) & 7
        result[i] |= lower3

    return bytes(result)


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    cracked = open("E:/Apple/ApplePanic_runtime.bin", 'rb').read()

    nibbles = read_track_nibbles(woz_path, 0)
    sectors, nib2 = get_sector_data_positions(nibbles)
    print(f"Track 0 sectors: {sorted(sectors.keys())}")

    # Get raw decoded values for all sectors
    raw_sectors = {}
    for sec, didx in sectors.items():
        raw = get_53_raw(nib2, didx)
        if raw:
            decoded, cksum_ok = raw
            raw_sectors[sec] = decoded
            if sec == 0:
                print(f"  S0 checksum: {'OK' if cksum_ok else 'BAD'}")

    if 0 not in raw_sectors:
        print("No sector 0!")
        return

    decoded = raw_sectors[0]

    print("\n=== Raw bit concatenation ===")
    for msb in [True, False]:
        result = reconstruct_bitstream(decoded, msb)
        label = "MSB-first" if msb else "LSB-first"
        first8 = ' '.join(f'{b:02X}' for b in result[:8])
        print(f"  {label}: byte0=${result[0]:02X} {first8}")

    print("\n=== P5A standard (primary=[0:256], secondary=[256:410]) ===")
    result = reconstruct_p5a(decoded)
    first16 = ' '.join(f'{b:02X}' for b in result[:16])
    print(f"  Forward: byte0=${result[0]:02X} {first16}")

    result = reconstruct_p5a_rev(decoded)
    first16 = ' '.join(f'{b:02X}' for b in result[:16])
    print(f"  Reverse: byte0=${result[0]:02X} {first16}")

    print("\n=== Interleaved secondary mappings (primary=[154:410]) ===")
    for interleave in range(1, 10):
        result = reconstruct_interleaved(decoded, interleave)
        first8 = ' '.join(f'{b:02X}' for b in result[:8])
        marker = " <--" if 0 < result[0] <= 13 else ""
        print(f"  Interleave {interleave}: byte0=${result[0]:02X} {first8}{marker}")

    # === Now try a completely different idea ===
    # What if the disk doesn't use 5-and-3 encoding at all, but rather
    # stores data as raw nibbles without any byte reconstruction?
    # What if each 5-bit value IS a byte (just the upper 5 bits)?
    print("\n=== Upper 5 bits only (no secondary) ===")
    result_5 = bytes([(d & 0x1F) << 3 for d in decoded[:256]])
    first16 = ' '.join(f'{b:02X}' for b in result_5[:16])
    print(f"  Primary [0:256]: {first16}")
    result_5b = bytes([(d & 0x1F) << 3 for d in decoded[154:]])
    first16 = ' '.join(f'{b:02X}' for b in result_5b[:16])
    print(f"  Primary [154:410]: {first16}")

    # === Check: what does the P5A ROM ACTUALLY use for sector 0 on track 0? ===
    # The P5A ROM reads the FIRST D5 AA B5 address field it finds.
    # On our disk, the first D5 AA B5 is at position 240 (sector 11).
    # So the P5A ROM reads SECTOR 11 first, NOT sector 0!
    # The P5A ROM's boot process reads ALL sectors (not just sector 0).
    # It stores sector N to $0800 + N * 256.
    # Sector 0 goes to $0800, sector 1 to $0900, etc.
    print("\n=== P5A boot loading order ===")
    print("  The P5A ROM reads sectors by NUMBER from the address field")
    print("  and stores sector N at $0800 + N * $100")
    print()

    # Build full track 0 image using P5A standard reconstruction
    t0_image = bytearray(13 * 256)  # 13 sectors * 256 bytes
    for sec_num in range(13):
        if sec_num in raw_sectors:
            result = reconstruct_p5a(raw_sectors[sec_num])
            t0_image[sec_num * 256: (sec_num + 1) * 256] = result

    # Show boot sector (sector 0)
    boot = t0_image[0:256]
    print(f"Boot sector (P5A standard):")
    print(f"  Byte 0: ${boot[0]:02X} ({boot[0]})")
    print(f"  First 32: {' '.join(f'{b:02X}' for b in boot[:32])}")

    # Show ALL sectors first 8 bytes
    print(f"\nAll T0 sectors (P5A standard):")
    for s in range(13):
        sec = t0_image[s * 256: (s + 1) * 256]
        first8 = ' '.join(f'{b:02X}' for b in sec[:8])
        nonzero = sum(1 for b in sec if b != 0)
        print(f"  S{s:2d}: {first8}... ({nonzero}/256 non-zero)")

    # Try matching against cracked version - look for partial matches
    print("\n=== Partial match search (8-byte sliding window) ===")
    for game_start in range(0x0800, 0xA800, 0x100):
        game_page = cracked[game_start:game_start + 256]
        if all(b == 0 for b in game_page):
            continue
        # Try each sector against this game page
        for s in range(13):
            sec = t0_image[s * 256:(s + 1) * 256]
            if all(b == 0 for b in sec):
                continue
            # Count matching bytes
            matches = sum(1 for a, b in zip(sec, game_page) if a == b)
            if matches > 128:  # more than 50% match
                print(f"  S{s} matches cracked ${game_start:04X}: "
                      f"{matches}/256 bytes ({matches*100//256}%)")

    # Try XOR between sectors and cracked pages
    print("\n=== XOR analysis (find encryption key) ===")
    for s in range(13):
        sec = t0_image[s * 256:(s + 1) * 256]
        if all(b == 0 for b in sec):
            continue
        for game_start in range(0x0800, 0x0C00, 0x100):
            game_page = cracked[game_start:game_start + 256]
            xor_result = bytes(a ^ b for a, b in zip(sec, game_page))
            # Check if XOR result is a repeating pattern
            unique = len(set(xor_result))
            if unique <= 3:
                print(f"  S{s} XOR cracked[${game_start:04X}]: "
                      f"{unique} unique values: "
                      f"{', '.join(f'${v:02X}' for v in sorted(set(xor_result))[:5])}")


if __name__ == '__main__':
    main()

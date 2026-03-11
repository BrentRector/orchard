#!/usr/bin/env python3
"""Quick test: try both secondary orderings and check which gives better results."""
import struct

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}
GRP = 51


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


def get_53_xor_decoded(nibbles, idx):
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


def reconstruct(decoded, reverse_sec=True):
    thr = [0] * 154
    if reverse_sec:
        for j in range(154):
            thr[j] = decoded[153 - j]
    else:
        for j in range(154):
            thr[j] = decoded[j]

    top = [0] * 256
    for j in range(256):
        top[j] = decoded[154 + j]

    output = bytearray()
    for i in range(GRP - 1, -1, -1):
        s0 = thr[0 * GRP + i] if (0 * GRP + i) < 154 else 0
        s1 = thr[1 * GRP + i] if (1 * GRP + i) < 154 else 0
        s2 = thr[2 * GRP + i] if (2 * GRP + i) < 154 else 0

        byte_a = (top[0 * GRP + i] << 3) | ((s0 >> 2) & 7)
        output.append(byte_a & 0xFF)
        byte_b = (top[1 * GRP + i] << 3) | ((s1 >> 2) & 7)
        output.append(byte_b & 0xFF)
        byte_c = (top[2 * GRP + i] << 3) | ((s2 >> 2) & 7)
        output.append(byte_c & 0xFF)

        d_low = ((s0 & 2) << 1) | (s1 & 2) | ((s2 & 2) >> 1)
        byte_d = (top[3 * GRP + i] << 3) | (d_low & 7)
        output.append(byte_d & 0xFF)

        e_low = ((s0 & 1) << 2) | ((s1 & 1) << 1) | (s2 & 1)
        byte_e = (top[4 * GRP + i] << 3) | (e_low & 7)
        output.append(byte_e & 0xFF)

    final_top = top[5 * GRP] if 5 * GRP < 256 else 0
    final_thr = thr[3 * GRP] if 3 * GRP < 154 else 0
    byte_final = (final_top << 3) | (final_thr & 7)
    output.append(byte_final & 0xFF)

    return bytes(output[:256])


def find_sectors(nibbles):
    nib2 = nibbles + nibbles[:2000]
    sectors = {}
    for i in range(len(nibbles)):
        if nib2[i] != 0xD5 or nib2[i + 2] != 0xB5:
            continue
        idx = i + 3
        if idx + 8 >= len(nib2):
            continue
        sec = decode_44(nib2[idx + 4], nib2[idx + 5])
        for j in range(idx + 8, idx + 80):
            if j + 2 >= len(nib2):
                break
            if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                didx = j + 3
                valid = sum(1 for k in range(411) if didx + k < len(nib2)
                            and nib2[didx + k] in DECODE_53)
                if valid >= 410 and sec not in sectors:
                    sectors[sec] = didx
                break
    return sectors, nib2


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    cracked = open("E:/Apple/ApplePanic_runtime.bin", 'rb').read()

    nibbles = read_track_nibbles(woz_path, 0)
    sectors, nib2 = find_sectors(nibbles)

    # For S12 (which matched exactly), check secondary values
    for sec_num in [12, 0, 2, 3]:
        if sec_num not in sectors:
            continue
        raw = get_53_xor_decoded(nib2, sectors[sec_num])
        if not raw:
            continue
        decoded, cksum_ok = raw

        # Check secondary values (decoded[0:154])
        sec_vals = decoded[0:154]
        nonzero_sec = sum(1 for v in sec_vals if v != 0)
        print(f"S{sec_num:2d}: secondary nonzero={nonzero_sec}/154, "
              f"first 10: {' '.join(f'{v:02X}' for v in sec_vals[:10])}")

        # Try both orderings
        for rev in [True, False]:
            result = reconstruct(decoded, reverse_sec=rev)
            label = "reversed" if rev else "forward"
            first16 = ' '.join(f'{b:02X}' for b in result[:16])

            # Count $FF bytes
            ff_count = sum(1 for b in result if b == 0xFF)

            # Check against cracked
            best_match = 0
            best_off = 0
            for game_off in range(0, len(cracked), 256):
                game_page = cracked[game_off:game_off + 256]
                matches = sum(1 for a, b in zip(result, game_page) if a == b)
                if matches > best_match:
                    best_match = matches
                    best_off = game_off

            exact = "EXACT" if best_match == 256 else f"{best_match}/256"
            print(f"  {label}: {first16}  FFs={ff_count} match={exact} @${best_off:04X}")

    # Also try: what if the ROM reads secondary FORWARD (not reversed)?
    # i.e., thr[0] = first disk byte, thr[1] = second, etc.
    # This would mean thr[j] = decoded[j] directly

    # Also try: swap the iteration direction (i from 0 to 50 instead of 50 to 0)
    print("\n=== Try forward iteration (i from 0 to 50) ===")
    for sec_num in [12, 0]:
        if sec_num not in sectors:
            continue
        raw = get_53_xor_decoded(nib2, sectors[sec_num])
        if not raw:
            continue
        decoded, _ = raw

        for rev in [True, False]:
            thr = [0] * 154
            if rev:
                for j in range(154):
                    thr[j] = decoded[153 - j]
            else:
                for j in range(154):
                    thr[j] = decoded[j]
            top = [0] * 256
            for j in range(256):
                top[j] = decoded[154 + j]

            output = bytearray()
            for i in range(GRP):  # 0 to 50
                s0 = thr[0 * GRP + i] if (0 * GRP + i) < 154 else 0
                s1 = thr[1 * GRP + i] if (1 * GRP + i) < 154 else 0
                s2 = thr[2 * GRP + i] if (2 * GRP + i) < 154 else 0

                output.append(((top[0 * GRP + i] << 3) | ((s0 >> 2) & 7)) & 0xFF)
                output.append(((top[1 * GRP + i] << 3) | ((s1 >> 2) & 7)) & 0xFF)
                output.append(((top[2 * GRP + i] << 3) | ((s2 >> 2) & 7)) & 0xFF)
                d_low = ((s0 & 2) << 1) | (s1 & 2) | ((s2 & 2) >> 1)
                output.append(((top[3 * GRP + i] << 3) | (d_low & 7)) & 0xFF)
                e_low = ((s0 & 1) << 2) | ((s1 & 1) << 1) | (s2 & 1)
                output.append(((top[4 * GRP + i] << 3) | (e_low & 7)) & 0xFF)

            final_top = top[5 * GRP] if 5 * GRP < 256 else 0
            final_thr = thr[3 * GRP] if 3 * GRP < 154 else 0
            output.append(((final_top << 3) | (final_thr & 7)) & 0xFF)

            result = bytes(output[:256])
            label = f"fwd_iter {'rev_sec' if rev else 'fwd_sec'}"
            first16 = ' '.join(f'{b:02X}' for b in result[:16])

            best_match = 0
            best_off = 0
            for game_off in range(0, len(cracked), 256):
                game_page = cracked[game_off:game_off + 256]
                matches = sum(1 for a, b in zip(result, game_page) if a == b)
                if matches > best_match:
                    best_match = matches
                    best_off = game_off
            exact = "EXACT" if best_match == 256 else f"{best_match}/256"
            ff_count = sum(1 for b in result if b == 0xFF)
            print(f"  S{sec_num:2d} {label}: {first16}  FFs={ff_count} match={exact} @${best_off:04X}")


if __name__ == '__main__':
    main()

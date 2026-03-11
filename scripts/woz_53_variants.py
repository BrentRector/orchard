#!/usr/bin/env python3
"""Try multiple 5-and-3 decode variants to find the correct one.
Key question: does the XOR chain reset between secondary and primary?
Also try different buffer orderings."""
import struct

ENCODE_53 = [
    0xAB, 0xAD, 0xAE, 0xAF, 0xB5, 0xB6, 0xB7, 0xBA,
    0xBB, 0xBD, 0xBE, 0xBF, 0xD6, 0xD7, 0xDA, 0xDB,
    0xDD, 0xDE, 0xDF, 0xEA, 0xEB, 0xED, 0xEE, 0xEF,
    0xF5, 0xF6, 0xF7, 0xFA, 0xFB, 0xFD, 0xFE, 0xFF,
]
DECODE_53 = {v: i for i, v in enumerate(ENCODE_53)}
GRP = 51


def read_nibbles(woz_path, track_num):
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


def find_53_sectors(nibbles):
    nib2 = nibbles + nibbles[:2000]
    sectors = {}
    for i in range(len(nibbles)):
        if nib2[i] != 0xD5 or nib2[i + 2] != 0xB5:
            continue
        idx = i + 3
        if idx + 8 >= len(nib2):
            continue
        sec = decode_44(nib2[idx + 4], nib2[idx + 5])
        if sec in sectors:
            continue
        for j in range(idx + 8, idx + 80):
            if j + 2 >= len(nib2):
                break
            if nib2[j] == 0xD5 and nib2[j + 1] == 0xAA and nib2[j + 2] == 0xAD:
                didx = j + 3
                valid = sum(1 for k in range(411) if didx + k < len(nib2)
                            and nib2[didx + k] in DECODE_53)
                if valid >= 410:
                    sectors[sec] = didx
                break
    return sectors, nib2


def get_translated(nib2, idx):
    """Get 411 translated 5-bit values."""
    translated = []
    for i in range(411):
        nib = nib2[idx + i]
        if nib not in DECODE_53:
            return None
        translated.append(DECODE_53[nib])
    return translated


def reconstruct(thr, top):
    """Reconstruct 256 bytes from thr[154] and top[256] arrays."""
    output = bytearray()
    for i in range(GRP - 1, -1, -1):
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
    return bytes(output[:256])


def main():
    woz_path = "E:/Apple/Apple Panic - Disk 1, Side A.woz"
    cracked = open("E:/Apple/ApplePanic_runtime.bin", 'rb').read()

    nibbles = read_nibbles(woz_path, 0)
    sectors, nib2 = find_53_sectors(nibbles)

    test_sectors = [0, 2, 3, 12]

    for sec_num in test_sectors:
        if sec_num not in sectors:
            continue

        translated = get_translated(nib2, sectors[sec_num])
        if not translated:
            continue

        print(f"\n{'='*60}")
        print(f"SECTOR {sec_num}")
        print(f"{'='*60}")

        # Variant 1: Standard continuous XOR chain, reversed secondary
        decoded = [0] * 410
        prev = 0
        for i in range(410):
            decoded[i] = translated[i] ^ prev
            prev = decoded[i]
        ck1 = prev == translated[410]

        thr = [decoded[153 - j] for j in range(154)]
        top = [decoded[154 + j] for j in range(256)]
        result1 = reconstruct(thr, top)
        print(f"  V1 (continuous XOR, rev sec): ck={'OK' if ck1 else 'BAD'} "
              f"first8={' '.join(f'{b:02X}' for b in result1[:8])} "
              f"FFs={sum(1 for b in result1 if b == 0xFF)}")

        # Variant 2: Split XOR chains (reset at boundary)
        sec_decoded = [0] * 154
        prev = 0
        for i in range(154):
            sec_decoded[i] = translated[i] ^ prev
            prev = sec_decoded[i]

        pri_decoded = [0] * 256
        prev2 = 0
        for i in range(256):
            pri_decoded[i] = translated[154 + i] ^ prev2
            prev2 = pri_decoded[i]

        thr2 = [sec_decoded[153 - j] for j in range(154)]
        top2 = pri_decoded
        result2 = reconstruct(thr2, top2)
        print(f"  V2 (split XOR, rev sec):      "
              f"first8={' '.join(f'{b:02X}' for b in result2[:8])} "
              f"FFs={sum(1 for b in result2 if b == 0xFF)}")

        # Variant 3: Continuous XOR, forward secondary (no reversal)
        thr3 = [decoded[j] for j in range(154)]
        top3 = [decoded[154 + j] for j in range(256)]
        result3 = reconstruct(thr3, top3)
        print(f"  V3 (continuous XOR, fwd sec):  "
              f"first8={' '.join(f'{b:02X}' for b in result3[:8])} "
              f"FFs={sum(1 for b in result3 if b == 0xFF)}")

        # Variant 4: Split XOR, forward secondary
        thr4 = sec_decoded
        top4 = pri_decoded
        result4 = reconstruct(thr4, top4)
        print(f"  V4 (split XOR, fwd sec):      "
              f"first8={' '.join(f'{b:02X}' for b in result4[:8])} "
              f"FFs={sum(1 for b in result4 if b == 0xFF)}")

        # Variant 5: Primary first (decoded[0..255]=top, [256..409]=thr)
        thr5 = [decoded[256 + 153 - j] for j in range(min(154, 410 - 256))]
        thr5 += [0] * (154 - len(thr5))
        top5 = [decoded[j] for j in range(256)]
        result5 = reconstruct(thr5, top5)
        print(f"  V5 (pri first, rev sec):      "
              f"first8={' '.join(f'{b:02X}' for b in result5[:8])} "
              f"FFs={sum(1 for b in result5 if b == 0xFF)}")

        # Variant 6: Primary first, forward secondary
        thr6 = [decoded[256 + j] for j in range(min(154, 410 - 256))]
        thr6 += [0] * (154 - len(thr6))
        top6 = [decoded[j] for j in range(256)]
        result6 = reconstruct(thr6, top6)
        print(f"  V6 (pri first, fwd sec):      "
              f"first8={' '.join(f'{b:02X}' for b in result6[:8])} "
              f"FFs={sum(1 for b in result6 if b == 0xFF)}")

        # Variant 7: No byte reconstruction - just use raw translated values
        # as if the ROM stores them directly without reconstruction
        raw_bytes = bytes([(translated[i] << 3) | (translated[i] & 7) for i in range(256)])
        print(f"  V7 (raw translated, no recon): "
              f"first8={' '.join(f'{b:02X}' for b in raw_bytes[:8])} "
              f"FFs={sum(1 for b in raw_bytes if b == 0xFF)}")

        # Variant 8: Skip XOR entirely - use raw translated values
        raw_noxor = bytes([translated[i] for i in range(256)])
        print(f"  V8 (raw translated, no XOR):   "
              f"first8={' '.join(f'{b:02X}' for b in raw_noxor[:8])} ")

        # Check each variant against cracked
        for vname, result in [("V1", result1), ("V2", result2), ("V3", result3),
                               ("V4", result4), ("V5", result5), ("V6", result6)]:
            best = 0
            best_off = 0
            for off in range(0, len(cracked), 256):
                m = sum(1 for a, b in zip(result, cracked[off:off + 256]) if a == b)
                if m > best:
                    best = m
                    best_off = off
            exact = "EXACT" if best == 256 else f"{best}/256"
            if best > 30 or exact == "EXACT":
                print(f"    {vname} match: {exact} @${best_off:04X}")


if __name__ == '__main__':
    main()

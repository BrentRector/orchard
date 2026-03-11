#!/usr/bin/env python3
"""
Search for known Apple Panic game code patterns in the decoded WOZ data.
Compare against the cracked version to find where game code lives.
"""
import hashlib

def main():
    # Load both versions
    with open("E:/Apple/ApplePanic_runtime.bin", 'rb') as f:
        cracked = bytearray(f.read())

    with open("E:/Apple/ApplePanic_original_raw.bin", 'rb') as f:
        woz_raw = bytearray(f.read())

    print(f"Cracked runtime: {len(cracked)} bytes")
    print(f"WOZ raw decode: {len(woz_raw)} bytes")

    # Extract known game code sequences from cracked version
    # These should be unique enough to find in the WOZ data
    search_patterns = {
        "GAME_START ($7000)": cracked[0x7000:0x7010],
        "HGR_CALC ($706B)": cracked[0x706B:0x707B],
        "GAME_INIT ($7465)": cracked[0x7465:0x7475],
        "DRAW_PLAYER ($7C66)": cracked[0x7C66:0x7C76],
        "ENEMY_AI ($87C6)": cracked[0x87C6:0x87D6],
        "LEVEL_TRANS ($9300)": cracked[0x9300:0x9310],
        "Player sprites ($6000)": cracked[0x6000:0x6010],
        "Font data ($7003)": cracked[0x7003:0x7013],
        "Score data ($70BB)": cracked[0x70BB:0x70CB],
        "Platform tiles ($6F00)": cracked[0x6F00:0x6F10],
        "Tile shift ($0800)": cracked[0x0800:0x0810],
        "Enemy spr ($1000)": cracked[0x1000:0x1010],
    }

    # Search for each pattern in the WOZ data
    print(f"\n=== Direct byte pattern search ===")
    for name, pattern in search_patterns.items():
        hex_str = ' '.join(f'{b:02X}' for b in pattern[:8])
        found = False
        for i in range(len(woz_raw) - len(pattern)):
            if woz_raw[i:i+len(pattern)] == pattern:
                print(f"  FOUND: {name} at WOZ offset ${i:04X} ({hex_str}...)")
                found = True
                break
        if not found:
            # Try XOR with common keys
            for xor_key in range(1, 256):
                xored = bytes(b ^ xor_key for b in pattern)
                for i in range(len(woz_raw) - len(xored)):
                    if woz_raw[i:i+len(xored)] == xored:
                        print(f"  FOUND (XOR ${xor_key:02X}): {name} at WOZ offset ${i:04X}")
                        found = True
                        break
                if found:
                    break
            if not found:
                print(f"  NOT FOUND: {name} ({hex_str}...)")

    # Try searching for shorter unique sequences (5 bytes)
    print(f"\n=== Short pattern search (5-byte) ===")
    for name, pattern in search_patterns.items():
        short = pattern[:5]
        hex_str = ' '.join(f'{b:02X}' for b in short)
        matches = []
        for i in range(len(woz_raw) - 5):
            if woz_raw[i:i+5] == short:
                matches.append(i)
        if matches:
            print(f"  {name}: {len(matches)} matches at {[f'${m:04X}' for m in matches[:5]]}")

    # Try EOR decryption - the boot code might EOR the loaded data
    # Check if XORing woz data with track number or sector number helps
    print(f"\n=== Sector-level comparison ===")
    # Try matching individual 256-byte sectors
    for game_start in range(0x6000, 0xA800, 0x100):
        cracked_sector = cracked[game_start:game_start+256]
        if all(b == 0 for b in cracked_sector):
            continue  # skip all-zero sectors

        for woz_off in range(0, len(woz_raw) - 256, 256):
            woz_sector = woz_raw[woz_off:woz_off+256]
            if woz_sector == cracked_sector:
                print(f"  EXACT MATCH: cracked ${game_start:04X} == WOZ offset ${woz_off:04X}")
            # Also try XOR
            for xk in (0x24, 0x01, 0x8E, 0xAA, 0xAB):
                xored = bytes(b ^ xk for b in woz_sector)
                if xored == cracked_sector:
                    print(f"  XOR ${xk:02X} MATCH: cracked ${game_start:04X} == WOZ offset ${woz_off:04X}")

    # Try finding the game start by looking for the JMP opcode ($4C)
    # followed by any target, in decoded data
    print(f"\n=== JMP instruction analysis ===")
    jmp_targets = {}
    for i in range(len(woz_raw) - 3):
        if woz_raw[i] == 0x4C:
            target = woz_raw[i+1] | (woz_raw[i+2] << 8)
            if 0x6000 <= target <= 0xA800:
                jmp_targets[target] = jmp_targets.get(target, 0) + 1
    # Show most common JMP targets in game code range
    for target, count in sorted(jmp_targets.items(), key=lambda x: -x[1])[:15]:
        print(f"  JMP ${target:04X}: {count} times")

    # Also check JSR targets
    print(f"\n=== JSR instruction analysis ===")
    jsr_targets = {}
    for i in range(len(woz_raw) - 3):
        if woz_raw[i] == 0x20:
            target = woz_raw[i+1] | (woz_raw[i+2] << 8)
            if 0x6000 <= target <= 0xA800:
                jsr_targets[target] = jsr_targets.get(target, 0) + 1
    for target, count in sorted(jsr_targets.items(), key=lambda x: -x[1])[:15]:
        print(f"  JSR ${target:04X}: {count} times")

    # EOR with multi-byte key analysis
    # If the data is encrypted with a per-page or per-sector XOR,
    # we can try to detect it by XORing corresponding sectors
    print(f"\n=== Per-byte XOR key detection ===")
    # For each WOZ sector, XOR with each cracked game code sector
    # and see if the result is a repeating pattern (indicating XOR key)
    best_matches = []
    for game_start in range(0x7000, 0x7100, 0x100):  # Just try first few pages
        cracked_sector = cracked[game_start:game_start+256]
        for woz_off in range(0, min(len(woz_raw) - 256, 49000), 256):
            woz_sector = woz_raw[woz_off:woz_off+256]
            xor_result = bytes(a ^ b for a, b in zip(cracked_sector, woz_sector))
            # Check if XOR result is a repeating single byte
            if len(set(xor_result)) == 1:
                key = xor_result[0]
                best_matches.append((game_start, woz_off, key))
                print(f"  Single-byte XOR: cracked ${game_start:04X} ^ WOZ ${woz_off:04X} = ${key:02X}")
            # Check if XOR result is a repeating 2-byte pattern
            elif len(set(xor_result[::2])) == 1 and len(set(xor_result[1::2])) == 1:
                k1, k2 = xor_result[0], xor_result[1]
                print(f"  Two-byte XOR: cracked ${game_start:04X} ^ WOZ ${woz_off:04X} = ${k1:02X} ${k2:02X}")

    # Check if WOZ data might use a different 6-and-2 byte ordering
    # or if the nibble translation table is different
    print(f"\n=== Nibble translation check ===")
    # The most common decoded byte across all tracks is $24 (BIT zp instruction)
    # In the game code, what's the most common byte?
    from collections import Counter
    game_code = cracked[0x7000:0xA800]
    gc_counter = Counter(game_code)
    print(f"  Most common in cracked game code: {[(f'${b:02X}', n) for b, n in gc_counter.most_common(5)]}")
    wz_counter = Counter(woz_raw)
    print(f"  Most common in WOZ raw decode: {[(f'${b:02X}', n) for b, n in wz_counter.most_common(5)]}")

    # If $24 XOR some_key = most_common_game_byte, find the key
    most_common_game = gc_counter.most_common(1)[0][0]
    key = 0x24 ^ most_common_game
    print(f"  If $24 is encrypted ${most_common_game:02X}: XOR key = ${key:02X}")


if __name__ == '__main__':
    main()

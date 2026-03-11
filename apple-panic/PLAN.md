# Apple Panic - Clean Reconstruction Plan

## Goal

Remove all cracking group artifacts from the binary and reconstruct the original,
un-copy-protected game as faithfully as possible. Produce a clean, fully commented
6502 assembly source that assembles into a working DOS 3.3 BRUN-able binary.

## Binary Overview

- **File**: `ApplePanic` (26,640 bytes / $6810)
- **Platform**: Apple ][+ with 48K RAM, DOS 3.3
- **Original author**: Ben Serki (Broderbund Software, 1981)
- **Crack group**: "RIP_EM_OFF SOFTWARE" (extracted from copy-protected boot disk)
- **Cracker's tools**: EDASM (Apple II Editor/Assembler)
- **Load address**: $07FD (cracker-chosen, will change in clean version)

## Game Description (from instructions)

A platformer where the player digs holes in brick floors to trap apples, then
stomps them through. Features:
- **Controls**: I/J/K/M (up/left/right/down), D/U (dig), X/E (stomp)
- **Enemies**: Apples (basic), Green Butterfly (advanced), Mask of Death
- **Mechanics**: Multi-floor levels with ladders, hole digging, gravity
- **Graphics**: Hi-res mode (280x192), likely page-flipping

---

## Cracker Artifact Inventory

### Confirmed cracker-added (to be removed/replaced)

| Component | File Offset | Runtime Addr | Size | Evidence |
|-----------|-------------|-------------|------|----------|
| `JMP $1900` entry | $0000-$0002 | $07FD-$07FF | 3B | Overwritten by loop 1 anyway |
| Relocation routine | $1103-$113C | $1900-$1939 | 58B | Self-modifying packer code |
| EDASM runtime code | $0580-$079F | $0D7D-$0F9C | 544B | Dead code; zero game refs |
| EDASM strings | $07A0-$07FF | $0F9D-$0FFC | 96B | "BLOAD","BSAVE",error msgs |
| Credit text | $65D7 area | $05CD (after copy) | ~31B | "COURTESY OF RIP_EM_OFF SOFTWARE" |

### Confirmed original game data (to be preserved)

| Component | File Offset | Runtime Addr | Size | Evidence |
|-----------|-------------|-------------|------|----------|
| Identity table | $1002-$1101 | $17FF-$18FE | 256B | 4 refs from game code at $97ED, $A189, $A5AB, $A687 |
| All game code | $2000-$67FF | $6000-$A7FF | 18KB | Main game (relocated) |
| Game state init | $6003-$6802 | $0000-$07FF | 2KB | Zero page + buffers (copied by loop 1) |
| Resident data | $0003-$057F | $0800-$0D7C | ~1.4KB | Sprites, shapes, graphics |
| Resident data | $0800-$0FFF | $0FFD-$17FC | 2KB | Patterns, level/color data |
| Game variables | $113D-$17FF | $193A-$1FFC | ~1.7KB | Zeroed state area |
| Sprite frames | $1800-$1FFF | $1FFD-$27FC | 2KB | Animation data |

### Unknown / needs investigation

| Component | File Offset | Runtime Addr | Notes |
|-----------|-------------|-------------|-------|
| EDASM region | $0580-$07FF | $0D7D-$0FFC | What was originally here? Game doesn't reference it — possibly unused padding, or original data lost when cracker overwrote it |
| Text page init | $6503-$6802 | $0500-$07FF | Pages 5-7 are mostly $A0 (spaces) + $FF borders. Credit text is at $05CD. Original probably had blank text screen here (all $A0 + $FF structure bytes) |

---

## Runtime Memory Map (post-relocation, the "real" game layout)

| Memory Range | Contents | Source |
|--------------|----------|--------|
| $0000-$00FF | Zero page: game variables | Loop 1 from file $6003 |
| $0100-$01FF | 6502 stack | Loop 1 from file $6103 |
| $0200-$04FF | Game state buffers | Loop 1 from file $6203-$6502 |
| $0500-$07FF | Text page 1 data (blank screen) | Loop 1 from file $6503-$6802 |
| $0800-$0D7C | Resident: sprites, shape tables | Direct from file $0003-$057F |
| $0D7D-$0FFC | **EDASM dead code (cracker)** | Direct from file $0580-$07FF |
| $0FFD-$17FC | Resident: patterns, level data | Direct from file $0800-$0FFF |
| $17FD-$18FE | Identity lookup table (game data) | Direct from file $1000-$1101 |
| $18FF | Padding byte ($FF) | Direct from file $1102 |
| $1900-$1939 | **Relocation routine (cracker)** | Direct from file $1103-$113C |
| $193A-$1FFC | Game state variables (zeroed) | Direct from file $113D-$17FF |
| $1FFD-$27FC | Sprite animation frame data | Direct from file $1800-$1FFF |
| $2000-$3FFF | HGR Page 1 (display buffer) | Freed by relocation |
| $4000-$5FFF | HGR Page 2 (display buffer) | Freed by relocation |
| $6000-$A7FF | Main game code + data | Loop 2 from file $2000-$67FF |

---

## Reconstruction Approach

### Strategy: Build the runtime memory image directly

Instead of loading at the cracker's $07FD and running a relocation routine, we
produce a clean binary that loads segments directly to their runtime addresses.

### Output Format: BRUN with minimal clean loader

```
; Clean loader at $1900 (replaces cracker's relocation routine)
; Total: ~20 bytes instead of 58
;
        ORG  $1900
INIT:   LDA  $C050        ; Graphics mode
        LDA  $C052        ; Full screen
        LDA  $C057        ; Hi-res mode
        JMP  $7000        ; Start game
```

The binary will be structured as a single BRUN file that loads at $0000:

```
File layout:
  $0000-$07FF  : Zero page + stack + game buffers + text page 1  (2KB)
  $0800-$1FFF  : Resident data (sprites, tables, clean loader)    (6KB)
  $2000-$5FFF  : Padding zeros (HGR pages, overwritten at runtime)(16KB)
  $6000-$A7FF  : Main game code + data                            (18KB)
  Total: ~42KB
```

**Alternative** (smaller file): Use a two-stage approach:
```
BLOAD APDATA1,A$0000       ; Load $0000-$1FFF (8KB)
BLOAD APDATA2,A$6000       ; Load $6000-$A7FF (18KB)
CALL  6400                  ; Or: a tiny BRUN that sets HGR + JMP $7000
```

### Decision needed: single file vs. multi-file
- Single BRUN is simplest and most faithful to "BRUN APPLE PANIC" experience
- Multi-file avoids 16KB of wasted padding
- Recommendation: **Single BRUN at $0000** for simplicity, document the padding

---

## Phases

### Phase 1: Extract the Clean Runtime Image

1. **Simulate relocation**
   - Write a Python script that applies both copy loops to produce the exact
     runtime memory state ($0000-$A7FF)
   - This is the "ground truth" the game sees when it starts

2. **Identify and neutralize cracker artifacts**
   - EDASM code at $0D7D-$0FFC → replace with $00 (zeros)
   - EDASM strings at $0F9D-$0FFC → replace with $00
   - Credit text at $05CD → replace with $A0 (spaces) to match surrounding blank text page
   - Relocation routine at $1900-$1939 → replace with minimal clean loader (~20 bytes)
   - Remove the identity table data at $18FF if it's just padding (keep $17FF-$18FE)

3. **Verify the clean image**
   - Confirm all JSR/JMP targets in $6000-$A7FF still resolve to valid code
   - Confirm no game code references the removed EDASM region ($0D7D-$0FFC)
   - Confirm identity table at $17FF-$18FE is intact and referenced correctly
   - Run in an Apple II emulator to verify the game works

### Phase 2: Disassemble the Game Code

4. **Recursive descent disassembly starting from known entry points**
   - Primary: $7000 → $7465 (game main init)
   - Trace all JSR/JMP/branch targets
   - Map every reachable subroutine
   - Mark unreachable bytes as data

5. **Classify all data regions**
   - Font bitmaps at $7003-$7464
   - Sprite shape tables at $0800-$0D7C
   - Hi-res patterns and color data at $0FFD-$17FC
   - Level map layouts
   - Enemy/player state arrays
   - Sound frequency/duration tables

6. **Map hardware and ROM interfaces**
   - Keyboard: LDA $C000 (3x), LDA $C010 (2x)
   - Speaker: LDA $C030 (12x)
   - Graphics: $C050/$C052/$C054/$C055/$C057
   - ROM: JSR $FDED (COUT, 2x)
   - Input keys: I/J/K/M ($C9/$CA/$CB/$CD), D/U ($C4/$D5), X/E ($D8/$C5)

### Phase 3: Annotate and Structure the Source

7. **Name all symbols**
   - Subroutines: descriptive names (e.g., `draw_player`, `move_enemy`, `check_hole`)
   - Zero-page vars: `player_x`, `player_y`, `score_lo`, `score_hi`, `lives`, etc.
   - Data tables: `font_data`, `level_maps`, `sprite_frames`, `hgr_line_table`
   - Constants: `KEY_UP=$C9`, `KEY_LEFT=$CA`, `FLOOR_TILE`, `HOLE_TILE`, etc.

8. **Comment every instruction**
   - Inline comments for straightforward code
   - Block comments explaining algorithms (enemy AI, collision, HGR rendering)
   - Document any self-modifying code in the game itself
   - Note clever tricks and optimizations

9. **Organize source into logical sections**
   ```
   ; === HEADER / BUILD CONFIG ===
   ; === ZERO PAGE VARIABLES ===
   ; === GAME STATE BUFFERS ($0100-$07FF) ===
   ; === RESIDENT DATA: SPRITES & SHAPES ($0800-$0D7C) ===
   ; === RESIDENT DATA: PATTERNS & LEVELS ($0FFD-$17FC) ===
   ; === IDENTITY TABLE ($17FF-$18FE) ===
   ; === CLEAN LOADER ($1900) ===
   ; === GAME STATE VARIABLES ($193A-$1FFC) ===
   ; === SPRITE ANIMATION FRAMES ($1FFD-$27FC) ===
   ; === [PADDING: HGR PAGES $2000-$5FFF] ===
   ; === MAIN GAME CODE ($6000-$A7FF) ===
   ;     - Game init ($7465)
   ;     - Main loop
   ;     - Player movement & animation
   ;     - Enemy AI
   ;     - Level management
   ;     - Graphics engine (HGR rendering)
   ;     - Sound engine
   ;     - Scoring & display
   ;     - Input handling
   ;     - Font data ($7003-$7464)
   ```

### Phase 4: Assemble and Verify

10. **Build the clean binary**
    - Assemble with ca65 or dasm targeting Apple II
    - Output as a DOS 3.3 BRUN-able binary (load address $0000)

11. **Binary verification**
    - Compare game code regions ($6000-$A7FF) byte-for-byte with original
    - Compare game data regions ($0000-$07FF, $0800-$0D7C, $0FFD-$18FE) with original
    - Confirm cracker regions are zeroed/cleaned

12. **Emulator testing**
    - Test in AppleWin, Virtual ][, or MAME apple2 driver
    - Verify: title screen, gameplay, all controls, enemy behavior
    - Verify: sound effects, scoring, level progression, extra lives
    - Verify: Green Butterfly and Mask of Death on advanced levels

---

## Key Challenges

1. **Lost data at $0D7D-$0FFC**: The cracker overwrote 640 bytes with EDASM code.
   The original content is unknown. Since no game code references this region, it
   was likely unused padding or non-essential data (perhaps part of the original
   boot loader that isn't needed for DOS 3.3 operation). We'll zero it out.

2. **Credit text at $05CD**: The cracker patched 31 bytes of text into text page 1
   data. The surrounding bytes are all $A0 (spaces) and $FF (border/control bytes),
   so the original was almost certainly a blank text screen. Replace credit with $A0.

3. **Possible hidden patches**: The cracker may have made other small modifications
   (NOPing out copy protection checks, altering jump targets). These would be in the
   game code at $6000-$A7FF. Look for suspicious NOP sequences, unused branch-over
   patterns, or JMPs that skip small code blocks.

4. **Load address change**: Moving from $07FD to $0000 means the resident data
   region ($0800-$1FFF) is now at the same addresses in both the file and memory.
   The game code ($6000-$A7FF) also loads directly to its runtime address.
   No relocation needed — the clean loader just sets HGR mode and jumps.

5. **File size**: The clean single-file BRUN will be ~42KB due to the 16KB HGR page
   gap ($2000-$5FFF). This is larger than the cracker's 26KB packed file but is the
   simplest and most faithful approach. A multi-file approach would be 26KB total.

6. **Self-modifying code in the game**: The game itself (not just the cracker's
   loader) likely uses self-modification for performance in the HGR rendering
   engine. These must be documented carefully in the source.

## Estimated Output

- **Clean binary**: ~42KB single BRUN file (or 26KB as two BLOAD segments + tiny BRUN)
- **Source file**: ~4000-6000 lines of fully commented 6502 assembly
- **Game code**: ~8-10KB of executable code across ~200-300 routines
- **Data**: ~8KB (sprites, fonts, patterns, levels, identity table)
- **State**: ~2KB (zeroed game variables + initialized buffers)

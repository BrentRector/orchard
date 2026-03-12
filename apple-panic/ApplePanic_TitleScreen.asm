; ============================================================================
; Apple Panic — Title Screen Code ($1000-$1FFF)
; Loaded from tracks 1-5 to $0800-$48FF by game loader at $B700
;
; This file documents the $1000-$1FFF portion: executable code and display
; data for the title screen sequence shown during boot.
;
; Assembler: Merlin32 syntax
; Target: Apple ][+ with 48K RAM
;
; LIFECYCLE:
; 1. Game loader at $B700 reads tracks 1-5 to $0800-$48FF
; 2. JSR $1000 — patches RWTS ($D5 -> $DE), enables graphics mode
; 3. Returns to game loader, which patches $129D to RTS
; 4. JSR $1290 — runs title screen display sequence (animation + sound)
; 5. Game loader reads tracks 6-13 to $4000-$A7FF, OVERWRITING
;    this code entirely (game payload occupies $4000-$A7FF)
;
; This code is TRANSIENT — it exists only during the boot sequence.
; After the game payload loads, $1000-$1FFF is overwritten with enemy
; sprite data ($5000-$5FFF relocated to $1000-$1FFF).
;
; COPY PROTECTION LAYER 8 ($DE first byte):
; The patcher at $1000-$1027 implements the $DE address marker scheme.
; Tracks 1-5 are already loaded using D5 [per-track] B5 prologs (second
; byte varies, but first byte is still the standard $D5). This code
; changes the RWTS first-byte check from $D5 to $DE for tracks 6-13:
;   $B976: CMP #$D5 -> CMP #$DE (address field search first byte)
;   $BEF5: LDA #$D5 -> LDA #$DE (address field write first byte)
; Note: the RWTS patch happens BEFORE the title screen display (at $1200).
; A copier that only looks for $D5 address markers will find nothing
; on tracks 6-13.
;
; MEMORY MAP ($1000-$1FFF):
;   $1000-$1027  RWTS patcher + graphics mode init (self-erasing)
;   $1028-$10EF  Title screen bitmap data (apple shape + text)
;   $10F0-$10FF  High-ASCII text data
;   $1100-$11C0  HGR shape rendering engine (XOR sprite blitter)
;   $11C1-$11FF  Shape shift parameter table
;   $1200-$1261  Sound effect and delay routines
;   $1262-$12AA  Display sequence player (command interpreter)
;   $12AB-$1366  Title screen setup sequence (main display routine)
;   $1367-$17FF  Shape coordinate/timing data tables
;   $1800-$19FF  HGR row address lookup table (192 entries)
;   $1A00-$1DFF  Shape/sprite pointer tables
;   $1E00-$1FFF  Pixel shift tables (7 shift positions)
; ============================================================================


; ============================================================================
; RWTS PATCHER + GRAPHICS MODE INIT ($1000-$1027)
;
; Called via JSR $1000 from the game loader at $B745.
; Sets Apple II soft switches for hi-res graphics display, patches two
; RWTS locations to change the address prolog first byte from $D5 to $DE,
; zeros one byte at $1080 (partial self-erasure), then jumps to the
; title screen display code at $1200.
;
; Copy Protection Layer 8: The $DE marker patch means tracks 6-13 use
; non-standard address field prologs (DE xx B5 instead of D5 xx B5).
; The per-track second byte is handled separately by the $B7CB routine.
; ============================================================================
            ORG $1000

RWTS_PATCH:
            LDA $C057            ; 1000: AD 57 C0  hi-res mode ON
            LDA $C054            ; 1003: AD 54 C0  display page 1
            LDA $C052            ; 1006: AD 52 C0  full-screen (no text window)
            LDA $C050            ; 1009: AD 50 C0  graphics mode ON

; Set up Y offset for indexed stores.
; Y = $80, so STA $B8F6,Y -> STA $B976, STA $BE75,Y -> STA $BEF5.
; This is an obfuscation technique: the target addresses are hidden
; behind the index offset to make static analysis harder.

            LDA #$03             ; 100C: A9 03     \ save/restore values
            STA $10              ; 100E: 85 10     / for zero-page $10/$11
            LDA #$80             ; 1010: A9 80
            STA $11              ; 1012: 85 11
            TAY                  ; 1014: A8        Y = $80

; --- COPY PROTECTION LAYER 7: Patch RWTS address prolog search ---
; $B976 contains CMP #$D5 (the byte being compared when scanning for
; address field headers). Changing it to CMP #$DE means the RWTS will
; now look for $DE as the first prolog byte on all subsequent reads.
; $BEF5 contains LDA #$D5 in the address field write routine; patching
; it to LDA #$DE ensures writes also use the new marker.

            LDA #$DE             ; 1015: A9 DE     non-standard marker byte
            STA $B8F6,Y          ; 1017: 99 F6 B8  Y=$80: patches $B976
                                 ;                  CMP #$D5 -> CMP #$DE
            STA $BE75,Y          ; 101A: 99 75 BE  Y=$80: patches $BEF5
                                 ;                  LDA #$D5 -> LDA #$DE

; --- Partial self-erasure ---
; Zeros one byte at $1080 (STA $1000,Y with Y=$80). After INY, Y=$81
; and CPY #$1E tests $81 >= $1E, so BCC fails — only ONE byte is
; zeroed. This clears a byte in the bitmap data area, not the patcher
; code itself. The patcher code at $1000-$1027 survives, but becomes
; unreachable since we JMP past it to $1200.

            LDA #$00             ; 101D: A9 00
ERASE_LOOP:
            STA $1000,Y          ; 101F: 9D 00 10  zero $1000+Y
            INY                  ; 1022: C8
            CPY #$1E             ; 1023: C0 1E     Y=$81 >= $1E: loop exits
            BCC ERASE_LOOP       ; 1025: 90 F8

            JMP TITLE_MAIN       ; 1027: 4C 00 12  -> title screen display


; ============================================================================
; TITLE SCREEN BITMAP DATA ($102A-$10EF)
;
; Shape/sprite bitmap for the apple logo and title graphics drawn on
; the HGR screen. Data is organized as rows of pixel bytes for the
; HGR shape rendering engine at $1100.
;
; The apple bitmap at $1040-$10EF is 4 bytes wide x 28 rows, encoding
; the iconic apple shape displayed on the title screen. Each byte
; represents 7 pixels in Apple II HGR format (bit 7 = color palette).
; ============================================================================

; $102A-$103F: Additional title data (animation frame coordinates)
            HEX AA81D480D480      ; 102A
            HEX 2A552A01542A5500  ; 1030
            HEX AAD5AA81D4AAD580  ; 1038

; --- Apple shape bitmap (4 bytes wide x 28 rows) ---
; Pixel data in Apple II HGR format: bit 7 = palette select,
; bits 6-0 = 7 horizontal pixels (LSB = leftmost)
APPLE_SHAPE:
            HEX 00000000007F7F01  ; 1040: rows 0-1
            HEX 007F5F01007B5F01  ; 1048: rows 2-3
            HEX 007B5F01007B5F01  ; 1050: rows 4-5
            HEX 007B5F01407B5F03  ; 1058: rows 6-7
            HEX 407B5F03407B1F03  ; 1060: rows 8-9
            HEX 407B0F03407B0F03  ; 1068: rows 10-11
            HEX 007B4F0300735F03  ; 1070: rows 12-13
            HEX 00735F0300735F01  ; 1078: rows 14-15
            HEX 00711F0100735F01  ; 1080: rows 16-17
            HEX 00735D0100701900  ; 1088: rows 18-19
            HEX 0070190000701900  ; 1090: rows 20-21
            HEX 0070190000701900  ; 1098: rows 22-23
            HEX 0060190000601900  ; 10A0: rows 24-25
            HEX 0060190000601900  ; 10A8: rows 26-27
            HEX 00601D0000601D00  ; 10B0: rows 28-29
            HEX 00703D0000703D00  ; 10B8: rows 30-31
            HEX 00703D0000703D00  ; 10C0: rows 32-33
            HEX 00707D0000707D00  ; 10C8: rows 34-35
            HEX 00787D0000787D00  ; 10D0: rows 36-37
            HEX 00787D0000787D00  ; 10D8: rows 38-39
            HEX 0070380000787800  ; 10E0: rows 40-41
            HEX 007C7801007E7801  ; 10E8: rows 42-43

; --- High-ASCII text data ---
; Encoded text for title screen display. $A0 = space, $D3 = 'S',
; $C5 = 'E', etc. in Apple II high-ASCII (bit 7 set = normal video).
TITLE_TEXT:
            HEX A0D3A085D385ADA4  ; 10F0
            HEX D2CE8AA0A0A0A0AA  ; 10F8


; ============================================================================
; HGR SHAPE RENDERING ENGINE ($1100-$11C0)
;
; Three entry points:
;   SUB_1100 — HGR row address lookup (A = row -> $04/$05 = HGR addr)
;   SUB_1115 — Shape pointer lookup ($01/$02 = index -> $06/$07 = ptr)
;   SUB_112D — Full shape draw: look up shape, shift pixels, XOR blit
;
; The renderer supports pixel-level horizontal positioning via shift
; tables at $1E00. It uses XOR blitting, which means calling it twice
; at the same position erases the shape (used for animation).
;
; Zero-page usage:
;   $00     HGR row number (Y position)
;   $01/$02 Shape index (into table at $1A00)
;   $03     Shift/column parameter (into table at $1E00)
;   $04/$05 HGR base address for current row
;   $06/$07 Starting column offset / shape pointer
;   $08/$09 Shift table pointer
;   $0A/$0B Scratch (table pointer)
;   $0C     Row counter (working copy)
;   $0D     Column counter (working copy)
;   $0E     Row count (from shape header)
;   $0F     Column count (from shape header)
;   $10/$11 Saved Y/X registers
; ============================================================================

; --- SUB_1100: HGR Row Address Lookup ---
; Input:  A = HGR row number (0-191)
; Output: $04/$05 = HGR base address for that row
; Method: A*2 indexes into 192-entry table at $1800
;         Each entry is a 2-byte HGR screen address

SUB_1100:
            ASL                  ; 1100: 0A        A*2 (2 bytes per entry)
            STA $0A              ; 1101: 85 0A     low byte of table offset
            LDA #$18             ; 1103: A9 18     table at $1800
            ADC #$00             ; 1105: 69 00     add carry from ASL
            STA $0B              ; 1107: 85 0B     high byte of pointer

; Falls through to SUB_1109 to fetch the address

; --- SUB_1109: Indirect Fetch from ($0A/$0B) ---
; Reads 2-byte value at ($0A),0 and ($0A),1 into $04/$05

SUB_1109:
            LDY #$00             ; 1109: A0 00
            LDA ($0A),Y          ; 110B: B1 0A     low byte of HGR address
            STA $04              ; 110D: 85 04
            INY                  ; 110F: C8
            LDA ($0A),Y          ; 1110: B1 0A     high byte of HGR address
            STA $05              ; 1112: 85 05
            RTS                  ; 1114: 60


; --- SUB_1115: Shape/Sprite Pointer Lookup ---
; Input:  $01/$02 = shape index
; Output: $06/$07 = pointer to shape data
; Method: ($01/$02)*2 indexes into table at $1A00+
;         Uses $02 to select table page ($1A, $1B, etc.)

SUB_1115:
            LDA $01              ; 1115: A5 01     shape index low
            ASL                  ; 1117: 0A        *2 (2 bytes per entry)
            STA $0A              ; 1118: 85 0A
            LDA $02              ; 111A: A5 02     shape index high
            ROL                  ; 111C: 2A        carry from ASL
            ADC #$1A             ; 111D: 69 1A     base at $1A00
            STA $0B              ; 111F: 85 0B
            LDY #$00             ; 1121: A0 00
            LDA ($0A),Y          ; 1123: B1 0A     shape pointer low
            STA $06              ; 1125: 85 06
            INY                  ; 1127: C8
            LDA ($0A),Y          ; 1128: B1 0A     shape pointer high
            STA $07              ; 112A: 85 07
            RTS                  ; 112C: 60


; --- SUB_112D: Full Shape Draw (XOR Blit with Pixel Shifting) ---
; Input:  $00 = HGR row, $01/$02 = shape index, $03 = shift/column param
; Output: Shape XOR-blitted to HGR screen
;
; Process:
; 1. Save registers (Y->$10, X->$11, A+flags pushed)
; 2. Look up shape pointer via SUB_1115
; 3. Look up shift table via $03 index into table at $1E00
; 4. Copy shape data to $1000 work area (may overlap bitmap data!)
; 5. Apply pixel shifts if needed (preserving HGR color bit 7)
; 6. XOR-blit shifted shape to HGR screen row by row

SUB_112D:
            STY $10              ; 112D: 84 10     save Y
            STX $11              ; 112F: 86 11     save X
            PHA                  ; 1131: 48        save A
            PHP                  ; 1132: 08        save flags

            JSR SUB_1115         ; 1133: 20 15 11  get shape pointer -> $06/$07

; Look up shift table for this shift position
            LDA $03              ; 1136: A5 03     shift parameter
            ASL                  ; 1138: 0A        *2 (2-byte table entries)
            TAY                  ; 1139: A8
            LDA $1E00,Y          ; 113A: AD 00 1E  shift table ptr low
            STA $08              ; 113D: 85 08
            LDA $1E01,Y          ; 113F: AD 01 1E  shift table ptr high
            STA $09              ; 1142: 85 09

; Read shape header: row count, column count
            LDY #$00             ; 1144: A0 00
            LDA ($08),Y          ; 1146: B1 08     row count
            STA $0E              ; 1148: 85 0E     save total rows
            STA $0C              ; 114A: 85 0C     working row counter
            INY                  ; 114C: C8
            LDA ($08),Y          ; 114D: B1 08     column count (bytes wide)
            STA $0F              ; 114F: 85 0F

; Copy shape data from shift table to $1000 work buffer
; This is the pre-shifted pixel data for the shape
COPY_ROWS:
            LDX $0F              ; 1151: A6 0F     columns per row
COPY_COLS:
            INY                  ; 1153: C8
            LDA ($08),Y          ; 1154: B1 08     shifted shape byte
            STA $0FFE,Y          ; 1156: 99 FE 0F  store at $1000 area
                                 ;                  ($0FFE + 2 = $1000 for Y=2)
            DEX                  ; 1159: CA
            BNE COPY_COLS        ; 115A: D0 F7
            DEC $0C              ; 115C: C6 0C     next row
            BNE COPY_ROWS        ; 115E: D0 F1

; Apply additional pixel shifts if $07 (from shape pointer high) is nonzero
; Each shift rotates all shape bytes right by 1 pixel, preserving the
; HGR color bit (bit 7). This allows sub-byte horizontal positioning.
            LDY $07              ; 1160: A4 07     shift count
            BEQ BLIT_SETUP       ; 1162: F0 2B     zero = no shift needed

SHIFT_PASS:
            CLC                  ; 1164: 18
            LDX #$00             ; 1165: A2 00
            LDA $0E              ; 1167: A5 0E     total rows
            STA $0C              ; 1169: 85 0C     reset row counter

SHIFT_ROW:
            LDA $0F              ; 116B: A5 0F     columns per row
            STA $0D              ; 116D: 85 0D     column counter

SHIFT_COL:
            LDA $1000,X          ; 116F: BD 00 10  read shape byte
            AND #$80             ; 1172: 29 80     isolate HGR color bit
            STA $0A              ; 1174: 85 0A     save it
            LDA $1000,X          ; 1176: BD 00 10  read again
            ROL                  ; 1179: 2A        rotate through carry
            ROL                  ; 117A: 2A        (brings carry into bit 0)
            PHP                  ; 117B: 08        save carry for next byte
            LSR                  ; 117C: 4A        shift right (bit 7 = 0)
            ORA $0A              ; 117D: 05 0A     restore HGR color bit
            STA $1000,X          ; 117F: 9D 00 10  store shifted byte
            PLP                  ; 1182: 28        restore carry
            INX                  ; 1183: E8
            DEC $0D              ; 1184: C6 0D     next column
            BNE SHIFT_COL        ; 1186: D0 E7
            DEC $0C              ; 1188: C6 0C     next row
            BNE SHIFT_ROW        ; 118A: D0 DF
            DEY                  ; 118C: 88        next shift pass
            BNE SHIFT_PASS       ; 118D: D0 D5

; --- XOR blit to HGR screen ---
; Reads shape data from $1000 work buffer, XOR's with screen bytes,
; stores result. XOR means: draw once = show, draw again = erase.

BLIT_SETUP:
            LDA #$00             ; 118F: A9 00
            STA BLIT_SRC+1       ; 1191: 8D 9E 11  self-modify: source offset
                                 ;                  (patches low byte of LDA addr)
            LDA $00              ; 1194: A5 00     HGR row number
            JSR SUB_1100         ; 1196: 20 00 11  look up HGR address

BLIT_ROW:
            LDX $0F              ; 1199: A6 0F     columns per row
            LDY $06              ; 119B: A4 06     starting column on screen

BLIT_COL:
BLIT_SRC:
            LDA $1040            ; 119D: AD 40 10  self-modifying address!
                                 ;                  low byte patched at $1191
            EOR ($04),Y          ; 11A0: 51 04     XOR with screen byte
            STA ($04),Y          ; 11A2: 91 04     write back to screen
            INY                  ; 11A4: C8        next screen column
            INC BLIT_SRC+1       ; 11A5: EE 9E 11  advance source offset
            DEX                  ; 11A8: CA
            BNE BLIT_COL         ; 11A9: D0 F2     next column

; Advance to next HGR row (rows are not contiguous in memory!)
            INC $0A              ; 11AB: E6 0A     next entry in row table
            INC $0A              ; 11AD: E6 0A     (2 bytes per entry)
            BNE BLIT_NEXT        ; 11AF: D0 02
            INC $0B              ; 11B1: E6 0B     handle page crossing

BLIT_NEXT:
            JSR SUB_1109         ; 11B3: 20 09 11  fetch next HGR row address
            DEC $0E              ; 11B6: C6 0E     decrement row count
            BNE BLIT_ROW         ; 11B8: D0 DF     next row

; Restore registers and return
            PLP                  ; 11BA: 28
            PLA                  ; 11BB: 68
            LDX $11              ; 11BC: A6 11     restore X
            LDY $10              ; 11BE: A4 10     restore Y
            RTS                  ; 11C0: 60


; ============================================================================
; SHAPE SHIFT PARAMETER TABLE ($11C1-$11FF)
;
; Lookup data used by the shape rendering engine. Each 16-byte block
; contains shift/offset parameters for different rendering modes.
; The $10 bytes at offset 5 and 13 in each block appear to be stride
; or page-boundary markers.
; ============================================================================

SHIFT_PARAMS:
            HEX 00000000000010000000000000001000  ; 11C1
            HEX 00000000000010000000000000001000  ; 11D1
            HEX 00000000000010000000000000001000  ; 11E1
            HEX 0000000000001000000000000000104C  ; 11F1


; ============================================================================
; SOUND EFFECT AND DELAY ROUTINES ($1200-$1261)
;
; Three sound routines and a general-purpose delay. All sound is
; produced by toggling the Apple II speaker soft switch at $C030.
; ============================================================================
            ORG $1200

; --- TITLE_MAIN: Entry from RWTS patcher JMP $1200 ---
; This is the main title screen routine. It begins with a jump table
; entry and then flows into the display sequence.

TITLE_MAIN:
            HEX 4C               ; 1200: JMP opcode (part of JMP $12AB)
            HEX AB12             ; 1201: target address $12AB

; --- SOUND_1: Descending tone ---
; Plays a descending pitch by decrementing the inner loop delay.
; X = number of cycles, $14 = starting pitch

SOUND_1:
            LDX #$06             ; 1203: A2 06     6 pitch steps
            LDA #$60             ; 1205: A9 60     starting frequency
            STA $14              ; 1207: 85 14     pitch delay counter

SOUND_1_OUTER:
            LDY $14              ; 1209: A4 14     current pitch
SOUND_1_TOGGLE:
            LDA $C030            ; 120B: AD 30 C0  toggle speaker
            DEY                  ; 120E: 88        count down pitch delay
            BNE SOUND_1_TOGGLE   ; 120F: D0 FA     inner loop
            DEC $14              ; 1211: C6 14     decrease pitch (faster)
            BNE SOUND_1_OUTER    ; 1213: D0 F4     next cycle

; Generate inverted waveform (complement pitch)
            LDA #$40             ; 1215: A9 40
            STA $14              ; 1217: 85 14
            EOR #$FF             ; 1219: 49 FF     complement
            STA $15              ; 121B: 85 15

SOUND_1_INV:
            LDY $15              ; 121D: A4 15     inverted pitch
SOUND_1_INV_TOGGLE:
            LDA $C030            ; 121F: AD 30 C0  toggle speaker
            INY                  ; 1222: C8        count up
            BNE SOUND_1_INV_TOGGLE ; 1223: D0 FA
            DEC $15              ; 1225: C6 15
            DEC $14              ; 1227: C6 14
            BNE SOUND_1_INV      ; 1229: D0 F2
            DEX                  ; 122B: CA        next pitch step
            BNE SOUND_1          ; 122C: D0 D7     (branch to $1205)
            RTS                  ; 122E: 60

; --- SOUND_2: Rising tone ---
; Similar structure but with complemented initial pitch.

SOUND_2:
            LDA $14              ; 122F: A5 14
            EOR #$FF             ; 1231: 49 FF     complement pitch
            STA $12              ; 1233: 85 12
            LDA $15              ; 1235: A5 15

SOUND_2_OUTER:
            LDY $14              ; 1237: A4 14
SOUND_2_TOGGLE:
            LDA $C030            ; 1239: AD 30 C0  toggle speaker
            INY                  ; 123C: C8
            BNE SOUND_2_TOGGLE   ; 123D: D0 FA
            DEX                  ; 123F: CA
            BNE SOUND_2_OUTER    ; 1240: D0 F5     (branch to $1237)
            DEC $12              ; 1242: C6 12
            BNE SOUND_2_OUTER    ; 1244: D0 EF     (branch to $1235? adjust)
            RTS                  ; 1246: 60

; --- SOUND_3: Quick chirp ---
; Short sound effect used during title animation.

SOUND_3:
            LDA #$C0             ; 1247: A9 C0     high frequency
            STA $14              ; 1249: 85 14
            LDA #$01             ; 124B: A9 01
            STA $15              ; 124D: 85 15
            JSR SOUND_2          ; 124F: 20 2F 12  play rising tone
            INC $14              ; 1252: E6 14     bump pitch
            BNE SOUND_3+8        ; 1254: D0 F9     (branch to $124F)
            RTS                  ; 1256: 60


; --- SUB_1257: General Delay ---
; Waits for $14 * 256 cycles (outer * inner loop).
; Used between animation frames for timing control.

SUB_1257:
            LDY $14              ; 1257: A4 14     outer loop count
DELAY_OUTER:
            LDX #$00             ; 1259: A2 00     inner = 256 iterations
DELAY_INNER:
            DEX                  ; 125B: CA
            BNE DELAY_INNER      ; 125C: D0 FD     ~1280 cycles per outer
            DEY                  ; 125E: 88
            BNE DELAY_OUTER      ; 125F: D0 F8
            RTS                  ; 1261: 60


; ============================================================================
; DISPLAY SEQUENCE PLAYER ($1262-$12AA)
;
; Interprets a command list to animate shapes across the HGR screen.
; Each command is 3 bytes: (row, shape_index, shift_param).
; A zero byte terminates the sequence.
;
; For each command:
; 1. Draw shape at position (XOR on)
; 2. Delay $14 frames
; 3. Erase shape (XOR off)
; 4. Advance column by 5
; 5. Draw at new position (XOR on) — creates sliding animation
; 6. Delay $14 frames
; 7. Erase shape (XOR off)
; 8. Loop to next command
;
; The sequence pointer is in $12/$13 (set by caller before JSR).
; ============================================================================

DISPLAY_SEQ:
            LDY #$00             ; 1262: A0 00
            STY $02              ; 1264: 84 02     shape index high = 0

SEQ_LOOP:
            LDA ($12),Y          ; 1266: B1 12     read HGR row
            BEQ SEQ_DONE         ; 1268: F0 40     zero = end of sequence
            STA $00              ; 126A: 85 00     store row

            INC $12              ; 126C: E6 12     advance pointer
            BNE :NO_CARRY1       ; 126E: D0 02
            INC $13              ; 1270: E6 13
:NO_CARRY1:
            LDA ($12),Y          ; 1272: B1 12     read shape index
            STA $01              ; 1274: 85 01

            INC $12              ; 1276: E6 12     advance pointer
            BNE :NO_CARRY2       ; 1278: D0 02
            INC $13              ; 127A: E6 13
:NO_CARRY2:
            LDA ($12),Y          ; 127C: B1 12     read shift/column param
            STA $03              ; 127E: 85 03

            INC $12              ; 1280: E6 12     advance pointer
            BNE :NO_CARRY3       ; 1282: D0 02
            INC $13              ; 1284: E6 13
:NO_CARRY3:

; --- Animate: draw, pause, erase, shift right, draw, pause, erase ---

            JSR SUB_112D         ; 1286: 20 2D 11  draw shape (XOR on)
            LDA #$14             ; 1289: A9 14     animation delay
            STA $14              ; 128B: 85 14
            JSR SUB_1257         ; 128D: 20 57 12  wait

; --- TITLE_ENTRY: Secondary entry point ($1290) ---
; The game loader at $B759 calls JSR $1290 to run the title
; display after the first call to $1000 has returned. Before calling,
; the loader patches $129D from LDA #$14 to RTS ($60), which changes
; the animation behavior: shapes are drawn and left visible instead
; of being erased and redrawn (static display mode).

TITLE_ENTRY:
            JSR SUB_112D         ; 1290: 20 2D 11  erase shape (XOR off)

            LDA $03              ; 1293: A5 03     current column param
            CLC                  ; 1295: 18
            ADC #$05             ; 1296: 69 05     shift right by 5 pixels
            STA $03              ; 1298: 85 03

            JSR SUB_112D         ; 129A: 20 2D 11  draw at new position

SEQ_DELAY:
            LDA #$14             ; 129D: A9 14     delay value
                                 ;        ^^^^
                                 ; PATCHED BY GAME LOADER:
                                 ; $B759 writes $60 (RTS) here to convert
                                 ; this into a subroutine return, making
                                 ; the display static (no erase+redraw cycle)
            STA $14              ; 129F: 85 14
            JSR SUB_1257         ; 12A1: 20 57 12  wait
            JSR SUB_112D         ; 12A4: 20 2D 11  erase (XOR off)
            JMP SEQ_LOOP         ; 12A7: 4C 66 12  next command

SEQ_DONE:
            RTS                  ; 12AA: 60


; ============================================================================
; TITLE SCREEN SETUP SEQUENCE ($12AB-$1366)
;
; Main title screen display routine. Called from JMP $12AB (via $1200).
; Draws the complete title screen: apple logo, "APPLE PANIC" text,
; animated character sprites, and plays sound effects.
;
; This routine:
; 1. Draws the large apple shape at the top of the screen
; 2. Draws animated text/sprites using SUB_112D (the XOR blitter)
; 3. Plays descending and chirp sound effects
; 4. Draws additional shapes for the "APPLE PANIC" title
; 5. Runs the display sequence player for scrolling text
; 6. Draws final decorative elements (characters, platforms)
; ============================================================================

TITLE_SETUP:
; --- Draw apple logo ---
            LDA #$00             ; 12AB: A9 00
            STA $02              ; 12AD: 85 02     shape table page = 0
            LDA #$46             ; 12AF: A9 46     HGR row 70
            STA $00              ; 12B1: 85 00
            LDA #$14             ; 12B3: A9 14     shape index $14
            STA $01              ; 12B5: 85 01
            LDA #$00             ; 12B7: A9 00     no shift
            STA $03              ; 12B9: 85 03
            JSR SUB_112D         ; 12BB: 20 2D 11  draw apple

; --- Draw animated title characters ---
            LDX #$17             ; 12BE: A2 17     23 characters to draw

TITLE_CHAR_LOOP:
            LDA #$41             ; 12C0: A9 41     HGR row 65
            STA $00              ; 12C2: 85 00
            LDA #$4D             ; 12C4: A9 4D     shape index $4D
            STA $01              ; 12C6: 85 01
            LDA #$01             ; 12C8: A9 01     shift = 1
            STA $03              ; 12CA: 85 03
            JSR SUB_112D         ; 12CC: 20 2D 11  draw character

; Draw additional shape variants
            LDA #$55             ; 12CF: A9 55     HGR row 85
            STA $00              ; 12D1: 85 00
            LDA #$27             ; 12D3: A9 27     shape index $27
            STA $01              ; 12D5: 85 01
            JSR SUB_112D         ; 12D7: 20 2D 11  draw

            LDA #$3A             ; 12DA: A9 3A     shape index $3A
            STA $01              ; 12DC: 85 01
            JSR SUB_112D         ; 12DE: 20 2D 11  draw
            DEX                  ; 12E1: CA
            BNE TITLE_CHAR_LOOP  ; 12E2: D0 DC

; --- Sound effect ---
            LDA #$80             ; 12E4: A9 80     long delay
            STA $14              ; 12E6: 85 14
            JSR SUB_1257         ; 12E8: 20 57 12  pause

; --- Draw more title elements ---
            LDA #$56             ; 12EB: A9 56     HGR row 86
            STA $00              ; 12ED: 85 00
            LDA #$E6             ; 12EF: A9 E6     shape index $E6
            STA $01              ; 12F1: 85 01
            LDA #$07             ; 12F3: A9 07     shift = 7
            STA $03              ; 12F5: 85 03
            JSR SUB_112D         ; 12F7: 20 2D 11  draw
            JSR SOUND_3          ; 12FA: 20 47 12  chirp sound

            LDA #$46             ; 12FD: A9 46     HGR row 70
            STA $00              ; 12FF: 85 00
            LDA #$69             ; 1301: A9 69     shape index $69
            STA $01              ; 1303: 85 01
            LDA #$0C             ; 1305: A9 0C     shift = 12
            STA $03              ; 1307: 85 03
            JSR SUB_112D         ; 1309: 20 2D 11  draw

; --- Long pause with sound ---
            LDA #$FF             ; 130C: A9 FF     maximum delay
            STA $14              ; 130E: 85 14
            JSR SUB_1257         ; 1310: 20 57 12  long pause
            JSR SUB_112D         ; 1313: 20 2D 11  erase (XOR toggle)

; --- Run display sequence from data table ---
            LDA #$67             ; 1316: A9 67     sequence data low
            STA $12              ; 1318: 85 12
            LDA #$13             ; 131A: A9 13     sequence data high ($1367)
            STA $13              ; 131C: 85 13
            JSR DISPLAY_SEQ      ; 131E: 20 62 12  run command sequence

; --- Draw remaining elements ---
            LDA #$4C             ; 1321: A9 4C     HGR row 76
            STA $00              ; 1323: 85 00
            LDA #$E6             ; 1325: A9 E6     shape index $E6
            STA $01              ; 1327: 85 01
            LDA #$08             ; 1329: A9 08     shift = 8
            STA $03              ; 132B: 85 03
            JSR SUB_112D         ; 132D: 20 2D 11  draw
            JSR SOUND_1          ; 1330: 20 03 12  descending tone

; --- Bottom section: platform and character shapes ---
            LDA #$64             ; 1333: A9 64     HGR row 100
            STA $00              ; 1335: 85 00
            LDA #$00             ; 1337: A9 00     shape index $00
            STA $01              ; 1339: 85 01
            LDA #$02             ; 133B: A9 02     shift = 2
            STA $03              ; 133D: 85 03
            JSR SUB_112D         ; 133F: 20 2D 11  draw

            LDA #$1E             ; 1342: A9 1E     shape index $1E
            STA $01              ; 1344: 85 01
            INC $03              ; 1346: E6 03     shift = 3
            JSR SUB_112D         ; 1348: 20 2D 11  draw

            LDA #$3C             ; 134B: A9 3C     shape index $3C
            STA $01              ; 134D: 85 01
            INC $03              ; 134F: E6 03     shift = 4
            JSR SUB_112D         ; 1351: 20 2D 11  draw

            LDA #$5A             ; 1354: A9 5A     shape index $5A
            STA $01              ; 1356: 85 01
            INC $03              ; 1358: E6 03     shift = 5
            JSR SUB_112D         ; 135A: 20 2D 11  draw

            LDA #$6A             ; 135D: A9 6A     shape index $6A
            STA $01              ; 135F: 85 01
            INC $03              ; 1361: E6 03     shift = 6
            JSR SUB_112D         ; 1363: 20 2D 11  draw
            RTS                  ; 1366: 60


; ============================================================================
; SHAPE COORDINATE / TIMING DATA ($1367-$17FF)
;
; Command data for the display sequence player at $1262.
; Each 3-byte entry: (HGR_row, shape_index, shift_param)
; A $00 byte terminates the sequence.
;
; These tables define the positions and timing of all animated elements
; on the title screen — the sliding letters, bouncing characters, and
; decorative border shapes.
; ============================================================================

SEQ_DATA:
            HEX 466B0C466D0C466F0C47710C47730B48  ; 1367

; ... additional coordinate/timing data continues through $17FF ...
; (Full data tables for title screen animation sequences.
;  Each track 1-5 sector contributes to this region.)


; ============================================================================
; HGR ROW ADDRESS LOOKUP TABLE ($1800-$19FF)
;
; 192 entries x 2 bytes = 384 bytes.
; Maps HGR row number (0-191) to the corresponding screen memory address.
;
; Apple II HGR memory is notoriously non-linear:
;   Rows 0-7:   $2000, $2400, $2800, $2C00, $3000, $3400, $3800, $3C00
;   Rows 8-15:  $2080, $2480, $2880, $2C80, $3080, $3480, $3880, $3C80
;   ...and so on in groups of 8, with $80-byte offsets within each group
;   and $28-byte offsets between groups of 64 rows.
;
; SUB_1100 reads this table: row * 2 indexes into $1800 to get the
; 2-byte HGR base address for that row.
;
; (Data generated at boot time or loaded from disk — 384 bytes of
;  pre-computed addresses for fast row lookup.)
; ============================================================================
            ORG $1800

HGR_ROW_TABLE:
            DS 384               ; 1800-$197F: 192 row addresses
                                 ; (pre-computed, loaded from disk)


; ============================================================================
; SHAPE / SPRITE POINTER TABLES ($1A00-$1DFF)
;
; Lookup tables used by SUB_1115. Each entry is a 2-byte pointer to
; shape data stored elsewhere in the $0800-$48FF region.
;
; Table organization:
;   $1A00-$1BFF: Primary shape pointer table (up to 256 shapes)
;   $1C00-$1DFF: Extended shape data / additional pointer tables
;
; Shape data format (pointed to by these entries):
;   Byte 0: Row count (height in HGR rows)
;   Byte 1: Column count (width in bytes, 7 pixels each)
;   Bytes 2+: Pixel data (row_count * col_count bytes)
;
; Shapes include: apple logo, letter characters for "APPLE PANIC",
; player/enemy sprites for title screen animation, platform tiles,
; and decorative border elements.
; ============================================================================
            ORG $1A00

SHAPE_PTR_TABLE:
            DS 1024              ; 1A00-$1DFF: shape pointer tables
                                 ; (loaded from disk)


; ============================================================================
; PIXEL SHIFT TABLES ($1E00-$1FFF)
;
; Lookup tables used by SUB_112D for pixel-level horizontal positioning.
; The $03 zero-page variable selects which shift table to use via:
;   $1E00 + ($03 * 2) -> 2-byte pointer to shift data
;
; Each shift table contains pre-shifted versions of shape data for one
; of 7 possible pixel positions within a byte. Since Apple II HGR
; pixels are packed 7 per byte (bits 6-0, bit 7 = palette), shifting
; a shape by N pixels requires rotating all pixel bits while preserving
; the color bit. Pre-computing these shifts avoids expensive per-pixel
; rotation at draw time.
;
; Table structure:
;   $1E00-$1E0F: 7 pointers (14 bytes) to shift data blocks
;   $1E10-$1FFF: Pre-shifted shape data for each shift position
;
; This is the key to smooth horizontal animation on the Apple II —
; without hardware scrolling, the only way to move a shape by less
; than 7 pixels is to pre-shift all its pixel data.
; ============================================================================
            ORG $1E00

SHIFT_TABLE_PTRS:
            DS 512               ; 1E00-$1FFF: shift table pointers + data
                                 ; (loaded from disk)


; ============================================================================
; END OF TITLE SCREEN CODE
;
; After the title screen sequence completes, control returns to the
; game loader at $B700, which:
; 1. Reads tracks 6-13 to $4000-$A7FF (game payload)
; 2. JMPs to $4000 (game entry — relocation + GAME_START)
;
; The entire $1000-$1FFF region is then overwritten:
;   $1000-$15FF <- enemy sprite data (from $5000-$55FF via relocation)
;   $1600-$16FF <- sprite transparency masks (from $5600)
;   $1700-$17FF <- solid fill pattern (from $5700)
;   $1800-$1FFF <- game state variables (from $5800-$5FFF)
;
; Nothing from the title screen code survives into gameplay.
; ============================================================================

; ============================================================================
; Apple Panic — Track 0 Copy Protection Code
; Disassembled from WOZ disk image (Apple Panic - Disk 1, Side A.woz)
;
; BOOT PROCESS:
; 1. Standard Disk II boot ROM ($C600) finds D5 AA 96 T0 S0, decodes 6-and-2,
;    loads 256 bytes to $0800, JMPs to $0801.
; 2. The D5 AA 96 sector 0 is an ANTI-COPY TRAP: the BNE at $080A targets
;    $0800 (= BRK), so the code crashes after copying one byte.
; 3. The original disk ships with a CUSTOM controller ROM that reads D5 AA B5
;    (13-sector) address fields with 5-and-3 GCR encoding instead.
; 4. The custom ROM loads track 0 sectors to $0800+N*$100 and transfers control
;    to the boot code, which uses the RWTS at $0B00 to read further tracks.
;
; TRACK 0 SECTORS (D5 AA B5 / 5-and-3):
;   S0  $0800  Configuration data (has $FF padding — see note)
;   S1  $0900  Data (checksum BAD — possibly encrypted or corrupt)
;   S2  $0A00  5-and-3 byte reconstruction routine
;   S3  $0B00  Custom RWTS — reads D5 AA B5 addr + D5 AA AD data
;   S4  $0C00  Byte reconstruction continued / completion
;   S5  $0D00  Data table (GCR translate or sector skew)
;   S6  $0E00  Data table (mostly zeros)
;   S7  $0F00  Disk command handler entry
;   S8  $1000  Disk command handler (seek/compare)
;   S9  $1100  Address field writer (nibble output)
;   S10 $1200  Data table (GCR translate / sector data)
;   S11 -----  NOT PRESENT (physical sector is the 6-and-2 anti-copy trap)
;   S12 $1400  I/O handler (EXACT match with cracked version $1F00)
; ============================================================================


; ============================================================================
; ANTI-COPY TRAP: D5 AA 96 Sector 0 (6-and-2 decoded)
; This is what the STANDARD Disk II boot ROM loads to $0800.
; ============================================================================
            .ORG $0800

trap_sector_count:
            .byte $00            ; 0800: sector count = 0 (BRK opcode!)

; Entry point for standard boot ROM (JMP $0801):
trap_entry:
            LDY #$00             ; 0801: A0 00
            LDY $0800,X          ; 0803: BC 00 08  X=$60 -> reads $0860
            SHY $0000,X          ; 0806: 9C 00 00  copies to $0060
            INX                  ; 0809: E8        X=$61
            BNE trap_sector_count ; 080A: D0 F4    -> $0800 = BRK! TRAP!
            ; If X somehow reached 0 (impossible on first pass):
            JMP $000C            ; 080C: 4C 0C 00

; Remaining bytes $080F-$08FF contain data that would be copied to zero page
; IF the loop ran to completion (which it doesn't — BRK fires on iteration 1).
; Some of this data resembles disk I/O code (LDA $C08C,X patterns at $0868+)
; suggesting it may be a remnant of the real boot code, or a decoy.


; ============================================================================
; SECTOR 2 ($0A00) — 5-and-3 Byte Reconstruction
; Called after RWTS reads raw 5-bit values into:
;   $BB00-$BBFF = primary buffer (256 bytes, upper 5 bits)
;   $BC00-$BC99 = secondary buffer (154 bytes, lower 3 bits packed)
; Reconstructs full 8-bit bytes and stores through ($3E),Y pointer.
; Checksum: OK
; ============================================================================
            .ORG $0A00

reconstruct_53:
            LDX #$32             ; 0A00: A2 32  counter = 50 (51 groups - 1)
            LDY #$00             ; 0A02: A0 00  output index

.group_loop:
            ; --- Read 3 primary bytes, extract upper 5 bits ---
            LDA ($3E),Y          ; 0A04: B1 3E  byte from buffer
            STA $26              ; 0A06: 85 26  save full byte
            LSR                  ; 0A08: 4A     >> 3 to get upper 5 bits
            LSR                  ; 0A09: 4A
            LSR                  ; 0A0A: 4A
            STA $BB00,X          ; 0A0B: 9D 00 BB  primary[X + 0*51]

            INY                  ; 0A0E: C8
            LDA ($3E),Y          ; 0A0F: B1 3E
            STA $27              ; 0A11: 85 27
            LSR                  ; 0A13: 4A
            LSR                  ; 0A14: 4A
            LSR                  ; 0A15: 4A
            STA $BB33,X          ; 0A16: 9D 33 BB  primary[X + 1*51]

            INY                  ; 0A19: C8
            LDA ($3E),Y          ; 0A1A: B1 3E
            STA $2A              ; 0A1C: 85 2A
            LSR                  ; 0A1E: 4A
            LSR                  ; 0A1F: 4A
            ; ... continues extracting and packing bits
            ; Stores upper 5 bits to $BB00+X, $BB33+X, $BB66+X, $BB99+X, $BBCC+X
            ; Packs lower 3 bits into $BC00 area (secondary buffer)
            ; X decrements through groups, Y increments through output bytes


; ============================================================================
; SECTOR 3 ($0B00) — Custom RWTS (Read/Write Track/Sector)
;
; Two main entry points:
;   $0B00 (rwts_read_data)  — Read a D5 AA AD data field
;   $0B65 (rwts_find_addr)  — Find a D5 AA B5 address field
;
; Data storage:
;   $BA00 = GCR 5-and-3 decode/translate table (32 entries)
;   $BB00 = Primary buffer (256 bytes, 5-bit values after XOR decode)
;   $BC00 = Secondary buffer (154 bytes, 5-bit values after XOR decode)
;
; Uses X register as slot offset ($60 for slot 6) throughout.
; Returns: C=0 success, C=1 error
; Checksum: OK
; ============================================================================
            .ORG $0B00

; ----- DATA FIELD READER -----
; Pre: address field already validated, disk spinning
; Searches for D5 AA AD data prologue, then reads 410 data nibbles

rwts_read_data:
            BEQ rwts_error       ; 0B00: F0 61  quick exit if Z set

; --- Search for D5 (first prolog byte) ---
.find_d5:
            LDA $C08C,X          ; 0B02: BD 8C C0  read disk data latch
            BPL .find_d5          ; 0B05: 10 FB     wait for valid nibble (bit 7)
            EOR #$D5              ; 0B07: 49 D5     is it D5?
            BNE .prev_caller      ; 0B09: D0 F4     no -> branch back (to $0AFF)
            NOP                   ; 0B0B: EA        timing

; --- Check for AA (second prolog byte) ---
.find_aa:
            LDA $C08C,X          ; 0B0C: BD 8C C0
            BPL .find_aa          ; 0B0F: 10 FB
            CMP #$AA              ; 0B11: C9 AA
            BNE .find_d5+5        ; 0B13: D0 F2     not AA -> re-check as D5

; --- Check for AD (third prolog byte) ---
            LDY #$9A              ; 0B15: A0 9A     154 = secondary buf count
.find_ad:
            LDA $C08C,X          ; 0B17: BD 8C C0
            BPL .find_ad          ; 0B1A: 10 FB
            CMP #$AD              ; 0B1C: C9 AD
            BNE .find_d5+5        ; 0B1E: D0 E7     not AD -> restart

; --- Read secondary buffer (154 bytes into $BC00, reversed) ---
; Y starts at $9A (154), counts down to $00
; A accumulates XOR checksum
            LDA #$00              ; 0B20: A9 00     init checksum

.read_sec_loop:
            DEY                   ; 0B22: 88        Y = 153, 152, ..., 0
            STY $26               ; 0B23: 84 26     save counter

.wait_sec_nib:
            LDY $C08C,X          ; 0B25: BC 8C C0  read disk nibble into Y
            BPL .wait_sec_nib     ; 0B28: 10 FB     wait for valid

            EOR $BA00,Y           ; 0B2A: 59 00 BA  XOR with GCR table[nibble]
                                  ;                  This both translates AND XOR-chains
            LDY $26               ; 0B2D: A4 26     restore counter
            STA $BC00,Y           ; 0B2F: 99 00 BC  store decoded secondary value
            BNE .read_sec_loop    ; 0B32: D0 EE     loop until Y=0

; --- Read primary buffer (256 bytes into $BB00, forward) ---
            STY $26               ; 0B34: 84 26     Y=0

.wait_pri_nib:
            LDY $C08C,X          ; 0B36: BC 8C C0  read disk nibble
            BPL .wait_pri_nib     ; 0B39: 10 FB

            EOR $BA00,Y           ; 0B3B: 59 00 BA  GCR translate + XOR chain
            LDY $26               ; 0B3E: A4 26
            STA $BB00,Y           ; 0B40: 99 00 BB  store decoded primary value
            INY                   ; 0B43: C8
            BNE .wait_pri_nib-2   ; 0B44: D0 EE     loop 256 times

; --- Read and verify checksum ---
.wait_ck:
            LDY $C08C,X          ; 0B46: BC 8C C0
            BPL .wait_ck          ; 0B49: 10 FB
            CMP $BA00,Y           ; 0B4B: D9 00 BA  XOR result should match
            BNE rwts_error        ; 0B4E: D0 13     checksum fail!

; --- Verify data epilogue (DE AA) ---
.wait_de:
            LDA $C08C,X          ; 0B50: BD 8C C0
            BPL .wait_de          ; 0B53: 10 FB
            CMP #$DE              ; 0B55: C9 DE
            BNE rwts_error        ; 0B57: D0 0A     wrong epilog

            NOP                   ; 0B59: EA        timing
.wait_aa2:
            LDA $C08C,X          ; 0B5A: BD 8C C0
            BPL .wait_aa2         ; 0B5D: 10 FB
            CMP #$AA              ; 0B5F: C9 AA
            BEQ rwts_success      ; 0B61: F0 5C     success -> $0BBF

; --- Error exit ---
rwts_error:
            SEC                   ; 0B63: 38        C=1 = error
            RTS                   ; 0B64: 60


; ----- ADDRESS FIELD READER -----
; Searches for D5 AA B5 address prolog with timeout

rwts_find_addr:
            LDY #$F8              ; 0B65: A0 F8     timeout counter
            STY $26               ; 0B67: 84 26

.addr_scan:
            INY                   ; 0B69: C8
            BNE .addr_check_d5    ; 0B6A: D0 04
            INC $26               ; 0B6C: E6 26     increment timeout high
            BEQ rwts_error        ; 0B6E: F0 F3     timeout expired!

.addr_check_d5:
            LDA $C08C,X          ; 0B70: BD 8C C0  read nibble
            BPL .addr_check_d5    ; 0B73: 10 FB
            CMP #$D5              ; 0B75: C9 D5
            BNE .addr_scan        ; 0B77: D0 F0     not D5, keep scanning

            NOP                   ; 0B79: EA        timing
.addr_wait_aa:
            LDA $C08C,X          ; 0B7A: BD 8C C0
            BPL .addr_wait_aa     ; 0B7D: 10 FB
            CMP #$AA              ; 0B7F: C9 AA
            BNE .addr_check_d5-2  ; 0B81: D0 F2     not AA -> re-check as D5

; --- Check for B5 (13-sector address prolog D5 AA B5) ---
            LDY #$03              ; 0B83: A0 03     4 address pairs to read
.addr_wait_b5:
            LDA $C08C,X          ; 0B85: BD 8C C0
            BPL .addr_wait_b5     ; 0B88: 10 FB
            CMP #$B5              ; 0B8A: C9 B5
            BNE .addr_check_d5-2  ; 0B8C: D0 E7     not B5 -> restart

; --- Read 4-and-4 encoded address field ---
; Reads volume, track, sector, checksum (each as 2-nibble 4-and-4 pair)
            LDA #$00              ; 0B8E: A9 00
            STA $27               ; 0B90: 85 27     init address checksum

.addr_read_pair:
            LDA $C08C,X          ; 0B92: BD 8C C0  first nibble of pair
            BPL .addr_read_pair   ; 0B95: 10 FB
            ROL                   ; 0B97: 2A        shift left (4-and-4)
            STA $26               ; 0B98: 85 26     save

.addr_read_pair2:
            LDA $C08C,X          ; 0B9A: BD 8C C0  second nibble of pair
            ; ... continues with 4-and-4 decode
            ; Extracts volume, track, sector, validates checksum
            ; On success, falls through to read data field

; At $0BBF (rwts_success):
; rwts_success:
;           CLC                   ; C=0 = success
;           RTS


; ============================================================================
; SECTOR 4 ($0C00) — Byte Reconstruction Completion
; Continuation of the reconstruct_53 routine from sector 2.
; Combines secondary 3-bit values with primary 5-bit values.
; Checksum: OK
; ============================================================================
            .ORG $0C00

; ... continues from $0A00 routine
; Combines $BB00 (primary) and $BC00 (secondary) into output bytes
; Stores completed bytes through ($3E),Y pointer
; ...
            RTS                   ; 0C1D: 60  return when reconstruction complete


; ============================================================================
; SECTOR 5 ($0D00) — Data Table
; Small values (0-31). Likely GCR decode table or sector interleave map.
; 42% match with cracked $1A00. Checksum: OK
; ============================================================================
            .ORG $0D00

; 1B 18 06 14 05 05 04 0D 04 03 02 01 0A 01 00 03
; 0B 08 0C 0A 02 0E 0A 07 04 00 00 00 00 00 0E 00
; Values all < $20 (32) — consistent with 5-and-3 decode table entries


; ============================================================================
; SECTOR 6 ($0E00) — Data Table
; Mostly zeros with a few values. 38% match with cracked $0E00.
; Checksum: OK
; ============================================================================
            .ORG $0E00

; 0C 00 00 00 00 00 00 00 14 1D 01 00 00 00 00 00


; ============================================================================
; SECTOR 7 ($0F00) — Disk Command Handler
; Entry point for disk operations. Parameters passed via ($48),Y pointer.
; Checksum: OK
; ============================================================================
            .ORG $0F00

disk_cmd_entry:
            STY $48               ; 0F00: 84 48  param pointer low
            STA $49               ; 0F02: 85 49  param pointer high
            LDY #$02              ; 0F04: A0 02
            STY $06F8             ; 0F06: 8C F8 06  slot status
            LDY #$04              ; 0F09: A0 04
            STY $04F8             ; 0F0B: 8C F8 04  motor state
            LDY #$01              ; 0F0E: A0 01
            LDA ($48),Y           ; 0F10: B1 48  command type
            TAX                   ; 0F12: AA
            LDY #$0F              ; 0F13: A0 0F
            ; ... dispatches to read/write/seek based on command


; ============================================================================
; SECTOR 8 ($1000) — Seek / Track Compare
; Checksum: OK
; ============================================================================
            .ORG $1000

            LDY #$03              ; 1000: A0 03
            LDA ($48),Y           ; 1002: B1 48  target track from params
            STA $2F               ; 1004: 85 2F  save target track
            JMP $BEA0             ; 1006: 4C A0 BE  seek to track


; ============================================================================
; SECTOR 9 ($1100) — Address Field Writer
; Writes D5 AA B5 address field with volume/track/sector/checksum.
; Uses nibble write subroutines at $BFBD/$BFCD.
; Checksum: OK
; ============================================================================
            .ORG $1100

write_addr_field:
            JSR $BFCD             ; 1100: 20 CD BF  write nibble sub
            LDA $2F               ; 1103: A5 2F     volume/track
            JSR $BFBD             ; 1105: 20 BD BF  encode + write
            LDA $41               ; 1108: A5 41     track
            JSR $BFBD             ; 110A: 20 BD BF
            LDA $4B               ; 110D: A5 4B     sector
            JSR $BFBD             ; 110F: 20 BD BF
            LDA $2F               ; 1112: A5 2F
            EOR $41               ; 1114: 45 41     compute checksum
            EOR $4B               ; 1116: 45 4B
            PHA                   ; 1118: 48
            LSR                   ; 1119: 4A        4-and-4 encode high
            ORA $4A               ; 111A: 05 4A
            STA $C08D,X           ; 111C: 9D 8D C0  write to disk
            CMP $C08C,X           ; 111F: DD 8C C0  verify
            PLA                   ; 1122: 68
            ORA #$AA              ; 1123: 09 AA     4-and-4 encode low
            JSR $BFCC             ; 1125: 20 CC BF
            LDA #$DE              ; 1128: A9 DE     epilog byte 1
            JSR $BFCD             ; 112A: 20 CD BF


; ============================================================================
; SECTOR 10 ($1200) — Data Table / GCR Values
; Contains high-bit-set values ($9C, $9E, $9F, $AA, etc.)
; May be part of the GCR encode/decode tables at $BA00.
; Checksum: OK
; ============================================================================
            .ORG $1200

; D3 9C 81 9E BD 9E 75 AA 93 AA 60 AA 00 9D BB B5
; EA 9E 11 9F 22 9F 2E 9F 51 9F 62 9F 6E 9F 91 9F


; ============================================================================
; SECTOR 12 ($1400) — Character I/O Handler
; EXACT MATCH with cracked version at $1F00.
; Part of the game's monitor/command processor.
; Checksum: OK
; ============================================================================
            .ORG $1400

char_input:
            LDX #$02              ; 1400: A2 02
            STX $AA52             ; 1402: 8E 52 AA  input state
            CMP $AAB2             ; 1405: CD B2 AA  check char
            BNE .no_match         ; 1408: D0 19
            DEX                   ; 140A: CA
            STX $AA52             ; 140B: 8E 52 AA
            DEX                   ; 140E: CA
            STX $AA5D             ; 140F: 8E 5D AA  buffer index
            LDX $AA5D             ; 1412: AE 5D AA
            STA $0200,X           ; 1415: 9D 00 02  store in input buffer
            INX                   ; 1418: E8
            STX $AA5D             ; 1419: 8E 5D AA
            CMP #$8D              ; 141C: C9 8D     carriage return?
            BNE .continue         ; 141E: D0 75
            JMP $9FCD             ; 1420: 4C CD 9F  process input line

.no_match:
            CMP #$8D              ; 1423: C9 8D
            BNE .other_char       ; 1425: D0 7D
            LDX #$00              ; 1427: A2 00
            STX $AA52             ; 1429: 8E 52 AA
            JMP $9FA4             ; 142C: 4C A4 9F


; ============================================================================
; END OF TRACK 0 DISASSEMBLY
; ============================================================================

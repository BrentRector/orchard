; ============================================================================
; Apple II Disk II 16-Sector Boot ROM (P5 PROM, 341-0027)
; Slot-independent ROM mapped at $Cs00 (where s = slot number)
; For slot 6: $C600-$C6FF
;
; This is the ACTUAL P6 boot ROM disassembly from the real PROM binary.
; Reads Track 0 using D5 AA 96 address fields and 6-and-2 GCR encoding.
; Can load multiple sectors based on sector count byte at $0800.
; Final entry: JMP $0801 with X = slot*16.
;
; Source: 6502disassembly.com verified against PROM dump.
; ============================================================================

            .ORG $C600

; Zero-page variables
slot16      = $2B               ; slot * 16 (e.g. $60 for slot 6)
dest_lo     = $26               ; destination pointer low byte
dest_hi     = $27               ; destination pointer high byte
temp        = $3C               ; temporary / 4-and-4 decode scratch
trk_want    = $3D               ; track number to find (starts 0)
checksum    = $40               ; address field checksum accumulator
sec_want    = $41               ; sector number to find (starts 0)

; I/O base for slot 6: $C080 + slot*16 = $C0E0
; All soft-switch accesses use X = slot*16 as index

; ============================================================================
; 1. BUILD GCR DECODE TABLE at $0356-$03D5
;    Maps 6-and-2 encoded nibble values ($80-$FF range) to 6-bit values (0-63)
;    Table is indexed by (nibble - $80), stored at $0356 + X
;    (Accessed later via EOR $02D6,Y where Y = full nibble value,
;     so $02D6 + $96 = $036C, etc.)
; ============================================================================
BOOT0:
C600: A2 20     LDX #$20            ; X = $20 (signature byte, overwritten below)
C602: A0 00     LDY #$00            ; Y = 0 (decoded value counter)
C604: A2 03     LDX #$03            ; X = 3 (candidate nibble value, $03-$7F)

build_tbl:
C606: 86 3C     STX temp            ; save candidate
C608: 8A        TXA                 ; A = candidate
C609: 0A        ASL A               ; A <<= 1
C60A: 24 3C     BIT temp            ; test A AND candidate → set N, V, Z
C60C: F0 10     BEQ $C61E           ; if no bits in common → skip (invalid)
C60E: 05 3C     ORA temp            ; A = A | candidate
C610: 49 FF     EOR #$FF            ; A = ~A (complement)
C612: 29 7E     AND #$7E            ; mask out bits 0 and 7
C614: B0 08     BCS $C61E           ; if carry set → skip

check_zeros:
C616: 4A        LSR A               ; shift right, check for consecutive 0-bits
C617: D0 FB     BNE $C614           ; loop until A = 0 (all zero-pairs checked)
C619: 98        TYA                 ; A = decoded value
C61A: 9D 56 03  STA $0356,X         ; store decoded value at table[candidate]
C61D: C8        INY                 ; next decoded value

skip:
C61E: E8        INX                 ; next candidate
C61F: 10 E5     BPL build_tbl       ; loop while X < $80 (candidates $03-$7F)

; ============================================================================
; 2. DETERMINE SLOT NUMBER from return address on stack
;    JSR $FF58 is the Monitor IORTS (just RTS). The return address on the
;    stack reveals which $Cx page we're in → gives slot number.
; ============================================================================
C621: 20 58 FF  JSR $FF58           ; RTS trick: pushes our return addr
C624: BA        TSX                 ; get stack pointer
C625: BD 00 01  LDA $0100,X         ; high byte of return addr = $C6 for slot 6
C628: 0A        ASL A               ; shift slot nibble into high nibble
C629: 0A        ASL A
C62A: 0A        ASL A
C62B: 0A        ASL A               ; A = slot * 16
C62C: 85 2B     STA slot16          ; save (e.g. $60 for slot 6)
C62E: AA        TAX                 ; X = slot * 16

; ============================================================================
; 3. INITIALIZE DISK HARDWARE
;    Select drive, turn on motor, seek to track 0
; ============================================================================
C62F: BD 8E C0  LDA $C08E,X         ; Q7L: set read mode
C632: BD 8C C0  LDA $C08C,X         ; Q6L: set data latch mode
C635: BD 8A C0  LDA $C08A,X         ; drive 1 select
C638: BD 89 C0  LDA $C089,X         ; motor on

; Seek to track 0 by stepping outward 80 phases (40 half-tracks)
C63B: A0 50     LDY #$50            ; 80 phase steps
seek_loop:
C63D: BD 80 C0  LDA $C080,X         ; phase 0 off (base)
C640: 98        TYA
C641: 29 03     AND #$03            ; phase = Y & 3
C643: 0A        ASL A               ; *2 for soft-switch spacing
C644: 05 2B     ORA slot16          ; add slot offset
C646: AA        TAX                 ; X = slot*16 + phase*2
C647: BD 81 C0  LDA $C081,X         ; turn on this phase
C64A: A9 56     LDA #$56            ; delay constant
C64C: 20 A8 FC  JSR $FCA8           ; Monitor WAIT routine (delay)
C64F: 88        DEY                 ; next step
C650: 10 EB     BPL seek_loop       ; loop 80 times → track 0

; Initialize sector/track search parameters
C652: 85 26     STA dest_lo         ; dest_lo = 0 (from WAIT return)
C654: 85 3D     STA trk_want        ; track = 0
C656: 85 41     STA sec_want        ; sector = 0
C658: A9 08     LDA #$08
C65A: 85 27     STA dest_hi         ; dest_hi = $08 → destination = $0800

; ============================================================================
; 4. SEARCH FOR FIELD PROLOG: D5 AA [96 or AD]
;    This routine handles BOTH address (D5 AA 96) and data (D5 AA AD) fields
;    using a clever state machine with the carry flag.
;    Carry clear = looking for address field (first pass)
;    Carry set = looking for data field (second pass)
; ============================================================================
restart:
C65C: 18        CLC                 ; carry = 0 → looking for address field

search_prolog:
C65D: 08        PHP                 ; save carry state

read_d5:
C65E: BD 8C C0  LDA $C08C,X         ; read nibble (data latch)
C661: 10 FB     BPL read_d5          ; wait for valid (bit 7 set)
C663: 49 D5     EOR #$D5            ; check for $D5
C665: D0 F7     BNE read_d5          ; not $D5 → keep reading

read_aa:
C667: BD 8C C0  LDA $C08C,X         ; read next nibble
C66A: 10 FB     BPL read_aa
C66C: C9 AA     CMP #$AA            ; must be $AA
C66E: D0 F3     BNE $C663           ; not $AA → check if THIS byte is $D5

C670: EA        NOP                 ; timing pad

read_third:
C671: BD 8C C0  LDA $C08C,X         ; read third byte
C674: 10 FB     BPL read_third
C676: C9 96     CMP #$96            ; is it $96 (address field)?
C678: F0 09     BEQ read_addr       ; yes → read address field

; Not $96 — check if we're looking for data field
C67A: 28        PLP                 ; restore carry
C67B: 90 DF     BCC restart          ; carry was clear → still looking for addr, retry
; Carry was set → we were looking for data field
C67D: 49 AD     EOR #$AD            ; check if third byte was $AD
C67F: F0 25     BEQ read_data       ; yes → found D5 AA AD → read data
C681: D0 D9     BNE restart          ; no → restart search

; ============================================================================
; 5. READ ADDRESS FIELD (4-and-4 encoded)
;    Format after D5 AA 96: vol(2) trk(2) sec(2) cksum(2)
;    4-and-4 decode: value = (byte1 ROL) AND byte2
;    Loop reads 3 pairs: volume, track, sector
;    (checksum pair is skipped / handled implicitly)
; ============================================================================
read_addr:
C683: A0 03     LDY #$03            ; 3 pairs to read
C685: 85 40     STA checksum         ; save for checksum

read_44_pair:
C687: BD 8C C0  LDA $C08C,X         ; read first byte of pair
C68A: 10 FB     BPL $C687
C68C: 2A        ROL A               ; rotate left through carry
C68D: 85 3C     STA temp            ; save

C68F: BD 8C C0  LDA $C08C,X         ; read second byte of pair
C692: 10 FB     BPL $C68F
C694: 25 3C     AND temp            ; 4-and-4 decode: (b1 ROL) AND b2

C696: 88        DEY
C697: D0 EC     BNE read_44_pair    ; loop 3 times

; After loop: A = sector, $40 = track (from previous iteration)
C699: 28        PLP                 ; restore carry (was clear)
C69A: C5 3D     CMP trk_want        ; compare sector with desired track...
                                    ; (actually: last decoded = sector, CMP with $3D)
C69C: D0 BE     BNE restart          ; mismatch → retry

C69E: A5 40     LDA checksum         ; load saved value (= track from prev iter)
C6A0: C5 41     CMP sec_want         ; compare track with $41
C6A2: D0 B8     BNE restart          ; mismatch → retry

C6A4: B0 B7     BCS search_prolog    ; always taken (carry set from CMP)
                                    ; → now search for D5 AA AD with carry set

; ============================================================================
; 6. READ DATA FIELD (6-and-2 GCR with XOR chain)
;    Phase 1: Read 86 auxiliary nibbles → XOR decode → store REVERSED at $0300
;    Phase 2: Read 256 primary nibbles → XOR decode → store at ($26) = $0800
;    Phase 3: Read checksum nibble → verify XOR = 0
;
;    The EOR $02D6,Y instruction serves DOUBLE DUTY:
;      1. GCR translate (table at $02D6+nibble_value = $0356+nibble-$80)
;      2. XOR chain (A accumulates running XOR of translated values)
;    Initial A = 0 (from the EOR #$AD that matched at $C67D)
; ============================================================================
read_data:
; Phase 1: Read 86 aux nibbles into $0300-$0355 (stored in REVERSE order)
C6A6: A0 56     LDY #$56            ; counter = 86 (counts DOWN)
C6A8: 84 3C     STY temp            ; save counter

read_aux:
C6AA: BC 8C C0  LDY $C08C,X         ; Y = read nibble (wait for ready)
C6AD: 10 FB     BPL read_aux
C6AF: 59 D6 02  EOR $02D6,Y         ; A ^= GCR_table[nibble] (XOR chain + translate)
C6B2: A4 3C     LDY temp            ; Y = counter
C6B4: 88        DEY                 ; counter--
C6B5: 99 00 03  STA $0300,Y         ; store at $0300 + (counter-1)
                                    ; First nibble → $0355, last → $0300
C6B8: D0 EE     BNE read_aux        ; loop until counter = 0

; Phase 2: Read 256 primary nibbles into ($26) = $0800+ (XOR chain continues)
C6BA: 84 3C     STY temp            ; Y = 0 (from loop exit)

read_pri:
C6BC: BC 8C C0  LDY $C08C,X         ; Y = read nibble
C6BF: 10 FB     BPL read_pri
C6C1: 59 D6 02  EOR $02D6,Y         ; A ^= GCR_table[nibble] (continues XOR chain)
C6C4: A4 3C     LDY temp            ; Y = output index
C6C6: 91 26     STA ($26),Y         ; store at $0800 + Y
C6C8: C8        INY                 ; next output byte
C6C9: D0 EF     BNE read_pri        ; loop 256 times

; Phase 3: Checksum verification
C6CB: BC 8C C0  LDY $C08C,X         ; Y = checksum nibble
C6CE: 10 FB     BPL $C6CB
C6D0: 59 D6 02  EOR $02D6,Y         ; final XOR — should give 0
C6D3: D0 87     BNE restart          ; checksum failed → retry

; ============================================================================
; 7. POST-DECODE: Combine auxiliary and primary bytes
;    Primary bytes at ($26) already have upper 6 bits (in bits 5-0).
;    Aux bytes at $0300 have the lower 2 bits (in groups).
;
;    For each output byte (Y = 0..255):
;      X cycles through aux indices 85, 84, ..., 0 (then resets to 85)
;      Two LSR $0300,X / ROL A pairs DESTRUCTIVELY extract 2 bits from
;      aux[X] and shift them into the primary byte:
;        Result = (primary << 2) | (aux_bit0 << 1) | aux_bit1
;
;    After 86 output bytes, X resets and the NEXT pair of bits (2,3) is
;    extracted from each aux byte (since prior LSRs already shifted them).
;    Three groups of ~86 bytes use bits [1:0], [3:2], [5:4] of each aux byte.
; ============================================================================
post_decode:
C6D5: A0 00     LDY #$00            ; output byte index
C6D7: A2 56     LDX #$56            ; aux index (reset point = 86)

combine:
C6D9: CA        DEX                 ; X-- (85, 84, ..., 0)
C6DA: 30 FB     BMI $C6D7           ; if X went negative ($FF) → reset to 86

C6DC: B1 26     LDA ($26),Y         ; A = primary byte at $0800+Y
C6DE: 5E 00 03  LSR $0300,X         ; aux[X] >>= 1, bit 0 → carry
C6E1: 2A        ROL A               ; A = (A << 1) | carry
C6E2: 5E 00 03  LSR $0300,X         ; aux[X] >>= 1, next bit → carry
C6E5: 2A        ROL A               ; A = (A << 1) | carry
C6E6: 91 26     STA ($26),Y         ; store final decoded byte
C6E8: C8        INY                 ; next output byte
C6E9: D0 EE     BNE combine         ; loop 256 times

; ============================================================================
; 8. MULTI-SECTOR LOAD
;    After decoding one sector, check if more sectors need loading.
;    $3D = current sector count (incremented after each sector)
;    $0800 byte 0 = total sector count requested by boot sector
;    If more sectors needed, increment dest page and loop back.
; ============================================================================
C6EB: E6 27     INC dest_hi         ; destination += $100 (next page)
C6ED: E6 3D     INC trk_want        ; sector counter++ (note: trk_want reused!)
C6EF: A5 3D     LDA trk_want        ; A = sectors loaded so far
C6F1: CD 00 08  CMP $0800           ; compare with sector count at $0800 byte 0
C6F4: A6 2B     LDX slot16          ; restore X = slot * 16
C6F6: 90 DB     BCC $C6D3           ; if loaded < count → read more sectors
                                    ; (jumps back to checksum point, falls through
                                    ;  to search for next D5 AA xx prolog)

; ============================================================================
; 9. DONE — JUMP TO BOOT SECTOR CODE
; ============================================================================
C6F8: 4C 01 08  JMP $0801           ; enter boot code at $0801
                                    ; X = slot * 16 (e.g. $60)

; Spare bytes
C6FB: 00 00 00 00 00               ; padding to fill 256-byte ROM

; ============================================================================
; NOTES:
;
; The GCR decode table built at $0356+ is accessed via EOR $02D6,Y where
; Y = raw disk nibble ($96-$FF). This means $02D6 + $96 = $036C, so the
; table entries for valid nibbles span $036C-$03D5.
;
; The EOR instruction cleverly combines GCR translation with XOR chain
; decoding in a single operation — no separate XOR pass needed.
;
; Aux bytes are stored in REVERSE order during reading (first nibble →
; $0355, last nibble → $0300). The post-decode loop then accesses them
; counting DOWN (X = 85, 84, ..., 0). The net effect is that aux byte
; order corresponds to the original on-disk XOR chain order.
;
; The destructive LSR in post-decode means each aux byte provides 6 bits
; total: 2 bits per group × 3 groups of 86 output bytes.
;
; CRITICAL: The two LSR/ROL pairs extract bits in this order:
;   First LSR: bit 0 of aux → carry → ROL into result
;   Second LSR: (original) bit 1 of aux → carry → ROL into result
;   So result low 2 bits = (original_bit0 << 1) | original_bit1
;   This is the OPPOSITE bit order from naive (aux & 3).
; ============================================================================

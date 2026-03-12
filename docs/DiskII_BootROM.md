# Apple II Disk II 16-Sector Boot ROM (P5 PROM, 341-0027)

## Actual P6 Boot ROM disassembly

Source: Verified against real PROM binary dump from 6502disassembly.com.

---

## 1. BUILD GCR DECODE TABLE ($C600-$C61F)

```asm
C600: A2 20     LDX #$20            ; signature byte (overwritten)
C602: A0 00     LDY #$00            ; decoded value counter
C604: A2 03     LDX #$03            ; candidate nibble ($03-$7F)
C606: 86 3C     STX $3C
C608: 8A        TXA
C609: 0A        ASL A
C60A: 24 3C     BIT $3C
C60C: F0 10     BEQ $C61E           ; skip invalid
C60E: 05 3C     ORA $3C
C610: 49 FF     EOR #$FF
C612: 29 7E     AND #$7E
C614: B0 08     BCS $C61E
C616: 4A        LSR A
C617: D0 FB     BNE $C614
C619: 98        TYA
C61A: 9D 56 03  STA $0356,X         ; store decoded value
C61D: C8        INY
C61E: E8        INX
C61F: 10 E5     BPL $C606
```

- Builds a 64-entry GCR decode table at $0356+
- Validates each candidate nibble for the 6-and-2 encoding rules
- Table is later accessed via `EOR $02D6,Y` (Y = raw nibble value)

## 2. SLOT DETECTION ($C621-$C62E)

```asm
C621: 20 58 FF  JSR $FF58           ; Monitor IORTS (RTS trick)
C624: BA        TSX
C625: BD 00 01  LDA $0100,X         ; get return address high byte
C628-C62B:      ASL x4              ; extract slot number → slot*16
C62C: 85 2B     STA $2B             ; save slot*16
C62E: AA        TAX
```

- Uses return address on stack to determine which slot ROM is in
- All subsequent I/O uses X = slot*16 for soft-switch indexing

## 3. HARDWARE INIT + SEEK TO TRACK 0 ($C62F-$C65A)

```asm
C62F: BD 8E C0  LDA $C08E,X         ; Q7L: read mode
C632: BD 8C C0  LDA $C08C,X         ; Q6L: data latch
C635: BD 8A C0  LDA $C08A,X         ; drive 1
C638: BD 89 C0  LDA $C089,X         ; motor on
C63B: A0 50     LDY #$50            ; 80 phase steps
seek_loop:
C63D-C650:      (step and delay)    ; seek outward → track 0
C652: 85 26     STA $26             ; dest_lo = 0
C654: 85 3D     STA $3D             ; track/sector counter = 0
C656: 85 41     STA $41             ; sector_want = 0
C658: A9 08     LDA #$08
C65A: 85 27     STA $27             ; dest_hi = $08 → destination $0800
```

## 4. SEARCH FOR FIELD PROLOG: D5 AA [96|AD] ($C65C-$C681)

```asm
C65C: 18        CLC                 ; carry clear = looking for address
C65D: 08        PHP                 ; save state
C65E-C665:      (read nibble, EOR #$D5, loop until match)
C667-C66E:      (read nibble, CMP #$AA)
C671-C676:      (read nibble, CMP #$96)
C678: F0 09     BEQ read_addr       ; found D5 AA 96 → address field
C67A: 28        PLP
C67B: 90 DF     BCC restart         ; still looking for addr → retry
C67D: 49 AD     EOR #$AD            ; check for $AD (data field)
C67F: F0 25     BEQ read_data       ; found D5 AA AD → data field
C681: D0 D9     BNE restart
```

- **Clever dual-purpose search**: same code finds both D5 AA 96 (address) and D5 AA AD (data)
- Carry flag tracks which field type we're looking for

## 5. READ ADDRESS FIELD ($C683-$C6A4)

```asm
C683: A0 03     LDY #$03            ; 3 pairs (vol, trk, sec)
C685: 85 40     STA $40             ; save for checksum
C687-C694:      (ROL/AND 4-and-4 decode)
C696: 88        DEY
C697: D0 EC     BNE read_44_pair
C699: 28        PLP
C69A: C5 3D     CMP $3D             ; sector matches?
C69C: D0 BE     BNE restart
C69E: A5 40     LDA $40
C6A0: C5 41     CMP $41             ; track matches?
C6A2: D0 B8     BNE restart
C6A4: B0 B7     BCS search_prolog   ; found → now look for data field
```

## 6. READ DATA FIELD with XOR chain ($C6A6-$C6D3)

```asm
; Phase 1: Read 86 aux nibbles → store REVERSED at $0300-$0355
C6A6: A0 56     LDY #$56            ; counter = 86
C6A8: 84 3C     STY $3C
C6AA: BC 8C C0  LDY $C08C,X         ; read nibble
C6AD: 10 FB     BPL $C6AA
C6AF: 59 D6 02  EOR $02D6,Y         ; GCR translate + XOR chain
C6B2: A4 3C     LDY $3C
C6B4: 88        DEY
C6B5: 99 00 03  STA $0300,Y         ; store REVERSED (first → $0355)
C6B8: D0 EE     BNE read_aux

; Phase 2: Read 256 primary nibbles → store at $0800+
C6BA: 84 3C     STY $3C             ; Y = 0
C6BC: BC 8C C0  LDY $C08C,X
C6BF: 10 FB     BPL $C6BC
C6C1: 59 D6 02  EOR $02D6,Y         ; continues XOR chain
C6C4: A4 3C     LDY $3C
C6C6: 91 26     STA ($26),Y         ; store at $0800+Y
C6C8: C8        INY
C6C9: D0 EF     BNE read_pri

; Phase 3: Checksum
C6CB: BC 8C C0  LDY $C08C,X
C6CE: 10 FB     BPL $C6CB
C6D0: 59 D6 02  EOR $02D6,Y         ; final XOR must = 0
C6D3: D0 87     BNE restart         ; bad checksum → retry
```

**Key insight**: `EOR $02D6,Y` does GCR translation AND XOR chain in one instruction.
Initial A = 0 (from the `EOR #$AD` that matched). XOR chain is continuous across aux and primary.

## 7. POST-DECODE: Combine aux + primary ($C6D5-$C6E9)

```asm
C6D5: A0 00     LDY #$00            ; output index
C6D7: A2 56     LDX #$56            ; aux index reset
C6D9: CA        DEX                 ; X = 85, 84, ..., 0
C6DA: 30 FB     BMI $C6D7           ; reset when X goes negative
C6DC: B1 26     LDA ($26),Y         ; get primary byte
C6DE: 5E 00 03  LSR $0300,X         ; aux[X] >>= 1, bit 0 → carry
C6E1: 2A        ROL A               ; A <<= 1, carry → bit 0
C6E2: 5E 00 03  LSR $0300,X         ; aux[X] >>= 1, bit 1 → carry
C6E5: 2A        ROL A               ; A <<= 1, carry → bit 0
C6E6: 91 26     STA ($26),Y         ; store combined byte
C6E8: C8        INY
C6E9: D0 EE     BNE combine
```

**CRITICAL**: Result = `(primary << 2) | (aux_bit0 << 1) | aux_bit1`

The bit order is **reversed** compared to naive `(aux & 3)`:
- Naive: `(bit1 << 1) | bit0`
- ROM:   `(bit0 << 1) | bit1`

The destructive LSR means each group of 86 bytes extracts the next 2 bits from each aux byte.

## 8. MULTI-SECTOR LOAD ($C6EB-$C6F6)

```asm
C6EB: E6 27     INC $27             ; dest page++
C6ED: E6 3D     INC $3D             ; sector counter++
C6EF: A5 3D     LDA $3D
C6F1: CD 00 08  CMP $0800           ; compare with sector count
C6F4: A6 2B     LDX $2B             ; restore slot*16
C6F6: 90 DB     BCC $C6D3           ; more to load → loop
```

- Byte 0 of the boot sector ($0800) = total sectors to load
- Count of 1 = just sector 0; count of 0 = just sector 0 (1 >= 0)
- Increments destination page for each additional sector

## 9. ENTRY TO BOOT CODE

```asm
C6F8: 4C 01 08  JMP $0801           ; X = slot*16
```

---

## Key Facts

| Item | Value |
|------|-------|
| Entry | Power-on or `PR#6` → JMP $C600 |
| Searches for | D5 AA 96 (address) + D5 AA AD (data) |
| Reads | 342 GCR bytes → 6-and-2 decode → 256 bytes at $0800 |
| Multi-sector | Byte 0 of sector 0 = page count |
| Exit | `JMP $0801` with X = slot*16 |
| Aux storage | Reversed in buffer ($0300), accessed counting down |
| Bit order | `(bit0 << 1) \| bit1` via destructive LSR/ROL |
| XOR chain | Continuous across aux (86) and primary (256), initial A=0 |

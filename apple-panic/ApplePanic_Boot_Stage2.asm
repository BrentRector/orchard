; ============================================================================
; Apple Panic — Boot RWTS and Stage 2 Loader ($0200-$03FF)
; Disassembled from WOZ disk image (Apple Panic - Disk 1, Side A.woz)
;
; This file covers the boot sector code that lives at $0200-$02FF (relocated
; from $0800 by the P6-loaded boot sector) plus the stage 2 loader at
; $0300-$03FF (loaded from 5-and-3 sector 0 on track 0).
;
; BOOT FLOW:
; 1. P6 Boot ROM loads 6-and-2 sector 0 to $0800, JMPs $0801
; 2. Boot code at $0801 relocates itself from $0800 to $0200 (freeing $0800
;    for the GCR decode table), then JMPs to $020F
; 3. GCR table builder ($020F) constructs the 5-and-3 decode table at $0800
; 4. RWTS reads 5-and-3 sector 0 data into $0300-$03FF using standard
;    post-decode at $02D1
; 5. Self-modifying code at $0237 patches $031F/$0320 from ORA #$C0 to
;    LDA #$02 (redirecting the RWTS call vector)
; 6. JMP $0301 enters stage 2: corrupts GCR table, loads sectors 0-9 to
;    $B600-$BFFF using custom post-decode at $0346
; 7. JMP ($003E) = JMP $B700 transfers to secondary loader
;
; Track 0 is DUAL FORMAT: one 6-and-2 sector (read by the standard P6 Boot
; ROM) plus thirteen 5-and-3 sectors. The P6 ROM loads the 6-and-2 boot
; sector to $0800 and JMPs to $0801; the boot code here then reads 5-and-3.
; See ApplePanic_Boot_T0.asm for the track 0 sector map.
; See ApplePanic.asm for the game code loaded by tracks 6-13.
;
; SECTIONS:
;   $0200-$020E  Relocation stub (copies $0800-$08FF to $0200-$02FF)
;   $020F-$0240  GCR table builder + first sector read + self-mod + JMP $0301
;   $0241-$025C  Unused padding (zeros)
;   $025D-$025E  RWTS preamble (CLC / PHP)
;   $025F-$029F  RWTS address field finder (D5 AA B5) + 4-and-4 reader
;   $02A1-$02D0  RWTS data field reader (D5 AA AD) + checksum
;   $02D1-$02F9  Standard 5-and-3 post-decode (used for first sector only)
;   $02FA-$02FF  Post-decode error handler + padding
;   $0300        Sector count verification byte ($99)
;   $0301-$030C  GCR table corruption — COPY PROTECTION (ASL x3 loop)
;   $030D-$0326  Stage 2 setup (destination pointers, RWTS vector)
;   $0327-$0338  Sector loading loop (reads sectors 0-9 to $B600-$BFFF)
;   $033A-$0345  Loading complete: set JMP vector, JMP ($003E) = JMP $B700
;   $0346-$03A4  Custom post-decode permutation — COPY PROTECTION
;   $03A5-$03CB  Unused padding ($FF)
;   $03CC        Initial destination page byte ($B6)
;   $03CD-$03FE  Unused padding ($FF)
;   $03FF        Target sector count byte ($09)
;
; Zero page usage:
;   $26/$27  Read buffer pointer (high byte: $03 for first read, $09 after)
;   $2A      Post-decode group counter (standard) / bit accumulator (custom)
;   $2B      Slot offset ($60 for slot 6)
;   $3C      GCR table builder temp / post-decode bit accumulator
;   $3D      Expected sector number for RWTS address field match
;   $3E/$3F  Indirect jump vector ($025D during loading, $B700 at end)
;   $40/$41  Destination pointer for custom post-decode ($B600+)
; ============================================================================


; ============================================================================
; RELOCATION STUB ($0200-$020E)
; Copies the boot sector from $0800 (where P6 ROM loaded it) to $0200
; (freeing $0800 for the GCR decode table), then jumps to $020F.
; ============================================================================
            ORG $0200

sector_count:
            DB $01               ; 0200: 01  sector count (loaded by P6 ROM)

relocate:
            LDX #$00             ; 0201: A2 00
:copy_loop
            LDA $0800,X          ; 0203: BD 00 08  read from original location
            STA $0200,X          ; 0206: 9D 00 02  write to new location
            INX                  ; 0209: E8
            BNE :copy_loop       ; 020A: D0 F7     copy all 256 bytes
            JMP gcr_table_build  ; 020C: 4C 0F 02  enter relocated code


; ============================================================================
; GCR TABLE BUILDER ($020F-$0227)
; Builds the 5-and-3 GCR decode table at $0800.
; Scans nibble values $AB-$FF, keeping only valid 5-and-3 disk bytes:
; a valid byte has the property that (byte >> 1) | byte == $FF, meaning
; it has no two consecutive zero bits.  $D5 is excluded (reserved as
; the data prolog marker).  The 32 valid values are assigned sequential
; indices 0-31 in the table.  After building, X = number of entries (32),
; Y has wrapped to $00.
; ============================================================================

gcr_table_build:
            LDY #$AB             ; 020F: A0 AB  start scanning from $AB
            TYA                  ; 0211: 98     A = Y = current nibble value
:test_entry
            STA $3C              ; 0212: 85 3C  save nibble value
            LSR                  ; 0214: 4A     A = nibble >> 1
            ORA $3C              ; 0215: 05 3C  A = (nibble >> 1) | nibble
            CMP #$FF             ; 0217: C9 FF  valid if all bits set?
            BNE :skip_entry      ; 0219: D0 09  no -> skip this nibble
            CPY #$D5             ; 021B: C0 D5  is it $D5 (reserved)?
            BEQ :skip_entry      ; 021D: F0 05  yes -> skip
            TXA                  ; 021F: 8A     A = current table index
            STA $0800,Y          ; 0220: 99 00 08  GCR_TABLE[nibble] = index
            INX                  ; 0223: E8     next index
:skip_entry
            INY                  ; 0224: C8     next nibble value ($AB..$FF)
            BNE :test_entry-1    ; 0225: D0 EA  -> $0211 (TYA) and continue
                                 ;               loop until Y wraps past $FF


; ============================================================================
; FIRST SECTOR READ ($0228-$0240)
; After building the GCR table, reads the first 5-and-3 sector (sector 0)
; using the RWTS at $025D and standard post-decode at $02D1.
; Sector 0 data is decoded into $0300-$03FF (the stage 2 loader code).
; Then applies self-modifying code and jumps to stage 2.
; ============================================================================

            STY $3D              ; 0228: 84 3D  sector to find = 0 (Y wrapped)
            STY $26              ; 022A: 84 26  ($26) low byte = $00
            LDA #$03             ; 022C: A9 03
            STA $27              ; 022E: 85 27  ($26) = $0300 (read buffer)
            LDX $2B              ; 0230: A6 2B  slot offset ($60)
            JSR rwts_entry       ; 0231: 20 5D 02  find addr + read data field
            JSR postdecode_std   ; 0234: 20 D1 02  standard 5-and-3 post-decode

; --- Self-modifying code: patch $031F/$0320 ---
; Changes the instruction at $031F from ORA #$C0 (opcode $09) to
; LDA #$02 (opcode $A9), redirecting the RWTS call vector from a
; slot-dependent ROM address to $025D (the boot RWTS).
; COPY PROTECTION LAYER 6: the on-disk code is intentionally misleading.

            LDA #$A9             ; 0237: A9 A9  opcode for LDA #imm
            STA $031F            ; 0239: 8D 1F 03  patch opcode at $031F
            LDA #$02             ; 023C: A9 02  operand: $02
            STA $0320            ; 023E: 8D 20 03  patch operand at $0320

            JMP stage2_entry     ; 0241: 4C 01 03  enter stage 2 loader


; ============================================================================
; UNUSED PADDING ($0244-$025C)
; ============================================================================

            HEX 0000000000000000   ; 0244-024B
            HEX 0000000000000000   ; 024C-0253
            HEX 0000000000000000   ; 0254-025B
            HEX 00                 ; 025C


; ============================================================================
; BOOT RWTS — READ/WRITE TRACK/SECTOR ($025D-$02D0)
;
; Custom RWTS for reading 5-and-3 encoded sectors from track 0.
; Uses X register as slot offset ($60 for slot 6) throughout.
;
; Entry: $025D (rwts_entry) — CLC, PHP, then search for D5 AA B5 address
;        field, decode 4-and-4 address pairs, match sector number in $3D,
;        then read D5 AA AD data field.
;
; Address field format: D5 AA B5 [vol_hi vol_lo trk_hi trk_lo sec_hi sec_lo
;                                  chk_hi chk_lo]
;   Each field pair is 4-and-4 encoded: value = (hi << 1 | 1) & lo
;   NOTE: Address checksums are NOT verified (copy protection layer 2:
;   all checksums are deliberately invalid on the original disk).
;
; Data field format: D5 AA AD [154 secondary nibs] [256 primary nibs] [chk]
;   Nibbles are XOR-chained through the GCR decode table at $0800.
;   Secondary data is stored at $0800 (overwrites GCR table entries).
;   Primary data is stored through ($26) pointer.
;
; Returns via RTS at $02D0 on success.
; On sector mismatch or checksum failure, retries from $025D.
;
; KEY TRICK: CLC/PHP at entry saves C=0 on stack.  After matching an address
; field, BCS at $029F sends execution back to $025E (PHP with C=1).  The
; next D5 AA sequence then checks the third byte: if not B5, PLP restores
; C=1, so BCC at $027C is NOT taken, and the code checks for $AD (data
; prolog).  This dual-purpose search finds the address field on the first
; pass (C=0) and the data field on the second pass (C=1).
; ============================================================================

rwts_entry:
            CLC                  ; 025D: 18     clear carry (C=0 for addr mode)
            PHP                  ; 025E: 08     save P with C=0

; ----- ADDRESS / DATA FIELD SCANNER -----
; Scans for D5 AA xx prologue.  Behavior depends on saved carry:
;   C=0 (first pass): look for B5 (address prolog)
;   C=1 (second pass): look for AD (data prolog)

:find_d5
            LDA $C08C,X          ; 025F: BD 8C C0  read disk data latch
            BPL :find_d5         ; 0262: 10 FB     wait for valid nibble
:recheck_d5
            EOR #$D5             ; 0264: 49 D5     is it $D5?
            BNE :find_d5         ; 0266: D0 F7     no -> keep scanning

; Found $D5 — check for $AA
:check_aa
            LDA $C08C,X          ; 0268: BD 8C C0
            BPL :check_aa       ; 026B: 10 FB
            CMP #$AA             ; 026D: C9 AA
            BNE :recheck_d5      ; 026F: D0 F3     not AA -> re-check this byte
                                 ;                  as potential D5 (-> $0264)
; (Branch target $0264 = EOR #$D5 — tests current nibble against D5)

; Found D5 AA — check third prolog byte
            NOP                  ; 0271: EA        timing delay
:check_third
            LDA $C08C,X          ; 0272: BD 8C C0
            BPL :check_third     ; 0275: 10 FB
            CMP #$B5             ; 0277: C9 B5     B5 = address prolog?
            BEQ :read_addr       ; 0279: F0 09     yes -> read address field

; Third byte is not B5.  Check which search mode we're in:
            PLP                  ; 027B: 28        restore saved status
            BCC rwts_entry       ; 027C: 90 DF     C=0 -> still in addr search,
                                 ;                  restart from CLC/PHP

; C=1 -> we're looking for a data field (address already matched).
; Check if the third byte is AD (data prolog):
            EOR #$AD             ; 027E: 49 AD     test for $AD
            BEQ :read_data_sec   ; 0280: F0 1F     yes -> read data field ($02A1)
            BNE rwts_entry       ; 0282: D0 D9     no -> restart from CLC
                                 ;                  (target $025D = rwts_entry)


; ----- ADDRESS FIELD READER -----
; Reads 4 pairs of 4-and-4 encoded bytes: volume, track, sector, checksum.
; After the loop, the last decoded value (sector number) is in A.
; Does NOT verify the checksum (copy protection layer 2).

:read_addr
            LDY #$03             ; 0284: A0 03     4 pairs to read (Y=3,2,1,0)
            STY $2A              ; 0286: 84 2A     also sets group counter = 3
                                 ;                  (used by $02D1 post-decode)

:read_pair
            LDA $C08C,X          ; 0288: BD 8C C0  first byte of 4-and-4 pair
            BPL :read_pair       ; 028B: 10 FB
            ROL                  ; 028D: 2A        shift left (prepare odd bits)
            STA $3C              ; 028E: 85 3C     save first byte << 1

:read_pair2
            LDA $C08C,X          ; 0290: BD 8C C0  second byte of 4-and-4 pair
            BPL :read_pair2      ; 0293: 10 FB
            AND $3C              ; 0295: 25 3C     decode: (hi<<1|1) & lo = value
            DEY                  ; 0297: 88        count down pairs
            BNE :read_pair       ; 0298: D0 EE     more pairs -> loop

; Loop runs for Y=3,2,1 (3 pairs: volume, track, sector).
; Falls through at Y=0 with A = sector number from last pair.
; The 4th pair (checksum) is never read — another reason address
; checksums don't matter (copy protection layer 2).

            PLP                  ; 029A: 28        restore saved status
            CMP $3D              ; 029B: C5 3D     compare with expected sector
            BNE rwts_entry       ; 029D: D0 BE     wrong sector -> retry
                                 ;                  (target: $029F - $42 = $025D)

; Sector matched!  Now search for the data field.
; BCS branches BACKWARD to $025E (PHP), pushing P with C=1 on stack.
; Execution then falls into :find_d5 to scan for D5 AA.  When a D5 AA xx
; sequence is found where xx != B5, PLP restores C=1 and the code checks
; for $AD (the data field prolog) instead of restarting the addr search.
            BCS *-$41            ; 029F: B0 BD     always taken (C=1 from CMP)
                                 ;                  target $025E = PHP (save C=1)


; ----- DATA FIELD READER ($02A1-$02D0) -----
; Entry: arrived here after finding D5 AA AD during second-pass scan.
; Reads 154 secondary nibbles (reversed into $0800) and 256 primary nibbles
; (forward into ($26)) via XOR chain through the GCR table at $0800.
; Verifies checksum; retries on failure.

:read_data_sec
rwts_read_data:
            LDY #$9A             ; 02A1: A0 9A     154 = secondary nibble count
            STY $3C              ; 02A3: 84 3C     save counter

; --- Read secondary buffer (154 nibbles into $0800, reversed order) ---
; XOR chain: A ^= GCR_TABLE[nibble], stored at $0800+Y (Y counts down).
; This overwrites the GCR table at $0800[$00]-$0800[$99] with decoded
; secondary data, but the table entries above $99 remain intact for
; decoding the primary nibbles.

:wait_sec_nib
            LDY $C08C,X          ; 02A5: BC 8C C0  read disk nibble into Y
            BPL :wait_sec_nib    ; 02A8: 10 FB

            EOR $0800,Y          ; 02AA: 59 00 08  XOR with GCR table entry
            LDY $3C              ; 02AD: A4 3C     restore counter
            DEY                  ; 02AF: 88        Y = 153, 152, ..., 0
            STA $0800,Y          ; 02B0: 99 00 08  store decoded secondary value
            BNE *-$10            ; 02B3: D0 EE     loop until Y = 0
                                 ;                  (target $02A3: STY $3C)

; --- Read primary buffer (256 nibbles into ($26), forward order) ---
; Same XOR chain, but stores through the ($26) pointer.

            STY $3C              ; 02B5: 84 3C     Y=0 -> reset index

:wait_pri_nib
            LDY $C08C,X          ; 02B7: BC 8C C0  read disk nibble
            BPL :wait_pri_nib    ; 02BA: 10 FB

            EOR $0800,Y          ; 02BC: 59 00 08  XOR with GCR table entry
            LDY $3C              ; 02BF: A4 3C     restore index
            STA ($26),Y          ; 02C1: 91 26     store primary byte
            INY                  ; 02C3: C8
            BNE *-$0F            ; 02C4: D0 EF     loop 256 times
                                 ;                  (target $02B5: STY $3C)

; --- Read and verify data checksum ---
; One more nibble: A ^= GCR_TABLE[nibble] should give zero if correct.

:wait_chk_nib
            LDY $C08C,X          ; 02C6: BC 8C C0
            BPL :wait_chk_nib    ; 02C9: 10 FB

            EOR $0800,Y          ; 02CB: 59 00 08  final XOR = checksum
            BNE rwts_entry       ; 02CE: D0 8D     non-zero = FAIL -> retry
                                 ;                  (offset $8D = -115,
                                 ;                  target: $02D0 - $73 = $025D)

; --- Data read success ---
rwts_data_rts:
            RTS                  ; 02D0: 60        return to caller


; ============================================================================
; STANDARD 5-AND-3 POST-DECODE ($02D1-$02F9)
;
; Reconstructs 256 bytes from the secondary buffer ($0800, 154 5-bit values)
; and primary buffer (($26), 256 5-bit values).  Used ONLY for the first
; sector read (sector 0 -> $0300).  Subsequent reads use the custom routine
; at $0346 instead.
;
; Algorithm: processes 3 groups of 51 bytes each (153 total).
; For each byte in a group:
;   1. Load secondary[$0800+Y], shift right twice via LSR
;   2. Rotate the 2 extracted bits into $03CC+X and $0399+X
;   3. Remaining 3 bits saved to $3C
;   4. Load primary[($26)+Y], shift left 3 (ASL x3)
;   5. ORA with $3C to combine upper 5 + lower 3 bits
;   6. Store reconstructed byte at ($26)+Y
;
; After 3 groups (Y=$99), verifies Y matches $0300 (which holds $99).
; On mismatch, JMPs to $FF2D (Monitor warm-start / RESET handler).
;
; ZP $2A = group counter (initialized to 3 at $0286 by address reader)
; ============================================================================

postdecode_std:
            TAY                  ; 02D1: A8     Y = A = 0 (from checksum = 0)

:group_start
            LDX #$00             ; 02D2: A2 00  inner loop counter

:inner_loop
            LDA $0800,Y          ; 02D4: B9 00 08  secondary value
            LSR                  ; 02D7: 4A        bit 0 -> carry
            ROL $03CC,X          ; 02D8: 3E CC 03  carry -> $03CC+X bit 0
            LSR                  ; 02DB: 4A        bit 1 -> carry
            ROL $0399,X          ; 02DC: 3E 99 03  carry -> $0399+X bit 0
            STA $3C              ; 02DF: 85 3C     save remaining 3 bits

            LDA ($26),Y          ; 02E1: B1 26     primary value
            ASL                  ; 02E3: 0A        shift left x3
            ASL                  ; 02E4: 0A        (making room for 3 low bits
            ASL                  ; 02E5: 0A         from secondary)
            ORA $3C              ; 02E6: 05 3C     combine: (primary<<3) | sec_bits
            STA ($26),Y          ; 02E8: 91 26     store reconstructed byte

            INY                  ; 02EA: C8        next position
            INX                  ; 02EB: E8        next in group
            CPX #$33             ; 02EC: E0 33     51 per group?
            BNE :inner_loop      ; 02EE: D0 E4     no -> continue

            DEC $2A              ; 02F0: C6 2A     decrement group counter
            BNE :group_start     ; 02F2: D0 DE     more groups -> reset X

; All 3 groups processed.  Y = 3 * 51 = 153 = $99.
            CPY $0300            ; 02F4: CC 00 03  verify Y = [$0300] = $99
            BNE :postdecode_err  ; 02F7: D0 03     mismatch -> error!
            RTS                  ; 02F9: 60        success -> return

; --- Post-decode error / padding ---
            BRK                  ; 02FA: 00  (unused)
            BRK                  ; 02FB: 00  (unused)

:postdecode_err
            JMP $FF2D            ; 02FC: 4C 2D FF  Monitor RESET entry
            BRK                  ; 02FF: 00  (page boundary padding)


; ============================================================================
; STAGE 2 LOADER ($0300-$03FF)
;
; This page is loaded from 5-and-3 sector 0 on track 0, decoded by the
; standard $02D1 post-decode into $0300.  It contains:
;   - A verification byte ($99) checked by CPY $0300 at $02F4
;   - The GCR table corruption loop (copy protection)
;   - Setup code and sector loading loop
;   - The custom post-decode permutation (copy protection)
;   - Configuration bytes at $03CC (dest page) and $03FF (target sector)
;
; ENTRY: JMP $0301 from $0241 (after first sector read and self-mod patch)
;        State: A=$02, X=$33, Y=$99, SP=$FD, C=1
; ============================================================================
            ORG $0300

postdecode_check_val:
            DB $99               ; 0300: 99  verification byte for CPY $0300
                                 ;           (3 groups * 51 iterations = $99)


; ============================================================================
; GCR TABLE CORRUPTION ($0301-$030C) — COPY PROTECTION LAYER 3
;
; Applies ASL x3 (Arithmetic Shift Left, 3 times) to every byte in the GCR
; decode table from $0800+Y for Y=$99 through Y=$FF (103 entries).
; Y=$99 on entry from the post-decode verification.
;
; Effect: each 5-bit GCR table value (0-31) is shifted left 3, turning
; it into a multiple of 8: $00,$08,$10,$18,$20,$28,...,$F8.
; The low 3 bits of every entry become zero.
;
; WHY THIS WORKS: XOR distributes over bit shifts:
;   (A<<3) XOR (B<<3) = (A XOR B)<<3
; So the data field checksum (XOR of all decoded values) is also shifted
; left 3 — it remains zero if the original checksum was zero.
; Data integrity is preserved for checksumming, but the VALUES are wrong
; if decoded with a standard (uncorrupted) table.
;
; The custom post-decode at $0346 expects and compensates for this
; corruption.  A nibble copier that builds a fresh GCR table would
; decode garbage.
; ============================================================================

stage2_entry:
:corrupt_loop
            LDA $0800,Y          ; 0301: B9 00 08  load GCR table entry
            ASL                  ; 0304: 0A        shift left (x1)
            ASL                  ; 0305: 0A        shift left (x2)
            ASL                  ; 0306: 0A        shift left (x3)
            STA $0800,Y          ; 0307: 99 00 08  store corrupted value
            INY                  ; 030A: C8        next entry
            BNE :corrupt_loop    ; 030B: D0 F4     Y=$99..$FF, wraps to 0 -> done


; ============================================================================
; STAGE 2 SETUP ($030D-$0326)
;
; Initializes pointers for the sector loading loop:
;   ($26/$27) = $09xx — primary data buffer (RWTS reads primary nibbles here)
;   ($40/$41) = $B600 — destination for custom post-decode output
;   ($3E/$3F) = $025D — RWTS entry point (called via JMP ($003E) at $0343)
;
; The initial destination page ($B6) comes from $03CC.
; The target sector ($09) is stored at $03FF.
;
; NOTE: The instruction at $031F was patched by self-modifying code at
; $0237-$0240 (executed before JMP $0301).  On disk, $031F/$0320 contains
; $09 $C0 (ORA #$C0), which would compute ($06 | $C0) = $C6 for the
; high byte — pointing into ROM space ($C65D), clearly non-functional.
; After patching, it reads $A9 $02 (LDA #$02), correctly setting the
; RWTS vector high byte to $02 for address $025D.
; This is COPY PROTECTION LAYER 6: static analysis of the on-disk bytes
; shows different (non-functional) code than what actually executes.
; ============================================================================

            LDX $2B              ; 030D: A6 2B     restore slot offset ($60)

            LDA #$09             ; 030F: A9 09
            STA $27              ; 0311: 85 27     ($26) high byte = $09
                                 ;                  primary buffer at $0900+

            LDA stage2_dest_page ; 0313: AD CC 03  = $B6 (initial dest page)
            STA $41              ; 0316: 85 41     ($40) high byte = $B6
            STY $40              ; 0318: 84 40     ($40) low byte = $00
                                 ;                  Y=0 from corruption loop
                                 ;                  so ($40/$41) = $B600

; --- Compute slot number (discarded by patched instruction) ---
            TXA                  ; 031A: 8A        A = $60 (slot offset)
            LSR                  ; 031B: 4A        A = $30
            LSR                  ; 031C: 4A        A = $18
            LSR                  ; 031D: 4A        A = $0C
            LSR                  ; 031E: 4A        A = $06 (slot number)

; *** PATCHED INSTRUCTION ***
; On disk:   ORA #$C0 ($09 $C0)  ->  A = $06 | $C0 = $C6 (broken)
; At runtime: LDA #$02 ($A9 $02)  ->  A = $02 (correct)
; Patched by self-modifying code at $0237-$0240 before JMP $0301.
            LDA #$02             ; 031F: A9 02     ** was ORA #$C0 on disk **
            STA $3F              ; 0321: 85 3F     ($3E) high byte = $02

            LDA #$5D             ; 0323: A9 5D
            STA $3E              ; 0325: 85 3E     ($3E) = $025D (RWTS entry)


; ============================================================================
; SECTOR LOADING LOOP ($0327-$0338)
;
; Reads sectors 0 through 9 from track 0 into pages $B600-$BFFF.
; Each iteration:
;   1. JSR $0343 -> JMP ($003E) -> $025D (RWTS: find address, read data)
;      The RWTS RTS returns to $032A (past the JSR).
;   2. JSR $0346 (custom post-decode: reconstruct 256 bytes to ($40))
;   3. Check if current sector ($3D) matches target ($03FF = $09)
;   4. If not done, increment destination page and sector, loop
;
; Memory map after loading:
;   $B600 = Sector 0   $B700 = Sector 1 (secondary loader entry)
;   $B800 = Sector 2   $B900 = Sector 3   $BA00 = Sector 4
;   $BB00 = Sector 5   $BC00 = Sector 6   $BD00 = Sector 7
;   $BE00 = Sector 8   $BF00 = Sector 9
; ============================================================================

sector_load_loop:
            JSR jmp_indirect_3e  ; 0327: 20 43 03  call RWTS via JMP ($003E)
            JSR postdecode_custom ; 032A: 20 46 03  custom 5-and-3 post-decode
            LDA $3D              ; 032D: A5 3D     current sector number
            EOR stage2_target_sec ; 032F: 4D FF 03  XOR with target ($09)
            BEQ :loading_done    ; 0332: F0 06     zero = match = done
            INC $41              ; 0334: E6 41     next destination page
            INC $3D              ; 0336: E6 3D     next sector number
            BNE sector_load_loop ; 0338: D0 ED     always taken -> loop back


; ============================================================================
; LOADING COMPLETE ($033A-$0345)
;
; All 10 sectors (0-9) loaded to $B600-$BFFF.
; Redirects the ($3E/$3F) vector from $025D (RWTS) to $B700 (secondary
; loader) and executes JMP ($003E) to transfer control.
;
; The JMP ($003E) instruction at $0343 serves DUAL PURPOSE:
;   During loading: ($3E/$3F) = $025D -> calls RWTS (via JSR at $0327)
;   After loading:  ($3E/$3F) = $B700 -> enters secondary loader
; ============================================================================

:loading_done
            STA $3E              ; 033A: 85 3E     A=0 (from EOR match)
                                 ;                  ($3E) low byte = $00
            LDA stage2_dest_page ; 033C: AD CC 03  = $B6
            STA $3F              ; 033F: 85 3F     ($3E) high byte = $B6
            INC $3F              ; 0341: E6 3F     ($3E) high byte = $B7
                                 ;                  ($3E/$3F) = $B700

jmp_indirect_3e:
            JMP ($003E)          ; 0343: 6C 3E 00  -> JMP $B700 (secondary loader)
                                 ;                  (during loading: -> $025D)


; ============================================================================
; CUSTOM POST-DECODE PERMUTATION ($0346-$03A4) — COPY PROTECTION LAYER 5
;
; Reconstructs 256 bytes from the secondary buffer ($0800, corrupted by
; ASL x3) and primary buffer ($0900) into the destination at ($40/$41).
;
; Unlike the standard $02D1 post-decode which processes 3 groups of 51
; bytes sequentially, this routine processes 51 iterations (X = 50..0)
; producing 5 output bytes per iteration — one from each "column":
;
;   Byte 5k+0:  secondary[$0800+X] bits combined with primary[$0900+X]
;   Byte 5k+1:  secondary[$0833+X] bits combined with primary[$0933+X]
;   Byte 5k+2:  secondary[$0866+X] bits combined with primary[$0966+X]
;   Byte 5k+3:  accumulated bits from $2A    + primary[$0999+X]
;   Byte 5k+4:  accumulated bits from $3C    + primary[$09CC+X]
;
; The secondary values were corrupted by ASL x3 at $0301.  The LSR
; sequences here undo that corruption while extracting the needed bits.
;
; The first 3 output bytes each get 5 upper bits from primary and 3 lower
; bits from secondary (via LSR x5 then ORA primary).  During the LSR
; shifts, intermediate carry bits are rotated into $3C and $2A, which
; accumulate the lower bits for output bytes 3 and 4.
;
; Permutation vs standard $02D1:
;   custom output[5k + n] = standard output[offset - k]
;   where offsets = [50, 101, 152, 203, 254] for n = [0, 1, 2, 3, 4]
;
; Byte 255 is a special case handled after the main loop.
;
; ENTRY: called from JSR $0346 in loading loop
; EXIT:  X = slot offset ($2B), 256 bytes written through ($40)
; ============================================================================

postdecode_custom:
            LDX #$32             ; 0346: A2 32     50 = iterations - 1 (X=50..0)
            LDY #$00             ; 0348: A0 00     output index

; ----- Main loop: 5 output bytes per iteration -----

:decode_loop

; --- Output byte 0: secondary[X] + primary[X] ---
            LDA $0800,X          ; 034A: BD 00 08  secondary[X] (corrupted: val<<3)
            LSR                  ; 034D: 4A        >> 1  (val<<2)
            LSR                  ; 034E: 4A        >> 2  (val<<1)
            LSR                  ; 034F: 4A        >> 3  (original val, bit 0 -> carry)
            STA $3C              ; 0350: 85 3C     save 5-bit value
            LSR                  ; 0352: 4A        >> 4  (bits 4..1)
            STA $2A              ; 0353: 85 2A     save for accumulation
            LSR                  ; 0355: 4A        >> 5  (bits 4..2, = upper 3 bits)
            ORA $0900,X          ; 0356: 1D 00 09  combine with primary[X]
            STA ($40),Y          ; 0359: 91 40     store output byte 0
            INY                  ; 035B: C8

; --- Output byte 1: secondary[X+$33] + primary[X+$33] ---
            LDA $0833,X          ; 035C: BD 33 08  secondary[X + 51]
            LSR                  ; 035F: 4A        >> 1
            LSR                  ; 0360: 4A        >> 2
            LSR                  ; 0361: 4A        >> 3
            LSR                  ; 0362: 4A        >> 4  (bit from >>3 is in carry)
            ROL $3C              ; 0363: 26 3C     rotate carry into $3C
            LSR                  ; 0365: 4A        >> 5  (bit from >>4 is in carry)
            ROL $2A              ; 0366: 26 2A     rotate carry into $2A
            ORA $0933,X          ; 0368: 1D 33 09  combine with primary[X + 51]
            STA ($40),Y          ; 036B: 91 40     store output byte 1
            INY                  ; 036D: C8

; --- Output byte 2: secondary[X+$66] + primary[X+$66] ---
            LDA $0866,X          ; 036E: BD 66 08  secondary[X + 102]
            LSR                  ; 0371: 4A        >> 1
            LSR                  ; 0372: 4A        >> 2
            LSR                  ; 0373: 4A        >> 3
            LSR                  ; 0374: 4A        >> 4
            ROL $3C              ; 0375: 26 3C     rotate carry into $3C
            LSR                  ; 0377: 4A        >> 5
            ROL $2A              ; 0378: 26 2A     rotate carry into $2A
            ORA $0966,X          ; 037A: 1D 66 09  combine with primary[X + 102]
            STA ($40),Y          ; 037D: 91 40     store output byte 2
            INY                  ; 037F: C8

; --- Output byte 3: accumulated $2A bits + primary[X+$99] ---
            LDA $2A              ; 0380: A5 2A     accumulated low bits
            AND #$07             ; 0382: 29 07     keep 3 bits
            ORA $0999,X          ; 0384: 1D 99 09  combine with primary[X + 153]
            STA ($40),Y          ; 0387: 91 40     store output byte 3
            INY                  ; 0389: C8

; --- Output byte 4: accumulated $3C bits + primary[X+$CC] ---
            LDA $3C              ; 038A: A5 3C     accumulated low bits
            AND #$07             ; 038C: 29 07     keep 3 bits
            ORA $09CC,X          ; 038E: 1D CC 09  combine with primary[X + 204]
            STA ($40),Y          ; 0391: 91 40     store output byte 4
            INY                  ; 0393: C8

; --- Loop control ---
            DEX                  ; 0394: CA        X = 49, 48, ..., 0
            BPL :decode_loop     ; 0395: 10 B3     loop until X goes negative

; ----- Special case: byte 255 -----
; Main loop produced 5 * 51 = 255 bytes (Y = $FF).
; Byte 255 is reconstructed from secondary[$0899] and primary[$09FF].

            LDA $0899            ; 0397: AD 99 08  secondary[153] (corrupted)
            LSR                  ; 039A: 4A        >> 1  (undo ASL x3)
            LSR                  ; 039B: 4A        >> 2
            LSR                  ; 039C: 4A        >> 3  (original 5-bit value)
            ORA $09FF            ; 039D: 0D FF 09  combine with primary[255]
            STA ($40),Y          ; 03A0: 91 40     store byte 255 (Y=$FF)

            LDX $2B              ; 03A2: A6 2B     restore slot offset ($60)
            RTS                  ; 03A4: 60        return to loading loop


; ============================================================================
; UNUSED PADDING AND CONFIGURATION DATA ($03A5-$03FF)
; ============================================================================

; --- Padding ($03A5-$03CB): 39 bytes of $FF ---
            HEX FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  ; 03A5-03B4
            HEX FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  ; 03B5-03C4
            HEX FFFFFFFFFFFFFF                    ; 03C5-03CB

; --- Initial destination page ---
stage2_dest_page:
            DB $B6               ; 03CC: B6  starting page for sector loading
                                 ;           (sectors 0-9 load to $B600-$BFFF)

; --- Padding ($03CD-$03FE): 50 bytes of $FF ---
            HEX FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  ; 03CD-03DC
            HEX FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  ; 03DD-03EC
            HEX FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  ; 03ED-03FC
            HEX FFFF                              ; 03FD-03FE

; --- Target sector count ---
stage2_target_sec:
            DB $09               ; 03FF: 09  last sector to load
                                 ;           (EOR at $032F: done when $3D = $09)


; ============================================================================
; END OF BOOT RWTS AND STAGE 2 LOADER
;
; After this code completes, control transfers to the secondary loader at
; $B700 (loaded from track 0, sector 1).  The secondary loader reads
; tracks 1-5 to $0800-$48FF, patches the RWTS ($D5 -> $DE markers),
; displays the title screen, then reads tracks 6-13 to $4000-$A7FF
; and JMPs to $4000 to start the game.
;
; See ApplePanic_Boot_T0.asm for the track 0 sector map and custom RWTS.
; See ApplePanic.asm for the game code at $4000-$A7FF.
; ============================================================================

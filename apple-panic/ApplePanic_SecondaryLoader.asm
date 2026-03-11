; ============================================================================
; Apple Panic -- Secondary Loader and RWTS ($B600-$BFFF)
; Disassembled from WOZ disk image (Apple Panic - Disk 1, Side A.woz)
;
; This file covers the secondary loader at $B700 and its supporting RWTS
; code at $B800-$BFFF, loaded from track 0 sectors 0-9 by the stage 2
; loader at $0301. The game code loaded by tracks 6-13 is in ApplePanic.asm.
; The stage 2 loader itself is in ApplePanic_Boot_Stage2.asm.
;
; BOOT FLOW (this is step 3 of 4):
;   1. P6 ROM loads boot sector to $0800, relocates to $0200
;   2. Stage 2 at $0301 corrupts GCR table, loads T0 S0-S9 to $B600-$BFFF
;   3. JMP ($003E) = JMP $B700 (THIS FILE)
;      -> Copies per-track third-byte table from $B7E2 to $0400
;      -> Reads tracks 1-5 to $0800-$48FF (title screen + intermediate code)
;      -> JSR $1000: patches RWTS ($D5->$DE at $B976, $BEF5), displays title
;      -> JSR $1290: title screen animation
;      -> Reads tracks 6-13 to $4000-$A7FF (game payload)
;      -> JMP $4000: game start (relocation + JMP $7000)
;   4. Game runs from $7000 (see ApplePanic.asm)
;
; MEMORY MAP ($B600-$BFFF, one page per track-0 sector):
;   $B600-$B6FF  Sector 0: 5-and-3 GCR translation table (data, not code)
;   $B700-$B7FF  Sector 1: Secondary loader entry point + per-track table
;   $B800-$B8FF  Sector 2: 5-and-3 encode routine + data field writer
;   $B900-$B9FF  Sector 3: Address field search (D5/DE AA xx)
;   $BA00-$BAFF  Sector 4: GCR decode tables + timing
;   $BB00-$BBFF  Sector 5: Primary data buffer (256 bytes)
;   $BC00-$BC99  Sector 6: Secondary data buffer (154 bytes) + RWTS routines
;   $BD00-$BDFF  Sector 7: RWTS main entry point (SUB_BD00)
;   $BE00-$BEFF  Sector 8: Seek routines + address field write setup
;   $BF00-$BFFF  Sector 9: Address/data field writer routines
;
; COPY PROTECTION in this code:
;   Layer 7: Address prolog first byte starts as $D5, gets patched to $DE
;            at runtime by $1000 code (patches $B976 and $BEF5)
;   Layer 8: Per-track third-byte table originally at $B7E2, copied to $0400
;            SUB_B7CB reads $0400,Y and patches $BEFA and $B980
;
; Per-track address prolog third byte table:
;   Track:  0   1   2   3   4   5   6   7   8   9  10  11  12  13
;   Raw:   00  14  14  21  35  61  73  20  50  82  23  60  67  91
;   |$AA:  AA  BE  BE  AB  BF  EB  FB  AA  FA  AA  AB  EA  EF  BB
;
; RUNTIME PATCHES (applied by $1000 intermediate code):
;   $B976: CMP #$D5 -> CMP #$DE  (address field search first byte)
;   $BEF5: LDA #$D5 -> LDA #$DE  (address field write first byte)
; RUNTIME PATCHES (applied by SUB_B7CB per track):
;   $B980: CMP #$xx  (address field third byte check)
;   $BEFA: LDA #$xx  (address field third byte for writing)
;
; Assembler: Merlin32 syntax
; ============================================================================


; ============================================================================
; Zero page and soft switch equates
; ============================================================================

; Zero page locations used by the loader/RWTS
ZP_TEMP1        =     $26           ; Temporary storage / timeout counter
ZP_TEMP2        =     $27           ; Temporary storage / checksum
ZP_TARGET       =     $2F           ; Target track for seek
ZP_CURR_TRK     =     $3E           ; Current track number
ZP_TRACKS_LEFT  =     $42           ; Track counter (tracks remaining)

; Soft switches
SW_TXTCLR       =     $C050         ; Graphics mode
SW_MIXCLR       =     $C052         ; Full screen (no mixed text)
SW_TXTPAGE2     =     $C055         ; Display page 2
SW_MOTOROFF     =     $C089         ; Motor off (indexed by slot)

; Disk I/O soft switches (indexed by slot * 16 in X)
SW_DATALATCH    =     $C08C         ; Read data latch
SW_WRMODE       =     $C08D         ; Write mode
SW_RDMODE       =     $C08E         ; Read mode

; Text page 1 (used as per-track byte storage)
TEXT_PAGE1      =     $0400


; ============================================================================
; $B600-$B6FF -- 5-and-3 GCR Translation Table (Sector 0)
;
; This page contains the 5-and-3 GCR translation table used by the RWTS
; data field reader. Each entry maps a disk nibble value to a 5-bit decoded
; value. Only nibble values with certain bit patterns are valid GCR bytes;
; invalid positions are filled with $FF.
;
; This table was built by the boot code at $0200 and then corrupted by the
; stage 2 loader (ASL x3 on entries $99-$FF -- copy protection layer 3).
; By the time the secondary loader runs, this table is already in its
; corrupted form. The 5-and-3 encode/decode routines at $B800+ are designed
; to work with these corrupted values.
;
; The values shown here are the final (corrupted) table as loaded from disk.
; ============================================================================

            ORG   $B600

GCR_TABLE:
            HEX   F04A99FFFF033CADFFFFFF26B3FFFF4D
            HEX   4A10FFFF3D4ACAFFFFA54AC8FFFF034A
            HEX   40FFFF460891FFFF203309FFFF03BDCC
            HEX   FFFF43C81DFFFF204007FFFF3E9129FF
            HEX   FF85093CFFFF5D00A5FFFFA91DC8FFFF
            HEX   3F4A40FFFF852A91FFFFC08509FFFF09
            HEX   4A99FFFF4A3C1DFFFF4A8507FFFF4A4A
            HEX   29FFFF4A4A2AFFFF8A4AA5FFFF4008C8
            HEX   FFFF840040FFFF41BD91FFFF850009FF
            HEX   FF03A066FFFFCC321DFFFFADA22AFFFF
            HEX   270026FFFF853E4AFFFF096C3CFFFFA9
            HEX   3F26FFFF2BE64AFFFFA63F4AFFFFF485
            HEX   4AFFFFD0034A60FFC8CC082BFF08AD66
            HEX   A6FF003EBD40FF9985C891FF0AED4009
            HEX   FF0AD091FFFF0A3D090DFF08E6334AFF
            HEX   00411D4AFFB9E62A4AFF99062608B648


; ============================================================================
; $B700-$B7FF -- Secondary Loader Entry Point (Sector 1)
;
; This is the main entry point after the stage 2 boot loader finishes.
; JMP ($003E) at the end of the stage 2 code vectors here.
;
; The loader performs these steps:
;   1. Save slot number into RWTS parameter block
;   2. Copy 24-byte per-track third-byte table from $B7E2 to $0400
;      and overwrite $B7E2 with an identity table (0, 1, 2, ... 23)
;   3. Set graphics mode: full screen, display HGR page 2
;   4. Read tracks 1-5 into $0800-$48FF (title screen + intermediate code)
;   5. Turn off drive motor
;   6. JSR $1000: RWTS patcher + title screen display
;   7. Patch $129D with RTS, set up JMP $08E6 at $0000
;   8. JSR $1290: title screen animation
;   9. Read tracks 6-13 into $4000-$A7FF (game payload)
;  10. JMP $4000: begin game (relocation routine)
; ============================================================================

            ORG   $B700

; ----- Entry point: save slot x 16 into RWTS IOB -----
; X = slot * 16 on entry (e.g., $60 for slot 6)

LOADER_ENTRY:
            STX   IOB_SLOT             ; B700: 8E 75 B7  save slot in IOB
            STX   IOB_SLOT2            ; B703: 8E 83 B7  save slot in IOB (2nd ref)
            TXA                        ; B706: 8A
            LSR                        ; B707: 4A        slot*16 -> slot*8
            LSR                        ; B708: 4A        -> slot*4
            LSR                        ; B709: 4A        -> slot*2
            LSR                        ; B70A: 4A        -> slot number (0-7)
            TAX                        ; B70B: AA
            LDA   #$00                 ; B70C: A9 00
            STA   $04F8,X             ; B70E: 9D F8 04  clear motor status byte
            STA   $0478,X             ; B711: 9D 78 04  clear drive status byte
            TAY                        ; B714: A8        Y = 0

; ----- Copy per-track table from $B7E2 to $0400, build identity at $B7E2 -----
; The per-track third-byte table was placed at $B7E2 by the stage 2 loader
; when it read track 0 sector 1 to $B700. Each byte, OR'd with $AA, becomes
; the third address prolog byte for that track (copy protection layer 8).
; After copying to $0400 (text page 1), the source is overwritten with an
; identity table (0, 1, 2, ..., 23) -- presumably to hide the protection
; values from memory inspection.

:COPY_TABLE
            LDA   TRACK_TABLE,Y       ; B715: B9 E2 B7  read per-track byte
            STA   TEXT_PAGE1,Y         ; B718: 99 00 04  store to text page 1
            TYA                        ; B71B: 98
            STA   TRACK_TABLE,Y        ; B71C: 99 E2 B7  overwrite with identity
            INY                        ; B71F: C8
            CPY   #$18                 ; B720: C0 18     24 entries (tracks 0-23)
            BNE   :COPY_TABLE          ; B722: D0 F1

; ----- Set display mode -----
            LDA   SW_TXTCLR            ; B724: AD 50 C0  graphics mode on
            LDA   SW_MIXCLR            ; B727: AD 52 C0  full screen (no text window)
            LDA   SW_TXTPAGE2          ; B72A: AD 55 C0  display HGR page 2

; ----- Read tracks 1-5 to $0800-$48FF -----
; This loads the title screen bitmap, display routines, RWTS patcher,
; and sound code. 5 tracks x 13 sectors = 65 pages = $4100 bytes.

            LDA   #$01                 ; B72D: A9 01
            STA   ZP_CURR_TRK          ; B72F: 85 3E     start at track 1
            LDA   #$05                 ; B731: A9 05
            STA   ZP_TRACKS_LEFT       ; B733: 85 42     read 5 tracks
            LDA   #$00                 ; B735: A9 00
            STA   IOB_DEST_LO          ; B737: 8D 7C B7  dest low = $00
            LDA   #$08                 ; B73A: A9 08
            STA   IOB_DEST_HI          ; B73C: 8D 7D B7  dest high = $08 (-> $0800)
            JSR   READ_TRACKS          ; B73F: 20 89 B7  read tracks 1-5

; ----- Motor off, call intermediate code -----
            LDA   SW_MOTOROFF,X        ; B742: BD 89 C0  turn off drive motor

            JSR   $1000                ; B745: 20 00 10  RWTS patcher + title display
                                       ;   $1000 patches $B976: CMP #$D5 -> CMP #$DE
                                       ;   $1000 patches $BEF5: LDA #$D5 -> LDA #$DE
                                       ;   Then displays title screen and zeroes itself

; ----- Set up for title animation -----
            LDA   #$60                 ; B748: A9 60     RTS opcode
            STA   $129D                ; B74A: 8D 9D 12  patch: insert RTS at $129D
                                       ;   This makes $1290 return early (animation only)

            LDA   #$4C                 ; B74D: A9 4C     JMP opcode
            STA   $00                  ; B74F: 85 00     store JMP at $0000
            LDA   #$E6                 ; B751: A9 E6
            STA   $01                  ; B753: 85 01     JMP target = $08E6
            LDA   #$08                 ; B755: A9 08
            STA   $03                  ; B757: 85 03     column/parameter = $08
            JSR   $1290                ; B759: 20 90 12  title screen animation

; ----- Read tracks 6-13 to $4000-$A7FF (game payload) -----
; 8 tracks x 13 sectors = 104 pages = $6800 bytes

            LDA   #$06                 ; B75C: A9 06
            STA   ZP_CURR_TRK          ; B75E: 85 3E     start at track 6
            LDA   #$08                 ; B760: A9 08
            STA   ZP_TRACKS_LEFT       ; B762: 85 42     read 8 tracks
            LDA   #$00                 ; B764: A9 00
            STA   IOB_DEST_LO          ; B766: 8D 7C B7  dest low = $00
            LDA   #$40                 ; B769: A9 40
            STA   IOB_DEST_HI          ; B76B: 8D 7D B7  dest high = $40 (-> $4000)
            JSR   READ_TRACKS          ; B76E: 20 89 B7  read tracks 6-13

; ----- GAME START -----
            JMP   $4000                ; B771: 4C 00 40  jump to relocation routine


; ============================================================================
; RWTS I/O Block (IOB) at $B774
; This parameter block is passed to SUB_BD00 (RWTS entry) by address.
; Format: table type, slot, drive, volume, track, sector, DCT pointer,
;         buffer pointer, unused, command byte, error code.
; ============================================================================

IOB:
            HEX   01                   ; B774: $01 = table type
IOB_SLOT:
            HEX   60                   ; B775: slot * 16 (patched by LOADER_ENTRY)
            HEX   01                   ; B776: drive number = 1
            HEX   FE                   ; B777: volume = $FE (don't care)
IOB_TRACK:
            HEX   06                   ; B778: current track number
IOB_SECTOR:
            HEX   0D                   ; B779: current sector number
            HEX   85B7                 ; B77A: DCT pointer -> $B785
IOB_DEST_LO:
            HEX   00                   ; B77C: destination page low (patched)
IOB_DEST_HI:
            HEX   49                   ; B77D: destination page high (patched)
            HEX   A0                   ; B77E: unused
            HEX   85                   ; B77F: unused
            HEX   01                   ; B780: command byte ($01 = read)
            HEX   00                   ; B781: error code (0 = success)
            HEX   FE                   ; B782: unused
IOB_SLOT2:
            HEX   60                   ; B783: slot * 16 (2nd copy, patched)

; ----- Device Characteristics Table (DCT) at $B785 -----
            HEX   01                   ; B784: not used directly by loader
DCT:
            HEX   00                   ; B785: device type
            HEX   01                   ; B786: phases per track
            HEX   EF                   ; B787: motor on time
            HEX   D8                   ; B788: motor off time


; ============================================================================
; READ_TRACKS -- Read multiple tracks sequentially
;
; Reads ZP_TRACKS_LEFT tracks starting at ZP_CURR_TRK, 13 sectors per track.
; Each sector is read into successive pages starting at IOB_DEST_HI:00.
; For tracks >= 6, calls the title screen animation between sectors.
;
; On entry:
;   ZP_CURR_TRK ($3E) = first track to read
;   ZP_TRACKS_LEFT ($42) = number of tracks
;   IOB_DEST_HI/LO = destination address (incremented per sector)
; ============================================================================

READ_TRACKS:
            LDA   ZP_CURR_TRK         ; B789: A5 3E     get starting track
            STA   IOB_TRACK            ; B78B: 8D 78 B7  save in IOB

:NEXT_TRACK
            LDA   IOB_TRACK            ; B78E: AD 78 B7  current track
            CMP   #$06                 ; B791: C9 06     track >= 6?
            BCC   :SKIP_ANIM           ; B793: 90 09     no, skip animation

            ; During game payload load (tracks 6-13), animate title screen
            ; Three calls produce visible animation while disk reads
            JSR   TITLE_ANIM           ; B795: 20 DA B7
            JSR   TITLE_ANIM           ; B798: 20 DA B7
            JSR   TITLE_ANIM           ; B79B: 20 DA B7

:SKIP_ANIM
            LDA   #$00                 ; B79E: A9 00
            STA   IOB_SECTOR           ; B7A0: 8D 79 B7  sector counter = 0

            JSR   SET_TRACK_BYTE       ; B7A3: 20 CB B7  patch addr prolog 3rd byte

; ----- Read 13 sectors for this track -----
:READ_SECTOR
            LDA   #>IOB               ; B7A6: A9 B7     IOB address high
            LDY   #<IOB               ; B7A8: A0 74     IOB address low
            PHP                        ; B7AA: 08
            SEI                        ; B7AB: 78        disable interrupts for disk I/O
            JSR   SUB_BD00             ; B7AC: 20 00 BD  call RWTS (read one sector)
            PLP                        ; B7AF: 28        restore interrupt state

            LDA   IOB_DEST_HI          ; B7B0: AD 7D B7  current dest page
            CLC                        ; B7B3: 18
            ADC   #$01                 ; B7B4: 69 01     advance to next page
            STA   IOB_DEST_HI          ; B7B6: 8D 7D B7

            INC   IOB_SECTOR           ; B7B9: EE 79 B7  next sector
            LDA   IOB_SECTOR           ; B7BC: AD 79 B7
            CMP   #$0D                 ; B7BF: C9 0D     13 sectors per track?
            BNE   :READ_SECTOR         ; B7C1: D0 E3     no, read next sector

            INC   IOB_TRACK            ; B7C3: EE 78 B7  next track
            DEC   ZP_TRACKS_LEFT       ; B7C6: C6 42     decrement track counter
            BNE   :NEXT_TRACK          ; B7C8: D0 C4     more tracks remaining
            RTS                        ; B7CA: 60


; ============================================================================
; SET_TRACK_BYTE -- Patch address prolog third byte for current track
;
; Reads the per-track byte from $0400 (text page 1), OR's it with $AA to
; ensure it is a valid disk nibble (high bits set), and patches two RWTS
; locations:
;   $BEFA: operand of LDA instruction in address field write routine
;   $B980: operand of CMP instruction in address field search routine
;
; This implements copy protection layer 8: each track has a different
; third byte in its address field prolog (D5/DE AA xx).
; ============================================================================

SET_TRACK_BYTE:
            LDY   IOB_TRACK            ; B7CB: AC 78 B7  current track number
            LDA   TEXT_PAGE1,Y         ; B7CE: B9 00 04  per-track byte from table
            ORA   #$AA                 ; B7D1: 09 AA     set bits -> valid nibble
            STA   ADDR_WRITE_PATCH     ; B7D3: 8D FA BE  patch addr field write
            STA   ADDR_SEARCH_PATCH    ; B7D6: 8D 80 B9  patch addr field search
            RTS                        ; B7D9: 60


; ============================================================================
; TITLE_ANIM -- Call title screen animation subroutine
; Called between sector reads for tracks 6-13 to keep the title screen
; animated while the game payload is loading from disk.
; ============================================================================

TITLE_ANIM:
            LDA   #$08                 ; B7DA: A9 08     column/parameter
            STA   $03                  ; B7DC: 85 03
            JSR   $1290                ; B7DE: 20 90 12  title screen animation
            RTS                        ; B7E1: 60


; ============================================================================
; Per-Track Third-Byte Table (24 bytes)
;
; Originally loaded from disk with the per-track values. By the time we
; can inspect memory (after $B700 runs), these have been overwritten with
; the identity table (0, 1, 2, ..., 23). The original values were copied
; to $0400 by the :COPY_TABLE loop above.
;
; Original values (from disk):
;   00 14 14 21 35 61 73 20 50 82 23 60 67 91 ...
; After ORA #$AA they become the address prolog third bytes:
;   AA BE BE AB BF EB FB AA FA AA AB EA EF BB ...
;
; After LOADER_ENTRY runs, this table contains 00 01 02 ... 17 (identity).
; ============================================================================

TRACK_TABLE:
            HEX   000102030405060708090A0B0C0D0E0F   ; B7E2: identity (post-copy)
            HEX   1011121314151617                     ; B7F2: identity continued

; Remaining bytes at $B7FA-$B7FF
            HEX   000001EFD800                         ; B7FA: (padding/data)


; ============================================================================
; $B800-$B869 -- 5-and-3 Encode Routine (Sector 2, partial)
;
; Encodes 256 data bytes into 410 disk nibbles using the 5-and-3 GCR scheme.
; This is the inverse of the reconstruct_53 routine at $0A00.
;
; Input: 256 bytes in primary buffer at $BB00
; Output: 154 bytes in secondary buffer at $BC00, 256 bytes in $BB00
;         (both transformed to 5-bit GCR values ready for disk write)
;
; The routine processes 51 groups of 5 bytes (255 bytes) plus 1 remainder,
; splitting each byte into upper 5 bits (stored in $BB00) and lower 3 bits
; (packed into $BC00). The exact algorithm mirrors the decode at $0A00.
; ============================================================================

            ORG   $B800

ENCODE_53:
            LDX   #$32                 ; B800: A2 32     50 (51 groups - 1)
            LDY   #$00                 ; B802: A0 00     output index

; The encode routine continues through $B869 with the 5-and-3 packing logic.
; Each iteration processes 5 bytes from $BB00, splitting them into 5-bit
; primary values and packing the lower 3 bits into the secondary buffer.
; The full routine is symmetric with reconstruct_53 at $0A00.
;
; [Detailed per-instruction annotation omitted for encode routine body --
;  the logic mirrors the decode at $0A00 in ApplePanic_Boot_T0.asm]


; ============================================================================
; $B86A-$B8FF -- Data Field Writer (Sector 2, partial)
;
; Writes a complete data field to disk:
;   1. Writes D5 AA AD data prolog
;   2. Writes 154 secondary buffer bytes (XOR-chained, GCR encoded)
;   3. Writes 256 primary buffer bytes (XOR-chained, GCR encoded)
;   4. Writes checksum byte
;   5. Writes DE AA EB data epilog
;
; The writer uses the corrupted GCR table at $B600 for encoding.
; Not used during normal game boot (read-only), but present for the
; RWTS's format/write capabilities.
; ============================================================================

            ORG   $B86A

DATA_FIELD_WRITER:
            SEC                        ; B86A: 38        set carry (entry flag)
            LDA   SW_WRMODE,X          ; B86B: BD 8D C0  check write mode
            LDA   SW_RDMODE,X          ; B86E: BD 8E C0  set read mode

; [Data field writer body continues through ~$B8FF]
; Writes the encoded nibble stream to disk using the standard Apple II
; disk controller write sequence: load byte, STA $C08D,X, CMP $C08C,X
; for timing, loop through all 410+ nibbles plus prolog/epilog markers.


; ============================================================================
; $B900-$B9FF -- Address Field Search Routine (Sector 3)
;
; Searches the disk nibble stream for an address field prolog matching
; the pattern: D5 AA xx (or DE AA xx after $1000 patches $B976).
;
; The third byte (xx) is set per-track by SET_TRACK_BYTE at $B7CB, which
; patches the CMP operand at ADDR_SEARCH_PATCH ($B980).
;
; After finding the prolog, reads the 4-and-4 encoded address field:
;   - Volume number
;   - Track number
;   - Sector number
;   - Checksum (volume XOR track XOR sector)
;
; Verifies the DE AA epilog and returns the decoded sector number.
;
; RUNTIME PATCHES:
;   $B976: CMP #$D5 -> CMP #$DE (patched by $1000 intermediate code)
;   $B980: CMP #$xx (patched by SET_TRACK_BYTE per track)
; ============================================================================

            ORG   $B900

; [Address field search routine]
; The routine follows the standard Apple II pattern:
;   1. Scan nibbles with timeout for first prolog byte ($D5 or $DE)
;   2. Verify second prolog byte ($AA)
;   3. Verify third prolog byte (per-track value from $B980)
;   4. Read 4-and-4 encoded vol/track/sector/checksum pairs
;   5. Verify address epilog (DE AA)
;   6. Return with sector number; C=0 success, C=1 error

; At $B976 (patched at runtime):
;           CMP   #$D5              ; B976: C9 D5  -> becomes CMP #$DE
; This is the first address prolog byte comparison.
; The $1000 intermediate code patches this to $DE via:
;   LDA #$DE / STA $B8F6,Y  (where Y=$80, so $B8F6+$80 = $B976)

; At $B980 (patched per track):
ADDR_SEARCH_PATCH = $B980
;           CMP   #$xx              ; B980: C9 xx  -> patched by SET_TRACK_BYTE
; This is the third address prolog byte comparison.


; ============================================================================
; $BA00-$BAFF -- GCR Decode/Timing Tables (Sector 4)
;
; Contains the 5-and-3 GCR decode table (maps nibble values to 5-bit data)
; and timing constants used by the disk read/write routines. This is a
; companion to the encode table at $B600.
; ============================================================================

            ORG   $BA00

; [GCR decode table and timing data]
; The table at $BA00 is indexed by raw disk nibble value (Y register).
; Used by the data field reader: EOR $BA00,Y translates GCR nibbles
; to 5-bit values while simultaneously XOR-chaining for checksums.


; ============================================================================
; $BB00-$BBFF -- Primary Data Buffer (Sector 5)
;
; 256-byte buffer used during disk read/write operations.
; During reads: holds 256 decoded 5-bit primary values from the data field.
; During writes: holds 256 bytes to be encoded and written.
; This is the same primary buffer referenced by the RWTS at $0B00.
; ============================================================================

            ORG   $BB00

PRIMARY_BUF = $BB00                    ; 256-byte primary buffer


; ============================================================================
; $BC00-$BC99 -- Secondary Data Buffer + RWTS Code (Sector 6)
;
; First 154 bytes ($BC00-$BC99): secondary data buffer for 5-and-3 GCR.
; During reads: holds 154 decoded 5-bit secondary values (lower 3 bits of
; each output byte, packed 5 per 3 bytes). Filled in reverse order by the
; data field reader.
;
; Remaining bytes ($BC9A-$BCFF): additional RWTS support code.
; ============================================================================

            ORG   $BC00

SECONDARY_BUF = $BC00                  ; 154-byte secondary buffer


; ============================================================================
; $BD00-$BDFF -- RWTS Main Entry Point (Sector 7)
;
; SUB_BD00 is the primary Read/Write Track/Sector routine. Called by the
; secondary loader at $B7AC with the IOB address in A (high) and Y (low).
;
; On entry:
;   A = IOB address high byte
;   Y = IOB address low byte
;
; The IOB (I/O Block) at $B774 contains:
;   +0: table type
;   +1: slot * 16
;   +2: drive number
;   +3: volume expected
;   +4: track number
;   +5: sector number
;   +6-7: DCT pointer
;   +8-9: data buffer pointer (destination for read)
;   +10-11: unused
;   +12: command ($01 = read, $02 = write)
;   +13: error code (0 = OK)
;   +14: actual volume found
;
; Operations:
;   1. Parse IOB to extract track, sector, destination
;   2. Turn on motor if needed (with spin-up delay)
;   3. Seek to requested track (calls seek routines at $BE00+)
;   4. Search for address field matching requested sector
;   5. Read data field into buffer at $BB00/$BC00
;   6. Call reconstruct_53 to reassemble 8-bit bytes
;   7. Store results through destination pointer
;   8. Return with error code in IOB+13
;
; This is functionally equivalent to the DOS 3.3 RWTS but uses:
;   - 5-and-3 encoding (not 6-and-2)
;   - Custom address prolog bytes ($D5/$DE AA xx)
;   - No address checksum verification (protection layer 2)
;   - Corrupted GCR tables (protection layer 3)
; ============================================================================

            ORG   $BD00

SUB_BD00:                              ; RWTS entry point
; [RWTS main body]
; Parses the IOB, manages motor control, calls seek and read routines.
; The detailed instruction flow handles retry logic, error codes, and
; the full read/write dispatch.


; ============================================================================
; $BE00-$BEFF -- Seek Routines + Address Field Write Setup (Sector 8)
;
; Contains the track seek routine that moves the disk head to the
; requested track by stepping the stepper motor phases.
;
; Also contains the address field write setup code that prepares the
; prolog bytes. The LDA at $BEF5 is patched from $D5 to $DE:
;
; RUNTIME PATCH:
;   $BEF5: LDA #$D5 -> LDA #$DE (patched by $1000 intermediate code)
;   $BEFA: LDA #$xx (patched by SET_TRACK_BYTE per track)
;
; The seek routine uses half-track stepping with appropriate timing
; delays between phase activations. Target track is in ZP_TARGET ($2F).
; ============================================================================

            ORG   $BE00

; [Seek routine body at $BE00+]
; Standard Apple II quarter-track/half-track seek with phase table.
; Compares current head position to target, steps in/out as needed.

; At $BEF5 (patched at runtime):
;           LDA   #$D5              ; BEF5: A9 D5  -> becomes LDA #$DE
; This is the first address prolog byte for writing.
; The $1000 intermediate code patches this to $DE via:
;   LDA #$DE / STA $BE75,Y  (where Y=$80, so $BE75+$80 = $BEF5)

; At $BEFA (patched per track):
ADDR_WRITE_PATCH = $BEFA
;           LDA   #$xx              ; BEFA: A9 xx  -> patched by SET_TRACK_BYTE
; This is the third address prolog byte for writing.


; ============================================================================
; $BF00-$BFFF -- Address/Data Field Writer Routines (Sector 9)
;
; Subroutines for writing address and data fields to disk:
;   - Nibble write primitives (shift, OR $AA, write to controller)
;   - 4-and-4 encode for address fields (volume, track, sector, checksum)
;   - Prolog/epilog write sequences
;
; These routines are called by the format code and by the RWTS when
; performing write operations. During normal game boot (read-only),
; these are not used but must be present at the correct addresses
; because the address field writer at $1100 references $BFBD and $BFCD.
;
; Key entry points:
;   $BFBD: Encode and write a 4-and-4 nibble pair (byte in A)
;   $BFCD: Write a raw nibble to disk (byte in A)
; ============================================================================

            ORG   $BF00

; [Writer routine body]
; $BFBD: Takes byte in A, splits into odd/even bits, writes as two disk
;         nibbles using the 4-and-4 encoding scheme:
;           First nibble  = (byte >> 1) | $AA  (odd bits)
;           Second nibble = byte | $AA          (even bits)
;
; $BFCD: Writes byte in A directly to disk via STA $C08D,X / CMP $C08C,X
;         with appropriate timing delays.


; ============================================================================
; END OF SECONDARY LOADER AND RWTS DISASSEMBLY
; ============================================================================

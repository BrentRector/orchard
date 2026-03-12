"""
Copy protection detection and analysis for WOZ disk images.

Scans all tracks for known copy protection techniques and generates
a markdown report.
"""

from .woz import WOZFile
from .gcr import (find_sectors_62, find_sectors_53, scan_address_fields,
                  auto_detect_address_prologs, ENCODE_53, DECODE_53)


class TrackInfo:
    """Analysis results for a single track."""

    def __init__(self, track_num):
        self.track_num = track_num
        self.has_data = False
        self.has_62 = False         # 6-and-2 sectors found
        self.has_53 = False         # 5-and-3 sectors found
        self.sectors_62 = {}        # sector -> SectorData
        self.sectors_53 = {}        # sector -> SectorData
        self.addr_fields = []       # all detected address fields
        self.bad_addr_checksums = 0
        self.bad_data_checksums = 0
        self.non_standard_prologs = []  # prolog tuples that differ from standard
        self.encoding = 'unknown'   # '6-and-2', '5-and-3', 'dual', 'unknown'


class DiskReport:
    """Complete analysis report for a WOZ disk image."""

    def __init__(self, woz_path):
        self.woz_path = woz_path
        self.tracks = {}          # track_num -> TrackInfo
        self.protections = []     # list of (name, description) tuples
        self.track_count = 0
        self.half_tracks = []     # quarter-track indices with data


class CopyProtectionAnalyzer:
    """Analyze a WOZ disk image for copy protection techniques.

    Usage:
        analyzer = CopyProtectionAnalyzer("disk.woz")
        report = analyzer.analyze_all()
        print(analyzer.generate_report(report))
    """

    def __init__(self, woz_path):
        self.woz_path = woz_path
        self.woz = WOZFile(woz_path)

    def analyze_all(self):
        """Scan all tracks and detect copy protection techniques.

        Returns a DiskReport with per-track analysis and detected protections.
        """
        report = DiskReport(self.woz_path)

        # Scan for half/quarter tracks
        for qt in range(160):
            tidx = self.woz.tmap[qt]
            if tidx != 0xFF and tidx in self.woz.track_entries:
                if qt % 4 != 0:  # not a whole track
                    report.half_tracks.append(qt)

        # Analyze each whole track
        for track_num in range(40):
            if not self.woz.track_exists(track_num):
                continue

            report.track_count += 1
            ti = self._analyze_track(track_num)
            report.tracks[track_num] = ti

        # Detect protection techniques
        self._detect_protections(report)

        return report

    def _analyze_track(self, track_num):
        """Analyze a single track for encoding type and sector data.

        Attempts to decode sectors using both 6-and-2 and 5-and-3 GCR
        encodings.  If standard address prologs fail, falls back to
        auto-detection of non-standard prolog byte sequences.

        Args:
            track_num: Whole track number (0-39).

        Returns:
            TrackInfo: Populated analysis results for the track.
        """
        ti = TrackInfo(track_num)
        ti.has_data = True

        nibbles = self.woz.get_track_nibbles(track_num, bit_double=True)
        if not nibbles:
            return ti

        # Try 6-and-2 decode with standard prologs ($D5 $AA $96)
        sectors_62 = find_sectors_62(nibbles)
        if sectors_62:
            ti.has_62 = True
            ti.sectors_62 = sectors_62

        # Try 5-and-3 decode with standard prologs ($D5 $AA $B5)
        sectors_53 = find_sectors_53(nibbles)
        if sectors_53:
            ti.has_53 = True
            ti.sectors_53 = sectors_53

        # If standard prologs found nothing, auto-detect address prologs.
        # Copy-protected disks frequently alter the prolog bytes to foil
        # nibble copiers that only look for $D5 $AA.
        if not sectors_62 or not sectors_53:
            detected = auto_detect_address_prologs(nibbles)
            for prolog in detected:
                # Third byte identifies the GCR scheme:
                #   $96 -> 6-and-2 (16 sectors, used by DOS 3.3 / ProDOS)
                #   $B5 -> 5-and-3 (13 sectors, used by DOS 3.2 / P5A ROM)
                if prolog[2] == 0x96 and not sectors_62:
                    alt_62 = find_sectors_62(nibbles, addr_prolog=prolog)
                    # >= 3 sectors threshold: a single match could be a
                    # coincidental byte pattern; three or more confirms
                    # the prolog is genuine.
                    if len(alt_62) >= 3:
                        ti.has_62 = True
                        ti.sectors_62 = alt_62
                        ti.non_standard_prologs.append(('addr_62', prolog))
                elif prolog[2] == 0xB5 and not sectors_53:
                    alt_53 = find_sectors_53(nibbles, addr_prolog=prolog)
                    if len(alt_53) >= 3:
                        ti.has_53 = True
                        ti.sectors_53 = alt_53
                        ti.non_standard_prologs.append(('addr_53', prolog))

        # Scan for all address fields (standard + non-standard)
        all_addr_fields = scan_address_fields(nibbles)

        # Build set of known prolog patterns for this track
        known_prologs = set()
        if sectors_62:
            known_prologs.add((0xD5, 0xAA, 0x96))
        if sectors_53:
            known_prologs.add((0xD5, 0xAA, 0xB5))
        for _, prolog in ti.non_standard_prologs:
            known_prologs.add(prolog)

        # Filter to address fields matching known prologs by (first, third) byte.
        # The second byte of the prolog is intentionally excluded from the match
        # because some copy-protection schemes vary it per-track or per-sector
        # while keeping the first byte (sync marker) and third byte (format
        # identifier: $96 or $B5) constant.  Matching on the (first, third)
        # tuple lets us capture all address fields regardless of second-byte
        # variation.
        known_ft = {(p[0], p[2]) for p in known_prologs}
        ti.addr_fields = [af for af in all_addr_fields
                          if (af['prolog'][0], af['prolog'][2]) in known_ft]

        # Count checksum failures
        for af in ti.addr_fields:
            if not af['checksum_ok']:
                ti.bad_addr_checksums += 1

        all_sectors = dict(ti.sectors_62)
        all_sectors.update(ti.sectors_53)
        for sd in all_sectors.values():
            if sd.data_checksum_ok is False:
                ti.bad_data_checksums += 1

        # Determine encoding
        if ti.has_62 and ti.has_53:
            ti.encoding = 'dual'
        elif ti.has_62:
            ti.encoding = '6-and-2'
        elif ti.has_53:
            ti.encoding = '5-and-3'
        else:
            ti.encoding = 'unknown'

        return ti

    def _detect_protections(self, report):
        """Detect copy protection techniques from per-track analysis.

        Examines the DiskReport for nine categories of anomalies that
        are indicative of intentional copy protection (as opposed to
        simple disk damage).  Each detected technique is appended to
        ``report.protections`` as a ``(name, description)`` tuple.

        Args:
            report: A DiskReport whose ``tracks`` dict is already populated.
        """

        # ------------------------------------------------------------------
        # 1. Dual-format tracks
        # A track containing BOTH 6-and-2 and 5-and-3 encoded sectors is a
        # strong protection signal.  Standard DOS only expects one format,
        # so nibble copiers configured for 16-sector will miss the 13-sector
        # data and vice versa.
        # ------------------------------------------------------------------
        dual_tracks = [t for t, ti in report.tracks.items()
                       if ti.encoding == 'dual']
        if dual_tracks:
            report.protections.append((
                'Dual-Format Track',
                f'Track(s) {dual_tracks} contain both 6-and-2 (16-sector) and '
                f'5-and-3 (13-sector) format data. Standard copy utilities '
                f'only expect one format per track.'
            ))

        # ------------------------------------------------------------------
        # 2. 5-and-3 encoding (uncommon after 1980)
        # After 1980 essentially all commercial Apple II software switched
        # to 6-and-2 encoding (DOS 3.3 / ProDOS).  Presence of 5-and-3
        # sectors on a post-1980 disk is usually deliberate obfuscation.
        # ------------------------------------------------------------------
        tracks_53 = [t for t, ti in report.tracks.items() if ti.has_53]
        if tracks_53:
            report.protections.append((
                '5-and-3 Encoding',
                f'Track(s) {tracks_53} use 5-and-3 GCR encoding (13-sector, '
                f'P5A ROM era format). This is unusual for post-1980 software '
                f'and incompatible with standard DOS 3.3 copy utilities.'
            ))

        # ------------------------------------------------------------------
        # 3. Bad address checksums
        # Deliberately wrong address checksums cause a validating copier to
        # skip the sector.  The original boot code simply ignores checksums,
        # so the disk still boots on real hardware.
        # ------------------------------------------------------------------
        tracks_bad_addr = [(t, ti.bad_addr_checksums)
                           for t, ti in report.tracks.items()
                           if ti.bad_addr_checksums > 0]
        if tracks_bad_addr:
            total_bad = sum(c for _, c in tracks_bad_addr)
            report.protections.append((
                'Invalid Address Checksums',
                f'{total_bad} address field(s) across {len(tracks_bad_addr)} '
                f'track(s) have deliberately wrong checksums. '
                f'Tracks: {[t for t, _ in tracks_bad_addr]}. '
                f'A copier that validates address checksums would reject these sectors.'
            ))

        # ------------------------------------------------------------------
        # 4. Bad data checksums
        # Similar idea: the original loader doesn't verify data checksums,
        # but a copier that does will think these sectors are corrupt.
        # ------------------------------------------------------------------
        tracks_bad_data = [(t, ti.bad_data_checksums)
                           for t, ti in report.tracks.items()
                           if ti.bad_data_checksums > 0]
        if tracks_bad_data:
            total_bad = sum(c for _, c in tracks_bad_data)
            report.protections.append((
                'Invalid Data Checksums',
                f'{total_bad} sector(s) across {len(tracks_bad_data)} '
                f'track(s) have data that fails checksum verification. '
                f'Tracks: {[t for t, _ in tracks_bad_data]}.'
            ))

        # ------------------------------------------------------------------
        # 5. Non-standard address field markers
        # The standard first prolog byte is $D5.  Changing it means standard
        # copiers (which scan for $D5) will never find the sector header.
        # ------------------------------------------------------------------
        non_std_tracks = []
        for t, ti in report.tracks.items():
            for af in ti.addr_fields:
                prolog = af['prolog']
                if prolog[0] != 0xD5:
                    if (t, prolog) not in non_std_tracks:
                        non_std_tracks.append((t, prolog))
                        break
        if non_std_tracks:
            report.protections.append((
                'Non-Standard Address Markers',
                f'{len(non_std_tracks)} track(s) use non-standard address field '
                f'prolog bytes instead of $D5 $AA xx. '
                f'A copier looking for standard markers would miss these sectors. '
                f'Details: {[(t, tuple(f"${b:02X}" for b in p)) for t, p in non_std_tracks]}'
            ))

        # ------------------------------------------------------------------
        # 6. Half/quarter track data
        # The Disk II stepper motor can position the head at quarter-track
        # granularity.  Standard copiers step whole tracks only, so data
        # placed on half or quarter tracks is invisible to them.
        # ------------------------------------------------------------------
        if report.half_tracks:
            report.protections.append((
                'Half/Quarter Track Data',
                f'Data found at non-standard quarter-track positions: '
                f'{report.half_tracks}. Standard copiers only read whole tracks.'
            ))

        # ------------------------------------------------------------------
        # 7. Variable address field second bytes across tracks
        # The standard second byte is $AA.  Varying it per-track forces
        # any copier that hard-codes $AA to fail on those tracks.
        # ------------------------------------------------------------------
        second_bytes = {}
        for t, ti in report.tracks.items():
            seconds = set()
            for af in ti.addr_fields:
                seconds.add(af['prolog'][1])
            if seconds:
                second_bytes[t] = seconds
        varying_seconds = {t: bs for t, bs in second_bytes.items()
                           if any(b != 0xAA for b in bs)}
        if varying_seconds:
            report.protections.append((
                'Custom Address Field Second Byte',
                f'{len(varying_seconds)} track(s) use non-standard second bytes '
                f'in address field prologs. Tracks and values: '
                f'{dict((t, [f"${b:02X}" for b in sorted(bs)]) for t, bs in varying_seconds.items())}'
            ))

        # ------------------------------------------------------------------
        # 8. Non-standard sector/track numbers in address fields
        # Sector numbers outside 0-15 (6+2) or 0-12 (5+3), or a track
        # field that doesn't match the physical track, mean the boot code
        # uses its own addressing scheme.  Copiers that rely on standard
        # numbering cannot reconstruct the disk layout.
        # ------------------------------------------------------------------
        nonstandard_addr = {}
        for t, ti in report.tracks.items():
            for af in ti.addr_fields:
                max_sec = 15 if ti.has_62 else (12 if ti.has_53 else 15)
                if af['sector'] > max_sec or af['track'] != t:
                    nonstandard_addr.setdefault(t, []).append(
                        (af['volume'], af['track'], af['sector']))
        if nonstandard_addr:
            total = sum(len(v) for v in nonstandard_addr.values())
            report.protections.append((
                'Non-Standard Sector/Track Numbers',
                f'{total} address field(s) across {len(nonstandard_addr)} track(s) '
                f'use sector or track numbers outside the normal range. '
                f'The boot code uses custom sector numbers to identify data, '
                f'making the disk unreadable by standard copy utilities. '
                f'Tracks: {sorted(nonstandard_addr.keys())}'
            ))

        # ------------------------------------------------------------------
        # 9. Missing sectors (informational, not flagged as protection)
        # Some tracks have fewer decodable sectors than expected.  This
        # could be intentional (unused sectors left unformatted) or simply
        # media damage, so we log it but do not report it as protection.
        # ------------------------------------------------------------------
        for t, ti in report.tracks.items():
            expected = 16 if ti.has_62 else (13 if ti.has_53 else 0)
            actual = len(ti.sectors_62) + len(ti.sectors_53)
            if 0 < actual < expected:
                # Don't flag this as protection, could just be damage
                pass

    def generate_report(self, report=None):
        """Generate a markdown report of copy protection analysis.

        Args:
            report: DiskReport from analyze_all() (or None to run analysis)

        Returns: markdown string
        """
        if report is None:
            report = self.analyze_all()

        lines = [
            f"# Copy Protection Analysis: {self.woz_path}",
            "",
            f"**Tracks with data:** {report.track_count}",
            "",
        ]

        # Track summary table
        lines.append("## Track Summary")
        lines.append("")
        lines.append("| Track | Encoding | 6+2 Sectors | 5+3 Sectors | Bad Addr CK | Bad Data CK | Notes |")
        lines.append("|-------|----------|-------------|-------------|-------------|-------------|-------|")

        for t in sorted(report.tracks.keys()):
            ti = report.tracks[t]
            notes = []
            if ti.non_standard_prologs:
                for kind, prolog in ti.non_standard_prologs:
                    notes.append(f"prolog: {' '.join(f'${b:02X}' if b is not None else '??' for b in prolog)}")

            lines.append(
                f"| {t:2d}    | {ti.encoding:8s} | "
                f"{len(ti.sectors_62):11d} | {len(ti.sectors_53):11d} | "
                f"{ti.bad_addr_checksums:11d} | {ti.bad_data_checksums:11d} | "
                f"{'; '.join(notes)} |"
            )

        lines.append("")

        # Copy protection techniques
        if report.protections:
            lines.append("## Detected Copy Protection Techniques")
            lines.append("")
            for i, (name, description) in enumerate(report.protections, 1):
                lines.append(f"### {i}. {name}")
                lines.append("")
                lines.append(description)
                lines.append("")
        else:
            lines.append("## No Copy Protection Detected")
            lines.append("")
            lines.append("This disk appears to use standard encoding with no "
                         "detectable copy protection techniques.")
            lines.append("")

        # Half/quarter tracks
        if report.half_tracks:
            lines.append("## Half/Quarter Track Data")
            lines.append("")
            lines.append(f"Quarter-track positions with data: {report.half_tracks}")
            lines.append("")

        return '\n'.join(lines)

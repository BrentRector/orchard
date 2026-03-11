"""
Copy protection detection and analysis for WOZ disk images.

Scans all tracks for known copy protection techniques and generates
a markdown report.
"""

from .woz import WOZFile
from .gcr import (find_sectors_62, find_sectors_53, scan_address_fields,
                  ENCODE_53, DECODE_53)


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
        """Analyze a single track for encoding type and sector data."""
        ti = TrackInfo(track_num)
        ti.has_data = True

        nibbles = self.woz.get_track_nibbles(track_num, bit_double=True)
        if not nibbles:
            return ti

        # Try 6-and-2 decode with standard prologs
        sectors_62 = find_sectors_62(nibbles)
        if sectors_62:
            ti.has_62 = True
            ti.sectors_62 = sectors_62

        # Try 5-and-3 decode with standard prologs
        sectors_53 = find_sectors_53(nibbles)
        if sectors_53:
            ti.has_53 = True
            ti.sectors_53 = sectors_53

        # If no standard 6-and-2 found, try with $DE first byte
        if not sectors_62:
            alt_62 = find_sectors_62(nibbles, addr_prolog=(0xDE, 0xAA, 0x96))
            if alt_62:
                ti.has_62 = True
                ti.sectors_62 = alt_62
                ti.non_standard_prologs.append(('addr_62', (0xDE, 0xAA, 0x96)))

        # If no standard 5-and-3 found, try with $DE first byte (wildcard third)
        if not sectors_53:
            alt_53 = find_sectors_53(nibbles, addr_prolog=(0xDE, 0xAA, None))
            if alt_53:
                ti.has_53 = True
                ti.sectors_53 = alt_53
                ti.non_standard_prologs.append(('addr_53', (0xDE, 0xAA, None)))

        # Scan for all address fields (standard + non-standard)
        ti.addr_fields = scan_address_fields(nibbles)

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
        """Detect copy protection techniques from track analysis."""

        # 1. Dual format tracks
        dual_tracks = [t for t, ti in report.tracks.items()
                       if ti.encoding == 'dual']
        if dual_tracks:
            report.protections.append((
                'Dual-Format Track',
                f'Track(s) {dual_tracks} contain both 6-and-2 (16-sector) and '
                f'5-and-3 (13-sector) format data. Standard copy utilities '
                f'only expect one format per track.'
            ))

        # 2. 5-and-3 encoding (uncommon after 1980)
        tracks_53 = [t for t, ti in report.tracks.items() if ti.has_53]
        if tracks_53:
            report.protections.append((
                '5-and-3 Encoding',
                f'Track(s) {tracks_53} use 5-and-3 GCR encoding (13-sector, '
                f'P5A ROM era format). This is unusual for post-1980 software '
                f'and incompatible with standard DOS 3.3 copy utilities.'
            ))

        # 3. Bad address checksums
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

        # 4. Bad data checksums
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

        # 5. Non-standard address field markers
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

        # 6. Half/quarter track data
        if report.half_tracks:
            report.protections.append((
                'Half/Quarter Track Data',
                f'Data found at non-standard quarter-track positions: '
                f'{report.half_tracks}. Standard copiers only read whole tracks.'
            ))

        # 7. Variable address field third bytes across tracks
        third_bytes = {}
        for t, ti in report.tracks.items():
            thirds = set()
            for af in ti.addr_fields:
                thirds.add(af['prolog'][2])
            if thirds:
                third_bytes[t] = thirds
        varying_thirds = {t: bs for t, bs in third_bytes.items()
                          if any(b not in (0x96, 0xB5) for b in bs)}
        if varying_thirds:
            report.protections.append((
                'Custom Address Field Third Byte',
                f'{len(varying_thirds)} track(s) use non-standard third bytes '
                f'in address field prologs. Tracks and values: '
                f'{dict((t, [f"${b:02X}" for b in sorted(bs)]) for t, bs in varying_thirds.items())}'
            ))

        # 8. Non-standard sector/track numbers in address fields
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

        # 9. Missing sectors (some tracks have fewer than expected)
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

#!/usr/bin/env python3
"""
Render a WOZ2 disk image as a top-down grayscale view of the magnetic disk surface.

This is a convenience wrapper around ``nibbler.flux.render_flux_image``.
For full options, use: python -m nibbler flux <woz_file> [options]
"""

import sys
from pathlib import Path

# Allow importing nibbler from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nibbler.flux import render_flux_image


def main():
    repo_root = Path(__file__).resolve().parent.parent
    woz_path = repo_root / "apple-panic" / "Apple Panic - Disk 1, Side A.woz"
    out_path = repo_root / "apple-panic" / "flux_image.png"

    print(f"Reading {woz_path} ...")
    track_data = render_flux_image(str(woz_path), str(out_path))

    print(f"Found {len(track_data)} tracks with data:")
    for tn, bits in track_data:
        print(f"  Track {tn:2d}: {bits} bits")


if __name__ == '__main__':
    main()

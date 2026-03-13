"""
Render a WOZ2 disk image as a top-down grayscale view of the magnetic surface.

White pixels represent 1-bits (flux transitions), black pixels represent 0-bits.
The result is a 5.25" circle with a spindle hole, showing the actual flux
patterns from each track as concentric rings.

Requires numpy and Pillow (PIL), which are optional dependencies of nibbler.
These are only needed for this visualization command.

Physical dimensions (Apple II 5.25" floppy):
  - Disk media diameter: ~5.25" (rendered circle)
  - Spindle hole diameter: 1.5" (radius 0.75")
  - Track 0 (outermost) center radius: ~2.25" from center
  - Track pitch: 1/48" (48 TPI)
  - Standard track count: 35
"""

import math

from .woz import WOZFile


# Physical geometry (inches)
DISK_RADIUS_IN = 2.625        # 5.25" / 2
SPINDLE_RADIUS_IN = 0.75      # 1.5" spindle hole / 2
TRACK0_RADIUS_IN = 2.25       # outermost track center
TRACK_PITCH_IN = 1.0 / 48.0   # 48 TPI
DEFAULT_DPI = 600
DEFAULT_TRACKS = 35


def render_flux_image(woz_path, output_path, dpi=DEFAULT_DPI, num_tracks=DEFAULT_TRACKS):
    """Render a WOZ disk image as a grayscale flux visualization.

    Args:
        woz_path: Path to WOZ2 file.
        output_path: Path for output PNG.
        dpi: Resolution in dots per inch (default 600).
        num_tracks: Number of track positions to show (default 35).

    Returns:
        List of (track_number, bit_count) for tracks that had data.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError as e:
        raise ImportError(
            f"The 'flux' command requires numpy and Pillow: {e}\n"
            f"Install them with: pip install numpy Pillow"
        ) from e

    woz = WOZFile(woz_path)

    image_size = int(DISK_RADIUS_IN * 2 * dpi)
    center = image_size / 2.0
    disk_radius_px = DISK_RADIUS_IN * dpi
    spindle_radius_px = SPINDLE_RADIUS_IN * dpi
    track0_radius_px = TRACK0_RADIUS_IN * dpi
    track_pitch_px = TRACK_PITCH_IN * dpi

    img = np.zeros((image_size, image_size), dtype=np.uint8)

    # Read track bit streams
    track_data = []
    track_angle_maps = {}

    for track_num in range(num_tracks):
        if not woz.track_exists(track_num):
            continue

        raw_data, bit_count = woz.get_track_data(track_num)
        if raw_data is None:
            continue

        bits = np.unpackbits(np.frombuffer(raw_data, dtype=np.uint8))[:bit_count]
        track_data.append((track_num, bit_count))

        radius_px = track0_radius_px - track_num * track_pitch_px
        circumference_px = int(2 * math.pi * radius_px)
        n_bins = max(circumference_px, 1)

        # Average bits into angular bins
        bin_sums = np.zeros(n_bins, dtype=np.float64)
        bin_counts = np.zeros(n_bins, dtype=np.int32)
        bit_indices = np.arange(bit_count)
        bin_assignments = (bit_indices * n_bins // bit_count).astype(np.int32)
        np.add.at(bin_sums, bin_assignments, bits.astype(np.float64))
        np.add.at(bin_counts, bin_assignments, 1)
        mask = bin_counts > 0
        bin_sums[mask] /= bin_counts[mask]

        track_angle_maps[track_num] = (radius_px, bin_sums, n_bins)

    # Build coordinate arrays
    y_coords, x_coords = np.mgrid[0:image_size, 0:image_size]
    dx = x_coords - center
    dy = y_coords - center
    r = np.sqrt(dx * dx + dy * dy)
    theta_norm = (np.arctan2(dy, dx) + math.pi) / (2 * math.pi)

    # Paint disk surface as dark gray
    disk_mask = (r <= disk_radius_px) & (r >= spindle_radius_px)
    img[disk_mask] = 32

    # Paint each track
    half_pitch = track_pitch_px / 2.0
    for track_num in range(num_tracks):
        radius_px = track0_radius_px - track_num * track_pitch_px
        inner_r = radius_px - half_pitch
        outer_r = radius_px + half_pitch
        track_mask = (r >= inner_r) & (r <= outer_r) & disk_mask

        if not np.any(track_mask):
            continue

        if track_num not in track_angle_maps:
            # Unused track — leave as dark gray
            continue

        _, angle_map, n_bins = track_angle_maps[track_num]
        pixel_theta = theta_norm[track_mask]
        bin_idx = np.clip((pixel_theta * n_bins).astype(np.int32), 0, n_bins - 1)
        img[track_mask] = (angle_map[bin_idx] * 255).astype(np.uint8)

    # Save
    pil_img = Image.fromarray(img, mode='L')
    pil_img.save(output_path, dpi=(dpi, dpi))

    return track_data

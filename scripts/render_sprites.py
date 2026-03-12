#!/usr/bin/env python3
"""Render Apple Panic sprites and graphics from the runtime binary as PNGs.

Reads ApplePanic_runtime.bin ($0000-$A7FF) and renders:
  - Player character sprite sheet (5 animations, shift-0 frames)
  - Enemy sprite sheets (Apple, Butterfly, Mask — both animation frames)
  - Platform tile (shift 0)
  - Title screen apple shape
  - Font/icon sheet (digits 0-9 + player icon)

Output: apple-panic/assets/*.png

Apple II HGR format:
  Each byte = 7 horizontal pixels (bits 0-6, bit 0=leftmost) + 1 palette bit (bit 7)
  Bit 7 = 0: violet/green palette
  Bit 7 = 1: blue/orange palette
  Adjacent lit pixels merge to white

Sprites are rendered at 6x scale in both monochrome green and Apple II color.

Enemy names from the game manual:
  Type 0: "Little Apples" — the basic enemies
  Type 1: "Green Butterfly" — advanced enemy
  Type 2: "Mask of Death" — appears at higher levels
"""

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow required: pip install Pillow")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
RUNTIME_BIN = REPO_DIR / "apple-panic" / "ApplePanic_runtime.bin"
ASSETS_DIR = REPO_DIR / "apple-panic" / "assets"

# Apple II HGR color palettes
COLOR_VIOLET = (0xD0, 0x00, 0xFF)
COLOR_GREEN  = (0x00, 0xDD, 0x00)
COLOR_BLUE   = (0x00, 0x80, 0xFF)
COLOR_ORANGE = (0xFF, 0x80, 0x00)
COLOR_WHITE  = (0xFF, 0xFF, 0xFF)
COLOR_BLACK  = (0x00, 0x00, 0x00)
BG_DARK      = (0x10, 0x10, 0x10)
MONO_GREEN   = (0x00, 0xDD, 0x00)

SCALE = 6
HSCALE = 2          # Apple II HGR color pixel aspect correction (width multiplier)
PADDING = 12


def load_runtime():
    with open(RUNTIME_BIN, "rb") as f:
        return bytearray(f.read())


def _get_font():
    try:
        return ImageFont.truetype("arial.ttf", 14)
    except (OSError, IOError):
        return ImageFont.load_default()

FONT = _get_font()


def hgr_byte_to_mono(byte_val):
    """Convert one HGR byte to 7 monochrome pixel on/off values."""
    return [(byte_val >> bit) & 1 for bit in range(7)]


def hgr_byte_to_color(byte_val, col_offset=0):
    """Convert one HGR byte to 7 RGB pixel tuples."""
    palette = (byte_val >> 7) & 1
    pixels = []
    for bit in range(7):
        on = (byte_val >> bit) & 1
        if not on:
            pixels.append(COLOR_BLACK)
        else:
            col = col_offset + bit
            if palette == 0:
                pixels.append(COLOR_GREEN if col % 2 else COLOR_VIOLET)
            else:
                pixels.append(COLOR_ORANGE if col % 2 else COLOR_BLUE)
    return pixels


def render_mono(data, offset, w_bytes, h, scale=SCALE, color=MONO_GREEN,
                hscale=1):
    """Render sprite as monochrome scaled image.

    hscale: horizontal pixel stretch factor (2 = Apple II color aspect ratio).
    """
    pw = w_bytes * 7
    sx = scale * hscale
    img = Image.new("RGB", (pw * sx, h * scale), COLOR_BLACK)
    draw = ImageDraw.Draw(img)
    for row in range(h):
        for cb in range(w_bytes):
            bv = data[offset + row * w_bytes + cb]
            for px, on in enumerate(hgr_byte_to_mono(bv)):
                if on:
                    x = (cb * 7 + px) * sx
                    y = row * scale
                    draw.rectangle([x, y, x + sx - 1, y + scale - 1], fill=color)
    return img


def render_color(data, offset, w_bytes, h, scale=SCALE, hscale=1):
    """Render sprite with Apple II color approximation.

    hscale: horizontal pixel stretch factor (2 = Apple II color aspect ratio).
    """
    pw = w_bytes * 7
    sx = scale * hscale
    img = Image.new("RGB", (pw * sx, h * scale), COLOR_BLACK)
    draw = ImageDraw.Draw(img)
    for row in range(h):
        row_pixels = []
        for cb in range(w_bytes):
            bv = data[offset + row * w_bytes + cb]
            row_pixels.extend(hgr_byte_to_color(bv, cb * 7))
        # White merging: adjacent lit pixels become white
        merged = list(row_pixels)
        for i in range(len(merged) - 1):
            if merged[i] != COLOR_BLACK and merged[i + 1] != COLOR_BLACK:
                merged[i] = COLOR_WHITE
                merged[i + 1] = COLOR_WHITE
        for px, c in enumerate(merged):
            if c != COLOR_BLACK:
                x = px * sx
                y = row * scale
                draw.rectangle([x, y, x + sx - 1, y + scale - 1], fill=c)
    return img


def label(text, color=MONO_GREEN):
    """Create a small label image with text."""
    bbox = FONT.getbbox(text)
    w = bbox[2] - bbox[0] + 4
    h = bbox[3] - bbox[1] + 4
    img = Image.new("RGB", (w, h), BG_DARK)
    draw = ImageDraw.Draw(img)
    draw.text((2, -bbox[1]), text, fill=color, font=FONT)
    return img


def labeled_sprite(data, offset, w_bytes, h, text, mono=True, scale=SCALE):
    """Render a sprite with a text label above it."""
    if mono:
        sprite = render_mono(data, offset, w_bytes, h, scale)
    else:
        sprite = render_color(data, offset, w_bytes, h, scale)
    lbl = label(text)
    # Ensure label is at least as wide as sprite
    lbl_w = max(lbl.width, sprite.width)
    result = Image.new("RGB", (lbl_w, lbl.height + 2 + sprite.height), BG_DARK)
    result.paste(lbl, (0, 0))
    result.paste(sprite, (0, lbl.height + 2))
    return result


def side_by_side(*images, padding=PADDING, bg=BG_DARK):
    """Join images horizontally with padding, bottom-aligned."""
    max_h = max(im.height for im in images)
    total_w = sum(im.width for im in images) + padding * (len(images) - 1)
    sheet = Image.new("RGB", (total_w, max_h), bg)
    x = 0
    for im in images:
        sheet.paste(im, (x, max_h - im.height))
        x += im.width + padding
    return sheet


def stack(*images, padding=PADDING, bg=BG_DARK):
    """Join images vertically with padding."""
    max_w = max(im.width for im in images)
    total_h = sum(im.height for im in images) + padding * (len(images) - 1)
    sheet = Image.new("RGB", (max_w, total_h), bg)
    y = 0
    for im in images:
        sheet.paste(im, (0, y))
        y += im.height + padding
    return sheet


def render_font_char(data, offset, scale=SCALE, color=MONO_GREEN):
    """Render an 8x8 font character (1 byte per row, bit 0=leftmost, same as HGR)."""
    img = Image.new("RGB", (8 * scale, 8 * scale), COLOR_BLACK)
    draw = ImageDraw.Draw(img)
    for row in range(8):
        bv = data[offset + row]
        for bit in range(8):
            if (bv >> bit) & 1:
                x = bit * scale
                y = row * scale
                draw.rectangle([x, y, x + scale - 1, y + scale - 1], fill=color)
    return img


def render_plat_patterns(data, scale=SCALE):
    """Render PLAT_TILE_MASK/TOP/BOT pattern tables from $6F00/$6F40/$6F80.

    Each table has 8 shift variants, 4-byte stride, 3 data bytes per variant.
    Renders as 8 rows of 3 bytes (21 pixels) showing the shift progression.
    """
    tables = [
        ("Mask (AND)", 0x6F00),
        ("Top (ORA)",  0x6F40),
        ("Bot (ORA)",  0x6F80),
    ]
    parts = []
    for tname, base in tables:
        pw = 3 * 7  # 3 bytes = 21 pixels
        h = 8       # 8 shift variants
        img = Image.new("RGB", (pw * scale, h * scale), COLOR_BLACK)
        draw = ImageDraw.Draw(img)
        for shift in range(8):
            for cb in range(3):
                bv = data[base + shift * 4 + cb]
                for px, on in enumerate(hgr_byte_to_mono(bv)):
                    if on:
                        x = (cb * 7 + px) * scale
                        y = shift * scale
                        draw.rectangle([x, y, x + scale - 1, y + scale - 1],
                                       fill=MONO_GREEN)
        lbl = label(tname)
        w = max(lbl.width, img.width)
        combined = Image.new("RGB", (w, lbl.height + 2 + img.height), BG_DARK)
        combined.paste(lbl, (0, 0))
        combined.paste(img, (0, lbl.height + 2))
        parts.append(combined)
    return side_by_side(*parts)


def render_apple_shape(scale=SCALE, mono=True):
    """Render the title screen apple shape from hardcoded data.

    The apple shape lives at $1040 in the title screen code (tracks 1-5),
    which is NOT in the runtime binary. Data extracted from the assembly.
    """
    # Apple shape: $1040-$10AF, 4 bytes wide x 28 rows = 112 bytes.
    # Data after $10AF is a separate shape (not the apple).
    apple_hex = (
        "00000000007F7F01"
        "007F5F01007B5F01"
        "007B5F01007B5F01"
        "007B5F01407B5F03"
        "407B5F03407B1F03"
        "407B0F03407B0F03"
        "007B4F0300735F03"
        "00735F0300735F01"
        "00711F0100735F01"
        "00735D0100701900"
        "0070190000701900"
        "0070190000701900"
        "0060190000601900"
        "0060190000601900"
    )
    apple_data = bytearray(bytes.fromhex(apple_hex))
    w, h = 4, len(apple_data) // 4
    if mono:
        return render_mono(apple_data, 0, w, h, scale)
    else:
        return render_color(apple_data, 0, w, h, scale)


def main():
    ASSETS_DIR.mkdir(exist_ok=True)
    data = load_runtime()
    print(f"Loaded runtime binary: {len(data)} bytes")
    print(f"Output: {ASSETS_DIR}/\n")

    # ==== 1. Player character sprites ====
    # Pre-shifted HGR bitmaps at $6000-$6EFF.
    # Format: 3 bytes wide x 16 rows = 48 bytes per shift variant.
    # 7 shift variants per animation frame (shift 0 is canonical).
    player_frames = [
        ("Walk R 1", 0x6000),
        ("Walk R 2", 0x6300),
        ("Climb",    0x6600),
        ("Dig L 1",  0x6900),
        ("Dig L 2",  0x6C00),
    ]
    print("1. Player sprites...")
    mono_imgs = [labeled_sprite(data, off, 3, 16, name, mono=True)
                 for name, off in player_frames]
    color_imgs = [labeled_sprite(data, off, 3, 16, name, mono=False)
                  for name, off in player_frames]
    player_sheet = stack(
        label("Player — monochrome green"),
        side_by_side(*mono_imgs),
        label("Player — Apple II color"),
        side_by_side(*color_imgs),
        padding=6
    )
    player_sheet.save(ASSETS_DIR / "player_sprites.png")
    print(f"  player_sprites.png ({player_sheet.width}x{player_sheet.height})")

    # ==== 2. Enemy sprites ====
    # Names from the game manual (see ApplePanicInstructions.png).
    # 3 bytes wide x 10 rows = 30 bytes per frame, 2 bytes padding.
    # 8 shift variants x 2 animation frames per type.
    # shift 0 anim 0 at +0, shift 0 anim 1 at +32.
    print("2. Enemy sprites...")
    enemy_types = [
        ("Apple",     0x1000),  # "Little Apples" — basic enemies
        ("Butterfly", 0x1200),  # "Green Butterfly" — advanced
        ("Mask",      0x1400),  # "Mask of Death" — highest level
    ]
    mono_enemies = []
    color_enemies = []
    for ename, base in enemy_types:
        a0 = bytearray(data[base:base + 30])
        a1 = bytearray(data[base + 32:base + 62])
        mono_enemies.append(labeled_sprite(a0, 0, 3, 10, f"{ename} 1", mono=True))
        mono_enemies.append(labeled_sprite(a1, 0, 3, 10, f"{ename} 2", mono=True))
        color_enemies.append(labeled_sprite(a0, 0, 3, 10, f"{ename} 1", mono=False))
        color_enemies.append(labeled_sprite(a1, 0, 3, 10, f"{ename} 2", mono=False))

    enemy_sheet = stack(
        label("Enemies — monochrome green"),
        side_by_side(*mono_enemies),
        label("Enemies — Apple II color"),
        side_by_side(*color_enemies),
        padding=6
    )
    enemy_sheet.save(ASSETS_DIR / "enemy_sprites.png")
    print(f"  enemy_sprites.png ({enemy_sheet.width}x{enemy_sheet.height})")

    # ==== 3. Platform tile ====
    # Shift 0 at $0800: 3 bytes wide x 16 rows = 48 bytes.
    print("3. Platform tile...")
    tile_sheet = side_by_side(
        labeled_sprite(data, 0x0800, 3, 16, "Mono", mono=True),
        labeled_sprite(data, 0x0800, 3, 16, "Color", mono=False),
    )
    tile_sheet.save(ASSETS_DIR / "platform_tile.png")
    print(f"  platform_tile.png ({tile_sheet.width}x{tile_sheet.height})")

    # ==== 4. Title screen apple shape ====
    # 4 bytes wide x 28 rows ($1040-$10AF), from assembly (not in runtime binary).
    # Rendered with Apple II color pixel aspect correction (HSCALE).
    print("4. Apple shape...")
    apple_sheet = side_by_side(
        render_apple_shape(mono=True),
        render_apple_shape(mono=False),
    )
    apple_sheet.save(ASSETS_DIR / "apple_shape.png")
    print(f"  apple_shape.png ({apple_sheet.width}x{apple_sheet.height})")

    # ==== 5. Font & icons ====
    # 8 bytes per character at $7003: digits 0-9, blank, player icon.
    # Stored as raw HGR bytes (bit 0=leftmost), written directly to screen.
    print("5. Font & icons...")
    char_names = ["0","1","2","3","4","5","6","7","8","9","(blank)","Life"]
    chars = []
    for i, cname in enumerate(char_names):
        c = render_font_char(data, 0x7003 + i * 8)
        chars.append(labeled_sprite(bytearray(c.tobytes()), 0, 0, 0, cname))
        # Simpler: just use the already-rendered image with a label
    # Redo without the fake labeled_sprite hack
    chars = []
    for i, cname in enumerate(char_names):
        cimg = render_font_char(data, 0x7003 + i * 8)
        lbl = label(cname)
        w = max(lbl.width, cimg.width)
        combined = Image.new("RGB", (w, lbl.height + 2 + cimg.height), BG_DARK)
        combined.paste(lbl, (0, 0))
        combined.paste(cimg, (0, lbl.height + 2))
        chars.append(combined)
    font_sheet = side_by_side(*chars, padding=6)
    font_sheet.save(ASSETS_DIR / "font_icons.png")
    print(f"  font_icons.png ({font_sheet.width}x{font_sheet.height})")

    # ==== 6. Platform tile patterns ====
    # PLAT_TILE_MASK/TOP/BOT at $6F00/$6F40/$6F80.
    # 8 shift variants per table, 4-byte stride, 3 data bytes per variant.
    # Used by DRAW_PLAT_TOP/BOT as AND mask + ORA overlay on screen bytes.
    print("6. Platform tile patterns...")
    pat_sheet = render_plat_patterns(data)
    pat_sheet.save(ASSETS_DIR / "platform_patterns.png")
    print(f"  platform_patterns.png ({pat_sheet.width}x{pat_sheet.height})")

    # ==== 7. Platform tile shift variants ====
    # 8 pre-shifted copies of the platform tile at $0800, $0830, ..., $0950.
    # Each: 3 bytes/row x 16 rows = 48 bytes. Used to draw platforms at
    # any pixel alignment without runtime shifting.
    print("7. Platform tile shifts...")
    shift_imgs = []
    for s in range(8):
        off = 0x0800 + s * 0x30
        shift_imgs.append(labeled_sprite(data, off, 3, 16,
                                         f"Shift {s}", mono=True))
    shift_sheet = side_by_side(*shift_imgs, padding=6)
    shift_sheet.save(ASSETS_DIR / "platform_shifts.png")
    print(f"  platform_shifts.png ({shift_sheet.width}x{shift_sheet.height})")

    # Clean up old per-enemy files
    for old in ["enemy_bug.png", "enemy_spider.png", "enemy_ghost.png"]:
        p = ASSETS_DIR / old
        if p.exists():
            p.unlink()

    n = len(list(ASSETS_DIR.glob("*.png")))
    print(f"\nDone! {n} images saved to {ASSETS_DIR}/")


if __name__ == "__main__":
    main()

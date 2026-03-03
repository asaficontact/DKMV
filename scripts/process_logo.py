#!/usr/bin/env python3
"""One-time script to process the DKMV logo GIF.

Fixes white corners by replacing near-white pixels with dark background,
resizes to 280x280, and saves as optimized GIF.

Usage:
    python3 scripts/process_logo.py

Requires: Pillow, NumPy
Optional: gifsicle (brew install gifsicle) for further compression
"""

import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent / "logo-concepts" / "core" / "also_logo.gif"
DST = Path(__file__).resolve().parent.parent / "assets" / "logo.gif"
TARGET_SIZE = (280, 280)
DARK_BG = (9, 9, 11)  # #09090b
WHITE_THRESHOLD = 240
MAX_COLORS = 128


def process_gif() -> None:
    img = Image.open(SRC)
    frames: list[Image.Image] = []
    durations: list[int] = []

    for i in range(img.n_frames):
        img.seek(i)
        frame = img.convert("RGBA")
        pixels = np.array(frame)

        # Replace near-white pixels (R>240, G>240, B>240) with dark background
        mask = (
            (pixels[:, :, 0] > WHITE_THRESHOLD)
            & (pixels[:, :, 1] > WHITE_THRESHOLD)
            & (pixels[:, :, 2] > WHITE_THRESHOLD)
        )
        pixels[mask] = (*DARK_BG, 255)

        frame = Image.fromarray(pixels, "RGBA")
        frame = frame.resize(TARGET_SIZE, Image.LANCZOS)

        # Composite onto dark background and quantize to reduce palette
        rgb_frame = Image.new("RGB", TARGET_SIZE, DARK_BG)
        rgb_frame.paste(frame, mask=frame.split()[3])
        quantized = rgb_frame.quantize(colors=MAX_COLORS, method=Image.MEDIANCUT)
        frames.append(quantized)
        durations.append(img.info.get("duration", 100))

    frames[0].save(
        DST,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )

    size_kb = DST.stat().st_size / 1024
    print(f"Saved {DST} ({size_kb:.0f}KB, {len(frames)} frames)")

    # Try gifsicle for further compression
    if shutil.which("gifsicle"):
        tmp = DST.with_suffix(".tmp.gif")
        subprocess.run(
            ["gifsicle", "-O3", "--lossy=100", "--colors", "128", str(DST), "-o", str(tmp)],
            check=True,
        )
        tmp.rename(DST)
        final_kb = DST.stat().st_size / 1024
        print(f"Optimized with gifsicle: {final_kb:.0f}KB")
    else:
        print("Tip: install gifsicle for further compression (brew install gifsicle)")


if __name__ == "__main__":
    process_gif()

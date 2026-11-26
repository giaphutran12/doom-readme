"""Make the banner and end-screen images from our own rendered frames (Freedoom art only)."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_frame(assets_dir, x, y, angle):
    return Image.open(Path(assets_dir) / f"doom_{x}_{y}_{angle}.webp").convert("RGB")


def with_caption(frame, lines, bar_height):
    canvas = frame.copy()
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    top = (canvas.height - bar_height) // 2
    draw.rectangle([0, top, canvas.width, top + bar_height], fill=(0, 0, 0, 170))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(canvas)
    sizes = [54, 26]
    y = top + 14
    for text, size in zip(lines, sizes):
        font = ImageFont.load_default(size=size)
        width = draw.textlength(text, font=font)
        draw.text(((canvas.width - width) / 2, y), text, font=font, fill=(255, 60, 40) if size > 30 else (235, 235, 235))
        y += size + 12
    return canvas.convert("RGB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--assets-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.data).read_text())
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    x, y = data["nodes"][data["spawn"]["node"]]
    banner = with_caption(load_frame(args.assets_dir, x, y, data["spawn"]["angle"]),
                          ["CLICK TO PLAY DOOM", "running inside this README"], 150)
    banner.save(out / "start-visual.png", optimize=True)

    exit_x, exit_y = data["nodes"][data["exit_nodes"][0]]
    exit_frame = load_frame(args.assets_dir, exit_x, exit_y, 90)
    with_caption(exit_frame, ["YOU SURVIVED E1M1", "thanks for playing"], 150).save(
        out / "end-screen.png", optimize=True)
    print(f"wrote banner and end screen to {out}", flush=True)


if __name__ == "__main__":
    main()

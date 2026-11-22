"""Encode generated self-role illustrations with a visible looping neon sweep."""

from pathlib import Path
from math import cos, pi

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

ART_DIR = Path(__file__).resolve().parents[1] / "Data" / "art"


def main() -> None:
    for name in ("colors", "pronouns", "platform", "age", "pings"):
        source = ART_DIR / f"self_roles_{name}.png"
        image = Image.open(source).convert("RGB")
        image.thumbnail((900, 380))
        frames = []
        for index in range(16):
            # Keep lettering readable while the moving streak makes animation
            # obvious even at Discord's reduced embed display size.
            level = 0.86 + 0.12 * (1 - cos(2 * pi * index / 16)) / 2
            frame = ImageEnhance.Brightness(image).enhance(level)
            x = -200 + (image.width + 400) * index / 16
            mask = Image.new("L", image.size)
            draw = ImageDraw.Draw(mask)
            draw.polygon(
                [(x - 110, 0), (x + 15, 0),
                 (x + 150, image.height), (x + 25, image.height)],
                fill=155,
            )
            mask = mask.filter(ImageFilter.GaussianBlur(28))
            glow = ImageChops.screen(frame, Image.new("RGB", image.size, (0, 135, 36)))
            frame = Image.composite(glow, frame, mask)
            frames.append(frame.quantize(colors=96, method=Image.Quantize.FASTOCTREE))
        target = ART_DIR / f"self_roles_{name}.gif"
        frames[0].save(
            target,
            save_all=True,
            append_images=frames[1:],
            duration=95,
            loop=0,
            optimize=True,
        )
        print(f"{target.name}: {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

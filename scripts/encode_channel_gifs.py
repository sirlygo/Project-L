"""Build small looping Discord GIFs from the bundled Project L artwork."""

from math import cos, pi
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

ART = Path(__file__).resolve().parents[1] / "Data" / "art"
ASSETS = ("rules", "announcements", "giveaways", "boosts", "stream_alerts")
PANELS = ("verification", "private_voice", "public_voice", "tickets")


def encode(source: Path, target: Path, size: tuple[int, int]) -> None:
    image = Image.open(source).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    frames = []
    for index in range(16):
        phase = 2 * pi * index / 16
        frame = ImageEnhance.Brightness(image).enhance(0.89 + 0.11 * (1 - cos(phase)) / 2)
        x = -image.width // 3 + (image.width * 5 // 3) * index / 15
        mask = Image.new("L", image.size)
        draw = ImageDraw.Draw(mask)
        draw.polygon(
            ((x - 80, 0), (x + 10, 0), (x + 115, image.height), (x + 25, image.height)),
            fill=115,
        )
        mask = mask.filter(ImageFilter.GaussianBlur(25))
        glow = ImageChops.screen(frame, Image.new("RGB", image.size, (0, 105, 50)))
        frames.append(Image.composite(glow, frame, mask).quantize(colors=88))
    frames[0].save(
        target, save_all=True, append_images=frames[1:], duration=100,
        loop=0, optimize=True, disposal=2,
    )


def main() -> None:
    encode(
        ART / "project_l_avatar_animated_source.png",
        ART / "project_l_avatar.gif", (384, 384),
    )
    for name in ASSETS:
        encode(ART / f"{name}_source.png", ART / f"{name}.gif", (900, 380))
    for name in PANELS:
        encode(ART / f"{name}.png", ART / f"{name}.gif", (900, 380))
    for path in [ART / "project_l_avatar.gif", *(ART / f"{name}.gif" for name in (*ASSETS, *PANELS))]:
        print(f"{path.name}: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

"""Encode generated self-role illustrations as small, gently pulsing GIFs."""

from pathlib import Path

from PIL import Image, ImageEnhance

ART_DIR = Path(__file__).resolve().parents[1] / "Data" / "art"


def main() -> None:
    for name in ("colors", "pronouns", "platform", "age", "pings"):
        source = ART_DIR / f"self_roles_{name}.png"
        image = Image.open(source).convert("RGB")
        image.thumbnail((900, 380))
        frames = [
            ImageEnhance.Brightness(image).enhance(level).quantize(colors=128)
            for level in (0.82, 0.94, 1.0, 0.94)
        ]
        target = ART_DIR / f"self_roles_{name}.gif"
        frames[0].save(
            target,
            save_all=True,
            append_images=frames[1:],
            duration=300,
            loop=0,
            optimize=True,
        )
        print(f"{target.name}: {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

"""Validated local artwork and editable channel copy for Project L panels."""

from pathlib import Path

from config_loader import BASE_DIR

ART_DIR = BASE_DIR / "Data" / "art"
ART_KEYS = (
    "verification", "private_voice", "public_voice", "tickets",
    "self_roles_header", "self_roles_colors", "self_roles_pronouns",
    "self_roles_platform", "self_roles_age", "self_roles_pings",
    "rules", "announcements", "giveaways", "boosts", "stream_alerts",
)
DEFAULT_RULES = (
    "👑 **SERVER RULES**\n\n"
    "**1. Be respectful.** No harassment, hate speech, threats, or bullying.\n\n"
    "**2. Keep it safe for everyone.** No NSFW content, graphic violence, or scams.\n\n"
    "**3. Stay on topic.** Use the appropriate channels and avoid spam.\n\n"
    "**4. Respect privacy.** Do not share anyone's personal information.\n\n"
    "**5. Follow Discord's rules.** https://discord.com/terms\n\n"
    "Staff may act on behavior that harms the community."
)


def default_art_path(key: str) -> Path:
    if key == "self_roles_header":
        return BASE_DIR / "Data" / "self_roles.gif"
    if key.startswith("self_roles_"):
        return ART_DIR / f"{key}.gif"
    return ART_DIR / f"{key}.gif"


def resolve_art_path(key: str, config: dict | None = None) -> Path:
    """Use a locally configured override, falling back to bundled art."""
    if key not in ART_KEYS:
        raise KeyError(key)
    override = (config or {}).get("branding", {}).get("art", {}).get(key, "")
    if override:
        path = Path(str(override)).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        if path.is_file() and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".gif"}:
            return path
    return default_art_path(key)

"""Safe built-in self-service role catalog."""

ROLE_GROUPS = {
    "colors": ("Red", "Orange", "Yellow", "Green", "Blue", "Purple", "Pink", "Cyan", "Black", "White"),
    "pronouns": ("He/Him", "She/Her", "They/Them", "Ask"),
    "platform": ("PC", "PlayStation", "Xbox", "Nintendo Switch", "Nintendo Switch 2", "Other Platform"),
    "age": ("Under 18", "18 or Older"),
    "pings": ("Movie Night Pings", "Game Night Pings", "Now Streaming Pings"),
}

ROLE_COLORS = {
    "Red": 0xE74C3C, "Orange": 0xF39C12, "Yellow": 0xF1C40F,
    "Green": 0x2ECC71, "Blue": 0x3498DB, "Purple": 0x9B59B6,
    "Pink": 0xFF69B4, "Cyan": 0x00CED1, "Black": 0x2C3E50,
    "White": 0xECF0F1, "He/Him": 0x3498DB, "She/Her": 0xE980C5,
    "They/Them": 0x9B59B6, "Ask": 0x95A5A6,
    "PC": 0x2ECC71, "PlayStation": 0x315DBC, "Xbox": 0x107C10,
    "Nintendo Switch": 0xE60012, "Nintendo Switch 2": 0xFF5C5C,
    "Other Platform": 0x7F8C8D, "Under 18": 0xF1C40F,
    "18 or Older": 0x27AE60, "Movie Night Pings": 0xAF7AC5,
    "Game Night Pings": 0x58D68D, "Now Streaming Pings": 0xE74C3C,
}


def role_name(group: str, choice: str) -> str:
    return f"Project L {choice}"


def managed_role_ids(config) -> dict[str, dict[str, int]]:
    managed = config.get("managedResources", {})
    roles = managed.get("selfRoles", {}) if isinstance(managed, dict) else {}
    return roles if isinstance(roles, dict) else {}

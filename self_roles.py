"""Safe built-in self-service role catalog."""

ROLE_GROUPS = {
    "colors": ("Red", "Orange", "Yellow", "Green", "Blue", "Purple"),
    "pronouns": ("He/Him", "She/Her", "They/Them", "Any Pronouns"),
    "platform": ("PC", "PlayStation", "Xbox", "Nintendo Switch"),
    "age": ("Under 18", "18 or Older"),
    "pings": ("Movie Night Pings", "Game Night Pings"),
}


def role_name(group: str, choice: str) -> str:
    return f"Project L {choice}"


def managed_role_ids(config) -> dict[str, dict[str, int]]:
    managed = config.get("managedResources", {})
    roles = managed.get("selfRoles", {}) if isinstance(managed, dict) else {}
    return roles if isinstance(roles, dict) else {}

"""Read-only live smoke test for a fully configured Project L Discord server."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from typing import Any

from config_loader import (
    AUTOMATIC_SETUP_VERSION,
    ConfigError,
    load_config,
    load_role_ids,
    missing_required_settings,
)
from discord_validation import (
    DiscordValidationError,
    _get_json,
    validate_live_discord_report,
)
from self_roles import ROLE_GROUPS

EXPECTED_PANELS = {
    "private voice": frozenset({"voicechannel"}),
    "public voice": frozenset({"publicvoicecreate"}),
    "tickets": frozenset({"ticket_help", "ticket_suggestions", "ticket_report"}),
}
VERIFY_COMPONENTS = frozenset({"verify"})


def message_component_ids(message: Mapping[str, Any]) -> set[str]:
    """Extract custom IDs from raw Discord message component rows."""
    result = set()
    for row in message.get("components", []) or []:
        if not isinstance(row, Mapping):
            continue
        for component in row.get("components", []) or []:
            if isinstance(component, Mapping) and component.get("custom_id"):
                result.add(str(component["custom_id"]))
    return result


def has_bot_panel(
    messages: list[Mapping[str, Any]], *, bot_user_id: int, required: frozenset[str]
) -> bool:
    return any(
        int((message.get("author") or {}).get("id", 0) or 0) == bot_user_id
        and required.issubset(message_component_ids(message))
        for message in messages
    )


def missing_panel_names(
    messages: list[Mapping[str, Any]],
    *,
    bot_user_id: int,
    reaction_roles_configured: bool,
    include_dedicated: bool = True,
) -> list[str]:
    """Return managed panel types not found in raw Discord messages."""
    expected = dict(EXPECTED_PANELS) if include_dedicated else {}
    if reaction_roles_configured:
        expected["reaction roles"] = frozenset({"roles"})
    authored_components = [
        message_component_ids(message)
        for message in messages
        if int((message.get("author") or {}).get("id", 0) or 0) == bot_user_id
    ]
    return [
        name
        for name, required in expected.items()
        if not any(
            required.issubset(component_ids) for component_ids in authored_components
        )
    ]


def _required_resource_errors(config: Mapping[str, Any]) -> list[str]:
    errors = []
    managed = config.get("managedResources", {})
    if not isinstance(managed, Mapping):
        return ["managedResources is missing or invalid; run the setup wizard again"]
    if int(managed.get("provisioningVersion", 0) or 0) < AUTOMATIC_SETUP_VERSION:
        errors.append("automatic Discord provisioning has not completed")

    required = {
        "welcome channel": config.get("welcome"),
        "verified role": config.get("verified"),
        "streamer role": config.get("streamRole"),
        "transcript channel": config.get("transcripts"),
        "modmail category": config.get("modmail"),
        "private voice category": config.get("voicecategory"),
        "community category": managed.get("communityCategory"),
        "staff category": managed.get("staffCategory"),
        "server statistics category": managed.get("statsCategory"),
        "panels channel": managed.get("panelsChannel"),
        "private voice creation channel": managed.get("privateVoicePanelChannel"),
        "help channel": managed.get("helpChannel"),
        "general channel": managed.get("welcomeMessagesChannel"),
        "rules channel": managed.get("rulesChannel"),
        "announcements channel": managed.get("announcementsChannel"),
        "boosts channel": managed.get("boostsChannel"),
        "giveaways channel": managed.get("giveawaysChannel"),
        "XP progress channel": managed.get("xpChannel"),
        "information category": managed.get("informationCategory"),
        "announcements category": managed.get("announcementsCategory"),
        "general chat channel": managed.get("generalChatChannel"),
        "voice creation category": managed.get("voiceHubCategory"),
        "public voice category": managed.get("publicVoiceCategory"),
        "public voice creation channel": managed.get("publicVoicePanelChannel"),
    }
    for key, value in (config.get("tickets") or {}).items():
        required[f"ticket resource {key}"] = value
    for key, value in (config.get("serverStatChannelIds") or {}).items():
        required[f"server statistic {key}"] = value
    for key, value in (config.get("logChannelIds") or {}).items():
        required[f"log resource {key}"] = value
    for level in ("5", "15", "30"):
        required[f"level {level} lounge"] = managed.get("levelLounges", {}).get(level)
        for track in ("chat", "voice"):
            required[f"{track} level {level} role"] = managed.get("levelRoles", {}).get(track, {}).get(level)
    for key in ("admin", "mod"):
        required[f"{key} role"] = managed.get("staffRoles", {}).get(key)
    errors.extend(
        f"{label} is not configured" for label, value in required.items() if not value
    )
    return errors


def run_live_smoke_test(*, timeout: float = 15) -> tuple[list[str], list[str]]:
    """Return blocking errors and warnings after read-only live Discord checks."""
    config = load_config()
    role_ids = load_role_ids()
    token = str(config.get("token", "")).strip()
    missing_settings = missing_required_settings(config)
    if missing_settings:
        return [
            "configuration is incomplete; run setup first: "
            + ", ".join(missing_settings)
        ], []
    errors = _required_resource_errors(config)
    if errors:
        return errors, []

    report = validate_live_discord_report(
        config,
        role_ids,
        token=token,
        timeout=timeout,
    )
    errors.extend(report.errors)
    if errors:
        return errors, report.warnings

    bot_user = _get_json("users/@me", token, timeout)
    panel_channel_id = int(config["managedResources"]["panelsChannel"])
    messages = _get_json(
        f"channels/{panel_channel_id}/messages?limit=100", token, timeout
    )
    welcome_messages = _get_json(
        f"channels/{int(config['welcome'])}/messages?limit=100", token, timeout
    )
    if (
        not isinstance(bot_user, Mapping)
        or not isinstance(messages, list)
        or not isinstance(welcome_messages, list)
    ):
        raise DiscordValidationError("Discord returned an unexpected panel response.")
    bot_user_id = int(bot_user["id"])
    if not has_bot_panel(welcome_messages, bot_user_id=bot_user_id, required=VERIFY_COMPONENTS):
        errors.append("verification panel is missing from the welcome channel")
    if has_bot_panel(messages, bot_user_id=bot_user_id, required=VERIFY_COMPONENTS):
        errors.append("verification panel is still in the self-roles/panels channel")
    missing = missing_panel_names(
        messages,
        bot_user_id=bot_user_id,
        reaction_roles_configured=bool(role_ids),
        include_dedicated=False,
    )
    errors.extend(f"{name} panel is missing" for name in missing)
    for kind, channel_id in (
        ("private voice", managed_id(config, "privateVoicePanelChannel")),
        ("public voice", managed_id(config, "publicVoicePanelChannel")),
        ("tickets", managed_id(config, "helpChannel")),
    ):
        target_messages = _get_json(
            f"channels/{channel_id}/messages?limit=100", token, timeout
        )
        if not isinstance(target_messages, list) or not has_bot_panel(
            target_messages,
            bot_user_id=bot_user_id,
            required=EXPECTED_PANELS[kind],
        ):
            errors.append(f"{kind} panel is missing from its dedicated channel")
        if has_bot_panel(messages, bot_user_id=bot_user_id, required=EXPECTED_PANELS[kind]):
            errors.append(f"{kind} panel is still in the self-roles/panels channel")
    if config.get("managedResources", {}).get("selfRoles"):
        for group, choices in ROLE_GROUPS.items():
            required = frozenset(f"selfrole:{group}:{index}" for index in range(len(choices)))
            if not has_bot_panel(messages, bot_user_id=bot_user_id, required=required):
                errors.append(f"{group} self-role buttons are incomplete")
    return errors, report.warnings


def managed_id(config: Mapping[str, Any], key: str) -> int:
    return int(config.get("managedResources", {}).get(key, 0) or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Project L live Discord smoke tests"
    )
    parser.add_argument("--timeout", type=float, default=15)
    arguments = parser.parse_args(argv)
    try:
        errors, warnings = run_live_smoke_test(timeout=arguments.timeout)
    except (ConfigError, DiscordValidationError, OSError, ValueError) as exc:
        print(f"[FAIL] Live smoke test could not run: {exc}", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 3
    print("[PASS] Discord resources, permissions, roles, and managed panels are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

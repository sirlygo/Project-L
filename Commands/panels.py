"""Reusable, durable Discord panels for Project L."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

from config_loader import BASE_DIR, load_config, load_role_ids
from logFunction import print_interaction_info
from self_roles import ROLE_GROUPS, managed_role_ids

SELF_ROLES_IMAGE = BASE_DIR / "Data" / "self_roles.gif"
PANEL_ART_DIR = BASE_DIR / "Data" / "art"
PANEL_ART_IMAGES = {
    "verification": PANEL_ART_DIR / "verification.png",
    "private_voice": PANEL_ART_DIR / "private_voice.png",
    "public_voice": PANEL_ART_DIR / "public_voice.png",
    "tickets": PANEL_ART_DIR / "tickets.png",
    "self_roles_header": SELF_ROLES_IMAGE,
    **{
        f"self_roles:{group}": PANEL_ART_DIR / f"self_roles_{group}.gif"
        for group in ROLE_GROUPS
    },
}
LEGACY_SELF_ROLE_GROUPS = {
    "color roles": "colors",
    "gender roles": "pronouns",
    "age roles": "age",
    "platform roles": "platform",
    "server notifications": "pings",
    "game roles": "platform",
}
SELF_ROLE_COPY = {
    "colors": ("Color Roles", "Choose your favorite color. Selecting another color replaces your previous one."),
    "pronouns": ("Pronoun Roles", "Choose the pronouns you use. Selecting another option replaces your previous one."),
    "platform": ("Gaming Platform Roles", "Choose the platform you play on. Selecting another platform replaces your previous one."),
    "age": ("Age Roles", "Choose Under 18 or 18 or Older. Selecting one replaces the other."),
    "pings": ("Event Pings", "Opt in to Movie Night, Game Night, or Now Streaming notifications. Select again to opt out."),
}
SELF_ROLE_PANEL_TITLES = frozenset(
    {
        "color roles",
        "gender roles",
        "age roles",
        "platform roles",
        "server notifications",
        "game roles",
    }
)
PANEL_COMPONENT_IDS = {
    "verification": frozenset({"verify"}),
    "private_voice": frozenset({"voicechannel"}),
    "public_voice": frozenset({"publicvoicecreate"}),
    "tickets": frozenset({"ticket_help", "ticket_suggestions", "ticket_report"}),
    "reaction_roles": frozenset({"roles"}),
    **{f"self_roles:{group}": frozenset({f"selfrole:{group}:0"}) for group in ROLE_GROUPS},
}


def normalized_panel_title(title):
    """Normalize decorated Discord embed titles for safe panel matching."""
    undecorated = str(title or "").replace("*", "").replace("_", "")
    return " ".join(undecorated.split()).casefold()


def is_self_role_panel_message(message, bot_user_id):
    """Return whether this is an older role panel needing image migration."""
    if getattr(getattr(message, "author", None), "id", None) != bot_user_id:
        return False
    if any(custom_id.startswith("selfrole:") for custom_id in _component_custom_ids(message)):
        return False
    embeds = getattr(message, "embeds", [])
    components = getattr(message, "components", [])
    return bool(
        embeds
        and components
        and normalized_panel_title(embeds[0].title) in SELF_ROLE_PANEL_TITLES
    )


def _panel_image_is_current(message, filename):
    image_url = str(getattr(message.embeds[0].image, "url", "") or "")
    return _is_same_message_art_url(image_url, filename, message)


def _is_same_message_art_url(image_url: str, filename: str, message) -> bool:
    parsed = urlparse(image_url)
    image_name = (parsed.path.rsplit("/", 1)[-1] or parsed.netloc).casefold()
    if image_name != filename.casefold():
        return False
    if parsed.scheme == "attachment":
        return True
    if parsed.scheme == "https" and parsed.hostname in {
        "cdn.discordapp.com", "media.discordapp.net"
    }:
        # Discord often consumes an attached embed image and omits it from
        # message.attachments. The CDN path still proves same-message upload.
        parts = parsed.path.strip("/").split("/")
        channel_id = getattr(getattr(message, "channel", None), "id", None)
        return len(parts) >= 4 and parts[0] == "attachments" and parts[1] == str(channel_id)
    return False


async def repair_self_role_panel_images(channel, bot_user_id):
    """Replace expired panel image URLs with durable same-message attachments."""
    repaired = 0
    failures = []
    async for message in channel.history(limit=100, oldest_first=False):
        if not is_self_role_panel_message(message, bot_user_id):
            continue
        group = LEGACY_SELF_ROLE_GROUPS[normalized_panel_title(message.embeds[0].title)]
        art_path = PANEL_ART_IMAGES[f"self_roles:{group}"]
        if not art_path.is_file():
            failures.append((message.id, FileNotFoundError(str(art_path))))
            continue
        digest = sha256(art_path.read_bytes()).hexdigest()[:10]
        filename = f"self_roles-{group}-{message.id}-{digest}.gif"
        if _panel_image_is_current(message, filename):
            continue
        image_file = None
        try:
            image_file = discord.File(art_path, filename=filename)
            embed = discord.Embed.from_dict(message.embeds[0].to_dict())
            embed.set_image(url=f"attachment://{filename}")
            preserved = [
                attachment
                for attachment in message.attachments
                if not str(getattr(attachment, "filename", "")).casefold().startswith(
                    f"self_roles-{group}-{message.id}".casefold()
                )
            ]
            await message.edit(embed=embed, attachments=[*preserved, image_file])
            repaired += 1
        except (
            OSError,
            discord.Forbidden,
            discord.NotFound,
            discord.HTTPException,
        ) as exc:
            failures.append((message.id, exc))
        finally:
            if image_file is not None:
                image_file.close()
    return repaired, failures


def _component_custom_ids(message) -> set[str]:
    result = set()
    for row in getattr(message, "components", []):
        children = getattr(row, "children", [row])
        for component in children:
            custom_id = getattr(component, "custom_id", None)
            if custom_id:
                result.add(str(custom_id))
    return result


def _managed_panel_art_filename(kind: str) -> str | None:
    art_path = PANEL_ART_IMAGES.get(kind)
    if art_path is None:
        return None
    stem = f"project_l_{kind.replace(':', '_')}"
    if kind.startswith("self_roles:") and art_path.is_file():
        stem += f"_{sha256(art_path.read_bytes()).hexdigest()[:10]}"
    return f"{stem}{art_path.suffix.casefold()}"


def _is_managed_art_attachment(attachment, kind: str) -> bool:
    name = str(getattr(attachment, "filename", "")).casefold()
    stem = f"project_l_{kind.replace(':', '_')}"
    suffix = PANEL_ART_IMAGES[kind].suffix.casefold()
    return name == f"{stem}{suffix}" or (
        name.startswith(f"{stem}_") and name.endswith(suffix)
    )


def managed_panel_art_is_current(message, kind: str) -> bool:
    """Return whether a managed panel uses its durable bundled attachment."""
    filename = _managed_panel_art_filename(kind)
    art_path = PANEL_ART_IMAGES.get(kind)
    if filename is None or art_path is None or not art_path.is_file():
        return True
    embeds = getattr(message, "embeds", [])
    if not embeds:
        return False
    image_url = str(getattr(embeds[0].image, "url", "") or "")
    return _is_same_message_art_url(image_url, filename, message)


async def repair_managed_panel_art(message, kind: str) -> bool:
    """Attach bundled art to an existing panel without replacing its controls."""
    art_path = PANEL_ART_IMAGES.get(kind)
    filename = _managed_panel_art_filename(kind)
    embeds = getattr(message, "embeds", [])
    if (
        art_path is None
        or filename is None
        or not art_path.is_file()
        or not embeds
        or managed_panel_art_is_current(message, kind)
    ):
        return False

    image_file = None
    try:
        image_file = discord.File(art_path, filename=filename)
        embed = discord.Embed.from_dict(embeds[0].to_dict())
        embed.set_image(url=f"attachment://{filename}")
        preserved = [
            attachment
            for attachment in getattr(message, "attachments", [])
            if not _is_managed_art_attachment(attachment, kind)
        ]
        await message.edit(embed=embed, attachments=[*preserved, image_file])
        return True
    finally:
        if image_file is not None:
            image_file.close()


def panel_kind_for_message(message, bot_user_id: int) -> str | None:
    """Identify a bot-authored managed panel by its stable component IDs."""
    if getattr(getattr(message, "author", None), "id", None) != bot_user_id:
        return None
    embeds = getattr(message, "embeds", [])
    if embeds and getattr(getattr(embeds[0], "footer", None), "text", None) == "Project L • Self Roles Header":
        return "self_roles_header"
    component_ids = _component_custom_ids(message)
    for kind, required in PANEL_COMPONENT_IDS.items():
        if required.issubset(component_ids):
            return kind
    return None


class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                emoji="✅",
                label="Verify",
                style=discord.ButtonStyle.success,
                custom_id="verify",
            )
        )


class PrivateVoiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                emoji="🔊",
                label="Create private voice channel",
                style=discord.ButtonStyle.primary,
                custom_id="voicechannel",
            )
        )


class PublicVoiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            emoji="🎙️", label="Create public voice chat",
            style=discord.ButtonStyle.success, custom_id="publicvoicecreate",
        ))


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for emoji, label, custom_id in (
            ("👥", "Help", "ticket_help"),
            ("📬", "Suggestion", "ticket_suggestions"),
            ("🛡️", "Report staff", "ticket_report"),
        ):
            self.add_item(
                discord.ui.Button(
                    emoji=emoji,
                    label=label,
                    style=discord.ButtonStyle.secondary,
                    custom_id=custom_id,
                )
            )


class ReactionRoleView(discord.ui.View):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Select(
                placeholder="Select a role",
                min_values=1,
                max_values=1,
                options=options,
                custom_id="roles",
            )
        )


class BuiltinSelfRoleView(discord.ui.View):
    def __init__(self, config, guild, group):
        super().__init__(timeout=None)
        managed = managed_role_ids(config)
        ids = managed.get(group, {})
        for index, choice in enumerate(ROLE_GROUPS[group]):
            if ids.get(choice) and guild.get_role(int(ids[choice])):
                self.add_item(
                    discord.ui.Button(
                        label=choice,
                        style=discord.ButtonStyle.success,
                        custom_id=f"selfrole:{group}:{index}",
                    )
                )


def reaction_role_options(guild, role_ids: list[int]) -> list[discord.SelectOption]:
    options = []
    bot_member = getattr(guild, "me", None)
    for role_id in role_ids:
        role = guild.get_role(int(role_id))
        if (
            role is None
            or role.id == guild.id
            or (hasattr(role, "is_default") and role.is_default())
            or getattr(role, "managed", False)
            or (bot_member is not None and role >= bot_member.top_role)
        ):
            continue
        options.append(
            discord.SelectOption(
                emoji="👤",
                label=role.name[:100],
                value=str(role.id),
            )
        )
        if len(options) == 25:
            break
    return options


def verification_embed(guild, colour) -> discord.Embed:
    embed = discord.Embed(
        title=f"Welcome to {guild.name}",
        description=(
            "Select **Verify** below to receive the server's verified role. "
            "If the button fails, ask an administrator to check the bot's role hierarchy."
        ),
        colour=colour,
    )
    embed.set_footer(text="Project L • Verification")
    return embed


def private_voice_embed(colour) -> discord.Embed:
    embed = discord.Embed(
        title="Private voice channels",
        description=(
            "Streamers can create a private voice channel with the button below. "
            "The creator receives permission to manage that channel."
        ),
        colour=colour,
    )
    embed.set_footer(text="Project L • Private Voice")
    return embed


def public_voice_embed(colour) -> discord.Embed:
    embed = discord.Embed(
        title="Public voice chats",
        description=(
            "Choose a name for a public voice chat. Anyone verified can join. "
            "The room is removed when everyone leaves."
        ),
        colour=colour,
    )
    embed.set_footer(text="Project L • Public Voice")
    return embed


def ticket_embed(colour) -> discord.Embed:
    embed = discord.Embed(
        title="Support tickets",
        description="Choose the ticket type that best matches what you need.",
        colour=colour,
    )
    embed.set_footer(text="Project L • Tickets")
    return embed


async def send_panel_with_local_art(kind, channel, *, embed, view):
    """Send a panel with its bundled art as a durable Discord attachment."""
    art_path = PANEL_ART_IMAGES.get(kind)
    image_file = None
    if art_path is not None and art_path.is_file():
        try:
            filename = _managed_panel_art_filename(kind)
            image_file = discord.File(art_path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")
        except OSError as exc:
            print(f"[!] Could not open local art for the {kind} panel: {exc}")

    try:
        send_options = {"embed": embed, "view": view}
        if image_file is not None:
            send_options["file"] = image_file
        return await channel.send(**send_options)
    finally:
        if image_file is not None:
            image_file.close()


async def send_reaction_role_panel(channel, guild, colour):
    options = reaction_role_options(guild, load_role_ids())
    if not options:
        raise ValueError("No assignable reaction roles are configured.")
    embed = discord.Embed(
        title="Reaction Roles",
        description="Choose a role from the menu below.",
        colour=colour,
    )
    embed.set_footer(text="Project L • Reaction Roles")
    image_file = None
    try:
        if SELF_ROLES_IMAGE.is_file():
            image_file = discord.File(SELF_ROLES_IMAGE, filename="self_roles.gif")
            embed.set_image(url="attachment://self_roles.gif")
        send_options = {"embed": embed, "view": ReactionRoleView(options)}
        if image_file is not None:
            send_options["file"] = image_file
        return await channel.send(**send_options)
    finally:
        if image_file is not None:
            image_file.close()


async def send_managed_panel(kind: str, channel, guild, colour):
    if kind == "self_roles_header":
        embed = discord.Embed(
            title="Self Roles",
            description="Pick the roles that fit you using the buttons below.",
            colour=colour,
        )
        embed.set_footer(text="Project L • Self Roles Header")
        return await send_panel_with_local_art(kind, channel, embed=embed, view=None)
    if kind == "verification":
        return await send_panel_with_local_art(
            kind,
            channel,
            embed=verification_embed(guild, colour),
            view=VerificationView(),
        )
    if kind == "private_voice":
        return await send_panel_with_local_art(
            kind,
            channel,
            embed=private_voice_embed(colour),
            view=PrivateVoiceView(),
        )
    if kind == "public_voice":
        return await send_panel_with_local_art(
            kind, channel, embed=public_voice_embed(colour), view=PublicVoiceView(),
        )
    if kind == "tickets":
        return await send_panel_with_local_art(
            kind,
            channel,
            embed=ticket_embed(colour),
            view=TicketView(),
        )
    if kind == "reaction_roles":
        return await send_reaction_role_panel(channel, guild, colour)
    if kind.startswith("self_roles:"):
        group = kind.split(":", 1)[1]
        view = BuiltinSelfRoleView(load_config(), guild, group)
        if len(view.children) != len(ROLE_GROUPS[group]):
            raise ValueError(f"{group} self-service roles are not fully configured.")
        title, description = SELF_ROLE_COPY[group]
        embed = discord.Embed(title=title, description=description, colour=colour)
        return await send_panel_with_local_art(kind, channel, embed=embed, view=view)
    raise ValueError(f"Unknown managed panel kind: {kind}")


@dataclass
class PanelInstallReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


async def ensure_automatic_panels(client) -> PanelInstallReport:
    """Keep Verify in welcome and self-role controls in the panels channel."""
    report = PanelInstallReport()
    config = load_config()
    guild = client.get_guild(config["guildId"])
    panels_id = int(config.get("managedResources", {}).get("panelsChannel", 0) or 0)
    welcome_id = int(config.get("welcome", 0) or 0)
    if guild is None or not panels_id:
        report.failed.append("server or panels channel is not configured")
        return report
    panels_channel = guild.get_channel(panels_id) or client.get_channel(panels_id)
    if panels_channel is None:
        try:
            panels_channel = await client.fetch_channel(panels_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            report.failed.append(f"panels channel is unavailable: {exc}")
            return report

    async def find_existing(channel):
        found = {}
        verification_messages = []
        async for message in channel.history(limit=200, oldest_first=False):
            kind = panel_kind_for_message(message, client.user.id)
            if kind == "verification":
                verification_messages.append(message)
            if kind and kind not in found:
                found[kind] = message
        return found, verification_messages

    try:
        panel_messages, misplaced_verification = await find_existing(panels_channel)
    except (discord.Forbidden, discord.HTTPException) as exc:
        report.failed.append(f"could not inspect existing panels: {exc}")
        return report

    welcome_channel = None
    if welcome_id and welcome_id != panels_id:
        welcome_channel = guild.get_channel(welcome_id) or client.get_channel(welcome_id)
        if welcome_channel is None:
            try:
                welcome_channel = await client.fetch_channel(welcome_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                report.failed.append(f"welcome channel is unavailable: {exc}")
        if welcome_channel is not None:
            try:
                welcome_messages, _ = await find_existing(welcome_channel)
                existing_verify = welcome_messages.get("verification")
                if existing_verify is None:
                    await send_managed_panel("verification", welcome_channel, guild, client.colour)
                    report.created.append("verification")
                elif await repair_managed_panel_art(existing_verify, "verification"):
                    report.updated.append("verification")
                else:
                    report.existing.append("verification")

                for misplaced_verify in misplaced_verification:
                    await misplaced_verify.delete()
                if misplaced_verification:
                    report.moved.append("verification")
            except (
                OSError,
                discord.Forbidden,
                discord.NotFound,
                discord.HTTPException,
            ) as exc:
                print(f"[!] Could not place verification panel in welcome: {exc}")
                report.failed.append("verification in welcome channel")
    else:
        report.failed.append("welcome channel is not configured separately from panels")

    desired = []
    if managed_role_ids(config):
        desired.append("self_roles_header")
        desired.extend(f"self_roles:{group}" for group in ROLE_GROUPS)
    if reaction_role_options(guild, load_role_ids()):
        desired.append("reaction_roles")
    for kind in desired:
        existing_message = panel_messages.get(kind)
        if existing_message is not None:
            try:
                changed = await repair_managed_panel_art(existing_message, kind)
                if kind.startswith("self_roles:"):
                    group = kind.split(":", 1)[1]
                    view = BuiltinSelfRoleView(config, guild, group)
                    expected = {item.custom_id for item in view.children}
                    if len(view.children) == len(ROLE_GROUPS[group]) and _component_custom_ids(existing_message) != expected:
                        await existing_message.edit(view=view)
                        changed = True
                if changed:
                    report.updated.append(kind)
                else:
                    report.existing.append(kind)
            except (
                OSError,
                discord.Forbidden,
                discord.NotFound,
                discord.HTTPException,
            ) as exc:
                print(f"[!] Could not update {kind} panel art: {exc}")
                report.failed.append(kind)
            continue
        try:
            await send_managed_panel(kind, panels_channel, guild, client.colour)
            report.created.append(kind)
        except (
            ValueError,
            OSError,
            discord.Forbidden,
            discord.NotFound,
            discord.HTTPException,
        ) as exc:
            print(f"[!] Could not install {kind} panel: {exc}")
            report.failed.append(kind)

    dedicated_channels = {
        "private_voice": int(config.get("managedResources", {}).get("privateVoicePanelChannel", 0) or panels_id),
        "public_voice": int(config.get("managedResources", {}).get("publicVoicePanelChannel", 0) or panels_id),
        "tickets": int(config.get("managedResources", {}).get("helpChannel", 0) or panels_id),
    }
    for kind, channel_id in dedicated_channels.items():
        target = panels_channel if channel_id == panels_id else guild.get_channel(channel_id) or client.get_channel(channel_id)
        try:
            if target is None:
                target = await client.fetch_channel(channel_id)
            old = panel_messages.get(kind) if target is not panels_channel else None
            if target is panels_channel:
                existing = panel_messages.get(kind)
            else:
                target_messages, _ = await find_existing(target)
                existing = target_messages.get(kind)
            if existing is None:
                await send_managed_panel(kind, target, guild, client.colour)
                report.created.append(kind)
            elif await repair_managed_panel_art(existing, kind):
                report.updated.append(kind)
            else:
                report.existing.append(kind)
            if old is not None:
                await old.delete()
                report.moved.append(kind)
        except (OSError, discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            print(f"[!] Could not place {kind} panel: {exc}")
            report.failed.append(kind)
    return report


class PanelsCommand(commands.Cog):
    def __init__(self, client):
        self.client = client

    @app_commands.command(
        name="reactionroles", description="Send the configured reaction-role panel"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def reactionroles(self, interaction: discord.Interaction):
        print_interaction_info(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            await send_reaction_role_panel(
                interaction.channel, interaction.guild, self.client.colour
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except (OSError, discord.Forbidden, discord.HTTPException) as exc:
            print(f"[!] Could not send reaction-role panel: {exc}")
            await interaction.followup.send(
                "I could not send that panel. Check my channel permissions.",
                ephemeral=True,
            )
            return
        await interaction.followup.send("Reaction-role panel sent.", ephemeral=True)

    @app_commands.command(
        name="repairselfroles",
        description="Repair expired images on self-role panels in this channel",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def repairselfroles(self, interaction: discord.Interaction):
        print_interaction_info(interaction)
        await interaction.response.defer(ephemeral=True)
        if not SELF_ROLES_IMAGE.is_file():
            await interaction.followup.send(
                "Data/self_roles.gif is missing, so the panels could not be repaired.",
                ephemeral=True,
            )
            return
        repaired, failures = await repair_self_role_panel_images(
            interaction.channel, self.client.user.id
        )
        summary = f"Repaired {repaired} self-role panel image(s)."
        if failures:
            summary += f" {len(failures)} panel(s) could not be edited."
        elif repaired == 0:
            summary = "No recognized self-role panel images needed repair here."
        await interaction.followup.send(summary, ephemeral=True)

    @app_commands.command(name="verifypanel", description="Send the verification panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def verifypanel(self, interaction: discord.Interaction):
        print_interaction_info(interaction)
        config = load_config()
        if interaction.guild.get_role(config["verified"]) is None:
            await interaction.response.send_message(
                "The verified role is unavailable. Run setup again first.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await send_managed_panel(
            "verification", interaction.channel, interaction.guild, self.client.colour
        )
        await interaction.followup.send("Verification panel sent.", ephemeral=True)

    @app_commands.command(name="voicepanel", description="Send the private-voice panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def voicepanel(self, interaction: discord.Interaction):
        print_interaction_info(interaction)
        config = load_config()
        role = interaction.guild.get_role(config["streamRole"])
        category = interaction.guild.get_channel(config["voicecategory"])
        if role is None or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "The streamer role or private-voice category is unavailable. Run setup again.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await send_managed_panel(
            "private_voice", interaction.channel, interaction.guild, self.client.colour
        )
        await interaction.followup.send("Private-voice panel sent.", ephemeral=True)

    @app_commands.command(name="ticketpanel", description="Send the ticket panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticketpanel(self, interaction: discord.Interaction):
        print_interaction_info(interaction)
        config = load_config()
        invalid = [
            key.removeprefix("category_")
            for key, channel_id in config["tickets"].items()
            if not isinstance(
                interaction.guild.get_channel(channel_id), discord.CategoryChannel
            )
        ]
        if invalid:
            await interaction.response.send_message(
                "Ticket panel not sent; rerun setup for: " + ", ".join(invalid),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await send_managed_panel(
            "tickets", interaction.channel, interaction.guild, self.client.colour
        )
        await interaction.followup.send("Ticket panel sent.", ephemeral=True)


async def setup(client):
    await client.add_cog(PanelsCommand(client))

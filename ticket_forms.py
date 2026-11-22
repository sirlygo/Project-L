"""Customizable intake forms for Project L support tickets."""

import sqlite3

import discord

from config_loader import load_config
from dashboard_store import create_ticket_record

DEFAULT_FORMS = {
    "help": [{"label": "What do you need help with?", "required": True, "maxLength": 1000}],
    "suggestions": [{"label": "What is your suggestion?", "required": True, "maxLength": 1000}],
    "report": [{"label": "What would you like to report?", "required": True, "maxLength": 1000}],
}


def validate_forms(value):
    if not isinstance(value, dict):
        raise ValueError("Ticket forms must be an object.")
    result = {}
    for kind in DEFAULT_FORMS:
        questions = value.get(kind, DEFAULT_FORMS[kind])
        if not isinstance(questions, list) or len(questions) > 5:
            raise ValueError(f"{kind} can have at most five questions.")
        clean = []
        for question in questions:
            if not isinstance(question, dict):
                raise ValueError("Each ticket question must be an object.")
            label = str(question.get("label", "")).strip()
            max_length = int(question.get("maxLength", 1000))
            if not 1 <= len(label) <= 45 or not 1 <= max_length <= 4000:
                raise ValueError("Ticket labels must be 1–45 characters and answers 1–4000.")
            clean.append({
                "label": label, "required": bool(question.get("required", True)),
                "maxLength": max_length,
            })
        result[kind] = clean
    return result


def questions_for(config, kind):
    forms = (config.get("ticketWorkspace") or {}).get("forms") or DEFAULT_FORMS
    return validate_forms(forms)[kind]


class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Transcript", emoji="📄", custom_id="transcript"))
        self.add_item(discord.ui.Button(label="Close", emoji="🔒", custom_id="close"))


class TicketOpenModal(discord.ui.Modal):
    def __init__(self, kind, questions):
        super().__init__(title=f"Open {kind.title()} Ticket", timeout=300)
        self.kind = kind
        self.questions = questions
        self.inputs = []
        for index, question in enumerate(questions):
            field = discord.ui.TextInput(
                label=question["label"], required=question["required"],
                max_length=question["maxLength"],
                style=discord.TextStyle.paragraph if question["maxLength"] > 200 else discord.TextStyle.short,
                custom_id=f"answer_{index}",
            )
            self.add_item(field)
            self.inputs.append(field)

    async def on_submit(self, interaction: discord.Interaction):
        config = load_config()
        guild = interaction.guild
        if guild is None or guild.id != config["guildId"]:
            await interaction.response.send_message("Use this in the configured server.", ephemeral=True)
            return
        category = guild.get_channel(int(config["tickets"].get(f"category_{self.kind}", 0) or 0))
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("The ticket category is unavailable. Ask staff to rerun setup.", ephemeral=True)
            return
        if len(category.channels) >= 50:
            await interaction.response.send_message("This ticket category is full. Ask staff to archive old tickets.", ephemeral=True)
            return
        from Commands.on_interaction import ticket_permission_overwrites
        owner_topic = f"ticket-owner:{interaction.user.id}"
        existing = next((channel for channel in category.text_channels if channel.topic == owner_topic), None)
        if existing:
            await interaction.response.send_message(f"You already have a ticket: {existing.mention}", ephemeral=True)
            return
        answers = {question["label"]: field.value for question, field in zip(self.questions, self.inputs)}
        room = None
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            room = await guild.create_text_channel(
                name=f"ticket-{self.kind}-{interaction.user.id}",
                category=category, topic=owner_topic,
                overwrites=ticket_permission_overwrites(category, interaction.user),
                reason=f"{self.kind.title()} ticket opened by {interaction.user.id}",
            )
            embed = discord.Embed(
                title=f"{self.kind.title()} Ticket",
                description=f"Welcome, {interaction.user.mention}. Staff will be with you soon.",
                colour=0x65FF00,
            )
            for label, answer in answers.items():
                if answer:
                    embed.add_field(name=label, value=answer[:1024], inline=False)
            await room.send(embed=embed, view=TicketControls(),
                            allowed_mentions=discord.AllowedMentions.none())
            create_ticket_record(room.id, guild.id, interaction.user.id, self.kind, answers)
        except (discord.Forbidden, discord.HTTPException, sqlite3.Error) as exc:
            if room is not None:
                try:
                    await room.delete(reason="Incomplete ticket setup")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            print(f"[!] Could not open ticket: {exc}")
            await interaction.followup.send("Ticket creation failed. Ask staff to check bot permissions.", ephemeral=True)
            return
        await interaction.followup.send(f"Your ticket is ready: {room.mention}", ephemeral=True)

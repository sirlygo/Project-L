import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import sqlite3
import random
import requests
import asyncio
from logFunction import print_interaction_info
from config_loader import ConfigError, load_config
from guild_config import active_guild_configs, guild_database_path, load_active_guild_config


class Invites(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.invites = {}
        self.refresh_invites.start()

    def cog_unload(self):
        self.refresh_invites.cancel()

    @tasks.loop(minutes=5)
    async def refresh_invites(self):
        for guild, _config in active_guild_configs(self.client.guilds):
            try:
                self.invites[guild.id] = await guild.invites()
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"Could not refresh invites for guild {guild.id}: {exc}")

    @refresh_invites.before_loop
    async def before_refresh_invites(self):
        await self.client.wait_until_ready()


    def connect(self, guild_id):
        try:
            primary_id = load_config()["guildId"]
            path = guild_database_path(guild_id, "users.db", primary_guild_id=primary_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            if guild_id != primary_id:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS users ("
                    "userid INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, "
                    "invited INTEGER DEFAULT 0, left INTEGER DEFAULT 0, voice INTEGER DEFAULT 0)"
                )
            curs = conn.cursor()
            return conn, curs
        except Exception as exc:
            print(exc)
            return None

    def find_invite_by_code(self, inv_list, code):
        for inv in inv_list:
            if inv.code == code:
                return inv


    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            load_active_guild_config(member.guild.id)
        except ConfigError:
            return
        invs_after = await member.guild.invites()
        self.invites[member.guild.id] = invs_after
        result = Invites.connect(self, member.guild.id)
        if result is None:
            return

        conn, curs = result
        query = f"""SELECT invited, left FROM users WHERE userid={member.id}"""
        curs.execute(query)
        records = curs.fetchall()
        if len(records) == 0:
            conn.close()
            return
        else:
            query = f"""UPDATE users SET (left) = (1) WHERE userid={member.id}"""
            curs.execute(query)

        conn.commit()
        conn.close()
        return



    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            config = load_active_guild_config(member.guild.id)
        except ConfigError:
            return
        try:
            welcomeid = config["invitechannel"]

            if member.avatar is None:
                userpfp = member.default_avatar
            else:
                userpfp = member.avatar

            channel = self.client.get_channel(welcomeid)

            result = Invites.connect(self, member.guild.id)
            if result is None:
                invs_after = await member.guild.invites()
                self.invites[member.guild.id] = invs_after
                return

            conn, curs = result

            query = f"""SELECT invited FROM users WHERE userid={member.id}"""
            curs.execute(query)
            records = curs.fetchall()

            if len(records) == 0:
                query = f"""INSERT OR IGNORE INTO users(userid, balance, invited, left) VALUES({member.id}, 0, 0, 0)"""
                curs.execute(query)

            query = f"""UPDATE users SET (left) = (0) WHERE userid={member.id}"""
            curs.execute(query)

            invs_before = self.invites.get(member.guild.id, [])
            invs_after = await member.guild.invites()
            self.invites[member.guild.id] = invs_after

            inviter = None
            for invite in invs_before:
                current_invite = self.find_invite_by_code(invs_after, invite.code)
                if current_invite is not None and invite.uses < current_invite.uses:
                    inviter = invite.inviter
                    query = f"""UPDATE users SET (invited) = ({invite.inviter.id}) WHERE userid={member.id}"""
                    curs.execute(query)

                    query = f"""SELECT * FROM users WHERE invited={invite.inviter.id} AND left = 0"""
                    curs.execute(query)
                    records = curs.fetchall()
                    invites = len(records)
                    break

            conn.commit()
            conn.close()

            if channel is not None:
                timer = int(str(member.created_at.timestamp()).split(".")[0])
                if inviter is not None:
                    emb = discord.Embed(description=f"{member.mention} has been invited by {inviter} who now has **{invites}** invites.\nWe now have {len(member.guild.members)} members in {member.guild.name}!", colour=self.client.colour)
                    emb.set_author(name=member, icon_url=userpfp)
                    emb.set_thumbnail(url=userpfp)
                    emb.add_field(name="Account Created At", value=f"<t:{timer}>", inline=False)
                    await channel.send(embed=emb)
                else:
                    emb = discord.Embed(description=f"{member.mention} joined the server.\nWe now have {len(member.guild.members)} members in {member.guild.name}!", colour=self.client.colour)
                    emb.set_author(name=member, icon_url=userpfp)
                    emb.set_thumbnail(url=userpfp)
                    emb.add_field(name="Account Created At", value=f"<t:{timer}>", inline=False)
                    await channel.send(embed=emb)


        except Exception as exc:
            invs_after = await member.guild.invites()
            self.invites[member.guild.id] = invs_after
            print(exc)
            return




    @app_commands.command(name="invites", description="Check your invites")
    async def invites(self, interaction: discord.Interaction):
        print_interaction_info(interaction)
        userid = interaction.user.id
        result = Invites.connect(self, interaction.guild_id)
        if result is None:
            return

        conn = result[0]
        curs = result[1]

        query = f"""SELECT * FROM users WHERE invited={userid} AND left = 0"""
        curs.execute(query)
        records = curs.fetchall()
        invites = len(records)

        query = f"""SELECT * FROM users WHERE invited={userid} AND left = 1"""
        curs.execute(query)
        records = curs.fetchall()
        left = len(records)

        total = invites + left

        conn.close()
        emb = discord.Embed(title=f"Invites", description=f"You have **{invites}** active invites, **{left}** left, **{total}** total.",
                            colour=self.client.colour)
        await interaction.response.send_message(embed=emb)
        return



async def setup(client):
    await client.add_cog(Invites(client))

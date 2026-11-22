"""Discord OAuth2 dashboard hosted by the bot behind an HTTPS reverse proxy."""

import asyncio
import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import aiohttp
import discord
from aiohttp import web
from PIL import Image

from branding import ART_KEYS, DEFAULT_RULES
from config_loader import BASE_DIR, CONFIG_PATH, load_config
from dashboard_store import (
    add_staff_note, case_exists, get_transcript, list_appeals, list_cases, list_config_history,
    list_staff_notes, list_tickets, overview, record_config_snapshot, review_appeal,
    search_transcripts, submit_appeal, ticket_exists, update_ticket,
)
from moderation_policy import validate_escalation
from ticket_forms import DEFAULT_FORMS, validate_forms
from setup_config import _write_json_atomic

STATIC = BASE_DIR / "dashboard_static"
DISCORD_API = "https://discord.com/api/v10"


def dashboard_options(config, environ=None):
    env = os.environ if environ is None else environ
    url = str(env.get("PROJECTL_DASHBOARD_PUBLIC_URL", "")).rstrip("/")
    secret = str(env.get("DISCORD_CLIENT_SECRET", ""))
    session_secret = str(env.get("PROJECTL_DASHBOARD_SESSION_SECRET", ""))
    if not (url and secret and session_secret):
        return None
    parsed = urlparse(url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if (not (parsed.scheme == "https" or local_http) or not parsed.netloc
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("Dashboard URL must be a public HTTPS origin or local HTTP origin.")
    if len(session_secret) < 32:
        raise ValueError("Dashboard session secret must contain at least 32 characters.")
    port = int(env.get("PROJECTL_DASHBOARD_PORT", "8765"))
    if not 1024 <= port <= 65535:
        raise ValueError("Dashboard port must be between 1024 and 65535.")
    return {"url": url, "client_id": int(config["client_id"]),
            "client_secret": secret, "session_secret": session_secret.encode(),
            "port": port}


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_session(user_id, secret, *, now=None):
    body = _b64(json.dumps({"uid": int(user_id), "exp": int(now or time.time()) + 43200},
                           separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return body + "." + signature


def verify_session(token, secret, *, now=None):
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_unb64(body))
        if int(data["exp"]) < int(now or time.time()):
            return None
        return int(data["uid"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error):
        return None


def csrf_for_session(token, secret):
    return _b64(hmac.new(secret, b"csrf:" + token.encode(), hashlib.sha256).digest())


def _json_error(message, status=400):
    return web.json_response({"error": message}, status=status)


class Dashboard:
    def __init__(self, bot, options):
        self.bot = bot
        self.options = options
        self.lock = asyncio.Lock()
        self.runner = None
        self.app = web.Application(client_max_size=9 * 1024 * 1024, middlewares=[self._security])
        self.app.add_routes([
            web.get("/", self.index), web.get("/dashboard.css", self.css),
            web.get("/dashboard.js", self.js), web.get("/login", self.login),
            web.get("/oauth/callback", self.callback), web.post("/logout", self.logout),
            web.get("/api/session", self.session_info),
            web.get("/api/overview", self.api_overview),
            web.get("/api/settings", self.get_settings),
            web.put("/api/settings", self.put_settings),
            web.post("/api/art/{key}", self.upload_art),
            web.get("/api/cases", self.api_cases),
            web.get("/api/tickets", self.api_tickets),
            web.get("/api/notes/{kind}/{subject_id}", self.get_notes),
            web.post("/api/notes/{kind}/{subject_id}", self.post_note),
            web.get("/api/config-history", self.config_history),
            web.patch("/api/tickets/{channel_id}", self.patch_ticket),
            web.get("/api/transcripts", self.api_transcripts),
            web.get("/api/transcripts/{channel_id}", self.download_transcript),
            web.get("/api/appeals", self.api_appeals),
            web.post("/api/appeals", self.create_appeal),
            web.post("/api/appeals/{appeal_id}/review", self.patch_appeal),
        ])

    @web.middleware
    async def _security(self, request, handler):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.path != "/logout":
            origin = request.headers.get("Origin", "")
            if origin and origin != self.options["url"]:
                return _json_error("Invalid request origin.", 403)
            token = request.cookies.get("pl_session", "")
            expected = csrf_for_session(token, self.options["session_secret"])
            if not token or not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), expected):
                return _json_error("Invalid session token.", 403)
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: https://cdn.discordapp.com; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def start(self):
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", self.options["port"])
        await site.start()
        print(f"[OK] Dashboard listening on 127.0.0.1:{self.options['port']} (proxy URL: {self.options['url']}).")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()

    async def index(self, _request):
        return web.FileResponse(STATIC / "index.html")

    async def css(self, _request):
        return web.FileResponse(STATIC / "dashboard.css")

    async def js(self, _request):
        return web.FileResponse(STATIC / "dashboard.js")

    async def login(self, _request):
        state = secrets.token_urlsafe(32)
        params = urlencode({
            "client_id": self.options["client_id"], "response_type": "code",
            "redirect_uri": self.options["url"] + "/oauth/callback",
            "scope": "identify", "state": state,
        })
        response = web.HTTPFound("https://discord.com/oauth2/authorize?" + params)
        response.set_cookie("pl_oauth_state", state, max_age=600, httponly=True,
                            secure=self.options["url"].startswith("https://"), samesite="Lax")
        return response

    async def callback(self, request):
        state = request.query.get("state", "")
        expected = request.cookies.get("pl_oauth_state", "")
        code = request.query.get("code", "")
        if not state or not code or not hmac.compare_digest(state, expected):
            return _json_error("Discord sign-in could not be verified.", 403)
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_API + "/oauth2/token", data={
                "client_id": str(self.options["client_id"]),
                "client_secret": self.options["client_secret"],
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": self.options["url"] + "/oauth/callback",
            }, timeout=aiohttp.ClientTimeout(total=15)) as token_response:
                if token_response.status != 200:
                    return _json_error("Discord sign-in failed.", 502)
                token_data = await token_response.json()
            async with session.get(DISCORD_API + "/users/@me", headers={
                "Authorization": "Bearer " + token_data["access_token"],
            }, timeout=aiohttp.ClientTimeout(total=15)) as user_response:
                if user_response.status != 200:
                    return _json_error("Discord user lookup failed.", 502)
                user_data = await user_response.json()
        token = sign_session(int(user_data["id"]), self.options["session_secret"])
        response = web.HTTPFound("/")
        response.set_cookie("pl_session", token, max_age=43200, httponly=True,
                            secure=self.options["url"].startswith("https://"), samesite="Lax")
        response.del_cookie("pl_oauth_state")
        return response

    async def logout(self, _request):
        response = web.HTTPFound("/")
        response.del_cookie("pl_session")
        return response

    async def _identity(self, request):
        token = request.cookies.get("pl_session", "")
        user_id = verify_session(token, self.options["session_secret"])
        if user_id is None:
            return None
        config = load_config()
        guild = self.bot.get_guild(config["guildId"])
        if guild is None:
            return {"user_id": user_id, "staff": False, "owner": False, "guild": None}
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member is None:
            return {"user_id": user_id, "staff": False, "owner": False, "guild": guild}
        perms = member.guild_permissions
        owner = member.id == guild.owner_id or perms.administrator or perms.manage_guild
        staff = owner or perms.manage_messages or perms.manage_channels or perms.moderate_members
        return {"user_id": user_id, "staff": staff, "owner": owner, "guild": guild}

    async def _require(self, request, *, owner=False, staff=False):
        identity = await self._identity(request)
        if identity is None:
            raise web.HTTPUnauthorized(text="Sign in with Discord first.")
        if owner and not identity["owner"] or staff and not identity["staff"]:
            raise web.HTTPForbidden(text="This action requires server staff permissions.")
        return identity

    async def session_info(self, request):
        identity = await self._identity(request)
        if identity is None:
            return web.json_response({"authenticated": False})
        return web.json_response({
            "authenticated": True, "userId": str(identity["user_id"]),
            "staff": identity["staff"], "owner": identity["owner"],
            "guildName": identity["guild"].name if identity["guild"] else "Project L",
            "csrf": csrf_for_session(request.cookies["pl_session"], self.options["session_secret"]),
        })

    async def api_overview(self, request):
        identity = await self._require(request, staff=True)
        guild = identity["guild"]
        data = overview(guild.id)
        data["members"] = guild.member_count or len(guild.members)
        data["in_voice"] = sum(len(channel.members) for channel in guild.voice_channels)
        data["dashboard_online"] = True
        return web.json_response(data)

    async def config_history(self, request):
        identity = await self._require(request, owner=True)
        return web.json_response({"history": list_config_history(identity["guild"].id)})

    async def get_notes(self, request):
        identity = await self._require(request, staff=True)
        try:
            kind = request.match_info["kind"]
            subject_id = int(request.match_info["subject_id"])
            if kind not in {"ticket", "case"}:
                raise ValueError("Unknown note type")
            if kind == "ticket" and not ticket_exists(identity["guild"].id, subject_id):
                return _json_error("Ticket not found.", 404)
            if kind == "case" and not case_exists(identity["guild"].id, subject_id):
                return _json_error("Case not found.", 404)
        except ValueError as exc:
            return _json_error(str(exc))
        return web.json_response({"notes": list_staff_notes(identity["guild"].id, kind, subject_id)})

    async def post_note(self, request):
        identity = await self._require(request, staff=True)
        check = await self.get_notes(request)
        if check.status != 200:
            return check
        try:
            body = str((await request.json()).get("body", "")).strip()
            if not 1 <= len(body) <= 2000:
                raise ValueError("Note must be 1–2000 characters.")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json_error(str(exc))
        note_id = add_staff_note(identity["guild"].id, request.match_info["kind"],
                                 int(request.match_info["subject_id"]), identity["user_id"], body)
        return web.json_response({"id": note_id}, status=201)

    async def get_settings(self, request):
        await self._require(request, owner=True)
        config = load_config()
        return web.json_response({
            "rulesText": (config.get("branding") or {}).get("rulesText") or DEFAULT_RULES,
            "art": (config.get("branding") or {}).get("art") or {},
            "moderation": config.get("moderation") or {},
            "tickets": config.get("ticketWorkspace") or {},
        })

    async def put_settings(self, request):
        await self._require(request, owner=True)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Settings must be an object.")
            rules = str(payload.get("rulesText", ""))
            if len(rules) > 4096:
                raise ValueError("Rules must be at most 4096 characters.")
            incoming = payload.get("moderation") or {}
            if not isinstance(incoming, dict):
                raise ValueError("Moderation settings must be an object.")
            moderation = {
                "antiSpamEnabled": bool(incoming.get("antiSpamEnabled", False)),
                "blockInviteLinks": bool(incoming.get("blockInviteLinks", False)),
                "spamLimit": max(2, min(30, int(incoming.get("spamLimit", 5)))),
                "spamWindowSeconds": max(2, min(120, int(incoming.get("spamWindowSeconds", 10)))),
                "raidEnabled": bool(incoming.get("raidEnabled", False)),
                "raidJoinLimit": max(3, min(100, int(incoming.get("raidJoinLimit", 8)))),
                "raidWindowSeconds": max(5, min(300, int(incoming.get("raidWindowSeconds", 30)))),
                "raidAction": str(incoming.get("raidAction", "alert")),
                "warningEscalationEnabled": bool(incoming.get("warningEscalationEnabled", False)),
                "warningEscalation": validate_escalation(incoming.get("warningEscalation", [])),
            }
            if moderation["raidAction"] not in {"alert", "timeout"}:
                raise ValueError("Raid action must be alert or timeout.")
            tickets = payload.get("tickets") or {}
            if not isinstance(tickets, dict):
                raise ValueError("Ticket settings must be an object.")
            priorities = tickets.get("priorities", ["low", "normal", "high", "urgent"])
            if not isinstance(priorities, list) or not 1 <= len(priorities) <= 10:
                raise ValueError("Choose 1–10 ticket priorities.")
            priorities = [str(item).strip()[:24] for item in priorities]
            if any(not item for item in priorities) or len(set(priorities)) != len(priorities):
                raise ValueError("Ticket priorities must be nonempty and unique.")
            workspace = {
                "priorities": priorities,
                "searchableTranscripts": bool(tickets.get("searchableTranscripts", False)),
                "responseTargetMinutes": max(0, min(10080, int(tickets.get("responseTargetMinutes", 0)))),
                "transcriptRetentionDays": max(0, min(365, int(tickets.get("transcriptRetentionDays", 0)))),
                "forms": validate_forms(tickets.get("forms") or DEFAULT_FORMS),
            }
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json_error(str(exc))
        async with self.lock:
            config = load_config()
            record_config_snapshot(config["guildId"], (await self._identity(request))["user_id"], {
                "branding": config.get("branding"), "moderation": config.get("moderation"),
                "ticketWorkspace": config.get("ticketWorkspace"),
            })
            config.setdefault("branding", {})["rulesText"] = rules
            config["moderation"] = moderation
            config["ticketWorkspace"] = workspace
            _write_json_atomic(CONFIG_PATH, config)
        from channel_headers import ensure_channel_headers
        await ensure_channel_headers(self.bot)
        return web.json_response({"saved": True})

    async def upload_art(self, request):
        await self._require(request, owner=True)
        key = request.match_info["key"]
        if key not in ART_KEYS:
            return _json_error("Unknown artwork slot.", 404)
        reader = await request.multipart()
        part = await reader.next()
        if part is None or part.name != "file":
            return _json_error("Choose an image file.")
        data = await part.read(decode=False)
        if not data or len(data) > 8 * 1024 * 1024:
            return _json_error("Artwork must be under 8 MiB.")
        try:
            image = Image.open(io.BytesIO(data))
            image.verify()
            image = Image.open(io.BytesIO(data))
            if image.width > 4096 or image.height > 4096:
                raise ValueError("Artwork dimensions must be at most 4096 pixels.")
            extension = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif"}[image.format]
        except (OSError, KeyError, ValueError) as exc:
            return _json_error(f"Invalid PNG, JPG, or GIF: {exc}")
        digest = hashlib.sha256(data).hexdigest()[:12]
        target_dir = BASE_DIR / "Data" / "art" / "custom"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{key}-{digest}{extension}"
        if not target.exists():
            target.write_bytes(data)
        async with self.lock:
            config = load_config()
            config.setdefault("branding", {}).setdefault("art", {})[key] = target.relative_to(BASE_DIR).as_posix()
            _write_json_atomic(CONFIG_PATH, config)
        from Commands.panels import ensure_automatic_panels
        from channel_headers import ensure_channel_headers
        await ensure_automatic_panels(self.bot)
        await ensure_channel_headers(self.bot)
        return web.json_response({"saved": True, "path": target.relative_to(BASE_DIR).as_posix()})

    async def api_cases(self, request):
        identity = await self._require(request, staff=True)
        member = request.query.get("member", "")
        if member and not member.isdecimal():
            return _json_error("Member ID must be numeric.")
        return web.json_response({"cases": list_cases(identity["guild"].id, member_id=int(member) if member else None)})

    async def api_tickets(self, request):
        identity = await self._require(request, staff=True)
        return web.json_response({"tickets": list_tickets(
            identity["guild"].id, status=request.query.get("status"),
            search=request.query.get("search", "")[:80],
        )})

    async def patch_ticket(self, request):
        identity = await self._require(request, staff=True)
        try:
            channel_id = int(request.match_info["channel_id"])
            data = await request.json()
            config = load_config()
            allowed = (config.get("ticketWorkspace") or {}).get("priorities") or ["low", "normal", "high", "urgent"]
            priority = data.get("priority")
            status = data.get("status")
            assignee = data.get("assigneeId")
            if priority is not None and priority not in allowed:
                raise ValueError("Unknown priority.")
            if status is not None and status not in {"open", "closed"}:
                raise ValueError("Unknown ticket status.")
            if assignee is not None:
                assignee = int(assignee)
                staff_member = identity["guild"].get_member(assignee)
                if not staff_member or not (staff_member.guild_permissions.manage_messages or staff_member.guild_permissions.administrator):
                    raise ValueError("Assignee must be a staff member in this server.")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json_error(str(exc))
        channel = identity["guild"].get_channel(channel_id)
        if not ticket_exists(identity["guild"].id, channel_id):
            return _json_error("Ticket record not found.", 404)
        if not isinstance(channel, discord.TextChannel):
            return _json_error("Ticket channel not found.", 404)
        from Commands.on_interaction import ticket_owner_id
        owner_id = ticket_owner_id(channel)
        if owner_id is None:
            return _json_error("This is not a Project L ticket.", 404)
        if status:
            owner = identity["guild"].get_member(owner_id) or discord.Object(id=owner_id)
            try:
                await channel.set_permissions(owner, view_channel=True,
                                              send_messages=status == "open",
                                              read_message_history=True,
                                              reason=f"Ticket {status} in dashboard")
            except (discord.Forbidden, discord.HTTPException):
                return _json_error("Discord denied the ticket status change.", 403)
        if not update_ticket(channel_id, identity["guild"].id, status=status,
                             priority=priority, assignee_id=assignee):
            return _json_error("Ticket record not found.", 404)
        return web.json_response({"saved": True})

    async def api_appeals(self, request):
        identity = await self._require(request, staff=True)
        return web.json_response({"appeals": list_appeals(identity["guild"].id, status=request.query.get("status"))})

    async def api_transcripts(self, request):
        identity = await self._require(request, staff=True)
        term = request.query.get("q", "")[:100]
        return web.json_response({"results": search_transcripts(identity["guild"].id, term)})

    async def download_transcript(self, request):
        identity = await self._require(request, staff=True)
        try:
            channel_id = int(request.match_info["channel_id"])
        except ValueError:
            return _json_error("Invalid ticket ID.")
        content = get_transcript(identity["guild"].id, channel_id)
        if content is None:
            return _json_error("Transcript not found.", 404)
        return web.Response(text=content, content_type="text/plain", headers={
            "Content-Disposition": f'attachment; filename="ticket-{channel_id}.txt"',
        })

    async def create_appeal(self, request):
        identity = await self._require(request)
        try:
            data = await request.json()
            message = str(data.get("message", "")).strip()
            if not 20 <= len(message) <= 2000:
                raise ValueError("Appeal must be 20–2000 characters.")
            case_id = int(data["caseId"]) if data.get("caseId") else None
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json_error(str(exc))
        guild_id = load_config()["guildId"]
        try:
            appeal_id = submit_appeal(guild_id, identity["user_id"], message, case_id)
        except ValueError as exc:
            return _json_error(str(exc))
        if appeal_id is None:
            return _json_error("You already have an open appeal.", 409)
        return web.json_response({"created": True, "id": appeal_id}, status=201)

    async def patch_appeal(self, request):
        identity = await self._require(request, staff=True)
        try:
            data = await request.json()
            appeal_id = int(request.match_info["appeal_id"])
            status = str(data.get("status", ""))
            response = str(data.get("response", "")).strip()
            if not 1 <= len(response) <= 2000:
                raise ValueError("Write a response of 1–2000 characters.")
            changed = review_appeal(identity["guild"].id, appeal_id,
                                    identity["user_id"], status, response)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json_error(str(exc))
        if not changed:
            return _json_error("Appeal is unavailable or already reviewed.", 404)
        return web.json_response({"saved": True})


async def start_dashboard(bot):
    options = dashboard_options(load_config())
    if not options:
        print("[i] Browser dashboard is off. Set its URL and OAuth secrets to enable it.")
        return None
    dashboard = Dashboard(bot, options)
    await dashboard.start()
    return dashboard

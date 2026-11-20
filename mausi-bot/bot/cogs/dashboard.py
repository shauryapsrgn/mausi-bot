"""Web dashboard: see and change every Mausi ji setting from a browser.

Runs inside the bot (same process), so every change is live immediately.
Turn it on by setting DASHBOARD_PASSWORD in .env, then open
http://localhost:8080 (or your host's URL) and log in.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import os
import secrets
from typing import Iterable, Optional
from urllib.parse import quote

import discord
from aiohttp import web
from discord.ext import commands

import json

from bot.actions import (PLANNED_CHANNELS, EmbedError, build_embed, embed_to_data, ensure_channels, load_presets,
                         parse_message_link, post_preset, sort_roles)
from bot.util import COMMAND_ACCESS_DEFAULTS, COMMAND_ACCESS_LABELS, TIER_LABEL, access_tier

log = logging.getLogger("mausi.dashboard")
COOKIE = "mausi_session"

CSS = """
:root{--bg:#1d0f24;--panel:#2a1634;--line:#4a2c57;--ink:#f6e9f2;--muted:#c3a8bd;--marigold:#ffb01f;--rani:#ff3d8b;
--good:#4ade80;--bad:#f87171;--display:"Rozha One",Georgia,serif;--body:"Mukta","Segoe UI",system-ui,sans-serif;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;color-scheme:dark}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--ink);font:16px/1.55 var(--body)}
a{color:var(--marigold)}.shell{display:grid;grid-template-columns:220px minmax(0,1fr);min-height:100vh}
nav{background:var(--panel);border-right:1px solid var(--line);padding:22px 14px;display:flex;flex-direction:column;gap:4px}
nav .brand{font:400 26px/1.1 var(--display);color:var(--rani);margin:0 8px 14px}nav .brand small{display:block;font:500 12px var(--mono);color:var(--muted)}
nav a{color:var(--muted);text-decoration:none;padding:8px 10px;border-radius:8px}nav a:hover{background:#3a2147;color:var(--ink)}
nav a.on{background:var(--rani);color:#fff}main{padding:28px 30px 60px;max-width:980px;display:grid;gap:18px;align-content:start}
h1{font:400 34px/1.1 var(--display);margin:0;color:var(--marigold)}h2{font:600 18px var(--body);margin:0 0 4px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;display:grid;gap:12px}
.muted{color:var(--muted);font-size:14px}label{display:grid;gap:4px;font-weight:500}
input[type=text],input[type=password],input[type=number],select,textarea{font:15px var(--body);color:var(--ink);background:var(--bg);
border:1px solid var(--line);border-radius:8px;padding:8px 10px;width:100%}textarea{min-height:120px;font-family:var(--body)}
select[multiple]{min-height:150px}.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.check{display:flex;gap:8px;align-items:center;font-weight:500}.check input{accent-color:var(--rani);width:18px;height:18px}
button{font:600 15px var(--body);border:0;border-radius:8px;padding:9px 16px;cursor:pointer;background:var(--rani);color:#fff;justify-self:start}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--ink)}button.danger{background:#7f1d1d}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--marigold);outline-offset:2px}
table{border-collapse:collapse;width:100%;font-size:15px}td,th{border-bottom:1px solid var(--line);padding:8px 6px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:500;font-size:13px;text-transform:uppercase;letter-spacing:.04em}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.tile{background:var(--panel);border:1px solid var(--line);
border-radius:12px;padding:14px}.tile b{display:block;font:400 30px var(--display);color:var(--marigold)}.pill{display:inline-block;font:600 12px var(--mono);
padding:3px 8px;border-radius:99px;border:1px solid var(--line)}.pill.on{color:var(--good);border-color:var(--good)}.pill.off{color:var(--muted)}
.flash{background:#3a2147;border-left:4px solid var(--marigold);padding:10px 14px;border-radius:8px}.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;vertical-align:middle}
code{font:13px var(--mono);color:var(--marigold)}.inline{display:flex;gap:8px;flex-wrap:wrap;align-items:end}.inline>*{flex:1 1 160px}.inline button{flex:0 0 auto}
@media(max-width:720px){.shell{grid-template-columns:1fr}nav{flex-direction:row;flex-wrap:wrap}main{padding:18px 14px}}
"""

PAGES = [("/", "Overview"), ("/welcome", "Welcome"), ("/tiers", "Mod tiers"), ("/access", "Command access"),
         ("/embed", "Embed maker"), ("/autoreact", "Auto-react"),
         ("/starboard", "Starboard"), ("/voice", "Voice rooms"), ("/panels", "Role panels"),
         ("/roles", "Roles & channels"), ("/warnings", "Warnings")]

e = html.escape


class Dashboard(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.password = os.getenv("DASHBOARD_PASSWORD", "")
        self.host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
        self.port = int(os.getenv("DASHBOARD_PORT") or os.getenv("PORT") or 8080)
        self.secret = secrets.token_bytes(32)
        self.sessions: set[str] = set()
        self.runner: Optional[web.AppRunner] = None

    # ------------------------------------------------------------ lifecycle
    async def cog_load(self) -> None:
        if not self.password:
            log.warning("DASHBOARD_PASSWORD not set: dashboard is off.")
            return
        app = web.Application(middlewares=[self.auth_middleware])
        app.add_routes([
            web.get("/login", self.login_page), web.post("/login", self.login_post), web.post("/logout", self.logout),
            web.get("/", self.overview),
            web.get("/welcome", self.welcome_page), web.post("/welcome", self.welcome_post),
            web.get("/tiers", self.tiers_page), web.post("/tiers", self.tiers_post),
            web.get("/access", self.access_page), web.post("/access", self.access_post),
            web.get("/embed", self.embed_page), web.post("/embed", self.embed_post),
            web.get("/autoreact", self.autoreact_page), web.post("/autoreact", self.autoreact_post),
            web.get("/starboard", self.starboard_page), web.post("/starboard", self.starboard_post),
            web.get("/voice", self.voice_page), web.post("/voice", self.voice_post),
            web.get("/panels", self.panels_page), web.post("/panels", self.panels_post),
            web.get("/roles", self.roles_page), web.post("/roles", self.roles_post),
            web.get("/warnings", self.warnings_page), web.post("/warnings", self.warnings_post),
        ])
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, self.host, self.port).start()
        log.info("Dashboard running on http://%s:%s", self.host, self.port)

    async def cog_unload(self) -> None:
        if self.runner:
            await self.runner.cleanup()

    # ------------------------------------------------------------ auth
    def _csrf(self, token: str) -> str:
        return hmac.new(self.secret, token.encode(), hashlib.sha256).hexdigest()[:32]

    @web.middleware
    async def auth_middleware(self, request: web.Request, handler):
        if request.path == "/login":
            return await handler(request)
        token = request.cookies.get(COOKIE)
        if not token or token not in self.sessions:
            raise web.HTTPFound("/login")
        request["session"] = token
        if request.method == "POST":
            data = await request.post()
            request["form"] = data
            if not hmac.compare_digest(data.get("csrf", ""), self._csrf(token)):
                raise web.HTTPForbidden(text="Form expired. Go back and reload the page.")
        return await handler(request)

    async def login_page(self, request: web.Request, error: str = "") -> web.Response:
        body = f"""<div class="card" style="max-width:380px;margin:12vh auto">
        <h1>Mausi ji</h1><p class="muted">Control room for your server. Enter the dashboard password from your .env file.</p>
        {f'<div class="flash">{e(error)}</div>' if error else ''}
        <form method="post" action="/login" class="card" style="padding:0;border:0;background:none">
        <label for="pw">Password<input id="pw" type="password" name="password" autofocus required></label>
        <button type="submit">Andar aane do</button></form></div>"""
        return web.Response(text=self._doc("Login", body), content_type="text/html")

    async def login_post(self, request: web.Request) -> web.Response:
        data = await request.post()
        if hmac.compare_digest(str(data.get("password", "")).encode(), self.password.encode()):
            token = secrets.token_urlsafe(32)
            self.sessions.add(token)
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, token, httponly=True, samesite="Lax", max_age=60 * 60 * 24 * 7)
            raise resp
        return await self.login_page(request, "Galat password, behen.")

    async def logout(self, request: web.Request) -> web.Response:
        self.sessions.discard(request["session"])
        resp = web.HTTPFound("/login")
        resp.del_cookie(COOKIE)
        raise resp

    # ------------------------------------------------------------ helpers
    def guild(self) -> Optional[discord.Guild]:
        gid = getattr(self.bot, "dev_guild_id", None)
        return self.bot.get_guild(gid) if gid else (self.bot.guilds[0] if self.bot.guilds else None)

    def _doc(self, title: str, body: str) -> str:
        return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · Mausi ji</title><link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rozha+One&family=Mukta:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>{body}</body></html>"""

    def page(self, request: web.Request, title: str, content: str) -> web.Response:
        guild = self.guild()
        links = "".join(f'<a href="{p}" class="{"on" if request.path == p else ""}">{e(n)}</a>' for p, n in PAGES)
        msg = request.query.get("msg")
        flash = f'<div class="flash">{e(msg)}</div>' if msg else ""
        csrf = self._csrf(request["session"])
        nav = f"""<nav><div class="brand">Mausi ji<small>{e(guild.name if guild else "no server")}</small></div>{links}
        <form method="post" action="/logout" style="margin-top:auto"><input type="hidden" name="csrf" value="{csrf}">
        <button class="ghost" type="submit">Log out</button></form></nav>"""
        body = f'<div class="shell">{nav}<main><h1>{e(title)}</h1>{flash}{content}</main></div>'
        return web.Response(text=self._doc(title, body.replace("{{CSRF}}", csrf)), content_type="text/html")

    @staticmethod
    def back(path: str, msg: str) -> web.HTTPFound:
        return web.HTTPFound(f"{path}?msg={quote(msg)}")

    def conf(self) -> dict:
        return self.bot.store.guild(self.guild().id)

    def no_guild(self, request) -> web.Response:
        return self.page(request, "Waiting for Discord", '<div class="card">Mausi ji is not in any server yet, or is still connecting. Refresh in a few seconds.</div>')

    @staticmethod
    def hidden() -> str:
        return '<input type="hidden" name="csrf" value="{{CSRF}}">'

    def channel_options(self, channels: Iterable, selected: Optional[int], blank: str = "— none —") -> str:
        opts = [f'<option value="">{e(blank)}</option>']
        for c in channels:
            sel = " selected" if selected == c.id else ""
            prefix = "#" if isinstance(c, discord.TextChannel) else ("🔊 " if isinstance(c, discord.VoiceChannel) else "")
            opts.append(f'<option value="{c.id}"{sel}>{e(prefix + c.name)}</option>')
        return "".join(opts)

    def role_options(self, selected: Iterable[int], below_bot: bool = False) -> str:
        guild = self.guild()
        sel = set(selected)
        out = []
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if r.is_default() or r.managed or (below_bot and r >= guild.me.top_role):
                continue
            out.append(f'<option value="{r.id}"{" selected" if r.id in sel else ""}>{e(r.name)}</option>')
        return "".join(out)

    @staticmethod
    def ids(form, key: str) -> list[int]:
        return [int(v) for v in form.getall(key, []) if str(v).isdigit()]

    @staticmethod
    def one_id(form, key: str) -> Optional[int]:
        v = form.get(key, "")
        return int(v) if str(v).isdigit() else None

    @staticmethod
    def pill(on: bool) -> str:
        return '<span class="pill on">ON</span>' if on else '<span class="pill off">OFF</span>'

    # ------------------------------------------------------------ overview
    async def overview(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        c = self.conf()
        me = guild.me
        missing = [n for n, ok in (("Manage Roles", me.guild_permissions.manage_roles),
                                   ("Manage Channels", me.guild_permissions.manage_channels),
                                   ("Time out members", me.guild_permissions.moderate_members),
                                   ("Kick", me.guild_permissions.kick_members), ("Ban", me.guild_permissions.ban_members),
                                   ("Manage Messages", me.guild_permissions.manage_messages),
                                   ("Move Members", me.guild_permissions.move_members)) if not ok]
        warn_total = sum(len(v) for v in c["warnings"].values())
        tiles = f"""<div class="tiles">
        <div class="tile"><b>{guild.member_count}</b>members</div>
        <div class="tile"><b>{len(guild.roles) - 1}</b>roles</div>
        <div class="tile"><b>{len(c['reaction_roles'])}</b>role panels</div>
        <div class="tile"><b>{len(c['autoreact']['triggers'])}</b>auto-react words</div>
        <div class="tile"><b>{warn_total}</b>warnings on record</div></div>"""
        rows = "".join(f"<tr><td>{e(n)}</td><td>{self.pill(on)}</td></tr>" for n, on in (
            ("Welcome post", c["welcome"]["enabled"] and bool(c["welcome"]["channel_id"])),
            ("Welcome DM", c["welcome"]["dm_enabled"]), ("Goodbye post", c["welcome"]["goodbye_enabled"]),
            ("Auto-reactions", c["autoreact"]["enabled"]),
            ("Starboard", c["starboard"]["enabled"] and bool(c["starboard"]["channel_id"])),
            ("Join-to-create voice", c["voicerooms"]["enabled"] and bool(c["voicerooms"]["lobby_channel_id"])),
            ("Mod log", bool(c["log_channel_id"]))))
        warn = (f'<div class="flash">Mausi ji is missing these permissions: {e(", ".join(missing))}</div>' if missing else "")
        pos = f'<p class="muted">My role: <b>{e(me.top_role.name)}</b>. I can only give out, sort or moderate roles below it.</p>'
        return self.page(request, guild.name, f"""{warn}{tiles}<div class="card"><h2>Features</h2>
        <table><tbody>{rows}</tbody></table>{pos}</div>""")

    # ------------------------------------------------------------ welcome
    async def welcome_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        w = self.conf()["welcome"]
        chk = lambda k: " checked" if w[k] else ""  # noqa: E731
        content = f"""<form method="post" class="card">{self.hidden()}
        <div class="row"><label for="ch">Welcome channel<select id="ch" name="channel_id">{self.channel_options(guild.text_channels, w['channel_id'])}</select></label>
        <label for="ar">Auto-roles for new members<select id="ar" name="autorole_ids" multiple>{self.role_options(w['autorole_ids'], below_bot=True)}</select></label></div>
        <label class="check"><input type="checkbox" name="enabled" value="1"{chk('enabled')}> Post a welcome message</label>
        <label for="msg">Welcome message<textarea id="msg" name="message">{e(w['message'])}</textarea></label>
        <p class="muted">Placeholders: <code>{{user}}</code> ping, <code>{{name}}</code> name, <code>{{server}}</code>, <code>{{count}}</code> member number, <code>{{#channel-name}}</code> clickable channel.</p>
        <label class="check"><input type="checkbox" name="dm_enabled" value="1"{chk('dm_enabled')}> Also DM new members</label>
        <label for="dm">DM message<textarea id="dm" name="dm_message">{e(w['dm_message'])}</textarea></label>
        <label class="check"><input type="checkbox" name="goodbye_enabled" value="1"{chk('goodbye_enabled')}> Post when someone leaves</label>
        <label for="gb">Goodbye message<textarea id="gb" name="goodbye_message" style="min-height:70px">{e(w['goodbye_message'])}</textarea></label>
        <button type="submit">Save welcome settings</button></form>"""
        return self.page(request, "Welcome", content)

    async def welcome_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        w = self.conf()["welcome"]
        w.update({"channel_id": self.one_id(f, "channel_id"), "autorole_ids": self.ids(f, "autorole_ids"),
                  "enabled": f.get("enabled") == "1", "dm_enabled": f.get("dm_enabled") == "1",
                  "goodbye_enabled": f.get("goodbye_enabled") == "1",
                  "message": str(f.get("message", ""))[:1500] or w["message"],
                  "dm_message": str(f.get("dm_message", ""))[:1500] or w["dm_message"],
                  "goodbye_message": str(f.get("goodbye_message", ""))[:500] or w["goodbye_message"]})
        await self.bot.store.save()
        raise self.back("/welcome", "Welcome settings saved.")

    # ------------------------------------------------------------ tiers
    async def tiers_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        c = self.conf()
        content = f"""<form method="post" class="card">{self.hidden()}
        <p class="muted">Hold Ctrl (or Cmd) to pick several roles. Anyone with Discord's Administrator permission always counts as admin.</p>
        <div class="row">
        <label for="h">Helpers: warn, timeout up to 1h<select id="h" name="helper" multiple>{self.role_options(c['tiers']['helper'])}</select></label>
        <label for="m">Mods: + kick, purge, lock, long timeouts<select id="m" name="mod" multiple>{self.role_options(c['tiers']['mod'])}</select></label>
        <label for="a">Admins: + ban, all settings<select id="a" name="admin" multiple>{self.role_options(c['tiers']['admin'])}</select></label></div>
        <label for="lg">Mod log channel<select id="lg" name="log_channel_id">{self.channel_options(guild.text_channels, c['log_channel_id'])}</select></label>
        <button type="submit">Save tiers</button></form>"""
        return self.page(request, "Mod tiers", content)

    async def tiers_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        c = self.conf()
        c["tiers"] = {t: self.ids(f, t) for t in ("helper", "mod", "admin")}
        c["log_channel_id"] = self.one_id(f, "log_channel_id")
        await self.bot.store.save()
        raise self.back("/tiers", "Tiers saved.")

    # ------------------------------------------------------------ command access
    async def access_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        c = self.conf()
        tier_roles = {t: ", ".join(r.name for r in (guild.get_role(i) for i in c["tiers"][t]) if r) or "no roles set"
                      for t in ("helper", "mod", "admin")}
        rows = []
        for cmd, label in COMMAND_ACCESS_LABELS.items():
            current = access_tier(c, cmd)
            opts = "".join(f'<option value="{t}"{" selected" if t == current else ""}>{e(TIER_LABEL[t])} and up</option>'
                           for t in ("helper", "mod", "admin"))
            default = " (default)" if current == COMMAND_ACCESS_DEFAULTS[cmd] else ""
            rows.append(f'<tr><td><code>{e(label)}</code><span class="muted">{default}</span></td>'
                        f'<td><select name="{cmd}" aria-label="Who can use {e(label)}">{opts}</select></td></tr>')
        content = f"""<div class="card"><h2>Who holds each tier</h2><table><tbody>
        <tr><td>Helpers</td><td>{e(tier_roles['helper'])}</td></tr><tr><td>Mods</td><td>{e(tier_roles['mod'])}</td></tr>
        <tr><td>Admins</td><td>{e(tier_roles['admin'])} + anyone with Administrator + you</td></tr></tbody></table>
        <p class="muted">Change these on the <a href="/tiers">Mod tiers</a> page. Everyone else can only use <code>/help</code> and their own <code>/kamra</code>.</p></div>
        <form method="post" class="card">{self.hidden()}<h2>Who can use what</h2>
        <table><thead><tr><th>Command</th><th>Allowed for</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
        <p class="muted">Discord also hides these commands from anyone without the matching Discord permission (Time out, Kick, Ban or Manage Messages). If you open a command to a lower tier here, give that tier's role the Discord permission too, or allow the command in Server Settings → Integrations → Mausi ji.</p>
        <div class="inline"><button type="submit">Save access</button></div></form>"""
        return self.page(request, "Command access", content)

    async def access_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        c = self.conf()
        c["command_access"] = {cmd: f.get(cmd) for cmd in COMMAND_ACCESS_DEFAULTS
                               if f.get(cmd) in ("helper", "mod", "admin") and f.get(cmd) != COMMAND_ACCESS_DEFAULTS[cmd]}
        await self.bot.store.save()
        raise self.back("/access", "Command access saved. It applies straight away.")

    # ------------------------------------------------------------ embed maker
    def _embed_form_data(self, f) -> dict:
        fields = []
        for i in range(6):
            fields.append({"name": str(f.get(f"f{i}_name", "")), "value": str(f.get(f"f{i}_value", "")),
                           "inline": f.get(f"f{i}_inline") == "1"})
        return {k: str(f.get(k, "")) for k in ("title", "url", "description", "color", "author", "author_icon",
                                               "footer", "image", "thumbnail")} | {
            "timestamp": f.get("timestamp") == "1", "fields": fields}

    async def embed_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        c = self.conf()
        tname = request.query.get("template", "")
        d = c["embed_templates"].get(tname) or {"color": "#ff3d8b", "fields": []}
        fields = (d.get("fields") or []) + [{}] * 6
        frows = "".join(f"""<div class="inline"><label for="f{i}n">Field {i + 1} name<input id="f{i}n" type="text" name="f{i}_name" value="{e(fields[i].get('name', ''))}" data-p></label>
        <label for="f{i}v">Value<input id="f{i}v" type="text" name="f{i}_value" value="{e(fields[i].get('value', ''))}" data-p></label>
        <label class="check" style="flex:0 0 auto"><input type="checkbox" name="f{i}_inline" value="1"{" checked" if fields[i].get('inline') else ""} data-p> side by side</label></div>""" for i in range(6))
        topts = "".join(f'<option value="{e(n)}"{" selected" if n == tname else ""}>{e(n)}</option>' for n in c["embed_templates"])
        v = lambda k: e(str(d.get(k, "") or ""))  # noqa: E731
        content = f"""<form method="get" class="card inline"><label for="tp">Load a saved template<select id="tp" name="template"><option value="">— new embed —</option>{topts}</select></label>
        <button class="ghost" type="submit">Load</button></form>
        <div class="row" style="grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);align-items:start">
        <form method="post" class="card" id="ef">{self.hidden()}
        <div class="row"><label for="et">Title<input id="et" type="text" name="title" maxlength="256" value="{v('title')}" data-p></label>
        <label for="ec">Colour<input id="ec" type="color" name="color" value="{v('color') or '#ff3d8b'}" data-p style="height:40px;padding:2px"></label></div>
        <label for="ed">Text (Discord markdown works: **bold**, *italic*, &gt; quote, links)<textarea id="ed" name="description" maxlength="4096" data-p>{v('description')}</textarea></label>
        <div class="row"><label for="ea">Author line<input id="ea" type="text" name="author" value="{v('author')}" data-p></label>
        <label for="ef2">Footer<input id="ef2" type="text" name="footer" value="{v('footer')}" data-p></label></div>
        <div class="row"><label for="ei">Big image link<input id="ei" type="text" name="image" placeholder="https://…" value="{v('image')}" data-p></label>
        <label for="eth">Small corner image link<input id="eth" type="text" name="thumbnail" placeholder="https://…" value="{v('thumbnail')}" data-p></label></div>
        <label for="eu">Title links to (optional)<input id="eu" type="text" name="url" placeholder="https://…" value="{v('url')}"></label>
        {frows}
        <label class="check"><input type="checkbox" name="timestamp" value="1"{" checked" if d.get('timestamp') else ""} data-p> Show the time it was posted</label>
        <div class="row"><label for="ech">Post in<select id="ech" name="channel_id">{self.channel_options(guild.text_channels, None, "— pick a channel —")}</select></label>
        <label for="eedit">…or edit a message Mausi ji already posted (paste its link)<input id="eedit" type="text" name="edit_link" placeholder="https://discord.com/channels/…"></label></div>
        <div class="inline"><button type="submit" name="action" value="post">Post / update in Discord</button>
        <label for="tn">Template name<input id="tn" type="text" name="template_name" value="{e(tname)}" placeholder="e.g. rules"></label>
        <button class="ghost" type="submit" name="action" value="save">Save as template</button>
        <button class="ghost danger" type="submit" name="action" value="delete">Delete template</button></div></form>
        <div class="card" style="position:sticky;top:16px"><h2>Preview</h2><div id="pv"></div>
        <p class="muted">Roughly how it'll look in Discord. Markdown shows as plain text here.</p></div></div>
        <script>
        (function(){{
          const f=document.getElementById('ef'), pv=document.getElementById('pv');
          const esc=s=>s.replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
          function draw(){{
            const g=n=>(f.elements[n]&&f.elements[n].value||'').trim();
            let h='<div style="border-left:4px solid '+esc(g('color')||'#ff3d8b')+';background:#2b2d31;border-radius:6px;padding:12px 14px;display:grid;gap:6px;font-size:15px;color:#dbdee1">';
            const th=g('thumbnail'); if(th.startsWith('http')) h+='<img src="'+esc(th)+'" alt="" style="float:right;max-width:80px;border-radius:4px">';
            if(g('author')) h+='<div style="font-weight:600;font-size:13px">'+esc(g('author'))+'</div>';
            if(g('title')) h+='<div style="font-weight:700;color:#fff">'+esc(g('title'))+'</div>';
            if(g('description')) h+='<div style="white-space:pre-wrap">'+esc(g('description'))+'</div>';
            let fl='<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px">';
            for(let i=0;i<6;i++){{ const n=g('f'+i+'_name'), v=g('f'+i+'_value'); if(!n||!v) continue;
              const inl=f.elements['f'+i+'_inline'].checked; fl+='<div style="grid-column:'+(inl?'auto':'1 / -1')+'"><div style="font-weight:600;color:#fff">'+esc(n)+'</div><div>'+esc(v)+'</div></div>'; }}
            h+=fl+'</div>';
            const im=g('image'); if(im.startsWith('http')) h+='<img src="'+esc(im)+'" alt="" style="max-width:100%;border-radius:4px">';
            const ft=g('footer'), ts=f.elements['timestamp'].checked; if(ft||ts) h+='<div style="font-size:12px;color:#b5bac1">'+esc(ft)+(ft&&ts?' • ':'')+(ts?'Today':'')+'</div>';
            pv.innerHTML=h+'</div>';
          }}
          f.addEventListener('input',draw); f.addEventListener('change',draw); draw();
        }})();
        </script>"""
        return self.page(request, "Embed maker", content)

    async def embed_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        guild = self.guild()
        c = self.conf()
        action = f.get("action")
        data = self._embed_form_data(f)
        name = str(f.get("template_name", "")).strip()[:60]
        if action == "save":
            if not name:
                raise self.back("/embed", "Give the template a name first.")
            c["embed_templates"][name] = data
            await self.bot.store.save()
            raise web.HTTPFound(f"/embed?template={quote(name)}&msg={quote('Template saved.')}")
        if action == "delete":
            c["embed_templates"].pop(name, None)
            await self.bot.store.save()
            raise self.back("/embed", "Template deleted.")
        try:
            embed = build_embed(data)
        except EmbedError as exc:
            raise self.back("/embed", f"Not posted: {exc}")
        link = str(f.get("edit_link", "")).strip()
        try:
            if link:
                ids = parse_message_link(link)
                channel = guild.get_channel(ids[0]) if ids else None
                msg = await channel.fetch_message(ids[1]) if channel else None
                if msg is None or msg.author.id != self.bot.user.id:
                    raise self.back("/embed", "That link isn't a message Mausi ji posted, so I can't edit it.")
                await msg.edit(embed=embed)
                raise self.back("/embed", "Embed updated in Discord.")
            channel = guild.get_channel(self.one_id(f, "channel_id") or 0)
            if not isinstance(channel, discord.TextChannel):
                raise self.back("/embed", "Pick a channel to post in.")
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            raise self.back("/embed", f"Discord said no ({exc.status}). Check I can send messages in that channel.")
        raise self.back("/embed", f"Posted in #{channel.name}.")

    # ------------------------------------------------------------ auto-react
    async def autoreact_page(self, request: web.Request) -> web.Response:
        if not self.guild():
            return self.no_guild(request)
        a = self.conf()["autoreact"]
        rows = "".join(f"""<tr><td><code>{e(t['word'])}</code></td><td>{e(' '.join(t['emojis']))}</td><td>
        <form method="post">{self.hidden()}<input type="hidden" name="action" value="remove"><input type="hidden" name="word" value="{e(t['word'])}">
        <button class="ghost" type="submit">Remove</button></form></td></tr>""" for t in a["triggers"])
        content = f"""<form method="post" class="card">{self.hidden()}<input type="hidden" name="action" value="settings">
        <label class="check"><input type="checkbox" name="enabled" value="1"{" checked" if a['enabled'] else ""}> Auto-reactions on</label>
        <label for="cd" style="max-width:260px">Cooldown per channel (seconds)<input id="cd" type="number" min="0" max="3600" name="cooldown" value="{a['cooldown_seconds']}"></label>
        <button type="submit">Save</button></form>
        <form method="post" class="card">{self.hidden()}<input type="hidden" name="action" value="add"><h2>Add a trigger</h2>
        <div class="inline"><label for="w">Word or phrase<input id="w" type="text" name="word" placeholder="e.g. tea" required></label>
        <label for="em">Emoji (up to 3, spaces between)<input id="em" type="text" name="emojis" placeholder="🫖 👀" required></label>
        <button type="submit">Add</button></div><p class="muted">Whole words only, so "ate" won't fire on "late".</p></form>
        <div class="card"><h2>Triggers</h2><table><thead><tr><th>Word</th><th>Reacts with</th><th></th></tr></thead><tbody>{rows or '<tr><td colspan=3 class="muted">None yet.</td></tr>'}</tbody></table></div>"""
        return self.page(request, "Auto-react", content)

    async def autoreact_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        a = self.conf()["autoreact"]
        action = f.get("action")
        word = str(f.get("word", "")).strip().lower()
        if action == "settings":
            a["enabled"] = f.get("enabled") == "1"
            a["cooldown_seconds"] = max(0, min(3600, int(f.get("cooldown") or 0)))
            msg = "Saved."
        elif action == "add" and word:
            emojis = str(f.get("emojis", "")).split()[:3]
            if not emojis:
                raise self.back("/autoreact", "Add at least one emoji.")
            a["triggers"] = [t for t in a["triggers"] if t["word"].lower() != word] + [{"word": word, "emojis": emojis}]
            msg = f"Added '{word}'."
        elif action == "remove":
            a["triggers"] = [t for t in a["triggers"] if t["word"].lower() != word]
            msg = f"Removed '{word}'."
        else:
            msg = "Nothing changed."
        await self.bot.store.save()
        raise self.back("/autoreact", msg)

    # ------------------------------------------------------------ starboard
    async def starboard_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        s = self.conf()["starboard"]
        content = f"""<form method="post" class="card">{self.hidden()}
        <label class="check"><input type="checkbox" name="enabled" value="1"{" checked" if s['enabled'] else ""}> Starboard on</label>
        <div class="row"><label for="sc">Starboard channel<select id="sc" name="channel_id">{self.channel_options(guild.text_channels, s['channel_id'])}</select></label>
        <label for="se">Emoji<input id="se" type="text" name="emoji" value="{e(s['emoji'])}"></label>
        <label for="st">Reactions needed<input id="st" type="number" min="1" max="50" name="threshold" value="{s['threshold']}"></label></div>
        <p class="muted">{len(s['posted'])} messages have made it to the starboard so far.</p>
        <button type="submit">Save starboard</button></form>"""
        return self.page(request, "Starboard", content)

    async def starboard_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        s = self.conf()["starboard"]
        s.update({"enabled": f.get("enabled") == "1", "channel_id": self.one_id(f, "channel_id"),
                  "emoji": str(f.get("emoji") or "⭐").strip()[:40],
                  "threshold": max(1, min(50, int(f.get("threshold") or 3)))})
        await self.bot.store.save()
        raise self.back("/starboard", "Starboard saved.")

    # ------------------------------------------------------------ voice rooms
    async def voice_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        v = self.conf()["voicerooms"]
        content = f"""<form method="post" class="card">{self.hidden()}
        <label class="check"><input type="checkbox" name="enabled" value="1"{" checked" if v['enabled'] else ""}> Join-to-create on</label>
        <div class="row"><label for="lb">Lobby voice channel<select id="lb" name="lobby_channel_id">{self.channel_options(guild.voice_channels, v['lobby_channel_id'])}</select></label>
        <label for="ct">Make rooms in category<select id="ct" name="category_id">{self.channel_options(guild.categories, v['category_id'], "same as lobby")}</select></label>
        <label for="nt">Room name<input id="nt" type="text" name="name_template" value="{e(v['name_template'])}"></label></div>
        <p class="muted"><code>{{name}}</code> becomes the person's name. Room owners can use <code>/kamra naam</code>, <code>/kamra limit</code> and <code>/kamra lock</code>. {len(v['rooms'])} rooms open right now.</p>
        <button type="submit">Save voice rooms</button></form>"""
        return self.page(request, "Voice rooms", content)

    async def voice_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        v = self.conf()["voicerooms"]
        v.update({"enabled": f.get("enabled") == "1", "lobby_channel_id": self.one_id(f, "lobby_channel_id"),
                  "category_id": self.one_id(f, "category_id"),
                  "name_template": str(f.get("name_template") or "{name} ka kamra")[:80]})
        await self.bot.store.save()
        raise self.back("/voice", "Voice rooms saved.")

    # ------------------------------------------------------------ role panels
    async def panels_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        c = self.conf()
        presets = load_presets()
        popts = "".join(f'<option value="{e(k)}">{e(p["title"])} ({len(p["roles"])} roles{", only one" if p.get("exclusive") else ""})</option>'
                        for k, p in presets.items())
        rows = []
        for mid, p in c["reaction_roles"].items():
            ch = guild.get_channel(p["channel_id"])
            rows.append(f"""<tr><td>{e(p['title'])}</td><td>{e('#' + ch.name) if ch else 'deleted'}</td><td>{len(p['mapping'])}</td>
            <td>{'only one' if p.get('exclusive') else 'any'}</td><td><form method="post">{self.hidden()}<input type="hidden" name="action" value="forget">
            <input type="hidden" name="message_id" value="{e(mid)}"><button class="ghost" type="submit">Stop panel</button></form></td></tr>""")
        default_ch = discord.utils.get(guild.text_channels, name="mata-ke-roles")
        content = f"""<form method="post" class="card">{self.hidden()}<input type="hidden" name="action" value="post"><h2>Post a panel</h2>
        <div class="row"><label for="pr">Preset<select id="pr" name="preset">{popts}</select></label>
        <label for="pc">Channel<select id="pc" name="channel_id">{self.channel_options(guild.text_channels, default_ch.id if default_ch else None)}</select></label></div>
        <label class="check"><input type="checkbox" name="create_missing" value="1" checked> Create roles that don't exist yet (no permissions; colour roles get their colour)</label>
        <button type="submit">Post panel</button><p class="muted">Edit <code>presets.json</code> to change what the presets contain.</p></form>
        <div class="card"><h2>Live panels</h2><table><thead><tr><th>Panel</th><th>Channel</th><th>Roles</th><th>Pick</th><th></th></tr></thead>
        <tbody>{''.join(rows) or '<tr><td colspan=5 class="muted">No panels yet.</td></tr>'}</tbody></table></div>"""
        return self.page(request, "Role panels", content)

    async def panels_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        guild = self.guild()
        if f.get("action") == "forget":
            self.conf()["reaction_roles"].pop(str(f.get("message_id")), None)
            await self.bot.store.save()
            raise self.back("/panels", "Panel stopped. Delete the message in Discord if you want it gone.")
        channel = guild.get_channel(self.one_id(f, "channel_id") or 0)
        if not isinstance(channel, discord.TextChannel):
            raise self.back("/panels", "Pick a text channel.")
        try:
            url, problems = await post_preset(self.bot, guild, str(f.get("preset")), channel, f.get("create_missing") == "1")
        except discord.HTTPException as exc:
            raise self.back("/panels", f"Discord said no ({exc.status}). Check my permissions in that channel.")
        msg = "Panel posted." if url else "Panel not posted."
        if problems:
            msg += " Notes: " + "; ".join(problems[:5])
        raise self.back("/panels", msg)

    # ------------------------------------------------------------ roles & channels
    async def roles_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        c = self.conf()
        rows = []
        for r in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if r.is_default():
                continue
            colour = str(r.colour) if r.colour.value else "#99aab5"
            tag = " (bot)" if r.managed else (" · above me" if r >= guild.me.top_role else "")
            rows.append(f'<tr><td><span class="dot" style="background:{colour}"></span>{e(r.name)}<span class="muted">{e(tag)}</span></td>'
                        f'<td>{len(r.members)}</td></tr>')
        planned = ", ".join(n for _, n, _, _ in PLANNED_CHANNELS)
        content = f"""<div class="card"><h2>Sort roles</h2>
        <p class="muted">Top to bottom, one role name per line. Roles not listed keep their order, just above <i>abhi tak shareef</i>. Only roles below Mausi ji can move.</p>
        <form method="post" class="card" style="padding:0;border:0;background:none">{self.hidden()}<input type="hidden" name="action" value="save_order">
        <textarea name="order" style="min-height:260px">{e(chr(10).join(c['role_order']))}</textarea>
        <div class="inline"><button type="submit">Save order</button></div></form>
        <form method="post">{self.hidden()}<input type="hidden" name="action" value="sort"><button type="submit">Sort roles in Discord now</button></form></div>
        <div class="card"><h2>Channels</h2><p class="muted">Creates any of these that are missing: {e(planned)}. The starboard is read-only for members.</p>
        <form method="post">{self.hidden()}<input type="hidden" name="action" value="channels"><button type="submit">Create missing channels</button></form></div>
        <div class="card"><h2>Current roles</h2><table><thead><tr><th>Role</th><th>Members</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""
        return self.page(request, "Roles & channels", content)

    async def roles_post(self, request: web.Request) -> web.Response:
        f = request["form"]
        guild = self.guild()
        c = self.conf()
        action = f.get("action")
        if action == "save_order":
            c["role_order"] = [ln.strip() for ln in str(f.get("order", "")).splitlines() if ln.strip()]
            await self.bot.store.save()
            raise self.back("/roles", "Order saved. Press 'Sort roles in Discord now' to apply it.")
        try:
            if action == "sort":
                count, missing = await sort_roles(guild, c["role_order"])
                msg = f"Sorted {count} roles." + (f" Not found: {', '.join(missing[:8])}" if missing else "")
            elif action == "channels":
                made = await ensure_channels(self.bot, guild)
                msg = ("Created: " + ", ".join(made)) if made else "All channels already exist."
            else:
                msg = "Nothing changed."
        except discord.HTTPException as exc:
            msg = f"Discord said no ({exc.status}). I need Manage Roles / Manage Channels."
        raise self.back("/roles", msg)

    # ------------------------------------------------------------ warnings
    async def warnings_page(self, request: web.Request) -> web.Response:
        guild = self.guild()
        if not guild:
            return self.no_guild(request)
        c = self.conf()
        rows = []
        for uid, items in sorted(c["warnings"].items(), key=lambda kv: -len(kv[1])):
            m = guild.get_member(int(uid))
            name = m.display_name if m else f"left server ({uid})"
            latest = "<br>".join(e(w["reason"]) for w in items[-3:])
            rows.append(f"""<tr><td>{e(name)}</td><td>{len(items)}</td><td>{latest}</td><td><form method="post">{self.hidden()}
            <input type="hidden" name="user_id" value="{e(uid)}"><button class="ghost" type="submit">Clear</button></form></td></tr>""")
        content = f"""<div class="card"><table><thead><tr><th>Member</th><th>Warnings</th><th>Latest reasons</th><th></th></tr></thead>
        <tbody>{''.join(rows) or '<tr><td colspan=4 class="muted">Sab shareef hain. No warnings.</td></tr>'}</tbody></table></div>"""
        return self.page(request, "Warnings", content)

    async def warnings_post(self, request: web.Request) -> web.Response:
        self.conf()["warnings"].pop(str(request["form"].get("user_id")), None)
        await self.bot.store.save()
        raise self.back("/warnings", "Warnings cleared.")


async def setup(bot) -> None:
    await bot.add_cog(Dashboard(bot))

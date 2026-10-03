import os
import json
import asyncio
import threading
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from web import keep_alive

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
WELCOME_CHANNEL = os.getenv("WELCOME_CHANNEL", "welcome")
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "mod-logs")
AUTOROLE_NAME = os.getenv("AUTOROLE_NAME", "Member")

ROLES = [
    {"name": "Admin", "color": 0xE74C3C, "hoist": True, "mentionable": False, "admin": True},
    {"name": "Moderator", "color": 0x3498DB, "hoist": True, "mentionable": True, "perms": ["manage_messages", "kick_members", "moderate_members"]},
    {"name": "Member", "color": 0x2ECC71, "hoist": False, "mentionable": True, "perms": []},
    {"name": "Bot", "color": 0x9B59B6, "hoist": True, "mentionable": False, "perms": []},
]

CATEGORIES = [
    {"name": "THONG TIN", "channels": [
        {"name": "welcome", "type": "text", "readonly": True},
        {"name": "rules", "type": "text", "readonly": True},
        {"name": "announce", "type": "text", "readonly": True},
    ]},
    {"name": "CONG DONG", "channels": [
        {"name": "general", "type": "text"},
        {"name": "chat", "type": "text"},
        {"name": "media", "type": "text"},
        {"name": "bot-commands", "type": "text"},
    ]},
    {"name": "VOICE", "channels": [
        {"name": "General", "type": "voice"},
        {"name": "Gaming", "type": "voice"},
        {"name": "Music", "type": "voice"},
        {"name": "AFK", "type": "voice"},
    ]},
    {"name": "STAFF", "staff_only": True, "channels": [
        {"name": "staff-chat", "type": "text"},
        {"name": "staff-logs", "type": "text"},
        {"name": "mod-logs", "type": "text"},
        {"name": "staff-voice", "type": "voice"},
    ]},
]

WELCOME_MESSAGE = "Chao mung den voi server! Doc #rules truoc khi tham gia chat nhe."

STATE_PATH = os.path.join(os.path.dirname(__file__), "data", "state.json")
STATE_LOCK = threading.Lock()

def state_load():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    if not os.path.exists(STATE_PATH):
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"reaction_roles": []}, f)
    with STATE_LOCK:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

def state_save(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with STATE_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)

def rr_add(message_id, emoji, role_id):
    s = state_load()
    s["reaction_roles"].append({"message_id": message_id, "emoji": emoji, "role_id": role_id})
    state_save(s)

def rr_find(message_id, emoji):
    for rr in state_load()["reaction_roles"]:
        if rr["message_id"] == message_id and rr["emoji"] == emoji:
            return rr
    return None

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.reactions = True
intents.moderation = True

bot = commands.Bot(command_prefix="!", intents=intents)

def build_perms(spec):
    if spec.get("admin"):
        return discord.Permissions(administrator=True)
    p = discord.Permissions.none()
    for name in spec.get("perms", []):
        setattr(p, name, True)
    return p

async def get_or_create_role(guild, spec):
    existing = discord.utils.get(guild.roles, name=spec["name"])
    if existing:
        return existing
    return await guild.create_role(
        name=spec["name"],
        color=discord.Color(spec.get("color", 0)),
        hoist=spec.get("hoist", False),
        mentionable=spec.get("mentionable", False),
        permissions=build_perms(spec),
        reason="Auto-setup",
    )

async def get_or_create_category(guild, name, overwrites):
    existing = discord.utils.get(guild.categories, name=name)
    if existing:
        return existing
    return await guild.create_category(name=name, overwrites=overwrites, reason="Auto-setup")

async def get_or_create_channel(category, spec, overwrites):
    t = spec["type"]
    if t == "text":
        existing = discord.utils.get(category.text_channels, name=spec["name"])
        if existing:
            return existing
        return await category.create_text_channel(spec["name"], overwrites=overwrites, reason="Auto-setup")
    if t == "voice":
        existing = discord.utils.get(category.voice_channels, name=spec["name"])
        if existing:
            return existing
        return await category.create_voice_channel(spec["name"], overwrites=overwrites, reason="Auto-setup")
    raise ValueError(t)

async def log_to(guild, embed):
    ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
    if not ch:
        return
    try:
        await ch.send(embed=embed)
    except discord.Forbidden:
        pass

async def setup_guild(guild):
    print("[SETUP] " + guild.name)
    created_roles = {}
    for spec in ROLES:
        try:
            r = await get_or_create_role(guild, spec)
            created_roles[spec["name"]] = r
            print("[ROLE] " + r.name)
            await asyncio.sleep(0.3)
        except discord.Forbidden:
            print("[ROLE] Forbidden: " + spec["name"])
        except discord.HTTPException as e:
            print("[ROLE] HTTP: " + str(e))
    member_role = created_roles.get("Member")
    staff_role = created_roles.get("Moderator") or created_roles.get("Admin")
    for cat_spec in CATEGORIES:
        staff_only = cat_spec.get("staff_only", False)
        ow = {guild.default_role: discord.PermissionOverwrite(view_channel=True)}
        if staff_only and staff_role:
            ow[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            ow[staff_role] = discord.PermissionOverwrite(view_channel=True)
        try:
            cat = await get_or_create_category(guild, cat_spec["name"], ow)
            print("[CAT] " + cat.name)
            await asyncio.sleep(0.4)
        except discord.Forbidden:
            print("[CAT] Forbidden: " + cat_spec["name"])
            continue
        for ch_spec in cat_spec["channels"]:
            ch_ow = dict(ow)
            if ch_spec.get("readonly") and member_role:
                ch_ow[member_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False)
            try:
                ch = await get_or_create_channel(cat, ch_spec, ch_ow)
                print("[CH] " + ch.name)
                await asyncio.sleep(0.4)
            except discord.Forbidden:
                print("[CH] Forbidden: " + ch_spec["name"])
            except discord.HTTPException as e:
                print("[CH] HTTP: " + str(e))
    print("[DONE] " + guild.name)

@bot.event
async def on_ready():
    print("[READY] " + str(bot.user))
    try:
        synced = await bot.tree.sync()
        print("[SYNC] " + str(len(synced)))
    except Exception as e:
        print("[SYNC] " + str(e))
    if GUILD_ID:
        g = bot.get_guild(int(GUILD_ID))
        if g:
            await setup_guild(g)

@bot.event
async def on_member_join(member):
    ch = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL)
    if ch:
        e = discord.Embed(title="Chao mung!", description=member.mention + " vua tham gia " + member.guild.name, color=0x2ECC71)
        e.set_thumbnail(url=member.display_avatar.url)
        try:
            await ch.send(embed=e)
        except discord.Forbidden:
            pass
    role_name = "Bot" if member.bot else AUTOROLE_NAME
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role:
        try:
            await member.add_roles(role, reason="Auto-role")
        except (discord.Forbidden, discord.HTTPException):
            pass

@bot.event
async def on_member_remove(member):
    e = discord.Embed(title="Member left", color=0x95A5A6, description=str(member))
    await log_to(member.guild, e)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    e = discord.Embed(title="Message deleted", color=0xE74C3C)
    e.add_field(name="Author", value=str(message.author), inline=False)
    e.add_field(name="Channel", value=message.channel.mention, inline=False)
    e.add_field(name="Content", value=(message.content or "empty")[:1024], inline=False)
    await log_to(message.guild, e)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    e = discord.Embed(title="Message edited", color=0xF1C40F)
    e.add_field(name="Author", value=str(before.author), inline=False)
    e.add_field(name="Channel", value=before.channel.mention, inline=False)
    e.add_field(name="Before", value=(before.content or "empty")[:512], inline=False)
    e.add_field(name="After", value=(after.content or "empty")[:512], inline=False)
    await log_to(before.guild, e)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    rr = rr_find(payload.message_id, str(payload.emoji))
    if not rr:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(rr["role_id"])
    member = guild.get_member(payload.user_id)
    if role and member:
        try:
            await member.add_roles(role, reason="Reaction role")
        except (discord.Forbidden, discord.HTTPException):
            pass

@bot.event
async def on_raw_reaction_remove(payload):
    rr = rr_find(payload.message_id, str(payload.emoji))
    if not rr:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(rr["role_id"])
    member = guild.get_member(payload.user_id)
    if role and member:
        try:
            await member.remove_roles(role, reason="Reaction role removed")
        except (discord.Forbidden, discord.HTTPException):
            pass

@bot.tree.command(name="setup", description="Auto setup server")
@app_commands.default_permissions(administrator=True)
async def slash_setup(interaction):
    await interaction.response.defer(thinking=True)
    try:
        await setup_guild(interaction.guild)
        await interaction.followup.send("Setup xong.")
    except Exception as e:
        await interaction.followup.send("Loi: " + str(e))

@bot.hybrid_command(name="reactionrole", description="Tao reaction role")
@commands.has_permissions(administrator=True)
async def cmd_reactionrole(ctx, role: discord.Role, emoji: str, title: str = "Chon role"):
    e = discord.Embed(title=title, description="React " + emoji + " de nhan " + role.mention, color=0x5865F2)
    msg = await ctx.send(embed=e)
    try:
        await msg.add_reaction(emoji)
    except discord.HTTPException:
        await ctx.reply("Emoji khong hop le.")
        return
    rr_add(msg.id, emoji, role.id)
    await ctx.reply("Da tao reaction-role cho " + role.mention, mention_author=False)

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Thieu DISCORD_TOKEN")
    keep_alive()
    bot.run(TOKEN)
    

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
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "mod-logs")

ROLES = [
    {"name": "Admin", "color": 0xE74C3C, "hoist": True, "mentionable": False, "admin": True},
    {"name": "Moderator", "color": 0x3498DB, "hoist": True, "mentionable": True},
    {"name": "Member", "color": 0x2ECC71, "hoist": False, "mentionable": True},
    {"name": "Bot", "color": 0x9B59B6, "hoist": True, "mentionable": False},
]

CATEGORIES = [
    {"name": "SERVER STATS", "channels": [
        {"name": "All member", "type": "voice", "stat": "all"},
        {"name": "Thanh vien", "type": "voice", "stat": "members"},
    ]},
    {"name": "Welcome", "channels": [
        {"name": "welcome", "type": "text", "readonly": True},
        {"name": "goodbye", "type": "text", "readonly": True},
        {"name": "invite", "type": "text", "readonly": True},
        {"name": "verify", "type": "text", "readonly": True},
    ]},
    {"name": "CONG VAO", "channels": [
        {"name": "rules", "type": "text", "readonly": True},
        {"name": "huong-dan", "type": "text", "readonly": True},
        {"name": "announcement", "type": "text", "readonly": True},
        {"name": "minecraft-smp", "type": "text"},
        {"name": "server-boost", "type": "text"},
        {"name": "donate", "type": "text"},
        {"name": "give-away", "type": "text"},
        {"name": "get-role", "type": "text"},
    ]},
    {"name": "CONG DONG", "channels": [
        {"name": "general", "type": "text"},
        {"name": "meme", "type": "text"},
        {"name": "media", "type": "text"},
        {"name": "music", "type": "text"},
        {"name": "gaming", "type": "text"},
        {"name": "study", "type": "text"},
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
        {"name": "mod-logs", "type": "text"},
        {"name": "report", "type": "text"},
        {"name": "Staff Voice", "type": "voice"},
    ]},
]

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.reactions = True
intents.moderation = True

bot = commands.Bot(command_prefix="!", intents=intents)

STATE_PATH = "data/state.json"
STATE_LOCK = threading.Lock()

def state_load():
    if not os.path.isdir("data"):
        os.makedirs("data")
    if not os.path.exists(STATE_PATH):
        f = open(STATE_PATH, "w", encoding="utf-8")
        json.dump({"reaction_roles": []}, f)
        f.close()
    STATE_LOCK.acquire()
    f = open(STATE_PATH, "r", encoding="utf-8")
    data = json.load(f)
    f.close()
    STATE_LOCK.release()
    return data

def state_save(state):
    if not os.path.isdir("data"):
        os.makedirs("data")
    STATE_LOCK.acquire()
    f = open(STATE_PATH, "w", encoding="utf-8")
    json.dump(state, f, indent=2)
    f.close()
    STATE_LOCK.release()

def rr_add(message_id, emoji, role_id):
    s = state_load()
    s["reaction_roles"].append({"message_id": message_id, "emoji": emoji, "role_id": role_id})
    state_save(s)

def rr_find(message_id, emoji):
    s = state_load()
    for rr in s["reaction_roles"]:
        if rr["message_id"] == message_id and rr["emoji"] == emoji:
            return rr
    return None

def build_perms(spec):
    if spec.get("admin"):
        return discord.Permissions(administrator=True)
    p = discord.Permissions.none()
    perms = spec.get("perms", [])
    for n in perms:
        setattr(p, n, True)
    return p

def norm_name(name):
    return name.lower().replace(" ", "-")

async def find_or_make_role(guild, spec):
    old = discord.utils.get(guild.roles, name=spec["name"])
    if old:
        return old
    try:
        return await guild.create_role(
            name=spec["name"],
            color=discord.Color(spec.get("color", 0)),
            hoist=spec.get("hoist", False),
            mentionable=spec.get("mentionable", False),
            permissions=build_perms(spec),
        )
    except:
        return None

async def find_or_make_cat(guild, name, overwrites):
    old = discord.utils.get(guild.categories, name=name)
    if old:
        return old
    try:
        return await guild.create_category(name=name, overwrites=overwrites)
    except:
        return None

async def find_or_make_ch(category, spec, overwrites):
    t = spec["type"]
    name = spec["name"]
    try:
        if t == "text":
            old = discord.utils.get(category.text_channels, name=norm_name(name))
            if old:
                return old
            return await category.create_text_channel(name, overwrites=overwrites)
        if t == "voice":
            old = discord.utils.get(category.voice_channels, name=name)
            if old:
                return old
            return await category.create_voice_channel(name, overwrites=overwrites)
    except:
        return None
    return None

async def log_it(guild, embed):
    ch = None
    for c in guild.text_channels:
        if "mod-logs" in c.name:
            ch = c
            break
    if not ch:
        return
    try:
        await ch.send(embed=embed)
    except:
        pass

async def do_setup(guild):
    if guild is None:
        return False, "no guild"
    print("[SETUP] " + guild.name)

    role_map = {}
    for spec in ROLES:
        r = await find_or_make_role(guild, spec)
        if r:
            role_map[spec["name"]] = r
            print("[ROLE] " + r.name)
        await asyncio.sleep(0.3)

    m_role = role_map.get("Member")
    s_role = role_map.get("Moderator")
    if s_role is None:
        s_role = role_map.get("Admin")

    for cat_spec in CATEGORIES:
        staff_only = cat_spec.get("staff_only", False)
        ow = {guild.default_role: discord.PermissionOverwrite(view_channel=True)}
        if staff_only and s_role is not None:
            ow[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            ow[s_role] = discord.PermissionOverwrite(view_channel=True)

        cat = await find_or_make_cat(guild, cat_spec["name"], ow)
        if cat is None:
            continue
        print("[CAT] " + cat.name)
        await asyncio.sleep(0.4)

        for ch_spec in cat_spec["channels"]:
            ch_ow = dict(ow)
            if ch_spec.get("readonly") and m_role is not None:
                ch_ow[m_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
            if ch_spec.get("stat"):
                ch_ow = {guild.default_role: discord.PermissionOverwrite(connect=False)}
            ch = await find_or_make_ch(cat, ch_spec, ch_ow)
            if ch is None:
                continue
            print("[CH] " + ch.name)
            await asyncio.sleep(0.4)

    print("[DONE] " + guild.name)
    return True, None

STAT_ON = False

async def stats_task():
    await bot.wait_until_ready()
    while True:
        try:
            for guild in bot.guilds:
                total = guild.member_count
                real = 0
                for m in guild.members:
                    if not m.bot:
                        real = real + 1
                pairs = [("All member", total), ("Thanh vien", real)]
                for label, num in pairs:
                    target = None
                    for c in guild.voice_channels:
                        if label in c.name:
                            target = c
                            break
                    if target is None:
                        continue
                    newn = label + ": " + str(num)
                    if target.name != newn:
                        try:
                            await target.edit(name=newn)
                        except:
                            pass
        except:
            pass
        await asyncio.sleep(300)

@bot.event
async def on_ready():
    print("[READY] " + str(bot.user))
    try:
        synced = await bot.tree.sync()
        print("[SYNC] " + str(len(synced)))
    except Exception as e:
        print("[SYNC] " + str(e))
    global STAT_ON
    if not STAT_ON:
        STAT_ON = True
        bot.loop.create_task(stats_task())

@bot.event
async def on_member_join(member):
    ch = None
    for c in member.guild.text_channels:
        if "welcome" in c.name.lower() and "goodbye" not in c.name.lower():
            ch = c
            break
    if ch:
        txt = member.mention + " vua vao server " + member.guild.name
        e = discord.Embed(title="Chao mung thanh vien moi", description=txt, color=0x2ECC71)
        e.set_thumbnail(url=member.display_avatar.url)
        try:
            await ch.send(embed=e)
        except:
            pass
    role = None
    target_name = "Bot" if member.bot else "Member"
    for r in member.guild.roles:
        if r.name == target_name:
            role = r
            break
    if role:
        try:
            await member.add_roles(role)
        except:
            pass

@bot.event
async def on_member_remove(member):
    ch = None
    for c in member.guild.text_channels:
        if "goodbye" in c.name.lower():
            ch = c
            break
    if ch:
        txt = str(member) + " da roi server"
        e = discord.Embed(title="Tam biet", description=txt, color=0xE74C3C)
        e.set_thumbnail(url=member.display_avatar.url)
        try:
            await ch.send(embed=e)
        except:
            pass

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    if not message.guild:
        return
    e = discord.Embed(title="Tin nhan bi xoa", color=0xE74C3C)
    e.add_field(name="Nguoi gui", value=str(message.author), inline=False)
    e.add_field(name="Kenh", value=message.channel.mention, inline=False)
    e.add_field(name="Noi dung", value=(message.content or "trong")[:1024], inline=False)
    await log_it(message.guild, e)

@bot.event
async def on_raw_reaction_add(payload):
    if bot.user is None:
        return
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
    if role is None:
        return
    if member is None:
        return
    try:
        await member.add_roles(role)
    except:
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
    if role is None:
        return
    if member is None:
        return
    try:
        await member.remove_roles(role)
    except:
        pass

@bot.tree.command(name="setup", description="Setup server")
@app_commands.default_permissions(administrator=True)
async def slash_setup(interaction):
    await interaction.response.defer(thinking=True)
    ok, err = await do_setup(interaction.guild)
    if ok:
        await interaction.followup.send("Setup xong")
    else:
        await interaction.followup.send("Loi: " + str(err))

@bot.hybrid_command(name="reactionrole", description="Tao reaction role")
@commands.has_permissions(administrator=True)
async def cmd_rr(ctx, role: discord.Role, emoji: str):
    e = discord.Embed(title="Chon role", description="React " + emoji + " de nhan " + role.mention, color=0x5865F2)
    msg = await ctx.send(embed=e)
    try:
        await msg.add_reaction(emoji)
    except:
        await ctx.reply("Emoji khong hop le")
        return
    rr_add(msg.id, emoji, role.id)
    await ctx.reply("Da tao", mention_author=False)

@bot.hybrid_command(name="kick", description="Kick")
@commands.has_permissions(kick_members=True)
async def cmd_kick(ctx, member: discord.Member, reason: str = "Khong co ly do"):
    if member.top_role >= ctx.author.top_role:
        await ctx.reply("Khong the kick")
        return
    try:
        await member.kick(reason=reason)
        await ctx.reply("Da kick " + str(member))
    except:
        await ctx.reply("Bot thieu quyen")

@bot.hybrid_command(name="ban", description="Ban")
@commands.has_permissions(ban_members=True)
async def cmd_ban(ctx, member: discord.Member, reason: str = "Khong co ly do"):
    if member.top_role >= ctx.author.top_role:
        await ctx.reply("Khong the ban")
        return
    try:
        await member.ban(reason=reason)
        await ctx.reply("Da ban " + str(member))
    except:
        await ctx.reply("Bot thieu quyen")

@bot.hybrid_command(name="mute", description="Timeout")
@commands.has_permissions(moderate_members=True)
async def cmd_mute(ctx, member: discord.Member, minutes: int = 10):
    try:
        from datetime import timedelta
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until)
        await ctx.reply("Da mute " + str(member))
    except:
        await ctx.reply("Bot thieu quyen")

@bot.hybrid_command(name="unmute", description="Bo timeout")
@commands.has_permissions(moderate_members=True)
async def cmd_unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.reply("Da unmute")
    except:
        await ctx.reply("Bot thieu quyen")

@bot.hybrid_command(name="warn", description="Canh cao")
@commands.has_permissions(moderate_members=True)
async def cmd_warn(ctx, member: discord.Member, reason: str = "Khong co ly do"):
    await ctx.send("Canh cao " + member.mention + " - " + reason)

@bot.hybrid_command(name="clear", description="Xoa tin nhan")
@commands.has_permissions(manage_messages=True)
async def cmd_clear(ctx, amount: int = 10):
    if amount < 1:
        return
    if amount > 100:
        return
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send("Da xoa " + str(len(deleted) - 1), delete_after=5)

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Thieu DISCORD_TOKEN")
    keep_alive()
    bot.run(TOKEN)
  

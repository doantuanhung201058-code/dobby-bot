import os
import json
import asyncio
import threading
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
PORT = int(os.getenv("PORT", 3000))

# ===== HTTP SERVER (giữ Render Free không sleep) =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass

def run_http_server():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()
    print(f"HTTP server port {PORT}")

# ===== FONT FANCY =====
def fancy(text: str) -> str:
    mapping = {}
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        mapping[c] = chr(0x1D41A + i)
    for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        mapping[c] = chr(0x1D400 + i)
    return "".join(mapping.get(ch, ch) for ch in text)

def small_caps(text: str) -> str:
    return re.sub(r"[a-z]", lambda m: chr(ord(m.group()) + 0x1D00), text)

# ===== CẤU HÌNH ROLES =====
ROLES = [
    {"name": "👑 Admin", "color": 0xE74C3C, "hoist": True, "mentionable": False, "admin": True},
    {"name": "🛡️ Moderator", "color": 0x3498DB, "hoist": True, "mentionable": True},
    {"name": "👤 Member", "color": 0x2ECC71, "hoist": False, "mentionable": True},
    {"name": "🤖 Bot", "color": 0x9B59B6, "hoist": True, "mentionable": False},
]

# ===== CẤU HÌNH CATEGORIES & CHANNELS =====
CATEGORIES = [
    {"name": "📊 SERVER STATS", "channels": [
        {"name": "👥 All member", "type": "voice", "stat": "all"},
        {"name": "🧑 Thanh vien", "type": "voice", "stat": "members"},
    ]},
    {"name": "👋 WELCOME", "channels": [
        {"name": "🎉-welcome", "type": "text", "readonly": True},
        {"name": "💔-goodbye", "type": "text", "readonly": True},
        {"name": "📨-invite", "type": "text", "readonly": True},
        {"name": "✅-verify", "type": "text", "readonly": True},
    ]},
    {"name": "📢 CỔNG VÀO", "channels": [
        {"name": "📜-rules", "type": "text", "readonly": True},
        {"name": "📖-huong-dan", "type": "text", "readonly": True},
        {"name": "📣-announcement", "type": "text", "readonly": True},
        {"name": "⛏️-minecraft-smp", "type": "text"},
        {"name": "🚀-server-boost", "type": "text"},
        {"name": "💰-donate", "type": "text"},
        {"name": "🎁-give-away", "type": "text"},
        {"name": "🎭-get-role", "type": "text"},
    ]},
    {"name": "💬 CỘNG ĐỒNG", "channels": [
        {"name": "💬-general", "type": "text"},
        {"name": "😂-meme", "type": "text"},
        {"name": "🖼️-media", "type": "text"},
        {"name": "🎵-music", "type": "text"},
        {"name": "🎮-gaming", "type": "text"},
        {"name": "📚-study", "type": "text"},
        {"name": "🤖-bot-commands", "type": "text"},
    ]},
    {"name": "🔊 VOICE", "channels": [
        {"name": "🔊 General", "type": "voice"},
        {"name": "🎮 Gaming", "type": "voice"},
        {"name": "🎵 Music", "type": "voice"},
        {"name": "💤 AFK", "type": "voice"},
    ]},
    {"name": "🛠️ STAFF", "staff_only": True, "channels": [
        {"name": "💼-staff-chat", "type": "text"},
        {"name": "📋-mod-logs", "type": "text"},
        {"name": "🚨-report", "type": "text"},
        {"name": "🎙️ Staff Voice", "type": "voice"},
    ]},
]

# ===== INTENTS =====
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
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"reaction_roles": []}, f)
    with STATE_LOCK:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

def state_save(state):
    if not os.path.isdir("data"):
        os.makedirs("data")
    with STATE_LOCK:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

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
    return discord.Permissions.none()

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
    except Exception as e:
        print(f"[ROLE ERROR] {spec['name']}: {e}")
        return None

async def find_or_make_cat(guild, name, overwrites):
    old = discord.utils.get(guild.categories, name=name)
    if old:
        return old
    try:
        return await guild.create_category(name=name, overwrites=overwrites)
    except Exception as e:
        print(f"[CAT ERROR] {name}: {e}")
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
    except Exception as e:
        print(f"[CH ERROR] {name}: {e}")
        return None
    return None

async def log_it(guild, embed):
    ch = None
    for c in guild.text_channels:
        if "mod-logs" in c.name:
            ch = c
            break
    if ch:
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

    m_role = role_map.get("👤 Member")
    s_role = role_map.get("🛡️ Moderator") or role_map.get("👑 Admin")

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
            if ch:
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
                real = sum(1 for m in guild.members if not m.bot)
                for label, num in [("👥 All member", total), ("🧑 Thanh vien", real)]:
                    target = None
                    for c in guild.voice_channels:
                        if label in c.name or label.split()[1] in c.name:
                            target = c
                            break
                    if target is None:
                        continue
                    newn = f"{label}: {num}"
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
    print(f"[READY] {bot.user}")

    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"[SYNC] {len(synced)} commands -> guild {GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"[SYNC] {len(synced)} commands global")
    except Exception as e:
        print(f"[SYNC ERROR] {e}")

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
        embed = discord.Embed(
            title=f"{fancy('Welcome')} 🎉",
            description=(
                f"{member.mention} vừa tham gia **{member.guild.name}**!\n\n"
                f"> 👥 Thành viên thứ **{member.guild.member_count}**\n"
                f"> 📜 Đọc nội quy ở kênh **rules**\n"
                f"> 🎭 Chọn role ở kênh **get-role**"
            ),
            color=0x57F287,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        embed.timestamp = discord.utils.utcnow()
        try:
            await ch.send(embed=embed)
        except:
            pass

    target_name = "🤖 Bot" if member.bot else "👤 Member"
    role = discord.utils.get(member.guild.roles, name=target_name)
    if role is None:
        for r in member.guild.roles:
            if target_name.split()[-1] in r.name:
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
        embed = discord.Embed(
            title=f"{fancy('Goodbye')} 💔",
            description=f"**{member.name}** đã rời khỏi server. Hẹn gặp lại!",
            color=0xED4245,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        try:
            await ch.send(embed=embed)
        except:
            pass

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    embed = discord.Embed(title="🗑️ Tin nhắn bị xóa", color=0xE74C3C)
    embed.add_field(name="👤 Người gửi", value=str(message.author), inline=False)
    embed.add_field(name="📍 Kênh", value=message.channel.mention, inline=False)
    embed.add_field(name="📝 Nội dung", value=(message.content or "trống")[:1024], inline=False)
    await log_it(message.guild, embed)

@bot.event
async def on_raw_reaction_add(payload):
    if bot.user is None or payload.user_id == bot.user.id:
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
    if role and member:
        try:
            await member.remove_roles(role)
        except:
            pass

# ===== SLASH COMMAND =====
@bot.tree.command(name="setup", description="Thiết lập server tự động")
@app_commands.default_permissions(administrator=True)
async def slash_setup(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    ok, err = await do_setup(interaction.guild)
    if ok:
        embed = discord.Embed(
            title=f"{fancy('Setup Complete')} ✨",
            description=(
                f"✅ Đã tạo xong cấu trúc server!\n\n"
                f"> 📁 **Categories:** `{len(CATEGORIES)}`\n"
                f"> 🎭 **Roles:** `{len(ROLES)}`"
            ),
            color=0x5865F2,
        )
        embed.set_footer(text="Powered by DobbySetup")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Lỗi: `{err}`")

# ===== HYBRID COMMANDS =====
@bot.hybrid_command(name="reactionrole", description="Tạo reaction role")
@commands.has_permissions(administrator=True)
async def cmd_rr(ctx, role: discord.Role, emoji: str):
    embed = discord.Embed(
        title="🎭 Chọn Role",
        description=f"React {emoji} để nhận {role.mention}",
        color=0x5865F2,
    )
    msg = await ctx.send(embed=embed)
    try:
        await msg.add_reaction(emoji)
    except:
        await ctx.reply("❌ Emoji không hợp lệ")
        return
    rr_add(msg.id, emoji, role.id)
    await ctx.reply("✅ Đã tạo reaction role", mention_author=False)

@bot.hybrid_command(name="kick", description="Kick thành viên")
@commands.has_permissions(kick_members=True)
async def cmd_kick(ctx, member: discord.Member, reason: str = "Không có lý do"):
    if member.top_role >= ctx.author.top_role:
        await ctx.reply("❌ Không thể kick người này")
        return
    try:
        await member.kick(reason=reason)
        await ctx.reply(f"✅ Đã kick {member}")
    except:
        await ctx.reply("❌ Bot thiếu quyền")

@bot.hybrid_command(name="ban", description="Ban thành viên")
@commands.has_permissions(ban_members=True)
async def cmd_ban(ctx, member: discord.Member, reason: str = "Không có lý do"):
    if member.top_role >= ctx.author.top_role:
        await ctx.reply("❌ Không thể ban người này")
        return
    try:
        await member.ban(reason=reason)
        await ctx.reply(f"✅ Đã ban {member}")
    except:
        await ctx.reply("❌ Bot thiếu quyền")

@bot.hybrid_command(name="mute", description="Timeout thành viên")
@commands.has_permissions(moderate_members=True)
async def cmd_mute(ctx, member: discord.Member, minutes: int = 10):
    from datetime import timedelta
    try:
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until)
        await ctx.reply(f"🔇 Đã mute {member} trong {minutes} phút")
    except:
        await ctx.reply("❌ Bot thiếu quyền")

@bot.hybrid_command(name="unmute", description="Bỏ timeout")
@commands.has_permissions(moderate_members=True)
async def cmd_unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.reply("🔊 Đã unmute")
    except:
        await ctx.reply("❌ Bot thiếu quyền")

@bot.hybrid_command(name="warn", description="Cảnh cáo thành viên")
@commands.has_permissions(moderate_members=True)
async def cmd_warn(ctx, member: discord.Member, reason: str = "Không có lý do"):
    await ctx.send(f"⚠️ Cảnh cáo {member.mention} - {reason}")

@bot.hybrid_command(name="clear", description="Xóa tin nhắn")
@commands.has_permissions(manage_messages=True)
async def cmd_clear(ctx, amount: int = 10):
    if amount < 1 or amount > 100:
        return
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🗑️ Đã xóa {len(deleted) - 1} tin nhắn", delete_after=5)

# ===== MAIN =====
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Thiếu DISCORD_TOKEN")
    threading.Thread(target=run_http_server, daemon=True).start()
    bot.run(TOKEN)
    

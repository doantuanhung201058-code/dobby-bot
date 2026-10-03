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
WELCOME_CHANNEL = os.getenv("WELCOME_CHANNEL", "welcome")
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "mod-logs")

ROLES = [
    {"name": "👑 Admin", "color": 0xE74C3C, "hoist": True, "mentionable": False, "admin": True},
    {"name": "🛡️ Moderator", "color": 0x3498DB, "hoist": True, "mentionable": True, "perms": ["manage_messages", "kick_members", "moderate_members"]},
    {"name": "🌟 Member", "color": 0x2ECC71, "hoist": False, "mentionable": True, "perms": []},
    {"name": "🤖 Bot", "color": 0x9B59B6, "hoist": True, "mentionable": False, "perms": []},
]

CATEGORIES = [
    {"name": "📢 THÔNG TIN", "channels": [
        {"name": "👋-welcome", "type": "text", "readonly": True},
        {"name": "📜-rules", "type": "text", "readonly": True},
        {"name": "📣-announce", "type": "text", "readonly": True},
    ]},
    {"name": "💬 CỘNG ĐỒNG", "channels": [
        {"name": "💬-general", "type": "text"},
        {"name": "🗨️-chat", "type": "text"},
        {"name": "🖼️-media", "type": "text"},
        {"name": "🤖-bot-commands", "type": "text"},
    ]},
    {"name": "🔊 VOICE", "channels": [
        {"name": "🔊 General", "type": "voice"},
        {"name": "🎮 Gaming", "type": "voice"},
        {"name": "🎵 Music", "type": "voice"},
        {"name": "💤 AFK", "type": "voice"},
    ]},
    {"name": "🛡️ STAFF", "staff_only": True, "channels": [
        {"name": "💼-staff-chat", "type": "text"},
        {"name": "📋-staff-logs", "type": "text"},
        {"name": "🚨-mod-logs", "type": "text"},
        {"name": "🎧 Staff Voice", "type": "voice"},
    ]},
]

WELCOME_MESSAGE = (
    "╔══════════════════════╗\n"
    "   ✨ **CHÀO MỪNG ĐẾN SERVER** ✨\n"
    "╚══════════════════════╝\n\n"
    "📖 Đọc kỹ **#rules** trước khi chat nhé!\n"
    "🎉 Chúc bạn có khoảng thời gian vui vẻ!"
)

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

def normalize_channel_name(name):
    return name.lower().replace(" ", "-")

async def get_or_create_role(guild, spec):
    try:
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
    except Exception as e:
        print("[ROLE-ERR] " + spec["name"] + ": " + str(e))
        return None

async def get_or_create_category(guild, name, overwrites):
    try:
        existing = discord.utils.get(guild.categories, name=name)
        if existing:
            return existing
        return await guild.create_category(name=name, overwrites=overwrites, reason="Auto-setup")
    except Exception as e:
        print("[CAT-ERR] " + name + ": " + str(e))
        return None

async def get_or_create_channel(category, spec, overwrites):
    t = spec["type"]
    target_name = spec["name"]
    try:
        if t == "text":
            existing = discord.utils.get(category.text_channels, name=normalize_channel_name(target_name))
            if existing:
                return existing
            return await category.create_text_channel(target_name, overwrites=overwrites, reason="Auto-setup")
        if t == "voice":
            existing = discord.utils.get(category.voice_channels, name=target_name)
            if existing:
                return existing
            return await category.create_voice_channel(target_name, overwrites=overwrites, reason="Auto-setup")
    except Exception as e:
        print("[CH-ERR] " + target_name + ": " + str(e))
        return None
    return None

async def log_to(guild, embed):
    ch = None
    for c in guild.text_channels:
        if "mod-logs" in c.name:
            ch = c
            break
    if not ch:
        return
    try:
        await ch.send(embed=embed)
    except discord.Forbidden:
        pass

async def setup_guild(guild):
    if guild is None:
        return False, "Khong tim thay server."
    print("[SETUP] " + guild.name)

    created_roles = {}
    for spec in ROLES:
        r = await get_or_create_role(guild, spec)
        if r is not None:
            created_roles[spec["name"]] = r
            print("[ROLE] " + r.name)
        await asyncio.sleep(0.3)

    member_role = created_roles.get("🌟 Member")
    staff_role = created_roles.get("🛡️ Moderator") or created_roles.get("👑 Admin")

    for cat_spec in CATEGORIES:
        staff_only = cat_spec.get("staff_only", False)
        ow = {guild.default_role: discord.PermissionOverwrite(view_channel=True)}
        if staff_only and staff_role is not None:
            ow[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            ow[staff_role] = discord.PermissionOverwrite(view_channel=True)

        cat = await get_or_create_category(guild, cat_spec["name"], ow)
        if cat is None:
            print("[CAT] SKIP: " + cat_spec["name"])
            continue
        print("[CAT] " + cat.name)
        await asyncio.sleep(0.4)

        for ch_spec in cat_spec["channels"]:
            ch_ow = dict(ow)
            if ch_spec.get("readonly") and member_role is not None:
                ch_ow[member_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False)
            ch = await get_or_create_channel(cat, ch_spec, ch_ow)
            if ch is None:
                print("[CH] SKIP: " + ch_spec["name"])
                continue
            print("[CH] " + ch.name)
            await asyncio.sleep(0.4)

    for c in guild.text_channels:
        if "welcome" in c.name:
            try:
                has = False
                async for m in c.history(limit=5):
                    if m.author == bot.user:
                        has = True
                        break
                if not has:
                    await c.send(WELCOME_MESSAGE)
            except discord.Forbidden:
                pass
            break

    print("[DONE] " + guild.name)
    return True, None

@bot.event
async def on_ready():
    print("[READY] " + str(bot.user))
    try:
        synced = await bot.tree.sync()
        print("[SYNC] " + str(len(synced)))
    except Exception as e:
        print("[SYNC] " + str(e))

@bot.event
async def on_member_join(member):
    ch = None
    for c in member.guild.text_channels:
        if "welcome" in c.name:
            ch = c
            break
    if ch:
        e = discord.Embed(
            title="✨ Chào mừng thành viên mới ✨",
            description=(
                f"🎊 {member.mention} vừa đặt chân đến **{member.guild.name}**!\n\n"
                f"👤 **Tên:** {member.name}\n"
                f"🔢 **Thành viên thứ:** `{member.guild.member_count}`\n\n"
                "📜 Đừng quên đọc **#rules** nhé!"
            ),
            color=0x2ECC71,
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"ID: {member.id}")
        try:
            await ch.send(embed=e)
        except discord.Forbidden:
            pass
    role = None
    target = "🤖 Bot" if member.bot else "🌟 Member"
    for r in member.guild.roles:
        if r.name == target:
            role = r
            break
    if role:
        try:
            await member.add_roles(role, reason="Auto-role")
        except (discord.Forbidden, discord.HTTPException):
            pass

@bot.event
async def on_member_remove(member):
    e = discord.Embed(
        title="📤 Thành viên rời đi",
        description=f"**{member}** đã rời server.\n👥 Còn lại: `{member.guild.member_count}`",
        color=0x95A5A6,
    )
    e.set_thumbnail(url=member.display_avatar.url)
    await log_to(member.guild, e)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    e = discord.Embed(title="🗑️ Tin nhắn bị xóa", color=0xE74C3C)
    e.add_field(name="👤 Người gửi", value=str(message.author), inline=False)
    e.add_field(name="📍 Kênh", value=message.channel.mention, inline=False)
    e.add_field(name="📝 Nội dung", value=(message.content or "*trống*")[:1024], inline=False)
    await log_to(message.guild, e)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    e = discord.Embed(title="✏️ Tin nhắn chỉnh sửa", color=0xF1C40F)
    e.add_field(name="👤 Người gửi", value=str(before.author), inline=False)
    e.add_field(name="📍 Kênh", value=before.channel.mention, inline=False)
    e.add_field(name="📝 Trước", value=(before.content or "*trống*")[:512], inline=False)
    e.add_field(name="🆕 Sau", value=(after.content or "*trống*")[:512], inline=False)
    await log_to(before.guild, e)

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

@bot.tree.command(name="setup", description="Tự động setup server (roles + channels)")
@app_commands.default_permissions(administrator=True)
async def slash_setup(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    ok, err = await setup_guild(interaction.guild)
    if ok:
        await interaction.followup.send("✅ Setup xong.")
    else:
        await interaction.followup.send("❌ Lỗi: " + str(err))

@bot.hybrid_command(name="reactionrole", description="Tạo tin nhắn tự chọn role")
@commands.has_permissions(administrator=True)
async def cmd_reactionrole(ctx, role: discord.Role, emoji: str, *, title: str = "Chọn role"):
    e = discord.Embed(
        title="🎭 " + title,
        description=f"React {emoji} để nhận {role.mention}\nBỏ react để mất role.",
        color=0x5865F2,
    )
    msg = await ctx.send(embed=e)
    try:
        await msg.add_reaction(emoji)
    except discord.HTTPException:
        await ctx.reply("❌ Emoji không hợp lệ.")
        return
    rr_add(msg.id, emoji, role.id)
    await ctx.reply(f"✅ Đã tạo reaction-role cho {role.mention}", mention_author=False)

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Thieu DISCORD_TOKEN")
    keep_alive()
    bot.run(TOKEN)

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# CAT Café bot. Your private .env file is never needed in chat.
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
DATABASE = Path(__file__).with_name("orders.db")

PAW_EMOJI = "<:kittypaws:1560198121278017596>"
DOT_EMOJI = "<:glowingdotwhite:1560197241896177704>"
SPARKLE_EMOJI = "<:sparkle:1560197132001222676>"
DANCE_EMOJI = "<:dancemoji:1560198047789744209>"
CAFE_TITLE = "# <:pixelletterc:1560218192478216233><:pixellettera:1560218167484350524><:pixellettert:1560218133124489316> <:pixelheartwhite:1560217990048260106> <:pixelletterc:1560218192478216233><:pixellettera:1560218167484350524><:pixelletterf:1560218850161598579><:pixellettere:1560218870730465360>"
ORDER_SUBTITLE = "__⁺　. ♡  𝐎𝐫𝐝𝐞𝐫 𝐋𝐨𝐠  ♡ .　⁺__"

DEFAULT_TEMPLATES = {
    "welcome": "♡ Welcome to **{server}**, {mention}! ♡\nInvited by: **{inviter}**\nYou are member **#{member_count}**!\nWe're so happy you're here! Please make yourself at home. 🐾",
    "join": "🐾 **{member}** joined **{server}**!\n{dot} Invited by: **{inviter}**\n{dot} Member count: **{member_count}**",
    "leave": "♡ **{member}** has left **{server}**. We wish you well! 🐾",
    "review": "♡ **𝐂𝐀𝐓 𝐂𝐚𝐟𝐞 · Chef Review** ♡\n{dot} **Chef being reviewed:** {chef_mention}\n{dot} **Customer:** {mention}\n{dot} **Rating:** {stars}\n{dot} **Review:** {comment}",
    "order": "{cafe_title}\n{order_subtitle}\n\n{sparkle}  __**𝐈𝐧𝐟𝐨**__\n> {dot} **𝖢𝗁𝖾𝖿:** {chef}\n> {dot} **𝖢𝗎𝗌𝗍𝗈𝗆𝖾𝗋:** {customer}\n> {dot} **𝖯𝖺𝗒𝗆𝖾𝗇𝗍:** {payment:,} Bloxburg cash\n> {dot} **𝖤𝗑𝗍𝗋𝖺 𝗇𝗈𝗍𝖾𝗌:** {notes}\n> {dot} **𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝗂𝗈𝗇 𝖣𝖺𝗍𝖾:** {date}\n\n{sparkle}   __**𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐢𝐨𝐧**__\n{dot} {chef} completed **{chef_orders}** purrfect orders!\n\n-# {dance} Server Order #{order_number}",
}


def connect_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def setup_database():
    """Create missing tables and only add columns; never erase existing order history."""
    with connect_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chef_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            payment INTEGER NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL
        )""")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)").fetchall()}
        if "is_test" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0")
        if "server_order_number" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN server_order_number INTEGER")
        db.execute("""CREATE TABLE IF NOT EXISTS bot_settings (
            setting_key TEXT PRIMARY KEY, setting_value INTEGER NOT NULL DEFAULT 0
        )""")
        db.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES ('server_order_counter', 0)")
        db.execute("""CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, reviewer_id INTEGER NOT NULL,
            rating INTEGER NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL,
            chef_id INTEGER
        )""")
        # Add the reviewed chef to existing review tables without deleting old reviews.
        review_columns = {row["name"] for row in db.execute("PRAGMA table_info(reviews)").fetchall()}
        if "chef_id" not in review_columns:
            db.execute("ALTER TABLE reviews ADD COLUMN chef_id INTEGER")
        # New configurable settings are stored separately from the existing counter.
        db.execute("CREATE TABLE IF NOT EXISTS cafe_config (config_key TEXT PRIMARY KEY, config_value TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO cafe_config (config_key, config_value) VALUES ('template_welcome', ?)", (DEFAULT_TEMPLATES["welcome"],))
        db.execute("INSERT OR IGNORE INTO cafe_config (config_key, config_value) VALUES ('template_join', ?)", (DEFAULT_TEMPLATES["join"],))
        db.execute("INSERT OR IGNORE INTO cafe_config (config_key, config_value) VALUES ('template_leave', ?)", (DEFAULT_TEMPLATES["leave"],))
        db.execute("INSERT OR IGNORE INTO cafe_config (config_key, config_value) VALUES ('template_review', ?)", (DEFAULT_TEMPLATES["review"],))
        db.execute("INSERT OR IGNORE INTO cafe_config (config_key, config_value) VALUES ('template_order', ?)", (DEFAULT_TEMPLATES["order"],))
        db.execute("""CREATE TABLE IF NOT EXISTS reaction_roles (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (message_id, emoji)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS tickets (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            opener_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        )""")
        # Each ticket panel has its own editable text and staff-ping role.
        db.execute("""CREATE TABLE IF NOT EXISTS ticket_panels (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            panel_title TEXT NOT NULL,
            panel_description TEXT NOT NULL,
            button_label TEXT NOT NULL,
            ticket_title TEXT NOT NULL,
            ticket_message TEXT NOT NULL,
            staff_role_id TEXT NOT NULL DEFAULT ''
        )""")


def get_config(key: str, default: str = "") -> str:
    with connect_db() as db:
        row = db.execute("SELECT config_value FROM cafe_config WHERE config_key = ?", (key,)).fetchone()
    return row["config_value"] if row else default


def set_config(key: str, value: str):
    with connect_db() as db:
        db.execute("INSERT INTO cafe_config (config_key, config_value) VALUES (?, ?) ON CONFLICT(config_key) DO UPDATE SET config_value = excluded.config_value", (key, value))


def get_channel_id(key: str) -> Optional[int]:
    value = get_config(key)
    if value.isdigit():
        return int(value)
    # Keep compatibility with the old .env channel settings.
    env_key = {"order_channel": "LOG_CHANNEL_ID", "welcome_channel": "WELCOME_CHANNEL_ID", "member_log_channel": "MEMBER_LOG_CHANNEL_ID", "review_channel": "REVIEW_CHANNEL_ID"}.get(key)
    env_value = os.getenv(env_key, "") if env_key else ""
    return int(env_value) if env_value.isdigit() else None


def get_chef_stats(chef_id: int):
    with connect_db() as db:
        row = db.execute("SELECT COUNT(*) AS order_count, COALESCE(SUM(payment), 0) AS total_payment FROM orders WHERE chef_id = ? AND is_test = 0", (chef_id,)).fetchone()
    return row["order_count"], row["total_payment"]


def get_period_bounds(period: str):
    now_local = datetime.now().astimezone()
    today = now_local.date()
    if period == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=7)
    else:
        start_date = today.replace(day=1)
        end_date = start_date.replace(year=start_date.year + 1, month=1) if start_date.month == 12 else start_date.replace(month=start_date.month + 1)
    start = datetime.combine(start_date, datetime.min.time()).astimezone().astimezone(timezone.utc).isoformat()
    end = datetime.combine(end_date, datetime.min.time()).astimezone().astimezone(timezone.utc).isoformat()
    return start, end


def get_period_leaderboard(period: str):
    start_at, end_at = get_period_bounds(period)
    with connect_db() as db:
        return db.execute("""SELECT chef_id, COUNT(*) AS order_count, COALESCE(SUM(payment), 0) AS total_payment
            FROM orders WHERE is_test = 0 AND completed_at >= ? AND completed_at < ?
            GROUP BY chef_id ORDER BY order_count DESC, total_payment DESC LIMIT 10""", (start_at, end_at)).fetchall()


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.guild and interaction.user.guild_permissions.administrator)


def has_chef_role(member: discord.Member) -> bool:
    role_id = get_config("chef_role_id")
    if not role_id.isdigit():
        return False
    return any(role.id == int(role_id) for role in member.roles)


def chef_allowed(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return is_admin(interaction) or has_chef_role(interaction.user)

async def get_text_channel(channel_id: Optional[int], fallback=None):
    if channel_id:
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel
    return fallback

async def require_admin(interaction: discord.Interaction) -> bool:
    if not is_admin(interaction):
        message = "🔒 This command is for **server administrators only**."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False
    return True

async def require_chef(interaction: discord.Interaction) -> bool:
    if not chef_allowed(interaction):
        await interaction.response.send_message("🐾 This command is for CAT Café chefs. Ask an administrator to assign you the configured **Chef** role.", ephemeral=True)
        return False
    return True


def safe_text(value: str, limit: int = 1000) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(value or "N/A"))[:limit]


def render_template(template: str, **values) -> str:
    # Only named placeholders are supported. Bad/missing placeholders won't crash the bot.
    try:
        return template.format(**values)[:1900]
    except (KeyError, ValueError, IndexError):
        return "Template has an unknown placeholder or invalid format. Ask an administrator to edit it with /set-template."


class TicketPanelView(discord.ui.View):
    def __init__(self, button_label: str = "Open a ticket"):
        super().__init__(timeout=None)
        # The custom ID stays stable so old panels keep working after restarts.
        self.open_ticket.label = (button_label or "Open a ticket")[:80]

    @discord.ui.button(label="Open a ticket", style=discord.ButtonStyle.primary, emoji="🎟️", custom_id="catcafe:ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Please use this button inside the server.", ephemeral=True)
            return

        with connect_db() as db:
            panel = db.execute(
                "SELECT * FROM ticket_panels WHERE message_id = ? AND guild_id = ?",
                (interaction.message.id, interaction.guild.id)
            ).fetchone()
            existing = db.execute(
                "SELECT channel_id FROM tickets WHERE guild_id = ? AND opener_id = ? AND status = 'open'",
                (interaction.guild.id, interaction.user.id)
            ).fetchone()

        if existing:
            existing_channel = interaction.guild.get_channel(existing["channel_id"])
            if existing_channel:
                await interaction.response.send_message(
                    f"You already have an open ticket: {existing_channel.mention}", ephemeral=True
                )
                return

        staff_role_id = (panel["staff_role_id"] if panel else get_config("ticket_staff_role_id")) or ""
        staff_role = interaction.guild.get_role(int(staff_role_id)) if staff_role_id.isdigit() else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if interaction.guild.me:
            overwrites[interaction.guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
            )
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        category_id = get_config("ticket_category_id")
        category = interaction.guild.get_channel(int(category_id)) if category_id.isdigit() else None
        try:
            channel = await interaction.guild.create_text_channel(
                name=f"ticket-{interaction.user.name}".lower().replace(" ", "-")[:90],
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                topic=f"CAT Café support ticket opened by {interaction.user} ({interaction.user.id})"
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need **Manage Channels** permission to create private tickets.", ephemeral=True
            )
            return
        except discord.HTTPException as error:
            await interaction.response.send_message(f"I couldn't create the ticket: {error}", ephemeral=True)
            return

        with connect_db() as db:
            db.execute(
                "INSERT OR REPLACE INTO tickets (channel_id, guild_id, opener_id, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (channel.id, interaction.guild.id, interaction.user.id, datetime.now(timezone.utc).isoformat())
            )

        ticket_title = panel["ticket_title"] if panel else "♡ CAT Café · Support Ticket ♡"
        ticket_message = panel["ticket_message"] if panel else "Hi {mention}! Please explain what you need help with, and a staff member will assist you. 🐾"
        try:
            message_text = render_template(
                ticket_message,
                mention=interaction.user.mention,
                member=safe_text(interaction.user.display_name),
                user_id=interaction.user.id,
                server=safe_text(interaction.guild.name),
                staff_role=staff_role.mention if staff_role else "the support team"
            )
            embed = discord.Embed(
                title=ticket_title[:256],
                description=message_text[:4000],
                color=discord.Color.from_rgb(245, 190, 215)
            )
            ping_content = f"{interaction.user.mention} {staff_role.mention if staff_role else ''}".strip()
            await channel.send(
                content=ping_content,
                embed=embed,
                view=TicketChannelView(),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False)
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                f"Your ticket channel was created: {channel.mention}, but I couldn't send the opening message. Check channel permissions.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(f"♡ Your private ticket is ready: {channel.mention}", ephemeral=True)


class TicketChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="catcafe:ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This can only be used in a server ticket.", ephemeral=True)
            return
        with connect_db() as db:
            ticket = db.execute(
                "SELECT opener_id, status FROM tickets WHERE channel_id = ? AND guild_id = ?",
                (interaction.channel_id, interaction.guild.id)
            ).fetchone()
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message("This ticket is already closed or isn't registered.", ephemeral=True)
            return
        if interaction.user.id != ticket["opener_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Only the person who opened this ticket or a server administrator can close it.", ephemeral=True
            )
            return
        with connect_db() as db:
            db.execute("UPDATE tickets SET status = 'closed' WHERE channel_id = ?", (interaction.channel_id,))
        opener = interaction.guild.get_member(ticket["opener_id"])
        try:
            if opener:
                await interaction.channel.set_permissions(opener, view_channel=False, send_messages=False)
            await interaction.channel.edit(name=f"closed-{interaction.channel.name}"[:100])
        except discord.HTTPException:
            pass
        await interaction.response.send_message("🔒 This ticket has been closed. An administrator can delete the channel when appropriate.")


class ChefBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(TicketPanelView())
        self.add_view(TicketChannelView())
        if GUILD_ID and GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print("Slash commands synced to your configured test server!")
        else:
            await self.tree.sync()
            print("Global slash commands synced; new commands can take a while to appear.")

intents = discord.Intents.default()
intents.members = True
intents.reactions = True
bot = ChefBot(command_prefix="!", intents=intents)

# Invite usage snapshots let us detect which invite was used when a member joins.
invite_cache: dict[int, dict[str, int]] = {}

async def refresh_invite_cache(guild: discord.Guild):
    try:
        invites = await guild.invites()
        invite_cache[guild.id] = {invite.code: (invite.uses or 0) for invite in invites}
    except (discord.Forbidden, discord.HTTPException) as error:
        # Invite tracking needs the bot to have Manage Server permission.
        print(f"Could not read invites for {guild.name}; invite tracking may be unavailable: {error}")


@bot.event
async def on_ready():
    print(f"CAT Café bot online as {bot.user}")
    for guild in bot.guilds:
        await refresh_invite_cache(guild)


@bot.event
async def on_member_join(member: discord.Member):
    inviter = await find_inviter(member.guild)
    member_count = member.guild.member_count or len(member.guild.members)
    welcome_id = get_channel_id("welcome_channel")
    if welcome_id:
        channel = await get_text_channel(welcome_id)
        if channel and hasattr(channel, "send"):
            template = get_config("template_welcome", DEFAULT_TEMPLATES["welcome"])
            message = render_template(
                template, server=safe_text(member.guild.name), member=safe_text(member.display_name),
                mention=member.mention, user_id=member.id, inviter=inviter,
                member_count=member_count, dot=DOT_EMOJI
            )
            try:
                await channel.send(message)
            except discord.HTTPException as error:
                print(f"Could not send welcome message: {error}")
    await send_member_log(member.guild, "join", member, inviter=inviter, member_count=member_count)


@bot.event
async def on_member_remove(member: discord.Member):
    await send_member_log(member.guild, "leave", member, member_count=member.guild.member_count or 0)


async def handle_reaction_role(payload: discord.RawReactionActionEvent, add: bool):
    if not payload.guild_id or not payload.member and add:
        return
    emoji_key = str(payload.emoji)
    with connect_db() as db:
        row = db.execute(
            "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (payload.guild_id, payload.message_id, emoji_key)
        ).fetchone()
    if not row:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = payload.member if add else guild.get_member(payload.user_id)
    if not isinstance(member, discord.Member) or member.bot:
        return
    role = guild.get_role(row["role_id"])
    if not role:
        return
    try:
        if add:
            await member.add_roles(role, reason="CAT Café reaction role")
        else:
            await member.remove_roles(role, reason="CAT Café reaction role removed")
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"Couldn't update reaction role {role.id}: {error}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_reaction_role(payload, True)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_reaction_role(payload, False)


async def find_inviter(guild: discord.Guild) -> str:
    """Detect an invite whose use count increased; may be unknown for vanity/one-use edge cases."""
    old_uses = invite_cache.get(guild.id, {})
    try:
        invites = await guild.invites()
        used_invite = None
        current = {}
        for invite in invites:
            uses = invite.uses or 0
            current[invite.code] = uses
            if uses > old_uses.get(invite.code, 0):
                used_invite = invite
        invite_cache[guild.id] = current
        if used_invite and used_invite.inviter:
            return safe_text(used_invite.inviter.display_name)
        return "Unknown (invite could not be identified)"
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"Could not identify inviter in {guild.name}: {error}")
        return "Unknown (bot needs Manage Server permission)"


async def send_member_log(guild: discord.Guild, event: str, member: discord.Member, inviter: str = "Unknown", member_count: int = 0):
    channel_id = get_channel_id("member_log_channel")
    if not channel_id:
        return
    channel = await get_text_channel(channel_id)
    if not channel or not hasattr(channel, "send"):
        return
    if event == "leave":
        template = get_config("template_leave", DEFAULT_TEMPLATES["leave"])
        message = render_template(template, server=safe_text(guild.name), member=safe_text(member.display_name), mention=member.mention, user_id=member.id, member_count=member_count, inviter=inviter, dot=DOT_EMOJI)
    else:
        template = get_config("template_join", DEFAULT_TEMPLATES["join"])
        message = render_template(template, server=safe_text(guild.name), member=safe_text(member.display_name), mention=member.mention, user_id=member.id, member_count=member_count, inviter=inviter, dot=DOT_EMOJI)
    try:
        await channel.send(message)
    except discord.HTTPException as error:
        print(f"Could not send member entry/exit log: {error}")


@bot.tree.command(name="log-order", description="Log a completed CAT Café chef order")
@app_commands.describe(client="The customer who placed the order", payment="Payment received in Bloxburg cash", notes="Optional notes", test_mode="Practice order excluded from real statistics")
async def log_order(interaction: discord.Interaction, client: discord.Member, payment: app_commands.Range[int, 0, 2_000_000_000], notes: str = "N/A", test_mode: bool = False):
    if not await require_chef(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    chef = interaction.user
    completed_at = datetime.now(timezone.utc)
    date_text = completed_at.astimezone().strftime("%B %d, %Y")
    with connect_db() as db:
        server_number = None
        if not test_mode:
            db.execute("UPDATE bot_settings SET setting_value = setting_value + 1 WHERE setting_key = 'server_order_counter'")
            server_number = db.execute("SELECT setting_value FROM bot_settings WHERE setting_key = 'server_order_counter'").fetchone()[0]
        cursor = db.execute("INSERT INTO orders (chef_id, client_id, payment, notes, completed_at, is_test, server_order_number) VALUES (?, ?, ?, ?, ?, ?, ?)", (chef.id, client.id, payment, notes, completed_at.isoformat(), int(test_mode), server_number))
        order_id = cursor.lastrowid
    order_count, _ = get_chef_stats(chef.id)
    if test_mode:
        content = f"🧪 **TEST ORDER — excluded from stats**\n{CAFE_TITLE}\n{ORDER_SUBTITLE}\n\n{DOT_EMOJI} Chef: {chef.mention}\n{DOT_EMOJI} Customer: {client.mention}\n{DOT_EMOJI} Payment: **{payment:,}** Bloxburg cash\n{DOT_EMOJI} Notes: {safe_text(notes)}\n{DOT_EMOJI} Date: {date_text}\n\n-# Practice order; no server order number used."
    else:
        template = get_config("template_order", DEFAULT_TEMPLATES["order"])
        content = render_template(template, cafe_title=CAFE_TITLE, order_subtitle=ORDER_SUBTITLE, sparkle=SPARKLE_EMOJI, dot=DOT_EMOJI, dance=DANCE_EMOJI, chef=chef.mention, customer=client.mention, payment=payment, notes=safe_text(notes), date=date_text, chef_orders=order_count, order_number=server_number)
    channel = await get_text_channel(get_channel_id("order_channel"), interaction.channel)
    try:
        if channel is None or not hasattr(channel, "send"):
            raise RuntimeError("Order log channel not found")
        await channel.send(content)
    except (discord.HTTPException, RuntimeError) as error:
        await interaction.followup.send(f"Order **#{order_id}** was saved, but I couldn't post the log. Check the configured order-log channel and bot permissions.", ephemeral=True)
        print(f"Could not post order #{order_id}: {error}")
        return
    await interaction.followup.send(f"♡ Order **#{order_id}** logged! Your real completed-order count is **{order_count}**.", ephemeral=True)


@bot.tree.command(name="stats", description="View a chef's all-time order stats (defaults to you)")
@app_commands.describe(chef="Optional chef to check")
async def stats(interaction: discord.Interaction, chef: Optional[discord.Member] = None):
    if not await require_chef(interaction):
        return
    chef = chef or interaction.user
    count, total = get_chef_stats(chef.id)
    embed = discord.Embed(title="♡ CAT Café · Chef Statistics ♡", color=discord.Color.from_rgb(245, 190, 215), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🐾 Chef", value=chef.mention, inline=False)
    embed.add_field(name="✨ Completed orders", value=f"**{count:,}**", inline=True)
    embed.add_field(name="💸 Recorded payments", value=f"**{total:,}** Bloxburg cash", inline=True)
    embed.set_footer(text="Practice orders are not included.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="my-orders", description="View your 10 most recent real orders")
async def my_orders(interaction: discord.Interaction):
    if not await require_chef(interaction):
        return
    with connect_db() as db:
        rows = db.execute("SELECT id, client_id, payment, notes, completed_at FROM orders WHERE chef_id = ? AND is_test = 0 ORDER BY id DESC LIMIT 10", (interaction.user.id,)).fetchall()
    embed = discord.Embed(title="♡ Your Recent CAT Café Orders ♡", color=discord.Color.from_rgb(245, 190, 215))
    if not rows:
        embed.description = "You haven't logged any real orders yet! 🐾"
    else:
        for row in rows:
            date_value = datetime.fromisoformat(row["completed_at"]).astimezone().strftime("%b %d, %Y")
            notes = safe_text(row["notes"], 250)
            embed.add_field(name=f"Order #{row['id']} · {date_value}", value=f"{DOT_EMOJI} Customer: <@{row['client_id']}>\n{DOT_EMOJI} Payment: **{row['payment']:,}** cash\n{DOT_EMOJI} Notes: {notes}", inline=False)
    embed.set_footer(text="Only real orders are shown.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def send_leaderboard(interaction: discord.Interaction, period: str = "all"):
    if period == "all":
        with connect_db() as db:
            rows = db.execute("SELECT chef_id, COUNT(*) AS order_count, COALESCE(SUM(payment), 0) AS total_payment FROM orders WHERE is_test = 0 GROUP BY chef_id ORDER BY order_count DESC, total_payment DESC LIMIT 10").fetchall()
        label = "All-Time Chef Leaderboard"
    else:
        rows = get_period_leaderboard(period)
        label = "Weekly Chef Leaderboard (Mon–Sun)" if period == "week" else "Monthly Chef Leaderboard"
    embed = discord.Embed(title=f"♡ CAT Café · {label} ♡", color=discord.Color.from_rgb(245, 190, 215))
    if not rows:
        embed.description = "No real orders have been logged for this period yet! 🐾"
    else:
        medals = ["🥇", "🥈", "🥉"]
        embed.description = "\n".join(f"{medals[i-1] if i <= 3 else f'**{i}.**'} <@{row['chef_id']}> — **{row['order_count']} orders** · {row['total_payment']:,} cash" for i, row in enumerate(rows, start=1))
    embed.set_footer(text="Practice orders are not included.")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the all-time top chefs")
async def leaderboard(interaction: discord.Interaction):
    await send_leaderboard(interaction, "all")


@bot.tree.command(name="weekly-orders", description="Show the weekly leaderboard or one chef's weekly stats")
@app_commands.describe(chef="Optional chef to check instead of the leaderboard")
async def weekly_orders(interaction: discord.Interaction, chef: Optional[discord.Member] = None):
    if chef:
        if not await require_chef(interaction): return
        start, end = get_period_bounds("week")
        with connect_db() as db:
            row = db.execute("SELECT COUNT(*) AS order_count, COALESCE(SUM(payment), 0) AS total_payment FROM orders WHERE chef_id = ? AND is_test = 0 AND completed_at >= ? AND completed_at < ?", (chef.id, start, end)).fetchone()
        embed = discord.Embed(title="♡ CAT Café · Weekly Chef Stats ♡", color=discord.Color.from_rgb(245, 190, 215))
        embed.add_field(name="Chef", value=chef.mention, inline=False)
        embed.add_field(name="Orders this week", value=str(row["order_count"]), inline=True)
        embed.add_field(name="Payments", value=f"{row['total_payment']:,} cash", inline=True)
        await interaction.response.send_message(embed=embed)
    else:
        await send_leaderboard(interaction, "week")


@bot.tree.command(name="monthly-orders", description="Show the monthly leaderboard or one chef's monthly stats")
@app_commands.describe(chef="Optional chef to check instead of the leaderboard")
async def monthly_orders(interaction: discord.Interaction, chef: Optional[discord.Member] = None):
    if chef:
        if not await require_chef(interaction): return
        start, end = get_period_bounds("month")
        with connect_db() as db:
            row = db.execute("SELECT COUNT(*) AS order_count, COALESCE(SUM(payment), 0) AS total_payment FROM orders WHERE chef_id = ? AND is_test = 0 AND completed_at >= ? AND completed_at < ?", (chef.id, start, end)).fetchone()
        embed = discord.Embed(title="♡ CAT Café · Monthly Chef Stats ♡", color=discord.Color.from_rgb(245, 190, 215))
        embed.add_field(name="Chef", value=chef.mention, inline=False)
        embed.add_field(name="Orders this month", value=str(row["order_count"]), inline=True)
        embed.add_field(name="Payments", value=f"{row['total_payment']:,} cash", inline=True)
        await interaction.response.send_message(embed=embed)
    else:
        await send_leaderboard(interaction, "month")


@bot.tree.command(name="cafe-stats", description="View overall CAT Café totals")
async def cafe_stats(interaction: discord.Interaction):
    if not await require_chef(interaction): return
    with connect_db() as db:
        row = db.execute("SELECT COUNT(*) AS order_count, COALESCE(SUM(payment), 0) AS total_payment, COUNT(DISTINCT chef_id) AS active_chefs FROM orders WHERE is_test = 0").fetchone()
    embed = discord.Embed(title="♡ CAT Café · Café Statistics ♡", color=discord.Color.from_rgb(245, 190, 215))
    embed.add_field(name="🐾 Chefs with orders", value=str(row["active_chefs"]), inline=True)
    embed.add_field(name="✨ Total orders", value=f"{row['order_count']:,}", inline=True)
    embed.add_field(name="💸 Total recorded payments", value=f"{row['total_payment']:,} cash", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="order-total", description="Calculate a Bloxburg order total with a discount")
@app_commands.describe(full_plates="Number of full plates at 250 cash each", quick_meals="Number of quick meals at 150 cash each", discount_percent="Discount percentage")
@app_commands.choices(discount_percent=[app_commands.Choice(name="No discount (0%)", value=0), app_commands.Choice(name="10% discount", value=10), app_commands.Choice(name="20% discount", value=20), app_commands.Choice(name="30% discount", value=30), app_commands.Choice(name="50% discount", value=50)])
async def order_total(interaction: discord.Interaction, full_plates: app_commands.Range[int, 0, 10000], quick_meals: app_commands.Range[int, 0, 10000], discount_percent: app_commands.Choice[int]):
    subtotal = full_plates * 250 + quick_meals * 150
    discount_amount = subtotal * discount_percent.value // 100
    final_total = subtotal - discount_amount
    embed = discord.Embed(title="♡ CAT Café · Order Calculator ♡", color=discord.Color.from_rgb(245, 190, 215))
    embed.add_field(name="🍽️ Full plates", value=f"{full_plates} × 250 = **{full_plates * 250:,}**", inline=True)
    embed.add_field(name="🥡 Quick meals", value=f"{quick_meals} × 150 = **{quick_meals * 150:,}**", inline=True)
    embed.add_field(name="Subtotal", value=f"**{subtotal:,}** Bloxburg cash", inline=False)
    embed.add_field(name=f"Discount ({discount_percent.value}%)", value=f"−**{discount_amount:,}**", inline=True)
    embed.add_field(name="♡ FINAL TOTAL ♡", value=f"**{final_total:,} Bloxburg cash**", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="menu", description="View the CAT Café menu")
async def menu(interaction: discord.Interaction):
    embed = discord.Embed(title="♡ CAT Café · Menu ♡", description="A little something tasty for every guest! 🐾", color=discord.Color.from_rgb(245, 190, 215))
    embed.add_field(name="🍽️ Full Plate", value="**250 Bloxburg cash**", inline=True)
    embed.add_field(name="🥡 Quick Meal", value="**150 Bloxburg cash**", inline=True)
    embed.set_footer(text="Use /order-total to calculate a bill with a discount!")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="review", description="Review a specific CAT Café chef")
@app_commands.describe(chef="The chef you are reviewing", rating="Your rating from 1 to 5 stars", comment="Tell us about your experience with this chef")
@app_commands.choices(rating=[app_commands.Choice(name="⭐ 1 star", value=1), app_commands.Choice(name="⭐⭐ 2 stars", value=2), app_commands.Choice(name="⭐⭐⭐ 3 stars", value=3), app_commands.Choice(name="⭐⭐⭐⭐ 4 stars", value=4), app_commands.Choice(name="⭐⭐⭐⭐⭐ 5 stars", value=5)])
async def review(interaction: discord.Interaction, chef: discord.Member, rating: app_commands.Choice[int], comment: str):
    if chef.bot:
        await interaction.response.send_message("Please choose a real chef, not a bot account.", ephemeral=True)
        return
    created = datetime.now(timezone.utc)
    with connect_db() as db:
        db.execute("INSERT INTO reviews (reviewer_id, rating, comment, created_at, chef_id) VALUES (?, ?, ?, ?, ?)", (interaction.user.id, rating.value, comment, created.isoformat(), chef.id))
    template = get_config("template_review", DEFAULT_TEMPLATES["review"])
    message = render_template(
        template, dot=DOT_EMOJI, mention=interaction.user.mention,
        member=safe_text(interaction.user.display_name), chef=safe_text(chef.display_name),
        chef_mention=chef.mention, chef_id=chef.id, server=safe_text(interaction.guild.name if interaction.guild else "CAT Café"),
        stars="⭐" * rating.value, rating=rating.value, comment=safe_text(comment)
    )
    channel = await get_text_channel(get_channel_id("review_channel"), interaction.channel)
    try:
        if channel is None or not hasattr(channel, "send"): raise RuntimeError("Review channel not found")
        await channel.send(message, allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False))
    except (discord.HTTPException, RuntimeError) as error:
        await interaction.response.send_message("Your review was saved, but I couldn't post it. Ask an administrator to check the review channel.", ephemeral=True)
        print(f"Could not post review: {error}")
        return
    await interaction.response.send_message(f"♡ Thank you for reviewing {chef.display_name}! Your feedback helps us recognize our chefs. 💗", ephemeral=True)


@bot.tree.command(name="edit-order", description="Edit a saved order (administrator only)")
@app_commands.describe(order_id="Saved database order ID", client="New customer (optional)", payment="New payment (optional)", notes="New notes (optional)")
async def edit_order(interaction: discord.Interaction, order_id: app_commands.Range[int, 1, 2_000_000_000], client: Optional[discord.Member] = None, payment: Optional[app_commands.Range[int, 0, 2_000_000_000]] = None, notes: Optional[str] = None):
    if not await require_admin(interaction): return
    if client is None and payment is None and notes is None:
        await interaction.response.send_message("Please provide at least one field to update.", ephemeral=True); return
    with connect_db() as db:
        row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            await interaction.response.send_message(f"Order **#{order_id}** wasn't found.", ephemeral=True); return
        db.execute("UPDATE orders SET client_id = ?, payment = ?, notes = ? WHERE id = ?", (client.id if client else row["client_id"], payment if payment is not None else row["payment"], notes if notes is not None else row["notes"], order_id))
    await interaction.response.send_message(f"♡ Order **#{order_id}** updated. Stats recalculate automatically.", ephemeral=True)


@bot.tree.command(name="delete-order", description="Delete one saved order record (administrator only)")
@app_commands.describe(order_id="Saved database order ID")
async def delete_order(interaction: discord.Interaction, order_id: app_commands.Range[int, 1, 2_000_000_000]):
    if not await require_admin(interaction): return
    with connect_db() as db:
        cursor = db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    if not cursor.rowcount:
        await interaction.response.send_message(f"Order **#{order_id}** wasn't found.", ephemeral=True); return
    await interaction.response.send_message(f"♡ Order record **#{order_id}** deleted. Stats and leaderboards recalculate automatically.", ephemeral=True)


@bot.tree.command(name="clear-chef-orders", description="Delete all order records for one chef (administrator only)")
@app_commands.describe(chef="Chef whose records should be cleared", confirm="Set to True to permanently delete the records")
async def clear_chef_orders(interaction: discord.Interaction, chef: discord.Member, confirm: bool = False):
    if not await require_admin(interaction): return
    if not confirm:
        await interaction.response.send_message(f"⚠️ This permanently deletes all saved orders for {chef.mention}, including test orders. Previously posted Discord messages remain. Run again with **confirm: True** to proceed.", ephemeral=True); return
    with connect_db() as db:
        cursor = db.execute("DELETE FROM orders WHERE chef_id = ?", (chef.id,))
    await interaction.response.send_message(f"♡ Cleared **{cursor.rowcount}** saved order records for {chef.mention}. Their stats are now reset; old Discord messages remain.", ephemeral=True)


@bot.tree.command(name="reset-server-orders", description="Reset displayed server order numbering (administrator only)")
@app_commands.describe(confirm="Set to True to confirm")
async def reset_server_orders(interaction: discord.Interaction, confirm: bool = False):
    if not await require_admin(interaction): return
    if not confirm:
        await interaction.response.send_message("⚠️ This resets only the displayed server order number for future logs to start at #1. It does not delete saved orders or reset chef stats. Run again with **confirm: True**.", ephemeral=True); return
    with connect_db() as db:
        db.execute("UPDATE bot_settings SET setting_value = 0 WHERE setting_key = 'server_order_counter'")
    await interaction.response.send_message("♡ Server order numbering reset! The next real order log will show **Server Order #1**. Saved history is unchanged.", ephemeral=True)


@bot.tree.command(name="set-chef-role", description="Set which Discord role is allowed to log orders and view staff stats (administrator only)")
@app_commands.describe(role="The server's Chef role")
async def set_chef_role(interaction: discord.Interaction, role: discord.Role):
    if not await require_admin(interaction): return
    set_config("chef_role_id", str(role.id))
    await interaction.response.send_message(f"♡ Chef role set to {role.mention}. Members with this role can use chef job commands.", ephemeral=True)


@bot.tree.command(name="set-cafe-channel", description="Configure a CAT Café bot channel (administrator only)")
@app_commands.describe(channel_type="Which channel to configure", channel="The channel to use")
@app_commands.choices(channel_type=[app_commands.Choice(name="Order logs", value="order_channel"), app_commands.Choice(name="Welcome messages", value="welcome_channel"), app_commands.Choice(name="Member join/leave log", value="member_log_channel"), app_commands.Choice(name="Chef reviews", value="review_channel")])
async def set_cafe_channel(interaction: discord.Interaction, channel_type: app_commands.Choice[str], channel: discord.TextChannel):
    if not await require_admin(interaction): return
    set_config(channel_type.value, str(channel.id))
    names = {"order_channel": "order logs", "welcome_channel": "welcome messages", "member_log_channel": "member join/leave logs", "review_channel": "chef reviews"}
    await interaction.response.send_message(f"♡ {names[channel_type.value].capitalize()} will now use {channel.mention}.", ephemeral=True)


@bot.tree.command(name="set-template", description="Customize a bot message template (administrator only)")
@app_commands.describe(template="Which message to customize", content="The full new message template")
@app_commands.choices(template=[app_commands.Choice(name="Welcome message", value="welcome"), app_commands.Choice(name="Join log", value="join"), app_commands.Choice(name="Leave message", value="leave"), app_commands.Choice(name="Order log", value="order"), app_commands.Choice(name="Review post", value="review")])
async def set_template(interaction: discord.Interaction, template: app_commands.Choice[str], content: str):
    if not await require_admin(interaction): return
    if len(content) > 1900:
        await interaction.response.send_message("Please keep the template under 1,900 characters so Discord can post it.", ephemeral=True); return
    set_config(f"template_{template.value}", content)
    await interaction.response.send_message(f"♡ The **{template.name}** template has been saved! Use `/preview-template` to check it.", ephemeral=True)


@bot.tree.command(name="preview-template", description="Preview a customizable bot message template (administrator only)")
@app_commands.describe(template="Which message to preview")
@app_commands.choices(template=[app_commands.Choice(name="Welcome message", value="welcome"), app_commands.Choice(name="Join log", value="join"), app_commands.Choice(name="Leave message", value="leave"), app_commands.Choice(name="Order log", value="order"), app_commands.Choice(name="Review post", value="review")])
async def preview_template(interaction: discord.Interaction, template: app_commands.Choice[str]):
    if not await require_admin(interaction): return
    defaults = DEFAULT_TEMPLATES[template.value]
    content = get_config(f"template_{template.value}", defaults)
    sample = render_template(content, server="CAT Café", member="Example Member", mention="@ExampleMember", user_id=123456, inviter="Example Inviter", member_count=123, dot=DOT_EMOJI, sparkle=SPARKLE_EMOJI, dance=DANCE_EMOJI, cafe_title=CAFE_TITLE, order_subtitle=ORDER_SUBTITLE, chef="Example Chef", chef_mention="@ExampleChef", chef_id=654321, customer="@ExampleCustomer", payment=500, notes="Example order", date="October 15, 2026", chef_orders=12, order_number=42, stars="⭐⭐⭐⭐⭐", rating=5, comment="Lovely service!")
    await interaction.response.send_message(f"**Preview: {template.name}**\n{sample}\n\nUse `/set-template` to change it.", ephemeral=True)


@bot.tree.command(name="reaction-role-panel", description="Create a reaction-role panel message (administrator only)")
@app_commands.describe(channel="Where the reaction-role panel should be posted", title="Panel title", description="Explain how members should choose roles")
async def reaction_role_panel(interaction: discord.Interaction, channel: discord.TextChannel, title: str = "♡ Choose Your Roles ♡", description: str = "React below to receive a role. Remove your reaction to remove the role. 🐾"):
    if not await require_admin(interaction):
        return
    embed = discord.Embed(title=title[:256], description=description[:4000], color=discord.Color.from_rgb(245, 190, 215))
    embed.set_footer(text="Administrators: use /reaction-role-add to connect emojis to roles.")
    try:
        message = await channel.send(embed=embed)
    except discord.HTTPException:
        await interaction.response.send_message("I couldn't post there. Check my channel permissions.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"♡ Reaction-role panel created in {channel.mention}! Its message ID is `{message.id}`. "
        "Next, run `/reaction-role-add` once for each emoji/role pair.", ephemeral=True
    )


@bot.tree.command(name="reaction-role-add", description="Connect a panel reaction to a role (administrator only)")
@app_commands.describe(message_id="ID of the reaction-role panel message", emoji="Emoji members should react with", role="Role to give/remove")
async def reaction_role_add(interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
    if not await require_admin(interaction):
        return
    if not message_id.isdigit():
        await interaction.response.send_message("Message ID must contain only numbers.", ephemeral=True)
        return
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("Run this command in the channel containing the reaction-role panel.", ephemeral=True)
        return
    try:
        message = await channel.fetch_message(int(message_id))
        await message.add_reaction(emoji)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InvalidArgument):
        await interaction.response.send_message(
            "I couldn't find that message or add that emoji. Run this command in the panel's channel and check my permissions/emoji.", ephemeral=True
        )
        return
    emoji_key = emoji
    # Store Discord's normalized emoji string so custom emoji and standard emoji match reactions.
    try:
        parsed = discord.PartialEmoji.from_str(emoji)
        emoji_key = str(parsed)
    except (ValueError, TypeError):
        pass
    with connect_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO reaction_roles (guild_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?)",
            (interaction.guild_id, int(message_id), emoji_key, role.id)
        )
    await interaction.response.send_message(
        f"♡ Reaction {emoji} now gives {role.mention} on panel message `{message_id}`. "
        "Make sure the bot's role is above the role it assigns.", ephemeral=True
    )


@bot.tree.command(name="reaction-role-remove", description="Remove a reaction-to-role mapping (administrator only)")
@app_commands.describe(message_id="Panel message ID", emoji="Emoji mapping to remove")
async def reaction_role_remove(interaction: discord.Interaction, message_id: str, emoji: str):
    if not await require_admin(interaction):
        return
    if not message_id.isdigit():
        await interaction.response.send_message("Message ID must contain only numbers.", ephemeral=True)
        return
    emoji_key = str(discord.PartialEmoji.from_str(emoji))
    with connect_db() as db:
        cursor = db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (interaction.guild_id, int(message_id), emoji_key)
        )
    await interaction.response.send_message(
        "♡ Reaction-role mapping removed." if cursor.rowcount else "I couldn't find that mapping.",
        ephemeral=True
    )


@bot.tree.command(name="ticket-panel", description="Create a customizable support-ticket panel (administrator only)")
@app_commands.describe(
    channel="Channel where the panel will be posted",
    title="Title shown on the public panel",
    description="Instructions shown on the public panel",
    button_label="Text on the open-ticket button",
    ticket_title="Title inside each new ticket",
    ticket_message="Message inside each new ticket; supports {mention}, {member}, {user_id}, {server}, {staff_role}",
    staff_role="Role to ping and give access to new tickets (optional; uses the default if omitted)"
)
async def ticket_panel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str = "♡ CAT Café Support ♡",
    description: str = "Need help? Click below to open a private ticket. A staff member will help you as soon as possible. 🐾",
    button_label: str = "Open a ticket",
    ticket_title: str = "♡ CAT Café · Support Ticket ♡",
    ticket_message: str = "Hi {mention}! Please explain what you need help with, and {staff_role} will assist you. 🐾",
    staff_role: Optional[discord.Role] = None
):
    if not await require_admin(interaction):
        return
    title = title[:256]
    description = description[:4000]
    button_label = button_label[:80] or "Open a ticket"
    ticket_title = ticket_title[:256]
    ticket_message = ticket_message[:4000]
    embed = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(245, 190, 215))
    embed.set_footer(text="Please open one ticket at a time.")
    try:
        message = await channel.send(embed=embed, view=TicketPanelView(button_label))
    except discord.HTTPException:
        await interaction.response.send_message("I couldn't post the ticket panel. Check my channel permissions.", ephemeral=True)
        return

    role_id = str(staff_role.id) if staff_role else get_config("ticket_staff_role_id")
    with connect_db() as db:
        db.execute(
            """INSERT OR REPLACE INTO ticket_panels
            (message_id, guild_id, channel_id, panel_title, panel_description, button_label, ticket_title, ticket_message, staff_role_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message.id, interaction.guild_id, channel.id, title, description, button_label, ticket_title, ticket_message, role_id)
        )
    await interaction.response.send_message(
        f"♡ Ticket panel posted in {channel.mention}!\nPanel message ID: `{message.id}`\n"
        "Save that ID if you want to edit this specific panel later.",
        ephemeral=True
    )


@bot.tree.command(name="edit-ticket-panel", description="Edit an existing ticket panel and its ticket messages (administrator only)")
@app_commands.describe(
    message_id="Message ID of the ticket panel to edit",
    title="New public panel title",
    description="New public panel instructions",
    button_label="New button text",
    ticket_title="New title inside tickets",
    ticket_message="New opening message; supports {mention}, {member}, {user_id}, {server}, {staff_role}",
    staff_role="Role to ping and give access to new tickets; choose the role you want"
)
async def edit_ticket_panel(
    interaction: discord.Interaction,
    message_id: app_commands.Range[int, 1, 2_147_483_647],
    title: str,
    description: str,
    button_label: str,
    ticket_title: str,
    ticket_message: str,
    staff_role: Optional[discord.Role] = None
):
    if not await require_admin(interaction):
        return
    with connect_db() as db:
        panel = db.execute(
            "SELECT * FROM ticket_panels WHERE message_id = ? AND guild_id = ?",
            (message_id, interaction.guild_id)
        ).fetchone()
    if not panel:
        await interaction.response.send_message(
            "I couldn't find a saved panel with that message ID. It may be an older panel; create a new one with `/ticket-panel`.",
            ephemeral=True
        )
        return
    channel = interaction.guild.get_channel(panel["channel_id"]) if interaction.guild else None
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("I couldn't find the channel containing that panel.", ephemeral=True)
        return
    try:
        message = await channel.fetch_message(message_id)
        title = title[:256]
        description = description[:4000]
        button_label = button_label[:80] or "Open a ticket"
        ticket_title = ticket_title[:256]
        ticket_message = ticket_message[:4000]
        embed = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(245, 190, 215))
        embed.set_footer(text="Please open one ticket at a time.")
        await message.edit(embed=embed, view=TicketPanelView(button_label))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        await interaction.response.send_message("I couldn't edit that panel. Check the message ID and bot permissions.", ephemeral=True)
        return
    role_id = str(staff_role.id) if staff_role else panel["staff_role_id"]
    with connect_db() as db:
        db.execute(
            """UPDATE ticket_panels SET panel_title=?, panel_description=?, button_label=?,
            ticket_title=?, ticket_message=?, staff_role_id=? WHERE message_id=? AND guild_id=?""",
            (title, description, button_label, ticket_title, ticket_message, role_id, message_id, interaction.guild_id)
        )
    await interaction.response.send_message(
        f"♡ Updated ticket panel `{message_id}`! Future tickets from this panel will use the new message and staff role.",
        ephemeral=True
    )


@bot.tree.command(name="set-ticket-staff-role", description="Set the default staff role for ticket access and pings (administrator only)")
@app_commands.describe(role="Support role that can see new tickets and will be pinged")
async def set_ticket_staff_role(interaction: discord.Interaction, role: discord.Role):
    if not await require_admin(interaction):
        return
    set_config("ticket_staff_role_id", str(role.id))
    await interaction.response.send_message(
        f"♡ Default ticket staff role set to {role.mention}. New panels will use this role unless you select another role.",
        ephemeral=True
    )

@bot.tree.command(name="set-ticket-category", description="Choose the category where private tickets are created (administrator only)")
@app_commands.describe(category="Category to hold new tickets")
async def set_ticket_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    if not await require_admin(interaction):
        return
    set_config("ticket_category_id", str(category.id))
    await interaction.response.send_message(f"♡ New tickets will be created in **{category.name}**.", ephemeral=True)



@bot.tree.command(name="setup-guide", description="Show the CAT Café bot setup guide")
async def setup_guide(interaction: discord.Interaction):
    embed = discord.Embed(
        title="♡ CAT Café · Setup Guide ♡",
        description="Follow these steps to configure the bot. Setup commands are administrator-only.",
        color=discord.Color.from_rgb(245, 190, 215)
    )
    embed.add_field(
        name="1 · Staff and channels",
        value="`/set-chef-role` — choose your Chef role.\n`/set-cafe-channel` — set order logs, welcome, member join/leave, and review channels.",
        inline=False
    )
    embed.add_field(
        name="2 · Editable messages",
        value="`/set-template` — edit the welcome, join, leave, order-log, or chef-review message.\n`/preview-template` — preview your saved template before relying on it.",
        inline=False
    )
    embed.add_field(
        name="3 · Reaction roles",
        value="`/reaction-role-panel` — post a panel.\nThen run `/reaction-role-add` for each role, using the panel message ID and the matching emoji. Run `/reaction-role-remove` to remove a mapping. The bot needs Manage Roles, and its top role must be above every role it assigns.",
        inline=False
    )
    embed.add_field(
        name="4 · Tickets",
        value="`/ticket-panel` — create a panel with editable public text, button text, opening-ticket title/message, and staff role ping.\n`/edit-ticket-panel` — edit a saved panel by its message ID.\n`/set-ticket-category` — choose a category; `/set-ticket-staff-role` — set the default staff role to ping and grant access. The bot needs Manage Channels and send/view permissions.",
        inline=False
    )
    embed.add_field(
        name="5 · Order logs",
        value="`/set-template` → **Order log** lets you edit the order log's text. Keep placeholders such as `{chef}`, `{customer}`, `{payment}`, `{notes}`, `{date}`, `{chef_orders}`, and `{order_number}` if you want those details to appear.",
        inline=False
    )
    embed.set_footer(text="Keep your .env and bot token private. Never delete orders.db when updating the bot.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="help", description="Show CAT Café bot commands and setup tips")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="♡ CAT Café · Bot Help ♡", color=discord.Color.from_rgb(245, 190, 215))
    embed.add_field(name="🐾 Chef commands", value="`/log-order` · Save a completed order\n`/stats` · View chef stats\n`/my-orders` · View your recent orders\n`/leaderboard` · All-time rankings\n`/weekly-orders` · Weekly rankings or a chef's stats\n`/monthly-orders` · Monthly rankings or a chef's stats\n`/cafe-stats` · Café-wide totals", inline=False)
    embed.add_field(name="🍰 Guest commands", value="`/menu` · View prices\n`/order-total` · Calculate a bill\n`/review` · Review a specific chef", inline=False)
    embed.add_field(name="🎭 Reaction roles and tickets", value="`/reaction-role-panel` · Post a reaction-role panel\n`/reaction-role-add` / `/reaction-role-remove` · Connect emojis to roles\n`/ticket-panel` · Create customizable ticket panels\n`/edit-ticket-panel` · Edit an existing panel and its opening message\n`/set-ticket-category` · Choose a ticket category\n`/set-ticket-staff-role` · Set default staff access and ping role", inline=False)
    embed.add_field(name="🔒 Administrator commands", value="`/set-chef-role` · Choose the Chef role\n`/set-cafe-channel` · Set order, welcome, member-log, and review channels\n`/set-template` · Customize welcome, join log, leave, order, and review messages\n`/preview-template` · Preview a template\n`/setup-guide` · Step-by-step setup instructions\n`/edit-order`, `/delete-order`, `/clear-chef-orders`, `/reset-server-orders` · Manage records and numbering", inline=False)
    embed.set_footer(text="Only server administrators can use setup and destructive commands.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN. Add it to your private .env file first.")
    setup_database()
    bot.run(TOKEN)

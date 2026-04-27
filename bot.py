"""
jji Squad Discord Bot
Discord bot for gaming community
Developed by NaveL for jji
"""

import os
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from src.services.database import db
from src.services.cache import cache
from src.services.economy_logger import EconomyLogger, EconomyAction, economy_logger
from src.models.database import TransactionType, ServerEconomy, User, Transaction, VoiceSession
from src.utils.helpers import load_config, save_config, is_prime_time, format_balance, get_standard_footer
from src.utils.logger import setup_logging, DiscordLogger
from src.utils.metrics import metrics
import logging

_bot_logger = logging.getLogger("jji.sb")

# ═══════════════════════════════════════════════
#  DM Ping Cooldown (seconds)
# ═══════════════════════════════════════════════
DM_PING_COOLDOWN = 900   # 15 minutes between DM pings per user
DM_SEND_DELAY = 0.35     # delay between each DM to avoid rate limits


# ═══════════════════════════════════════════════
#  SB Assembly View — persistent panel with DM Ping button
# ═══════════════════════════════════════════════

class SBAssemblyView(discord.ui.View):
    """Persistent view attached to SB assembly messages with DM Ping button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="DM Ping",
        style=discord.ButtonStyle.primary,
        emoji="📨",
        custom_id="sb:dm_ping",
    )
    async def dm_ping_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal for DM ping message."""
        bot: JJIBot = interaction.client  # type: ignore
        config = bot.config

        # Only sergeant/admin/developer can use (officers excluded)
        sergeant_role_id = config.get("roles", {}).get("sergeant")
        admin_role_id = config.get("roles", {}).get("admin")
        developer_id = config.get("developer_id")
        member_role_ids = [r.id for r in interaction.user.roles]

        is_authorized = (
            interaction.user.id == developer_id
            or (sergeant_role_id and sergeant_role_id in member_role_ids)
            or (admin_role_id and admin_role_id in member_role_ids)
        )
        if not is_authorized:
            embed = discord.Embed(
                title="❌ Access Denied",
                description="Only **Sergeants** and **Admins** can send DM pings.",
                color=0xFF3333,
            )
            embed.set_footer(text=get_standard_footer())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check cooldown via Redis
        on_cd, ttl = await cache.check_cooldown(interaction.user.id, "sb_dm_ping")
        if on_cd:
            embed = discord.Embed(
                title="⏳ Cooldown",
                description=f"You can send next DM ping in **{ttl}s**.",
                color=0xFFAA00,
            )
            embed.set_footer(text=get_standard_footer())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Extract squad number from the embed title
        squad_num = "?"
        if interaction.message and interaction.message.embeds:
            title = interaction.message.embeds[0].title or ""
            # "📢 SQUADRON ASSEMBLY!" or "📢 SOLDIERS NEEDED!" — look at description
            desc = interaction.message.embeds[0].description or ""
            # "**Squadron #3** is forming up!"
            import re
            m = re.search(r"Squadron #(\d+)", desc)
            if m:
                squad_num = m.group(1)

        # Show modal
        modal = SBDmPingModal(squad_num=squad_num)
        await interaction.response.send_modal(modal)


class SBDmPingModal(discord.ui.Modal, title="📨 DM Ping — Message"):
    """Modal for entering custom DM ping message."""

    message = discord.ui.TextInput(
        label="Message to soldiers",
        style=discord.TextStyle.paragraph,
        placeholder="Join Squadron Battles now! We need you!",
        default="We're forming up for Squadron Battles — join us for salary and fun!",
        max_length=1500,
        required=True,
    )

    def __init__(self, squad_num: str = "?"):
        super().__init__()
        self.squad_num = squad_num

    async def on_submit(self, interaction: discord.Interaction):
        bot: JJIBot = interaction.client  # type: ignore
        config = bot.config
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        soldier_role_id = config.get("roles", {}).get("soldier")
        if not soldier_role_id:
            embed = discord.Embed(
                title="❌ No Soldier Role",
                description="Soldier role is not configured. Use `/sb_config` to set it up.",
                color=0xFF3333,
            )
            embed.set_footer(text=get_standard_footer())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        soldier_role = guild.get_role(soldier_role_id)
        if not soldier_role:
            embed = discord.Embed(
                title="❌ Role Not Found",
                description="Soldier role not found on this server.",
                color=0xFF3333,
            )
            embed.set_footer(text=get_standard_footer())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Collect targets: soldiers NOT already in SB voice channels
        sb_voice_members = set()
        for ch in guild.voice_channels:
            if ch.name.startswith("SB #") or ch.name.startswith("Squadron Battle #"):
                for m in ch.members:
                    sb_voice_members.add(m.id)

        targets = [
            m for m in soldier_role.members
            if not m.bot and m.id not in sb_voice_members and m.id != interaction.user.id
        ]

        if not targets:
            embed = discord.Embed(
                title="📭 No Targets",
                description="All soldiers are already in Squadron Battle channels or offline with DMs closed.",
                color=0xFFAA00,
            )
            embed.set_footer(text=get_standard_footer())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Preview
        custom_text = self.message.value
        preview = discord.Embed(
            title="📨 DM Ping Preview",
            description=f"Will send to **{len(targets)}** soldier(s).\n\n"
                        f"**Message:**\n>>> {custom_text[:500]}",
            color=0x3498DB,
        )
        preview.set_footer(text=get_standard_footer())

        confirm_view = SBDmPingConfirmView(
            targets=targets,
            custom_text=custom_text,
            squad_num=self.squad_num,
            sender=interaction.user,
        )
        await interaction.followup.send(embed=preview, view=confirm_view, ephemeral=True)


class SBDmPingConfirmView(discord.ui.View):
    """Confirm / Cancel DM ping delivery."""

    def __init__(self, targets: list, custom_text: str, squad_num: str, sender):
        super().__init__(timeout=120)
        self.targets = targets
        self.custom_text = custom_text
        self.squad_num = squad_num
        self.sender = sender

    @discord.ui.button(label="Send", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sender.id:
            await interaction.response.send_message("Only the sender can confirm.", ephemeral=True)
            return

        await interaction.response.defer()

        # Set cooldown
        await cache.set_cooldown(interaction.user.id, "sb_dm_ping", DM_PING_COOLDOWN)

        # Disable buttons
        for child in self.children:
            child.disabled = True  # type: ignore
        progress_embed = discord.Embed(
            title="📨 Sending DMs…",
            description=f"0 / {len(self.targets)}",
            color=0x3498DB,
        )
        progress_embed.set_footer(text=get_standard_footer())
        await interaction.edit_original_response(embed=progress_embed, view=self)

        guild = interaction.guild
        delivered = 0
        failed = 0

        dm_embed = discord.Embed(
            title=f"📢 Squadron #{self.squad_num} — Join Now!",
            description=self.custom_text,
            color=0xFF6600,
        )
        dm_embed.add_field(
            name="💰 Salary",
            value="You earn money while playing in SB!",
            inline=True,
        )
        dm_embed.add_field(
            name="🏠 Server",
            value=guild.name if guild else "JJI",
            inline=True,
        )
        dm_embed.set_footer(text=get_standard_footer())

        for i, target in enumerate(self.targets, 1):
            try:
                await target.send(embed=dm_embed)
                delivered += 1
            except Exception:
                failed += 1

            if i % 5 == 0:
                try:
                    progress_embed.description = f"{i} / {len(self.targets)}"
                    await interaction.edit_original_response(embed=progress_embed)
                except Exception:
                    pass

            await asyncio.sleep(DM_SEND_DELAY)

        # Final report
        report = discord.Embed(
            title="📨 DM Ping Complete",
            description=f"✅ Delivered: **{delivered}**\n❌ Failed: **{failed}**",
            color=0x2ECC71 if failed == 0 else 0xFFAA00,
        )
        report.set_footer(text=get_standard_footer())
        await interaction.edit_original_response(embed=report, view=None)
        _bot_logger.info(f"DM ping SB #{self.squad_num}: {delivered} delivered, {failed} failed (by {self.sender})")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sender.id:
            await interaction.response.send_message("Only the sender can cancel.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True  # type: ignore
        cancel_embed = discord.Embed(
            title="❌ DM Ping Cancelled",
            description="No messages were sent.",
            color=0x95A5A6,
        )
        cancel_embed.set_footer(text=get_standard_footer())
        await interaction.response.edit_message(embed=cancel_embed, view=self)


# Load environment
load_dotenv()

# Constants
TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_WEBHOOK = os.getenv("LOG_WEBHOOK_URL")
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "8000"))


class JJIBot(commands.Bot):
    """Main bot class"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        intents.message_content = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        
        self.config = load_config()
        self.logger = setup_logging(LOG_LEVEL, "logs/bot.log", LOG_WEBHOOK)
        self.discord_logger = None
        self.start_time = datetime.now(timezone.utc)
        
        # SB channel monitoring: {channel_id: {"last_ping": datetime, "commander_id": int}}
        self.sb_channels: dict[int, dict] = {}
    
    async def setup_hook(self):
        """Setup hook called before bot starts"""
        self.logger.info("Starting JJI Bot...")
        
        # Register persistent views (survive bot restarts)
        self.add_view(SBAssemblyView())
        
        # Initialize database
        await db.init_db()
        self.logger.info("Database initialized")
        
        # Connect to Redis
        redis_connected = await cache.connect()
        if redis_connected:
            self.logger.info("Redis connected")
        else:
            self.logger.warning("Redis not available, running without cache")
        
        # Start Prometheus metrics
        try:
            metrics.start_server(PROMETHEUS_PORT)
            self.logger.info(f"Prometheus metrics on port {PROMETHEUS_PORT}")
        except Exception as e:
            self.logger.warning(f"Prometheus failed: {e}")
        
        # Load cogs
        cogs = [
            "src.cogs.economy",
            "src.cogs.profile",
            "src.cogs.games",
            "src.cogs.marketplace",
            "src.cogs.officer",
            "src.cogs.admin",
            "src.cogs.faq",
            "src.cogs.logger",
        ]
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                self.logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                self.logger.error(f"Failed to load {cog}: {e}")
        
        # Initialize Economy Logger
        EconomyLogger.setup(self)
        self.logger.info("Economy Logger initialized")
        
        # Sync commands to guild (faster updates than global)
        try:
            guild_id = self.config.get("guild_id")
            if guild_id:
                guild = discord.Object(id=guild_id)
                # Copy all commands to guild and sync
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                self.logger.info(f"Commands synced: {len(synced)} to guild")
            else:
                synced = await self.tree.sync()
                self.logger.info(f"Commands synced: {len(synced)} globally")
        except Exception as e:
            self.logger.error(f"Failed to sync commands: {e}")
        
        # Start background tasks
        self.salary_task.start()
        self.pb_bonus_task.start()
        self.cleanup_task.start()
        self.metrics_task.start()
        self.sb_monitor_task.start()
        
        self.logger.info("Background tasks started")
    
    async def on_ready(self):
        """Called when bot is ready"""
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        self.discord_logger = DiscordLogger(self)
        
        # Set bot info
        metrics.set_bot_info(
            name=str(self.user),
            version="1.0.0",
            developer="NaveL"
        )
        
        # Update presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="JJI Squad"
            )
        )

        # Sync roles
        await self.sync_roles()

        # Sweep stale (empty) Squadron Battle voice channels left over from
        # a previous bot session. Without this the channels linger forever
        # because deletion only happens on voice_state_update.
        await self._sweep_stale_sb_channels()

    async def _sweep_stale_sb_channels(self) -> None:
        """Delete empty SB voice channels left behind by a previous run."""
        config = self.config
        guild_id = config.get("guild_id")
        if not guild_id:
            return
        guild = self.get_guild(guild_id)
        if not guild:
            return

        deleted = 0
        for ch in list(guild.voice_channels):
            name = ch.name
            if not (name.startswith("SB #") or name.startswith("Squadron Battle #")):
                continue
            if len(ch.members) > 0:
                continue
            try:
                await ch.delete(reason="Startup sweep: stale empty SB channel")
                deleted += 1
                # Drop any stale tracking
                self.sb_channels.pop(ch.id, None)
                await cache.delete_sb_last_ping(ch.id)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                self.logger.warning(f"Missing permissions to delete stale SB channel {name}")
            except Exception as e:
                self.logger.error(f"Failed to delete stale SB channel {name}: {e}")

        if deleted:
            self.logger.info(f"Startup sweep: deleted {deleted} stale SB channel(s)")
    
    async def sync_roles(self):
        """Sync user roles from Discord to Database on startup"""
        self.logger.info("Syncing roles...")
        config = self.config
        guild_id = config.get("guild_id")

        if not guild_id:
            self.logger.warning("No guild_id in config, skipping role sync")
            return

        guild = self.get_guild(guild_id)
        if not guild:
            self.logger.warning(f"Guild {guild_id} not found, skipping role sync")
            return

        soldier_role_id = config.get("roles", {}).get("soldier")
        sergeant_role_id = config.get("roles", {}).get("sergeant")
        officer_role_id = config.get("roles", {}).get("officer")

        count = 0
        for member in guild.members:
            if member.bot:
                continue

            roles = set(r.id for r in member.roles)
            is_soldier = soldier_role_id in roles if soldier_role_id else False
            is_sergeant = sergeant_role_id in roles if sergeant_role_id else False
            is_officer = officer_role_id in roles if officer_role_id else False

            if is_soldier or is_sergeant or is_officer:
                await db.update_user_roles(
                    member.id,
                    is_officer=is_officer,
                    is_sergeant=is_sergeant,
                    is_soldier=is_soldier
                )
                count += 1

        self.logger.info(f"Synced roles for {count} members")

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """Handle voice channel changes"""
        if member.bot:
            return
        
        config = self.config
        master_channel_id = config.get("channels", {}).get("master_voice")
        
        # Check if user left a temp SB channel - delete paired channels if both empty
        if before.channel and (before.channel.name.startswith("SB #") or before.channel.name.startswith("Squadron Battle #")):
            await self._check_and_delete_sb_channels(before.channel)
        
        # User left voice completely
        if before.channel and not after.channel:
            duration = await db.end_voice_session(member.id)
            if duration:
                await db.update_pb_time(member.id, duration)
                self.logger.debug(f"{member} left voice, added {duration}s SB time")
        
        # User joined voice
        elif after.channel and not before.channel:
            is_master = master_channel_id and after.channel.id == master_channel_id
            await db.start_voice_session(member.id, after.channel.id, is_master)
            
            # Handle master channel entry - create SB channel
            if is_master:
                await self._handle_master_channel_join(member, after.channel)
        
        # User switched channels
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            # Check if old channel was temp SB - delete paired channels if both empty
            if before.channel.name.startswith("SB #") or before.channel.name.startswith("Squadron Battle #"):
                await self._check_and_delete_sb_channels(before.channel)
            
            # End old session
            duration = await db.end_voice_session(member.id)
            if duration:
                await db.update_pb_time(member.id, duration)
            
            # Start new session
            is_master = master_channel_id and after.channel.id == master_channel_id
            await db.start_voice_session(member.id, after.channel.id, is_master)
            
            # Handle master channel entry - create SB channel
            if is_master:
                await self._handle_master_channel_join(member, after.channel)
    
    async def _check_and_delete_sb_channels(self, channel: discord.VoiceChannel):
        """Check and delete paired SB channels if both are empty"""
        try:
            # Extract squadron number from channel name
            name = channel.name
            if name.startswith("SB #"):
                # New format: "SB #1 Ground" or "SB #1 Air"
                parts = name.replace("SB #", "").split()
                if len(parts) >= 1:
                    sb_num = parts[0]
            elif name.startswith("Squadron Battle #"):
                # Old format compatibility
                sb_num = name.replace("Squadron Battle #", "").strip()
            else:
                return
            
            guild = channel.guild
            
            # Find paired channels (Ground and Air with same number)
            ground_channel = None
            air_channel = None
            old_format_channel = None
            
            for ch in guild.voice_channels:
                if ch.name == f"SB #{sb_num} Ground":
                    ground_channel = ch
                elif ch.name == f"SB #{sb_num} Air":
                    air_channel = ch
                elif ch.name == f"Squadron Battle #{sb_num}":
                    old_format_channel = ch
            
            # Delete if both paired channels are empty (or old format single channel is empty)
            if ground_channel and air_channel:
                if len(ground_channel.members) == 0 and len(air_channel.members) == 0:
                    try:
                        await ground_channel.delete(reason="Squadron Battle ended - both channels empty")
                    except discord.NotFound:
                        pass  # Already deleted
                    try:
                        await air_channel.delete(reason="Squadron Battle ended - both channels empty")
                    except discord.NotFound:
                        pass  # Already deleted
                    self.logger.info(f"Deleted empty SB #{sb_num} channels (Ground + Air)")
                    
                    # Clean up tracker (race-safe)
                    self.sb_channels.pop(ground_channel.id, None)
                    self.sb_channels.pop(air_channel.id, None)
                    await cache.delete_sb_last_ping(ground_channel.id)
                    await cache.delete_sb_last_ping(air_channel.id)
            elif old_format_channel and len(old_format_channel.members) == 0:
                # Old format single channel
                try:
                    await old_format_channel.delete(reason="Squadron Battle ended - channel empty")
                except discord.NotFound:
                    pass  # Already deleted
                self.logger.info(f"Deleted empty SB channel: {old_format_channel.name}")
                self.sb_channels.pop(old_format_channel.id, None)
                await cache.delete_sb_last_ping(old_format_channel.id)
                    
        except discord.NotFound:
            pass  # Channel already deleted
        except Exception as e:
            self.logger.error(f"Failed to delete SB channel: {e}")
    
    async def _handle_master_channel_join(self, member: discord.Member, master_channel: discord.VoiceChannel):
        """Handle when someone joins master channel - create paired SB channels (Ground + Air) for sergeants"""
        config = self.config
        developer_id = config.get("developer_id")
        is_developer = member.id == developer_id
        
        # Check prime time (developer bypasses)
        prime_time = config.get("prime_time", {})
        is_prime = is_prime_time(
            prime_time.get("start_hour", 14),
            prime_time.get("end_hour", 22)
        )
        
        if not is_prime and not is_developer:
            # Not prime time - deny channel creation
            try:
                embed = discord.Embed(
                    title="Squadron Battles Unavailable",
                    description="Squadron Battles can only be created during **Prime Time**.",
                    color=0xFF3333
                )
                embed.add_field(
                    name="Prime Time Hours",
                    value=f"`{prime_time.get('start_hour', 14):02d}:00 - {prime_time.get('end_hour', 22):02d}:00 UTC`",
                    inline=False
                )
                embed.add_field(
                    name="Why Prime Time?",
                    value="We concentrate battles during peak hours to ensure full squads and better gameplay experience.",
                    inline=False
                )
                embed.set_footer(text=get_standard_footer())
                
                await member.send(embed=embed)
            except Exception as e:
                self.logger.error(f"Failed to send prime time notification to {member}: {e}")
            return
        
        # Check if user has sergeant role (developer bypasses)
        sergeant_role_id = config.get("roles", {}).get("sergeant")
        officer_role_id = config.get("roles", {}).get("officer")
        admin_role_id = config.get("roles", {}).get("admin")
        
        member_role_ids = [r.id for r in member.roles]
        
        # Sergeants, officers, admins, and developer can create SB channels
        is_authorized = is_developer or (
            (sergeant_role_id and sergeant_role_id in member_role_ids) or
            (officer_role_id and officer_role_id in member_role_ids) or
            (admin_role_id and admin_role_id in member_role_ids)
        )
        
        if not is_authorized:
            self.logger.debug(f"{member} joined master but not authorized to create SB channel")
            return
        
        self.logger.info(f"{member} authorized - creating SB channels...")
        
        # Find next available SB number (check both old and new format)
        guild = member.guild
        sb_numbers = set()
        
        for ch in guild.voice_channels:
            # New format: "SB #1 Ground" or "SB #1 Air"
            if ch.name.startswith("SB #"):
                try:
                    parts = ch.name.replace("SB #", "").split()
                    if parts:
                        num = int(parts[0])
                        sb_numbers.add(num)
                except ValueError:
                    pass
            # Old format: "Squadron Battle #1"
            elif ch.name.startswith("Squadron Battle #"):
                try:
                    num = int(ch.name.replace("Squadron Battle #", ""))
                    sb_numbers.add(num)
                except ValueError:
                    pass
        
        next_num = 1
        while next_num in sb_numbers:
            next_num += 1
        
        # Create new paired SB channels cloning master channel's permissions
        try:
            # Create Ground channel (🛡️ Tanks)
            ground_channel = await master_channel.clone(
                name=f"SB #{next_num} Ground",
                reason=f"Squadron Battle Ground channel created by {member.display_name}"
            )
            
            # Create Air channel (✈️ Aviation)
            air_channel = await master_channel.clone(
                name=f"SB #{next_num} Air",
                reason=f"Squadron Battle Air channel created by {member.display_name}"
            )
            
            # Move to same category as master
            if master_channel.category:
                base_position = master_channel.position + (next_num * 2)
                await ground_channel.edit(category=master_channel.category, position=base_position)
                await air_channel.edit(category=master_channel.category, position=base_position + 1)
            
            # Developer test mode: make channels unjoinable but visible (so mentions resolve)
            if is_developer:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(connect=False),
                    member: discord.PermissionOverwrite(connect=True),
                    guild.me: discord.PermissionOverwrite(connect=True),
                }
                await ground_channel.edit(overwrites=overwrites)
                await air_channel.edit(overwrites=overwrites)
                self.logger.info(f"Developer {member} — SB #{next_num} channels set to private (connect=False)")
            
            # Sergeant daily bonus - atomic claim+payout (no flag set if payout fails)
            bonus = config.get("salaries", {}).get("sergeant_master_bonus", 50)
            result = await db.claim_master_bonus_atomic(
                discord_id=member.id,
                bonus_amount=bonus,
                description="Daily Squadron Battle host bonus",
            )

            if result["success"]:
                self.logger.info(f"Sergeant {member} claimed SB host bonus: ${bonus}")
                metrics.track_transaction("master_bonus")

                # DM the sergeant about their bonus
                try:
                    dm_embed = discord.Embed(
                        title="🎖️ Squadron Battle Host Bonus!",
                        description=f"You received **{format_balance(bonus)}** for hosting Squadron Battles today!",
                        color=0x00FF00
                    )
                    await member.send(embed=dm_embed)
                except Exception:
                    pass
            else:
                err = result.get("error")
                if err == "already_claimed":
                    pass  # silent — already paid today
                elif err == "no_active_master_session":
                    self.logger.debug(f"SB bonus skipped for {member}: no active master session")
                else:
                    self.logger.warning(f"Failed to pay SB bonus to {member}: {err}")
            
            # Move the sergeant to the ground channel by default (AFTER claiming bonus)
            await member.move_to(ground_channel, reason="Moved to new Squadron Battle Ground channel")
            
            self.logger.info(f"Created SB #{next_num} channels (Ground + Air) by {member}")
            
            # Ping in sergeant channel with recruitment message
            ping_channel_id = config.get("channels", {}).get("ping_sergeant")
            if ping_channel_id:
                try:
                    channel = self.get_channel(ping_channel_id)
                    if channel:
                        # Count current members across both channels
                        ground_count = len(ground_channel.members)
                        air_count = len(air_channel.members)
                        total_count = ground_count + air_count
                        max_squad = config.get("sb", {}).get("max_squad", 8)
                        needed = max(0, max_squad - total_count)
                        
                        embed = discord.Embed(
                            title="📢 SQUADRON ASSEMBLY!",
                            description=f"**Squadron #{next_num}** is forming up!",
                            color=0xFF6600
                        )
                        embed.add_field(
                            name="👑 Commander",
                            value=member.mention,
                            inline=True
                        )
                        embed.add_field(
                            name="🔊 Voice Channels",
                            value=f"🛡️ {ground_channel.mention}\n✈️ {air_channel.mention}",
                            inline=True
                        )
                        embed.add_field(
                            name="👥 Current Squadron",
                            value=f"🛡️ Ground: `{ground_count}`\n✈️ Air: `{air_count}`\n**Total:** `{total_count}/{max_squad}` — need {needed} more!",
                            inline=False
                        )
                        embed.add_field(
                            name="💰 Rewards",
                            value="Earn salary while playing in Squadron Battles!",
                            inline=False
                        )
                        embed.set_footer(text="Join Ground for tanks or Air for aviation! • JJI Squadron System")
                        
                        # Ping soldier role if configured
                        soldier_role_id = config.get("roles", {}).get("soldier")
                        ping_content = f"<@&{soldier_role_id}>" if soldier_role_id else ""
                        
                        await channel.send(
                            content=ping_content,
                            embed=embed,
                            view=SBAssemblyView(),
                        )
                        
                        # Register both channels in tracker
                        now_ts = datetime.now(timezone.utc)
                        self.sb_channels[ground_channel.id] = {
                            "last_ping": now_ts,
                            "commander_id": member.id,
                            "last_status": "initial",
                            "squad_num": next_num,
                            "type": "ground",
                            "paired_id": air_channel.id
                        }
                        self.sb_channels[air_channel.id] = {
                            "last_ping": now_ts,
                            "commander_id": member.id,
                            "last_status": "initial",
                            "squad_num": next_num,
                            "type": "air",
                            "paired_id": ground_channel.id
                        }
                        # Persist for restart recovery
                        await cache.set_sb_last_ping(ground_channel.id, now_ts.timestamp())
                        await cache.set_sb_last_ping(air_channel.id, now_ts.timestamp())
                except Exception as e:
                    self.logger.error(f"Failed to send SB ping: {e}")
                        
        except discord.Forbidden:
            self.logger.error(f"No permission to create SB channels")
        except Exception as e:
            self.logger.error(f"Failed to create SB channels: {e}")
    
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Handle member role changes and mute detection"""
        if before.bot:
            return
        
        config = self.config
        
        # Check for role changes
        old_roles = set(r.id for r in before.roles)
        new_roles = set(r.id for r in after.roles)
        
        soldier_role = config.get("roles", {}).get("soldier")
        sergeant_role = config.get("roles", {}).get("sergeant")
        officer_role = config.get("roles", {}).get("officer")
        
        # Update database role flags
        is_soldier = soldier_role in new_roles if soldier_role else False
        is_sergeant = sergeant_role in new_roles if sergeant_role else False
        is_officer = officer_role in new_roles if officer_role else False
        
        was_soldier = soldier_role in old_roles if soldier_role else False
        
        if old_roles != new_roles:
            await db.update_user_roles(
                after.id,
                is_officer=is_officer,
                is_sergeant=is_sergeant,
                is_soldier=is_soldier
            )
            
            # Handle soldier role changes - budget impact
            if soldier_role:
                economy = await db.get_server_economy()
                soldier_value = economy.soldier_value
                
                if not was_soldier and is_soldier:
                    # Got soldier role - add soldier value to budget
                    await db.update_server_budget(soldier_value)
                    self.logger.info(f"New soldier: {after}, budget +{format_balance(soldier_value)}")
                    
                    # Log to recruit channel
                    log_channel_id = config.get("channels", {}).get("log_recruit")
                    if log_channel_id:
                        try:
                            channel = self.get_channel(log_channel_id)
                            if channel:
                                embed = discord.Embed(
                                    title="⚔️ New Soldier Recruited!",
                                    description=f"{after.mention} is now a soldier!",
                                    color=0x00FF00,
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.add_field(
                                    name="💰 Budget Impact",
                                    value=f"+{format_balance(soldier_value)}",
                                    inline=True
                                )
                                embed.set_footer(text="Soldier Value added to server budget")
                                await channel.send(embed=embed)
                        except Exception as e:
                            self.logger.error(f"Failed to log new soldier: {e}")
                
                elif was_soldier and not is_soldier:
                    # Lost soldier role - deduct soldier value from budget
                    await db.update_server_budget(-soldier_value)
                    self.logger.info(f"Lost soldier: {after}, budget -{format_balance(soldier_value)}")
                    
                    # Log to recruit channel
                    log_channel_id = config.get("channels", {}).get("log_recruit")
                    if log_channel_id:
                        try:
                            channel = self.get_channel(log_channel_id)
                            if channel:
                                embed = discord.Embed(
                                    title="📉 Soldier Role Removed",
                                    description=f"{after.mention} is no longer a soldier",
                                    color=0xFF6600,
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.add_field(
                                    name="💰 Budget Impact",
                                    value=f"-{format_balance(soldier_value)}",
                                    inline=True
                                )
                                embed.set_footer(text="Soldier value deducted from server budget")
                                await channel.send(embed=embed)
                        except Exception as e:
                            self.logger.error(f"Failed to log soldier removal: {e}")
        
        # Mute penalty detection
        mute_config = config.get("mute_penalty", {})
        if mute_config.get("enabled", True):
            # Check if user got muted (timed out)
            was_muted = before.timed_out_until is None
            is_muted = after.timed_out_until is not None
            
            if not was_muted and is_muted:
                # User just got muted - apply penalty
                penalty_percent = mute_config.get("percentage", 50)
                user = await db.get_or_create_user(after.id)
                
                if user.balance > 0:
                    penalty = user.balance * (penalty_percent / 100)
                    
                    result = await db.admin_adjust_balance_atomic(
                        after.id,
                        -penalty,
                        TransactionType.MUTE_PENALTY,
                        description=f"Mute penalty ({penalty_percent}%)"
                    )
                    
                    if result["success"]:
                        self.logger.info(f"Mute penalty for {after}: {format_balance(penalty)}")
                        metrics.track_transaction("mute_penalty")
    
    async def on_member_join(self, member: discord.Member):
        """Handle new member joining - add soldier value to budget"""
        if member.bot:
            return
        
        config = self.config
        soldier_role_id = config.get("roles", {}).get("soldier")
        
        # Only add budget if they will get soldier role
        # The actual addition happens when they get the soldier role in on_member_update
        # But we can log the join
        self.logger.info(f"Member joined: {member}")
        
        # Log to recruit channel
        log_channel_id = config.get("channels", {}).get("log_recruit")
        if log_channel_id:
            try:
                channel = self.get_channel(log_channel_id)
                if channel:
                    embed = discord.Embed(
                        title="👋 Member Joined",
                        description=f"{member.mention} joined the server",
                        color=0x00FF00,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
                    await channel.send(embed=embed)
            except Exception as e:
                self.logger.error(f"Failed to log member join: {e}")
    
    async def on_member_remove(self, member: discord.Member):
        """Handle member leaving - deduct soldier value and optionally confiscate balance"""
        if member.bot:
            return
        
        config = self.config
        soldier_role_id = config.get("roles", {}).get("soldier")
        member_leave_config = config.get("member_leave", {})
        confiscate_balance = member_leave_config.get("confiscate_balance", True)
        return_to_budget = member_leave_config.get("return_to_budget", True)
        
        # Check if they had soldier role
        had_soldier_role = soldier_role_id and any(r.id == soldier_role_id for r in member.roles)
        
        economy = await db.get_server_economy()
        soldier_value = economy.soldier_value if had_soldier_role else 0
        confiscated_amount = 0
        
        # Confiscate user balance if enabled
        if confiscate_balance:
            user = await db.get_user(member.id)
            if user and user.balance > 0:
                confiscated_amount = user.balance
                if return_to_budget:
                    # Atomic: take user balance and add to budget
                    result = await db.admin_adjust_balance_atomic(
                        member.id,
                        -confiscated_amount,
                        TransactionType.CONFISCATE,
                        description=f"Auto-confiscated on server leave"
                    )
                    if result["success"]:
                        self.logger.info(f"Confiscated {format_balance(confiscated_amount)} from {member} on leave")
                else:
                    # Just zero out balance without returning to budget (money destroyed)
                    async with db.session() as session:
                        from sqlalchemy import update as sql_update
                        await session.execute(
                            sql_update(User).where(User.discord_id == member.id).values(balance=0)
                        )
                        await session.commit()
        
        # If soldier left - deduct soldier value from budget
        # This is symmetric: /accept adds soldier_value, leaving removes it
        if had_soldier_role:
            await db.update_server_budget(-soldier_value)
            self.logger.info(f"Soldier left server: {member}, budget -{format_balance(soldier_value)}")
        
        # Log to recruit channel
        log_channel_id = config.get("channels", {}).get("log_recruit")
        if log_channel_id:
            try:
                channel = self.get_channel(log_channel_id)
                if channel:
                    embed = discord.Embed(
                        title="👋 Member Left",
                        description=f"**{member.display_name}** left the server",
                        color=0xFF0000,
                        timestamp=discord.utils.utcnow()
                    )
                    
                    impact_lines = []
                    if had_soldier_role:
                        impact_lines.append(f"Soldier value: -{format_balance(soldier_value)}")
                    if confiscated_amount > 0:
                        impact_lines.append(f"Confiscated balance: +{format_balance(confiscated_amount)}")
                    
                    if impact_lines:
                        net_impact = confiscated_amount - soldier_value
                        net_str = f"+{format_balance(net_impact)}" if net_impact >= 0 else format_balance(net_impact)
                        embed.add_field(
                            name="💰 Budget Impact",
                            value="\n".join(impact_lines) + f"\n**Net:** {net_str}",
                            inline=True
                        )
                        embed.set_footer(text="Balance confiscated and returned to server budget")
                    await channel.send(embed=embed)
            except Exception as e:
                self.logger.error(f"Failed to log member leave: {e}")

    @tasks.loop(seconds=60)
    async def salary_task(self):
        """Distribute salaries every minute (accumulates for 10min intervals)"""
        # Reload config to get latest rates
        self.config = load_config()
        config = self.config
        prime_time = config.get("prime_time", {})
        mute_config = config.get("mute_penalty", {})
        mute_penalty_enabled = mute_config.get("enabled", True)
        
        # Check prime time
        is_prime = is_prime_time(
            prime_time.get("start_hour", 14),
            prime_time.get("end_hour", 22)
        )
        
        # Prime time 2x multiplier, otherwise 1x
        prime_multiplier = 2.0 if is_prime else 1.0
        
        salaries = config.get("salaries", {})
        # Apply prime time multiplier to all rates
        soldier_rate = (salaries.get("soldier_per_10min", 10) / 10) * prime_multiplier  # Per minute
        sergeant_rate = (salaries.get("sergeant_per_10min", 20) / 10) * prime_multiplier
        officer_rate = (salaries.get("officer_per_10min", 20) / 10) * prime_multiplier
        
        # Get guild for mute checking
        guild_id = config.get("guild_id")
        guild = self.get_guild(guild_id) if guild_id else None
        
        # Use single transaction for atomic salary distribution
        async with db.session() as session:
            # Lock economy row for update
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            if not economy:
                return
            
            remaining_budget = economy.total_budget
            budget_before = economy.total_budget
            total_paid = 0
            total_tax = 0
            paid_users = []
            skipped_muted = 0
            
            # Get active voice sessions with users (with FOR UPDATE to prevent race conditions)
            # Only pay users NOT in master channel (is_in_master=False means they're in actual SB channels)
            sessions_result = await session.execute(
                select(VoiceSession)
                .where(
                    VoiceSession.is_active == True,
                    VoiceSession.is_in_master == False  # Only SB channels, not master channel
                )
                .options(selectinload(VoiceSession.user))
            )
            sessions = sessions_result.scalars().all()
            
            for voice_session in sessions:
                user = voice_session.user
                
                # Check if user is muted (Discord timeout or server mute)
                if mute_penalty_enabled and guild:
                    try:
                        member = guild.get_member(user.discord_id)
                        if member:
                            # Check for timeout (timed_out_until) or voice mute
                            is_timed_out = member.timed_out_until is not None
                            voice_state = member.voice
                            is_voice_muted = voice_state and voice_state.mute
                            
                            if is_timed_out or is_voice_muted:
                                skipped_muted += 1
                                continue  # Skip muted users - no salary
                    except Exception:
                        pass  # If can't check, give benefit of doubt

                # Determine rate based on highest-paying role
                # Check all roles and select the one with maximum rate
                role_rates = []
                if user.is_officer:
                    role_rates.append((officer_rate, "Officer"))
                if user.is_sergeant:
                    role_rates.append((sergeant_rate, "Sergeant"))
                if user.is_soldier:
                    role_rates.append((soldier_rate, "Soldier"))
                
                if not role_rates:
                    continue  # No salary for non-role members
                
                # Select the role with maximum rate
                rate, role_name = max(role_rates, key=lambda x: x[0])

                # Apply salary tax (compute first so budget check uses the
                # actual outflow — net amount — instead of gross rate)
                tax_amount = rate * (economy.tax_rate / 100)
                net_salary = rate - tax_amount

                # Check budget BEFORE paying. We compare against net_salary
                # because that's what really leaves the budget; tax stays in.
                if remaining_budget < net_salary:
                    self.logger.warning(f"Server budget depleted! Stopping salary distribution. Remaining: {remaining_budget}")
                    break

                user_before = user.balance

                # Lock user row and update balance atomically
                user_result = await session.execute(
                    select(User).where(User.id == user.id).with_for_update()
                )
                locked_user = user_result.scalar_one_or_none()
                if not locked_user:
                    continue
                
                locked_user.balance += net_salary

                # Log transaction
                transaction = Transaction(
                    user_id=locked_user.id,
                    amount=net_salary,
                    transaction_type=TransactionType.SALARY,
                    tax_amount=tax_amount,
                    before_balance=user_before,
                    after_balance=locked_user.balance,
                    description=f"SB time salary ({'Prime Time 2x' if is_prime else 'Standard 1x'})"
                )
                session.add(transaction)

                remaining_budget -= net_salary  # Only deduct net from budget
                total_paid += net_salary
                total_tax += tax_amount
                paid_users.append(f"{locked_user.discord_id} ({role_name}): +${net_salary:.2f}")

                # Tax stays in server budget (not deducted), but we track it
                if tax_amount > 0:
                    economy.total_taxes_collected += tax_amount
            
            # Update server economy stats
            if total_paid > 0:
                economy.total_rewards_paid += total_paid
                economy.total_budget -= total_paid

                multiplier_text = "Prime Time 2x" if is_prime else "Standard 1x"
                self.logger.debug(f"Distributed salaries: {format_balance(total_paid)} ({multiplier_text})")

                # Log salary distribution (aggregate)
                await economy_logger.log(
                    action=EconomyAction.BUDGET_SALARY_PAID,
                    amount=total_paid,
                    before_budget=budget_before,
                    after_budget=economy.total_budget,
                    description=f"Salary paid to {len(paid_users)} users ({multiplier_text})",
                    details={
                        "Total Net Paid": f"${total_paid:,.2f}",
                        "Total Tax Kept": f"${total_tax:,.2f}",
                        "Users Paid": len(paid_users),
                        "Muted Skipped": skipped_muted,
                        "Multiplier": multiplier_text
                    },
                    source="SalaryTask"
                )
    
    @salary_task.before_loop
    async def before_salary(self):
        await self.wait_until_ready()
    
    @tasks.loop(minutes=5)
    async def pb_bonus_task(self):
        """Check for 10h PB bonuses"""
        config = self.config
        officer_config = config.get("officer_system", {})
        tracking_hours = officer_config.get("tracking_hours", 10)
        bonus_amount = officer_config.get("pb_10h_bonus", 50)
        required_seconds = tracking_hours * 3600
        
        pending = await db.get_pending_10h_bonuses()
        
        for log, recruit in pending:
            # Check if recruit has reached 10h
            if recruit.total_pb_time >= log.pb_time_at_accept + required_seconds:
                # Get officer
                officer = await db.get_user_by_id(log.officer_id)
                if not officer:
                    continue
                
                economy = await db.get_server_economy()
                if economy.total_budget < bonus_amount:
                    self.logger.warning("Not enough budget for 10h PB bonus")
                    continue
                
                # Pay bonus atomically from budget (no tax on bonuses)
                result = await db.pay_from_budget_atomic(
                    discord_id=officer.discord_id,
                    gross_amount=bonus_amount,
                    net_amount=bonus_amount,  # No tax on bonus
                    tax_amount=0,
                    transaction_type=TransactionType.PB_10H_BONUS,
                    description=f"10h SB bonus for recruit"
                )
                
                if result["success"]:
                    await db.mark_10h_bonus_rewarded(log.id)
                    self.logger.info(f"Paid 10h bonus to officer {officer.discord_id}: ${bonus_amount}")
                    metrics.track_transaction("pb_10h_bonus")
                else:
                    self.logger.warning(f"Failed to pay 10h bonus: {result.get('error', 'Unknown')}")
    
    @pb_bonus_task.before_loop
    async def before_pb_bonus(self):
        await self.wait_until_ready()
    
    @tasks.loop(hours=1)
    async def cleanup_task(self):
        """Clean up expired sessions and rate limits"""
        expired = await db.cleanup_expired_sessions()
        rate_limits = await db.cleanup_old_rate_limits()
        
        self.logger.debug(f"Cleanup: {expired} game sessions, {rate_limits} rate limits")
    
    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.wait_until_ready()
    
    @tasks.loop(seconds=30)
    async def metrics_task(self):
        """Update Prometheus metrics"""
        try:
            # Update bot metrics
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            metrics.update_uptime(uptime)
            metrics.update_latency(self.latency * 1000)
            metrics.update_guilds(len(self.guilds))
            
            # Update economy metrics
            economy = await db.get_server_economy()
            metrics.update_server_budget(economy.total_budget)
            
            total_users = await db.get_total_users()
            total_balance = await db.get_total_balance()
            metrics.update_user_counts(total_users)
            metrics.update_user_balance_sum(total_balance)
            
            # Voice users
            sessions = await db.get_active_voice_sessions()
            metrics.update_voice_users(len(sessions))
        except Exception as e:
            self.logger.error(f"Metrics update error: {e}")
    
    @metrics_task.before_loop
    async def before_metrics(self):
        await self.wait_until_ready()
    
    @tasks.loop(minutes=1)
    async def sb_monitor_task(self):
        """Monitor Squadron Battle channels and send recruitment pings"""
        try:
            config = self.config
            guild_id = config.get("guild_id")
            if not guild_id:
                return
            
            guild = self.get_guild(guild_id)
            if not guild:
                return
            
            ping_channel_id = config.get("channels", {}).get("ping_sergeant")
            if not ping_channel_id:
                return
            
            ping_channel = self.get_channel(ping_channel_id)
            if not ping_channel:
                return
            
            soldier_role_id = config.get("roles", {}).get("soldier")
            max_squad = config.get("sb", {}).get("max_squad", 8)
            now = datetime.now(timezone.utc)
            
            # Find all active SB channels (new format: "SB #N Ground/Air")
            # Group them by squadron number
            squadrons = {}  # {num: {"ground": channel, "air": channel}}
            
            for ch in guild.voice_channels:
                if ch.name.startswith("SB #"):
                    parts = ch.name.replace("SB #", "").split()
                    if len(parts) >= 2:
                        try:
                            num = int(parts[0])
                            channel_type = parts[1].lower()  # "ground" or "air"
                            if num not in squadrons:
                                squadrons[num] = {"ground": None, "air": None, "members": 0}
                            squadrons[num][channel_type] = ch
                            squadrons[num]["members"] += len(ch.members)
                        except ValueError:
                            pass
                # Also support old format for backwards compatibility
                elif ch.name.startswith("Squadron Battle #"):
                    try:
                        num = int(ch.name.replace("Squadron Battle #", ""))
                        if num not in squadrons:
                            squadrons[num] = {"ground": ch, "air": None, "members": len(ch.members)}
                    except ValueError:
                        pass
            
            for squad_num, squad_info in squadrons.items():
                member_count = squad_info["members"]
                ground_ch = squad_info.get("ground")
                air_ch = squad_info.get("air")
                
                # Get the main channel for reference (prefer ground)
                main_channel = ground_ch or air_ch
                if not main_channel:
                    continue
                
                # Skip empty squadrons (will be deleted by voice_state_update)
                if member_count == 0:
                    # Clean up tracking (race-safe)
                    if ground_ch:
                        self.sb_channels.pop(ground_ch.id, None)
                        await cache.delete_sb_last_ping(ground_ch.id)
                    if air_ch:
                        self.sb_channels.pop(air_ch.id, None)
                        await cache.delete_sb_last_ping(air_ch.id)
                    continue
                
                # Use ground channel id for tracking (or air if no ground)
                tracking_id = ground_ch.id if ground_ch else air_ch.id
                
                # Get or create channel tracking
                if tracking_id not in self.sb_channels:
                    # Find commander (first member)
                    all_members = []
                    if ground_ch:
                        all_members.extend(ground_ch.members)
                    if air_ch:
                        all_members.extend(air_ch.members)
                    commander = all_members[0] if all_members else None

                    # Restore last_ping from Redis if the bot restarted while
                    # this squadron was active. Falls back to ``now`` (skips
                    # the first iteration so no spam ping right after start).
                    persisted_ts = await cache.get_sb_last_ping(tracking_id)
                    restored_last_ping = (
                        datetime.fromtimestamp(persisted_ts, tz=timezone.utc)
                        if persisted_ts is not None
                        else now
                    )

                    self.sb_channels[tracking_id] = {
                        "last_ping": restored_last_ping,
                        "commander_id": commander.id if commander else None,
                        "last_status": "initial",
                        "squad_num": squad_num
                    }
                    if persisted_ts is None:
                        # First time we see this squadron in this process —
                        # seed Redis and skip ping this tick.
                        await cache.set_sb_last_ping(tracking_id, now.timestamp())
                        continue
                    # Otherwise fall through and let the regular interval
                    # check below decide whether to ping.
                
                tracking = self.sb_channels[tracking_id]
                last_ping = tracking.get("last_ping", now)
                time_since_ping = (now - last_ping).total_seconds() / 60  # in minutes
                
                # Determine ping interval based on squad status
                if member_count < max_squad:
                    # Need more soldiers - ping every 30 minutes
                    ping_interval = 30
                    needed = max_squad - member_count
                    
                    if time_since_ping >= ping_interval:
                        # Build channel mentions
                        if ground_ch and air_ch:
                            channels_value = f"🛡️ {ground_ch.mention}\n✈️ {air_ch.mention}"
                        else:
                            channels_value = main_channel.mention
                        
                        embed = discord.Embed(
                            title="📢 SOLDIERS NEEDED!",
                            description=f"**Squadron #{squad_num}** needs reinforcements!",
                            color=0xFF4444
                        )
                        embed.add_field(
                            name="🔊 Voice Channels",
                            value=channels_value,
                            inline=True
                        )
                        embed.add_field(
                            name="👥 Current Squadron",
                            value=f"`{member_count}/{max_squad}`",
                            inline=True
                        )
                        embed.add_field(
                            name="⚠️ Need",
                            value=f"**{needed}** more soldiers!",
                            inline=True
                        )
                        embed.add_field(
                            name="💰 Rewards",
                            value="Join now and earn salary!",
                            inline=False
                        )
                        embed.set_footer(text="Join Ground for tanks or Air for aviation! • Squadron System")
                        
                        ping_content = f"<@&{soldier_role_id}>" if soldier_role_id else ""
                        await ping_channel.send(
                            content=ping_content,
                            embed=embed,
                            view=SBAssemblyView(),
                        )
                        
                        tracking["last_ping"] = now
                        tracking["last_status"] = "recruiting"
                        await cache.set_sb_last_ping(tracking_id, now.timestamp())
                        self.logger.debug(f"SB ping: Squadron #{squad_num} needs {needed} more")
                
                else:
                    # Full squad - ping every 60 minutes (1 hour) for standby
                    ping_interval = 60
                    
                    if time_since_ping >= ping_interval:
                        # Build channel mentions
                        if ground_ch and air_ch:
                            channels_value = f"🛡️ {ground_ch.mention}\n✈️ {air_ch.mention}"
                        else:
                            channels_value = main_channel.mention
                        
                        embed = discord.Embed(
                            title="✅ SQUADRON FULL - STANDBY!",
                            description=f"**Squadron #{squad_num}** is fully staffed!",
                            color=0x00FF00
                        )
                        embed.add_field(
                            name="🔊 Voice Channels",
                            value=channels_value,
                            inline=True
                        )
                        embed.add_field(
                            name="👥 Squadron Size",
                            value=f"`{member_count}/{max_squad}`",
                            inline=True
                        )
                        embed.add_field(
                            name="🔄 Be Ready!",
                            value="Be prepared to join as replacement if someone leaves!",
                            inline=False
                        )
                        embed.set_footer(text="Stay alert for openings! • Squadron System")
                        
                        # No ping for standby, just info message
                        await ping_channel.send(embed=embed, view=SBAssemblyView())
                        
                        tracking["last_ping"] = now
                        tracking["last_status"] = "full"
                        await cache.set_sb_last_ping(tracking_id, now.timestamp())
                        self.logger.debug(f"SB standby: Squadron #{squad_num} is full")
            
            # Clean up tracking for deleted channels
            active_ids = set()
            for squad_info in squadrons.values():
                if squad_info.get("ground"):
                    active_ids.add(squad_info["ground"].id)
                if squad_info.get("air"):
                    active_ids.add(squad_info["air"].id)
            
            for channel_id in list(self.sb_channels.keys()):
                if channel_id not in active_ids:
                    self.sb_channels.pop(channel_id, None)
                    await cache.delete_sb_last_ping(channel_id)
                    
        except Exception as e:
            self.logger.error(f"SB monitor error: {e}")
    
    @sb_monitor_task.before_loop
    async def before_sb_monitor(self):
        await self.wait_until_ready()
    
    async def close(self):
        """Cleanup on shutdown"""
        self.logger.info("Shutting down...")
        
        # End all voice sessions
        sessions = await db.get_active_voice_sessions()
        for session in sessions:
            await db.end_voice_session(session.user.discord_id)
        
        # Disconnect Redis
        await cache.disconnect()
        
        await super().close()


def main():
    """Main entry point"""
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN not set!")
        print("Create a .env file with DISCORD_TOKEN=your_token")
        sys.exit(1)
    
    bot = JJIBot()
    
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("ERROR: Invalid bot token!")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

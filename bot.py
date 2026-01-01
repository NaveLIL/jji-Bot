"""
JJI Squad Discord Bot
Discord bot for gaming community
Developed by NaveL for JJI in 2025
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
from src.utils.helpers import load_config, save_config, is_prime_time, format_balance
from src.utils.logger import setup_logging, DiscordLogger
from src.utils.metrics import metrics


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
        
        # Check if user left a temp SB channel - delete if empty
        if before.channel and before.channel.name.startswith("Squadron Battle #"):
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Squadron Battle ended - channel empty")
                    self.logger.info(f"Deleted empty SB channel: {before.channel.name}")
                except Exception as e:
                    self.logger.error(f"Failed to delete SB channel: {e}")
        
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
            # Check if old channel was temp SB and now empty
            if before.channel.name.startswith("Squadron Battle #"):
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete(reason="Squadron Battle ended - channel empty")
                        self.logger.info(f"Deleted empty SB channel: {before.channel.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete SB channel: {e}")
            
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
    
    async def _handle_master_channel_join(self, member: discord.Member, master_channel: discord.VoiceChannel):
        """Handle when someone joins master channel - create SB channel for sergeants"""
        config = self.config
        
        # Check if user has sergeant role (from Discord, not just DB flag)
        sergeant_role_id = config.get("roles", {}).get("sergeant")
        officer_role_id = config.get("roles", {}).get("officer")
        admin_role_id = config.get("roles", {}).get("admin")
        
        member_role_ids = [r.id for r in member.roles]
        
        # Sergeants, officers, and admins can create SB channels
        is_authorized = (
            (sergeant_role_id and sergeant_role_id in member_role_ids) or
            (officer_role_id and officer_role_id in member_role_ids) or
            (admin_role_id and admin_role_id in member_role_ids)
        )
        
        if not is_authorized:
            self.logger.debug(f"{member} joined master but not authorized to create SB channel")
            return
        
        self.logger.info(f"{member} authorized - creating SB channel...")
        
        # Find next available SB number
        guild = member.guild
        existing_sb = [ch for ch in guild.voice_channels if ch.name.startswith("Squadron Battle #")]
        sb_numbers = []
        for ch in existing_sb:
            try:
                num = int(ch.name.replace("Squadron Battle #", ""))
                sb_numbers.append(num)
            except ValueError:
                pass
        
        next_num = 1
        while next_num in sb_numbers:
            next_num += 1
        
        # Create new SB channel cloning master channel's permissions
        try:
            # Clone the master channel with same permissions
            new_channel = await master_channel.clone(
                name=f"Squadron Battle #{next_num}",
                reason=f"Squadron Battle created by {member.display_name}"
            )
            
            # Move to same category as master
            if master_channel.category:
                await new_channel.edit(category=master_channel.category, position=master_channel.position + next_num)
            
            # Move the sergeant to the new channel
            await member.move_to(new_channel, reason="Moved to new Squadron Battle channel")
            
            self.logger.info(f"Created SB channel #{next_num} by {member}")
            
            # Ping in sergeant channel with recruitment message
            ping_channel_id = config.get("channels", {}).get("ping_sergeant")
            if ping_channel_id:
                try:
                    channel = self.get_channel(ping_channel_id)
                    if channel:
                        # Count current members in the new channel
                        current_count = len(new_channel.members)
                        max_squad = 8  # Max squad size
                        needed = max_squad - current_count
                        
                        embed = discord.Embed(
                            title="📢 SQUADRON ASSEMBLY!",
                            description=f"**Squadron #{next_num}** is looking for soldiers!",
                            color=0xFF6600
                        )
                        embed.add_field(
                            name="👑 Commander",
                            value=member.mention,
                            inline=True
                        )
                        embed.add_field(
                            name="🔊 Voice Channel",
                            value=new_channel.mention,
                            inline=True
                        )
                        embed.add_field(
                            name="👥 Current Squadron",
                            value=f"`{current_count}/{max_squad}` — need {needed} more!",
                            inline=False
                        )
                        embed.add_field(
                            name="💰 Rewards",
                            value="Earn salary while playing in Squadron Battles!",
                            inline=False
                        )
                        embed.set_footer(text="Join the voice channel to participate! • JJI Squadron System")
                        
                        # Ping soldier role if configured
                        soldier_role_id = config.get("roles", {}).get("soldier")
                        ping_content = f"<@&{soldier_role_id}>" if soldier_role_id else ""
                        
                        await channel.send(content=ping_content, embed=embed)
                        
                        # Register channel in tracker to avoid duplicate ping
                        self.sb_channels[new_channel.id] = {
                            "last_ping": datetime.now(timezone.utc),
                            "commander_id": member.id,
                            "last_status": "initial"
                        }
                except Exception as e:
                    self.logger.error(f"Failed to send SB ping: {e}")
            
            # Sergeant daily bonus
            claimed = await db.claim_master_bonus(member.id)
            if claimed:
                bonus = config.get("salaries", {}).get("sergeant_master_bonus", 50)
                
                # Pay bonus atomically from budget (no tax on bonuses)
                result = await db.pay_from_budget_atomic(
                    discord_id=member.id,
                    gross_amount=bonus,
                    net_amount=bonus,  # No tax on bonus
                    tax_amount=0,
                    transaction_type=TransactionType.MASTER_BONUS,
                    description="Daily Squadron Battle host bonus"
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
                    self.logger.warning(f"Failed to pay SB bonus to {member}: {result.get('error')}")
                        
        except discord.Forbidden:
            self.logger.error(f"No permission to create SB channel")
        except Exception as e:
            self.logger.error(f"Failed to create SB channel: {e}")
    
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
                    # Got soldier role - no budget change (closed-loop economy)
                    self.logger.info(f"New soldier: {after}")
                    
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
                    
                    await db.update_user_balance(
                        after.id,
                        -penalty,
                        TransactionType.MUTE_PENALTY,
                        description=f"Mute penalty ({penalty_percent}%)"
                    )
                    
                    await db.update_server_budget(penalty, add=True)
                    
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
        """Handle member leaving - deduct soldier value if was soldier"""
        if member.bot:
            return
        
        config = self.config
        soldier_role_id = config.get("roles", {}).get("soldier")
        
        # Check if they had soldier role
        had_soldier_role = soldier_role_id and any(r.id == soldier_role_id for r in member.roles)
        
        # If soldier left - deduct soldier value from budget
        # This is symmetric: /accept adds soldier_value, leaving removes it
        if had_soldier_role:
            economy = await db.get_server_economy()
            soldier_value = economy.soldier_value
            
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
                    if had_soldier_role:
                        economy = await db.get_server_economy()
                        embed.add_field(
                            name="💰 Budget Impact",
                            value=f"-{format_balance(economy.soldier_value)}",
                            inline=True
                        )
                        embed.set_footer(text="Soldier value deducted from server budget")
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
        
        # Check prime time - if not prime time, no salaries
        is_prime = is_prime_time(
            prime_time.get("start_hour", 14),
            prime_time.get("end_hour", 22)
        )
        if not is_prime:
            return
        
        # Prime time 2x multiplier
        prime_multiplier = 2.0
        
        salaries = config.get("salaries", {})
        # Apply prime time multiplier to all rates
        soldier_rate = (salaries.get("soldier_per_10min", 10) / 10) * prime_multiplier  # Per minute with 2x
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
            sessions_result = await session.execute(
                select(VoiceSession)
                .where(VoiceSession.is_active == True)
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
                            is_voice_muted = voice_state and (voice_state.mute or voice_state.self_mute)
                            
                            if is_timed_out:
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

                # Check budget before paying
                if remaining_budget < rate:
                    self.logger.warning(f"Server budget depleted! Stopping salary distribution. Remaining: {remaining_budget}")
                    break

                # Apply salary tax
                tax_amount = rate * (economy.tax_rate / 100)
                net_salary = rate - tax_amount

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
                    description=f"SB time salary (Prime Time 2x)"
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

                self.logger.debug(f"Distributed salaries: {format_balance(total_paid)} (Prime Time 2x)")

                # Log salary distribution (aggregate)
                await economy_logger.log(
                    action=EconomyAction.BUDGET_SALARY_PAID,
                    amount=total_paid,
                    before_budget=budget_before,
                    after_budget=economy.total_budget,
                    description=f"Salary paid to {len(paid_users)} users (Prime Time 2x)",
                    details={
                        "Total Net Paid": f"${total_paid:,.2f}",
                        "Total Tax Kept": f"${total_tax:,.2f}",
                        "Users Paid": len(paid_users),
                        "Muted Skipped": skipped_muted,
                        "Prime Time Multiplier": "2x"
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
            max_squad = 8
            now = datetime.now(timezone.utc)
            
            # Find all active SB channels
            sb_channels = [ch for ch in guild.voice_channels if ch.name.startswith("Squadron Battle #")]
            
            for channel in sb_channels:
                member_count = len(channel.members)
                
                # Skip empty channels (will be deleted by voice_state_update)
                if member_count == 0:
                    if channel.id in self.sb_channels:
                        del self.sb_channels[channel.id]
                    continue
                
                # Get or create channel tracking
                if channel.id not in self.sb_channels:
                    # Find commander (first member or member with sergeant role)
                    commander = channel.members[0] if channel.members else None
                    self.sb_channels[channel.id] = {
                        "last_ping": now,
                        "commander_id": commander.id if commander else None,
                        "last_status": "initial"
                    }
                    continue  # Skip first check, let initial message work
                
                tracking = self.sb_channels[channel.id]
                last_ping = tracking.get("last_ping", now)
                time_since_ping = (now - last_ping).total_seconds() / 60  # in minutes
                
                # Determine ping interval based on squad status
                if member_count < max_squad:
                    # Need more soldiers - ping every 30 minutes
                    ping_interval = 30
                    needed = max_squad - member_count
                    
                    if time_since_ping >= ping_interval:
                        embed = discord.Embed(
                            title="📢 SOLDIERS NEEDED!",
                            description=f"**Squadron #{channel.name.split('#')[1]}** needs reinforcements!",
                            color=0xFF4444
                        )
                        embed.add_field(
                            name="🔊 Voice Channel",
                            value=channel.mention,
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
                        embed.set_footer(text="Join the battle! • Squadron System")
                        
                        ping_content = f"<@&{soldier_role_id}>" if soldier_role_id else ""
                        await ping_channel.send(content=ping_content, embed=embed)
                        
                        tracking["last_ping"] = now
                        tracking["last_status"] = "recruiting"
                        self.logger.debug(f"SB ping: {channel.name} needs {needed} more")
                
                else:
                    # Full squad - ping every 60 minutes (1 hour) for standby
                    ping_interval = 60
                    
                    if time_since_ping >= ping_interval:
                        embed = discord.Embed(
                            title="✅ SQUADRON FULL - STANDBY!",
                            description=f"**Squadron #{channel.name.split('#')[1]}** is fully staffed!",
                            color=0x00FF00
                        )
                        embed.add_field(
                            name="🔊 Voice Channel",
                            value=channel.mention,
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
                        await ping_channel.send(embed=embed)
                        
                        tracking["last_ping"] = now
                        tracking["last_status"] = "full"
                        self.logger.debug(f"SB standby: {channel.name} is full")
            
            # Clean up tracking for deleted channels
            active_ids = {ch.id for ch in sb_channels}
            for channel_id in list(self.sb_channels.keys()):
                if channel_id not in active_ids:
                    del self.sb_channels[channel_id]
                    
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

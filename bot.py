"""
JJI Regiment Discord Bot
Production-grade bot for military gaming community
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

from src.services.database import db
from src.services.cache import cache
from src.models.database import TransactionType
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
        self.start_time = datetime.utcnow()
    
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
        
        # Sync commands
        try:
            guild_id = self.config.get("guild_id")
            if guild_id:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            else:
                await self.tree.sync()
            self.logger.info("Commands synced")
        except Exception as e:
            self.logger.error(f"Failed to sync commands: {e}")
        
        # Start background tasks
        self.salary_task.start()
        self.pb_bonus_task.start()
        self.cleanup_task.start()
        self.metrics_task.start()
        
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
                name="JJI Regiment"
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
        
        # User left voice
        if before.channel and not after.channel:
            duration = await db.end_voice_session(member.id)
            if duration:
                await db.update_pb_time(member.id, duration)
                self.logger.debug(f"{member} left voice, added {duration}s PB time")
        
        # User joined voice
        elif after.channel and not before.channel:
            is_master = master_channel_id and after.channel.id == master_channel_id
            await db.start_voice_session(member.id, after.channel.id, is_master)
            
            # Handle master channel entry for sergeants
            if is_master:
                user = await db.get_or_create_user(member.id)
                if user.is_sergeant:
                    # Check if can claim bonus today
                    claimed = await db.claim_master_bonus(member.id)
                    if claimed:
                        bonus = config.get("salaries", {}).get("sergeant_master_bonus", 50)
                        economy = await db.get_server_economy()
                        
                        if economy.total_budget >= bonus:
                            await db.update_user_balance(
                                member.id,
                                bonus,
                                TransactionType.MASTER_BONUS,
                                description="Daily master channel bonus"
                            )
                            await db.add_rewards_paid(bonus)
                            
                            self.logger.info(f"Sergeant {member} claimed master bonus: ${bonus}")
                            metrics.track_transaction("master_bonus")
                            
                            # Ping channel if configured
                            ping_channel_id = config.get("channels", {}).get("ping_sergeant")
                            if ping_channel_id:
                                try:
                                    channel = self.get_channel(ping_channel_id)
                                    if channel:
                                        embed = discord.Embed(
                                            title="🎖️ Master Channel Entry!",
                                            description=f"{member.mention} entered the master channel and received {format_balance(bonus)}!",
                                            color=discord.Color.gold()
                                        )
                                        await channel.send(embed=embed)
                                except Exception:
                                    pass
        
        # User switched channels
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            # End old session
            duration = await db.end_voice_session(member.id)
            if duration:
                await db.update_pb_time(member.id, duration)
            
            # Start new session
            is_master = master_channel_id and after.channel.id == master_channel_id
            await db.start_voice_session(member.id, after.channel.id, is_master)
    
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
        
        if old_roles != new_roles:
            await db.update_user_roles(
                after.id,
                is_officer=is_officer,
                is_sergeant=is_sergeant,
                is_soldier=is_soldier
            )
        
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
    
    @tasks.loop(seconds=60)
    async def salary_task(self):
        """Distribute salaries every minute (accumulates for 10min intervals)"""
        config = self.config
        prime_time = config.get("prime_time", {})
        
        # Check prime time
        if not is_prime_time(
            prime_time.get("start_hour", 14),
            prime_time.get("end_hour", 22)
        ):
            return
        
        salaries = config.get("salaries", {})
        soldier_rate = salaries.get("soldier_per_10min", 10) / 10  # Per minute
        sergeant_rate = salaries.get("sergeant_per_10min", 20) / 10
        officer_rate = salaries.get("officer_per_10min", 20) / 10
        
        # Get active voice sessions
        sessions = await db.get_active_voice_sessions()
        
        economy = await db.get_server_economy()
        total_paid = 0
        
        for session in sessions:
            user = session.user
            
            # Determine rate based on role
            if user.is_officer:
                rate = officer_rate
            elif user.is_sergeant:
                rate = sergeant_rate
            elif user.is_soldier:
                rate = soldier_rate
            else:
                continue  # No salary for non-role members
            
            # Check budget
            if economy.total_budget < rate:
                self.logger.warning("Server budget depleted!")
                break
            
            # Pay salary
            await db.update_user_balance(
                user.discord_id,
                rate,
                TransactionType.SALARY,
                description="PB time salary"
            )
            
            total_paid += rate
        
        if total_paid > 0:
            await db.add_rewards_paid(total_paid)
            self.logger.debug(f"Distributed salaries: {format_balance(total_paid)}")
    
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
                    continue
                
                # Pay bonus
                await db.update_user_balance(
                    officer.discord_id,
                    bonus_amount,
                    TransactionType.PB_10H_BONUS,
                    description=f"10h PB bonus for recruit"
                )
                
                await db.add_rewards_paid(bonus_amount)
                await db.mark_10h_bonus_rewarded(log.id)
                
                self.logger.info(f"Paid 10h bonus to officer {officer.discord_id}: ${bonus_amount}")
                metrics.track_transaction("pb_10h_bonus")
    
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
            uptime = (datetime.utcnow() - self.start_time).total_seconds()
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

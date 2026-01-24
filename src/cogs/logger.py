
import discord
from discord.ext import commands
import logging
from datetime import datetime, timezone

class LoggerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("discord_logger")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Log when a message from the bot is deleted"""
        # Only care about messages sent by the bot itself
        if message.author.id != self.bot.user.id:
            return

        # Check if it looks like an FAQ panel (has embed, maybe title 'Frequently Asked Questions' or similar)
        is_faq = False
        if message.embeds:
            for embed in message.embeds:
                if embed.footer and "Use buttons below" in str(embed.footer.text):
                     is_faq = True
                # Or check database if this message ID was a known FAQ panel
                # But we want to be fast and not query DB on every delete if possible.
        
        # We can also check if the message ID corresponds to a known FAQ panel in the DB
        # This requires importing db, let's do it lazily or just log everything for now.
        
        # Log to console/file
        log_msg = f"⚠️ BOT MESSAGE DELETED: Channel #{message.channel.name} ({message.channel.id}), Message ID {message.id}"
        if message.embeds:
            log_msg += f", Embed Title: {message.embeds[0].title}"
        
        self.logger.warning(log_msg)

        # Try to find who deleted it via Audit Logs
        if message.guild:
            try:
                # wait a bit for audit log to populate
                import asyncio
                await asyncio.sleep(1)
                
                async for entry in message.guild.audit_logs(limit=5, action=discord.AuditLogAction.message_delete):
                    if entry.target.id == self.bot.user.id and entry.extra.channel.id == message.channel.id:
                        # Check time diff
                        time_diff = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
                        if time_diff < 10:
                            self.logger.warning(f"   ↳ Likely deleted by user: {entry.user} (ID: {entry.user.id})")
                            break
            except Exception as e:
                self.logger.error(f"Failed to check audit logs: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(LoggerCog(bot))

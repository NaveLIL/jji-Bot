"""
Structured Logging System with Discord Webhook Integration
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

import structlog
import discord
from discord import Webhook
import aiohttp


class DiscordWebhookHandler(logging.Handler):
    """Send critical logs to Discord webhook"""
    
    def __init__(self, webhook_url: str, min_level: int = logging.ERROR):
        super().__init__(level=min_level)
        self.webhook_url = webhook_url
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def send_to_webhook(self, record: logging.LogRecord) -> None:
        """Send log record to Discord webhook"""
        if not self.webhook_url:
            return
        
        try:
            session = await self._get_session()
            webhook = Webhook.from_url(self.webhook_url, session=session)
            
            # Create embed
            color = discord.Color.red() if record.levelno >= logging.ERROR else discord.Color.yellow()
            
            embed = discord.Embed(
                title=f"🚨 {record.levelname}",
                description=f"```\n{record.getMessage()[:1900]}\n```",
                color=color,
                timestamp=datetime.utcnow()
            )
            
            # Add extra fields if present
            if hasattr(record, "extra_data"):
                for key, value in record.extra_data.items():
                    embed.add_field(
                        name=key,
                        value=str(value)[:1024],
                        inline=True
                    )
            
            embed.set_footer(text="JJI Bot Logger")
            
            await webhook.send(embed=embed)
        except Exception as e:
            # Don't raise - we don't want logging to break the bot
            print(f"Failed to send log to webhook: {e}")
    
    def emit(self, record: logging.LogRecord) -> None:
        """Emit is sync but we need async - use fire and forget"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.send_to_webhook(record))
            else:
                loop.run_until_complete(self.send_to_webhook(record))
        except Exception:
            pass


def json_serializer(obj: Any) -> str:
    """Custom JSON serializer for structlog"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, discord.User) or isinstance(obj, discord.Member):
        return f"{obj.name}#{obj.discriminator} ({obj.id})"
    if isinstance(obj, discord.Guild):
        return f"{obj.name} ({obj.id})"
    return str(obj)


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/bot.log",
    webhook_url: Optional[str] = None,
    json_format: bool = True
) -> structlog.BoundLogger:
    """
    Setup structured logging with file output and optional webhook.
    Returns configured structlog logger.
    """
    
    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Configure standard logging
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    handlers.append(console_handler)
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(level)
    handlers.append(file_handler)
    
    # Webhook handler for errors
    if webhook_url:
        webhook_handler = DiscordWebhookHandler(webhook_url, min_level=logging.ERROR)
        handlers.append(webhook_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=level,
        handlers=handlers,
        format="%(message)s" if json_format else "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Suppress noisy loggers
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    
    # Configure structlog
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if json_format:
        processors.append(
            structlog.processors.JSONRenderer(serializer=lambda obj, **kwargs: json.dumps(obj, default=json_serializer))
        )
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    return structlog.get_logger("jji_bot")


# Create module-level logger instance
logger: Optional[structlog.BoundLogger] = None


def get_logger() -> structlog.BoundLogger:
    """Get or create the global logger"""
    global logger
    if logger is None:
        logger = setup_logging()
    return logger


class DiscordLogger:
    """Helper class for logging to Discord channels"""
    
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._log_channels: Dict[str, Optional[discord.TextChannel]] = {}
    
    async def _get_channel(self, channel_id: int) -> Optional[discord.TextChannel]:
        """Get or fetch a channel"""
        if channel_id in self._log_channels:
            return self._log_channels[channel_id]
        
        try:
            channel = await self.bot.fetch_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                self._log_channels[channel_id] = channel
                return channel
        except Exception:
            pass
        
        return None
    
    async def log_officer_action(
        self,
        channel_id: int,
        officer: discord.Member,
        recruit: discord.Member,
        action: str = "accept"
    ) -> None:
        """Log officer recruitment actions"""
        channel = await self._get_channel(channel_id)
        if not channel:
            return
        
        embed = discord.Embed(
            title=f"👮 Officer Action: {action.upper()}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Officer", value=f"{officer.mention}", inline=True)
        embed.add_field(name="Recruit", value=f"{recruit.mention}", inline=True)
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        try:
            await channel.send(embed=embed)
        except Exception:
            pass
    
    async def log_economy(
        self,
        channel_id: int,
        user: discord.Member,
        action: str,
        amount: float,
        tax: float = 0,
        before: float = 0,
        after: float = 0,
        description: str = ""
    ) -> None:
        """Log economy transactions"""
        channel = await self._get_channel(channel_id)
        if not channel:
            return
        
        if amount >= 0:
            color = discord.Color.green()
            emoji = "💰"
        else:
            color = discord.Color.red()
            emoji = "💸"
        
        embed = discord.Embed(
            title=f"{emoji} {action}",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user.mention}", inline=True)
        embed.add_field(name="Amount", value=f"${amount:,.2f}", inline=True)
        
        if tax > 0:
            embed.add_field(name="Tax", value=f"${tax:,.2f}", inline=True)
        
        embed.add_field(name="Before", value=f"${before:,.2f}", inline=True)
        embed.add_field(name="After", value=f"${after:,.2f}", inline=True)
        
        if description:
            embed.add_field(name="Description", value=description, inline=False)
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        try:
            await channel.send(embed=embed)
        except Exception:
            pass
    
    async def log_game(
        self,
        channel_id: int,
        user: discord.Member,
        game: str,
        result: str,
        bet: float,
        winnings: float,
        tax: float = 0
    ) -> None:
        """Log game results"""
        channel = await self._get_channel(channel_id)
        if not channel:
            return
        
        if winnings > 0:
            color = discord.Color.green()
            emoji = "🎉"
        elif winnings < 0:
            color = discord.Color.red()
            emoji = "💔"
        else:
            color = discord.Color.gold()
            emoji = "🤝"
        
        embed = discord.Embed(
            title=f"🎮 {game.title()} - {result}",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Player", value=f"{user.mention}", inline=True)
        embed.add_field(name="Bet", value=f"${bet:,.2f}", inline=True)
        embed.add_field(name=f"{emoji} Result", value=f"${winnings:,.2f}", inline=True)
        
        if tax > 0:
            embed.add_field(name="Tax", value=f"${tax:,.2f}", inline=True)
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        try:
            await channel.send(embed=embed)
        except Exception:
            pass
    
    async def log_security(
        self,
        channel_id: int,
        user_id: int,
        event_type: str,
        description: str,
        severity: str = "medium",
        action_taken: str = None
    ) -> None:
        """Log security events"""
        channel = await self._get_channel(channel_id)
        if not channel:
            return
        
        color_map = {
            "low": discord.Color.blue(),
            "medium": discord.Color.yellow(),
            "high": discord.Color.orange(),
            "critical": discord.Color.red()
        }
        
        embed = discord.Embed(
            title=f"🔒 Security: {event_type}",
            description=description,
            color=color_map.get(severity, discord.Color.yellow()),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User ID", value=str(user_id), inline=True)
        embed.add_field(name="Severity", value=severity.upper(), inline=True)
        
        if action_taken:
            embed.add_field(name="Action Taken", value=action_taken, inline=True)
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        try:
            await channel.send(embed=embed)
        except Exception:
            pass
    
    async def log_server_event(
        self,
        channel_id: int,
        event: str,
        description: str,
        user: discord.Member = None
    ) -> None:
        """Log general server events"""
        channel = await self._get_channel(channel_id)
        if not channel:
            return
        
        embed = discord.Embed(
            title=f"📢 {event}",
            description=description,
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        
        if user:
            embed.add_field(name="User", value=f"{user.mention}", inline=True)
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

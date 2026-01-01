"""
Economy Logger Module
=====================
Professional logging system for tracking all monetary operations.
Sends detailed embed logs to Discord channel for full transparency.
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import traceback


# Economy log channel ID
ECONOMY_LOG_CHANNEL_ID = 1442156749288378479


class EconomyAction(Enum):
    """Types of economy actions - professional labels without emojis"""
    # User balance changes
    USER_EARN = "EARN"
    USER_SPEND = "SPEND"
    USER_TRANSFER_OUT = "TRANSFER OUT"
    USER_TRANSFER_IN = "TRANSFER IN"
    USER_TAX_PAID = "TAX PAID"
    USER_REWARD = "REWARD"
    USER_SALARY = "SALARY"
    USER_REFUND = "REFUND"
    
    # Game results
    GAME_WIN = "GAME WIN"
    GAME_LOSE = "GAME LOSS"
    GAME_BET = "GAME BET"
    
    # Server budget changes
    BUDGET_ADD = "BUDGET CREDIT"
    BUDGET_REMOVE = "BUDGET DEBIT"
    BUDGET_TAX_COLLECTED = "TAX COLLECTED"
    BUDGET_SALARY_PAID = "SALARY PAID"
    BUDGET_REWARD_PAID = "REWARD PAID"
    
    # Shop operations
    SHOP_PURCHASE = "SHOP PURCHASE"
    SHOP_SALE = "SHOP SALE"
    SHOP_ROLE_REPLACE = "ROLE REPLACE"
    
    # Admin operations
    ADMIN_ADD = "ADMIN CREDIT"
    ADMIN_REMOVE = "ADMIN DEBIT"
    ADMIN_SET = "ADMIN SET"
    
    # Cases
    CASE_OPEN = "CASE OPENED"
    CASE_WIN = "CASE REWARD"


class EconomyLogger:
    """
    Singleton logger for economy operations.
    Sends detailed embeds to Discord channel.
    """
    _instance = None
    _bot: Optional[commands.Bot] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def setup(cls, bot: commands.Bot):
        """Initialize logger with bot instance"""
        cls._bot = bot
        print(f"[EconomyLogger] Initialized | Channel: {ECONOMY_LOG_CHANNEL_ID}")
    
    @classmethod
    def _format_currency(cls, amount: float, show_sign: bool = False) -> str:
        """Format currency consistently"""
        if show_sign:
            return f"+${amount:,.2f}" if amount >= 0 else f"-${abs(amount):,.2f}"
        return f"${amount:,.2f}"
    
    @classmethod
    async def log(
        cls,
        action: EconomyAction,
        amount: float,
        user_id: Optional[int] = None,
        user_name: Optional[str] = None,
        target_id: Optional[int] = None,
        target_name: Optional[str] = None,
        before_balance: Optional[float] = None,
        after_balance: Optional[float] = None,
        before_budget: Optional[float] = None,
        after_budget: Optional[float] = None,
        description: str = "",
        details: Optional[dict] = None,
        source: str = "Unknown"
    ):
        """Log an economy operation with full details."""
        if not cls._bot:
            print(f"[EconomyLogger] Bot not initialized | Action: {action.value}")
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                print(f"[EconomyLogger] Channel not found: {ECONOMY_LOG_CHANNEL_ID}")
                return
            
            color = cls._get_color(action)
            
            # Build embed with clean header
            embed = discord.Embed(
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Title bar with action type
            embed.set_author(name=f"ECONOMY LOG | {action.value}")
            
            # Determine amount display
            is_debit = action in [
                EconomyAction.USER_SPEND, EconomyAction.USER_TAX_PAID,
                EconomyAction.GAME_LOSE, EconomyAction.GAME_BET,
                EconomyAction.BUDGET_REMOVE, EconomyAction.BUDGET_SALARY_PAID,
                EconomyAction.BUDGET_REWARD_PAID, EconomyAction.SHOP_PURCHASE,
                EconomyAction.ADMIN_REMOVE
            ]
            
            amount_str = f"-${amount:,.2f}" if is_debit else f"+${amount:,.2f}"
            embed.add_field(name="Amount", value=f"```{amount_str}```", inline=True)
            
            # User info
            if user_id:
                user_str = f"<@{user_id}>\n`ID: {user_id}`"
                embed.add_field(name="User", value=user_str, inline=True)
            
            # Target info (for transfers)
            if target_id:
                target_str = f"<@{target_id}>\n`ID: {target_id}`"
                embed.add_field(name="Target", value=target_str, inline=True)
            
            # Balance changes section
            balance_info = []
            if before_balance is not None and after_balance is not None:
                diff = after_balance - before_balance
                balance_info.append(
                    f"**User Balance**\n"
                    f"Before: {cls._format_currency(before_balance)}\n"
                    f"After: {cls._format_currency(after_balance)}\n"
                    f"Delta: {cls._format_currency(diff, show_sign=True)}"
                )
            
            if before_budget is not None and after_budget is not None:
                diff = after_budget - before_budget
                balance_info.append(
                    f"**Server Budget**\n"
                    f"Before: {cls._format_currency(before_budget)}\n"
                    f"After: {cls._format_currency(after_budget)}\n"
                    f"Delta: {cls._format_currency(diff, show_sign=True)}"
                )
            
            if balance_info:
                embed.add_field(
                    name="Balance Changes",
                    value="\n\n".join(balance_info),
                    inline=False
                )
            
            # Description
            if description:
                embed.add_field(name="Description", value=description, inline=False)
            
            # Additional details in code block
            if details:
                details_lines = [f"{k}: {v}" for k, v in details.items()]
                embed.add_field(
                    name="Details",
                    value=f"```\n{chr(10).join(details_lines)}\n```",
                    inline=False
                )
            
            # Footer
            embed.set_footer(text=f"Source: {source}")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] Error: {e}")
            traceback.print_exc()
    
    @classmethod
    def _get_color(cls, action: EconomyAction) -> int:
        """Get embed color based on action type"""
        # Green - positive for user/budget
        if action in [EconomyAction.USER_EARN, EconomyAction.USER_REWARD,
                     EconomyAction.USER_SALARY, EconomyAction.USER_REFUND,
                     EconomyAction.USER_TRANSFER_IN, EconomyAction.GAME_WIN,
                     EconomyAction.CASE_WIN, EconomyAction.SHOP_SALE,
                     EconomyAction.BUDGET_ADD, EconomyAction.BUDGET_TAX_COLLECTED]:
            return 0x57F287  # Discord Green
        
        # Red - negative/loss
        if action in [EconomyAction.USER_SPEND, EconomyAction.USER_TAX_PAID,
                     EconomyAction.USER_TRANSFER_OUT, EconomyAction.GAME_LOSE,
                     EconomyAction.GAME_BET, EconomyAction.SHOP_PURCHASE,
                     EconomyAction.BUDGET_REMOVE, EconomyAction.BUDGET_SALARY_PAID,
                     EconomyAction.BUDGET_REWARD_PAID]:
            return 0xED4245  # Discord Red
        
        # Purple - admin actions
        if action in [EconomyAction.ADMIN_ADD, EconomyAction.ADMIN_REMOVE,
                     EconomyAction.ADMIN_SET]:
            return 0x9B59B6
        
        # Blue - cases/misc
        if action in [EconomyAction.CASE_OPEN, EconomyAction.SHOP_ROLE_REPLACE]:
            return 0x5865F2  # Discord Blurple
        
        return 0x99AAB5  # Discord Gray default
    
    @classmethod
    async def log_transfer(
        cls,
        sender_id: int,
        sender_name: str,
        receiver_id: int,
        receiver_name: str,
        amount: float,
        tax: float,
        sender_before: float,
        sender_after: float,
        receiver_before: float,
        receiver_after: float,
        budget_before: float,
        budget_after: float,
        source: str = "Transfer"
    ):
        """Log money transfer with complete audit trail."""
        if not cls._bot:
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                return
            
            embed = discord.Embed(
                color=0x5865F2,  # Blurple for transfers
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.set_author(name="ECONOMY LOG | TRANSFER")
            
            # Transfer summary
            net_amount = amount - tax
            embed.add_field(
                name="Transaction",
                value=f"```\nGross:  ${amount:,.2f}\nTax:    ${tax:,.2f}\nNet:    ${net_amount:,.2f}\n```",
                inline=False
            )
            
            # Parties
            embed.add_field(
                name="From",
                value=f"<@{sender_id}>\n`{sender_name}`",
                inline=True
            )
            embed.add_field(
                name="To",
                value=f"<@{receiver_id}>\n`{receiver_name}`",
                inline=True
            )
            embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer
            
            # Balance changes
            sender_diff = sender_after - sender_before
            receiver_diff = receiver_after - receiver_before
            budget_diff = budget_after - budget_before
            
            balance_text = (
                f"**Sender**\n"
                f"{cls._format_currency(sender_before)} -> {cls._format_currency(sender_after)} "
                f"({cls._format_currency(sender_diff, True)})\n\n"
                f"**Receiver**\n"
                f"{cls._format_currency(receiver_before)} -> {cls._format_currency(receiver_after)} "
                f"({cls._format_currency(receiver_diff, True)})"
            )
            
            if tax > 0:
                balance_text += (
                    f"\n\n**Server Budget (Tax)**\n"
                    f"{cls._format_currency(budget_before)} -> {cls._format_currency(budget_after)} "
                    f"({cls._format_currency(budget_diff, True)})"
                )
            
            embed.add_field(name="Balance Changes", value=balance_text, inline=False)
            
            embed.set_footer(text=f"Source: {source}")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] Transfer log error: {e}")
    
    @classmethod
    async def log_game(
        cls,
        game_name: str,
        user_id: int,
        user_name: str,
        bet: float,
        result: str,
        winnings: float,
        profit: float,
        user_before: float,
        user_after: float,
        budget_before: float,
        budget_after: float,
        details: Optional[dict] = None
    ):
        """Log game result with financial impact."""
        if not cls._bot:
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                return
            
            # Color based on result
            if profit > 0:
                color = 0x57F287  # Green - win
                result_label = "WIN"
            elif profit < 0:
                color = 0xED4245  # Red - loss
                result_label = "LOSS"
            else:
                color = 0xFEE75C  # Yellow - push
                result_label = "PUSH"
            
            embed = discord.Embed(
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.set_author(name=f"GAME LOG | {game_name.upper()} - {result_label}")
            
            # Player info
            embed.add_field(
                name="Player",
                value=f"<@{user_id}>\n`{user_name}`",
                inline=True
            )
            
            # Game summary
            embed.add_field(
                name="Result",
                value=f"```\nBet:     ${bet:,.2f}\nPayout:  ${winnings:,.2f}\nProfit:  {cls._format_currency(profit, True)}\n```",
                inline=True
            )
            
            embed.add_field(
                name="Outcome",
                value=f"```{result}```",
                inline=True
            )
            
            # Balance impact
            user_diff = user_after - user_before
            budget_diff = budget_after - budget_before
            
            embed.add_field(
                name="Balance Changes",
                value=(
                    f"**Player**\n"
                    f"{cls._format_currency(user_before)} -> {cls._format_currency(user_after)} "
                    f"({cls._format_currency(user_diff, True)})\n\n"
                    f"**Server Budget**\n"
                    f"{cls._format_currency(budget_before)} -> {cls._format_currency(budget_after)} "
                    f"({cls._format_currency(budget_diff, True)})"
                ),
                inline=False
            )
            
            # Game details
            if details:
                details_lines = [f"{k}: {v}" for k, v in details.items()]
                embed.add_field(
                    name="Game Details",
                    value=f"```\n{chr(10).join(details_lines)}\n```",
                    inline=False
                )
            
            embed.set_footer(text=f"Game: {game_name}")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] Game log error: {e}")
    
    @classmethod
    async def log_shop(
        cls,
        action: str,
        user_id: int,
        user_name: str,
        role_name: str,
        role_price: float,
        tax: float,
        refund: float,
        user_before: float,
        user_after: float,
        budget_before: float,
        budget_after: float,
        replaced_role: Optional[str] = None
    ):
        """Log shop transaction."""
        if not cls._bot:
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                return
            
            if action == "purchase":
                color = 0xED4245  # Red (spending)
                action_label = "PURCHASE"
            elif action == "sale":
                color = 0x57F287  # Green (earning)
                action_label = "SALE"
            else:
                color = 0x5865F2
                action_label = "OPERATION"
            
            embed = discord.Embed(
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.set_author(name=f"SHOP LOG | {action_label}")
            
            # User
            embed.add_field(
                name="User",
                value=f"<@{user_id}>\n`{user_name}`",
                inline=True
            )
            
            # Role info
            role_info = f"**{role_name}**\nPrice: {cls._format_currency(role_price)}"
            if replaced_role:
                role_info += f"\nReplaced: {replaced_role}"
            embed.add_field(name="Role", value=role_info, inline=True)
            
            # Transaction details
            if action == "purchase":
                total = role_price + tax
                embed.add_field(
                    name="Transaction",
                    value=f"```\nPrice:  ${role_price:,.2f}\nTax:    ${tax:,.2f}\nTotal:  ${total:,.2f}\n```",
                    inline=True
                )
            else:
                embed.add_field(
                    name="Refund",
                    value=f"```\nOriginal: ${role_price:,.2f}\nRefund:   ${refund:,.2f}\n```",
                    inline=True
                )
            
            # Balance changes
            user_diff = user_after - user_before
            budget_diff = budget_after - budget_before
            
            embed.add_field(
                name="Balance Changes",
                value=(
                    f"**User**\n"
                    f"{cls._format_currency(user_before)} -> {cls._format_currency(user_after)} "
                    f"({cls._format_currency(user_diff, True)})\n\n"
                    f"**Server Budget**\n"
                    f"{cls._format_currency(budget_before)} -> {cls._format_currency(budget_after)} "
                    f"({cls._format_currency(budget_diff, True)})"
                ),
                inline=False
            )
            
            embed.set_footer(text="Source: Role Shop")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] Shop log error: {e}")


# Singleton instance
economy_logger = EconomyLogger()

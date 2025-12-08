"""
Economy Logger Module
=====================
Comprehensive logging system for tracking all monetary operations.
Sends detailed embed logs to Discord channel for full transparency.
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union
import traceback


# Hardcoded economy log channel
ECONOMY_LOG_CHANNEL_ID = 1442156749288378479


class EconomyAction(Enum):
    """Types of economy actions"""
    # User balance changes
    USER_EARN = "💰 EARN"
    USER_SPEND = "💸 SPEND"
    USER_TRANSFER_OUT = "📤 TRANSFER OUT"
    USER_TRANSFER_IN = "📥 TRANSFER IN"
    USER_TAX_PAID = "🏛️ TAX PAID"
    USER_REWARD = "🎁 REWARD"
    USER_SALARY = "💵 SALARY"
    USER_REFUND = "🔄 REFUND"
    
    # Game results
    GAME_WIN = "🎰 GAME WIN"
    GAME_LOSE = "🎰 GAME LOSE"
    GAME_BET = "🎲 GAME BET"
    
    # Server budget changes
    BUDGET_ADD = "📈 BUDGET+"
    BUDGET_REMOVE = "📉 BUDGET-"
    BUDGET_TAX_COLLECTED = "🏦 TAX COLLECTED"
    BUDGET_SALARY_PAID = "💳 SALARY PAID"
    BUDGET_REWARD_PAID = "🎁 REWARD PAID"
    
    # Shop operations
    SHOP_PURCHASE = "🛒 PURCHASE"
    SHOP_SALE = "💰 SALE"
    SHOP_ROLE_REPLACE = "🔄 ROLE REPLACE"
    
    # Admin operations
    ADMIN_ADD = "⚙️ ADMIN ADD"
    ADMIN_REMOVE = "⚙️ ADMIN REMOVE"
    ADMIN_SET = "⚙️ ADMIN SET"
    
    # Cases
    CASE_OPEN = "📦 CASE OPEN"
    CASE_WIN = "🎉 CASE WIN"


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
        print(f"[EconomyLogger] Initialized. Log channel: {ECONOMY_LOG_CHANNEL_ID}")
    
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
        """
        Log an economy operation with full details.
        
        Args:
            action: Type of economy action
            amount: Amount of money involved
            user_id: Discord ID of the user involved
            user_name: Username for display
            target_id: Target user ID (for transfers)
            target_name: Target username
            before_balance: User's balance before operation
            after_balance: User's balance after operation
            before_budget: Server budget before operation
            after_budget: Server budget after operation
            description: Human-readable description
            details: Additional details dict
            source: Module/command that triggered this
        """
        if not cls._bot:
            print(f"[EconomyLogger] WARNING: Bot not initialized! Action: {action.value}")
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                print(f"[EconomyLogger] ERROR: Cannot find channel {ECONOMY_LOG_CHANNEL_ID}")
                return
            
            # Determine embed color based on action
            color = cls._get_color(action)
            
            # Build embed
            embed = discord.Embed(
                title=f"{action.value}",
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Amount field (always first)
            amount_str = f"${amount:,.2f}"
            if action in [EconomyAction.USER_SPEND, EconomyAction.USER_TAX_PAID, 
                         EconomyAction.GAME_LOSE, EconomyAction.GAME_BET,
                         EconomyAction.BUDGET_REMOVE, EconomyAction.BUDGET_SALARY_PAID,
                         EconomyAction.BUDGET_REWARD_PAID, EconomyAction.SHOP_PURCHASE]:
                amount_str = f"-${amount:,.2f}"
            elif action in [EconomyAction.USER_EARN, EconomyAction.USER_REWARD,
                           EconomyAction.USER_SALARY, EconomyAction.USER_REFUND,
                           EconomyAction.GAME_WIN, EconomyAction.BUDGET_ADD,
                           EconomyAction.BUDGET_TAX_COLLECTED, EconomyAction.SHOP_SALE,
                           EconomyAction.CASE_WIN]:
                amount_str = f"+${amount:,.2f}"
            
            embed.add_field(name="💵 Amount", value=f"**{amount_str}**", inline=True)
            
            # User info
            if user_id:
                user_str = f"<@{user_id}>"
                if user_name:
                    user_str += f"\n`{user_name}`"
                user_str += f"\n`ID: {user_id}`"
                embed.add_field(name="👤 User", value=user_str, inline=True)
            
            # Target info (for transfers)
            if target_id:
                target_str = f"<@{target_id}>"
                if target_name:
                    target_str += f"\n`{target_name}`"
                target_str += f"\n`ID: {target_id}`"
                embed.add_field(name="🎯 Target", value=target_str, inline=True)
            
            # Balance changes
            if before_balance is not None and after_balance is not None:
                diff = after_balance - before_balance
                diff_str = f"+${diff:,.2f}" if diff >= 0 else f"-${abs(diff):,.2f}"
                balance_str = (
                    f"Before: ${before_balance:,.2f}\n"
                    f"After: ${after_balance:,.2f}\n"
                    f"Change: **{diff_str}**"
                )
                embed.add_field(name="💰 User Balance", value=balance_str, inline=True)
            
            # Budget changes
            if before_budget is not None and after_budget is not None:
                diff = after_budget - before_budget
                diff_str = f"+${diff:,.2f}" if diff >= 0 else f"-${abs(diff):,.2f}"
                budget_str = (
                    f"Before: ${before_budget:,.2f}\n"
                    f"After: ${after_budget:,.2f}\n"
                    f"Change: **{diff_str}**"
                )
                embed.add_field(name="🏦 Server Budget", value=budget_str, inline=True)
            
            # Description
            if description:
                embed.add_field(name="📝 Description", value=description, inline=False)
            
            # Additional details
            if details:
                details_str = "\n".join([f"• **{k}**: {v}" for k, v in details.items()])
                embed.add_field(name="📋 Details", value=details_str, inline=False)
            
            # Footer with source
            embed.set_footer(text=f"Source: {source} | Economy Tracker v1.0")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] ERROR sending log: {e}")
            traceback.print_exc()
    
    @classmethod
    def _get_color(cls, action: EconomyAction) -> int:
        """Get embed color based on action type"""
        # Green - positive for user
        if action in [EconomyAction.USER_EARN, EconomyAction.USER_REWARD,
                     EconomyAction.USER_SALARY, EconomyAction.USER_REFUND,
                     EconomyAction.USER_TRANSFER_IN, EconomyAction.GAME_WIN,
                     EconomyAction.CASE_WIN, EconomyAction.SHOP_SALE]:
            return 0x2ECC71  # Green
        
        # Red - negative for user
        if action in [EconomyAction.USER_SPEND, EconomyAction.USER_TAX_PAID,
                     EconomyAction.USER_TRANSFER_OUT, EconomyAction.GAME_LOSE,
                     EconomyAction.GAME_BET, EconomyAction.SHOP_PURCHASE]:
            return 0xE74C3C  # Red
        
        # Gold - budget operations
        if action in [EconomyAction.BUDGET_ADD, EconomyAction.BUDGET_TAX_COLLECTED]:
            return 0xF1C40F  # Gold
        
        # Orange - budget expenses
        if action in [EconomyAction.BUDGET_REMOVE, EconomyAction.BUDGET_SALARY_PAID,
                     EconomyAction.BUDGET_REWARD_PAID]:
            return 0xE67E22  # Orange
        
        # Purple - admin actions
        if action in [EconomyAction.ADMIN_ADD, EconomyAction.ADMIN_REMOVE,
                     EconomyAction.ADMIN_SET]:
            return 0x9B59B6  # Purple
        
        # Blue - cases/misc
        if action in [EconomyAction.CASE_OPEN, EconomyAction.SHOP_ROLE_REPLACE]:
            return 0x3498DB  # Blue
        
        return 0x95A5A6  # Gray default
    
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
        """Special method for logging transfers with full details"""
        if not cls._bot:
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                return
            
            embed = discord.Embed(
                title="💸 MONEY TRANSFER",
                color=0x3498DB,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Transfer info
            embed.add_field(
                name="📤 Sender",
                value=f"<@{sender_id}>\n`{sender_name}`\n`ID: {sender_id}`",
                inline=True
            )
            embed.add_field(
                name="📥 Receiver", 
                value=f"<@{receiver_id}>\n`{receiver_name}`\n`ID: {receiver_id}`",
                inline=True
            )
            embed.add_field(
                name="💵 Amount",
                value=f"**${amount:,.2f}**\nTax: ${tax:,.2f}",
                inline=True
            )
            
            # Sender balance
            sender_diff = sender_after - sender_before
            embed.add_field(
                name="📊 Sender Balance",
                value=f"Before: ${sender_before:,.2f}\nAfter: ${sender_after:,.2f}\nChange: **-${abs(sender_diff):,.2f}**",
                inline=True
            )
            
            # Receiver balance
            receiver_diff = receiver_after - receiver_before
            embed.add_field(
                name="📊 Receiver Balance",
                value=f"Before: ${receiver_before:,.2f}\nAfter: ${receiver_after:,.2f}\nChange: **+${receiver_diff:,.2f}**",
                inline=True
            )
            
            # Server budget (tax)
            if tax > 0:
                budget_diff = budget_after - budget_before
                embed.add_field(
                    name="🏦 Server Budget (Tax)",
                    value=f"Before: ${budget_before:,.2f}\nAfter: ${budget_after:,.2f}\nChange: **+${budget_diff:,.2f}**",
                    inline=True
                )
            
            # Summary
            net_received = amount - tax
            embed.add_field(
                name="📝 Summary",
                value=(
                    f"• Gross Amount: ${amount:,.2f}\n"
                    f"• Tax Deducted: ${tax:,.2f}\n"
                    f"• Net Received: ${net_received:,.2f}"
                ),
                inline=False
            )
            
            embed.set_footer(text=f"Source: {source} | Economy Tracker v1.0")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] ERROR logging transfer: {e}")
    
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
        """Special method for logging game results"""
        if not cls._bot:
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                return
            
            # Determine color and title based on result
            if profit > 0:
                color = 0x2ECC71  # Green - win
                title = f"🎰 {game_name.upper()} - WIN!"
            elif profit < 0:
                color = 0xE74C3C  # Red - loss
                title = f"🎰 {game_name.upper()} - LOSS"
            else:
                color = 0xF1C40F  # Gold - push/tie
                title = f"🎰 {game_name.upper()} - PUSH"
            
            embed = discord.Embed(
                title=title,
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Player
            embed.add_field(
                name="🎮 Player",
                value=f"<@{user_id}>\n`{user_name}`",
                inline=True
            )
            
            # Bet & Result
            embed.add_field(
                name="🎲 Bet",
                value=f"**${bet:,.2f}**",
                inline=True
            )
            
            embed.add_field(
                name="📊 Result",
                value=f"**{result}**",
                inline=True
            )
            
            # Profit/Loss
            if profit >= 0:
                profit_str = f"+${profit:,.2f}"
            else:
                profit_str = f"-${abs(profit):,.2f}"
            embed.add_field(
                name="💰 Profit/Loss",
                value=f"**{profit_str}**",
                inline=True
            )
            
            # User balance
            user_diff = user_after - user_before
            diff_str = f"+${user_diff:,.2f}" if user_diff >= 0 else f"-${abs(user_diff):,.2f}"
            embed.add_field(
                name="👤 Player Balance",
                value=f"Before: ${user_before:,.2f}\nAfter: ${user_after:,.2f}\nChange: **{diff_str}**",
                inline=True
            )
            
            # Server budget
            budget_diff = budget_after - budget_before
            budget_diff_str = f"+${budget_diff:,.2f}" if budget_diff >= 0 else f"-${abs(budget_diff):,.2f}"
            embed.add_field(
                name="🏦 Server Budget",
                value=f"Before: ${budget_before:,.2f}\nAfter: ${budget_after:,.2f}\nChange: **{budget_diff_str}**",
                inline=True
            )
            
            # Game details
            if details:
                details_str = "\n".join([f"• **{k}**: {v}" for k, v in details.items()])
                embed.add_field(name="🎯 Game Details", value=details_str, inline=False)
            
            embed.set_footer(text=f"Game: {game_name} | Economy Tracker v1.0")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] ERROR logging game: {e}")
    
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
        """Special method for logging shop transactions"""
        if not cls._bot:
            return
        
        try:
            channel = cls._bot.get_channel(ECONOMY_LOG_CHANNEL_ID)
            if not channel:
                channel = await cls._bot.fetch_channel(ECONOMY_LOG_CHANNEL_ID)
            
            if not channel:
                return
            
            if action == "purchase":
                color = 0xE74C3C  # Red (spending)
                title = "🛒 ROLE PURCHASE"
            elif action == "sale":
                color = 0x2ECC71  # Green (earning)
                title = "💰 ROLE SALE"
            else:
                color = 0x3498DB  # Blue
                title = "🔄 ROLE OPERATION"
            
            embed = discord.Embed(
                title=title,
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            
            # User
            embed.add_field(
                name="👤 User",
                value=f"<@{user_id}>\n`{user_name}`",
                inline=True
            )
            
            # Role
            role_info = f"**{role_name}**\nPrice: ${role_price:,.2f}"
            if replaced_role:
                role_info += f"\nReplaced: {replaced_role}"
            embed.add_field(name="🏷️ Role", value=role_info, inline=True)
            
            # Transaction
            if action == "purchase":
                total = role_price + tax
                embed.add_field(
                    name="💵 Transaction",
                    value=f"Price: ${role_price:,.2f}\nTax: ${tax:,.2f}\n**Total: ${total:,.2f}**",
                    inline=True
                )
            else:
                embed.add_field(
                    name="💵 Refund",
                    value=f"Original: ${role_price:,.2f}\n**Refund: ${refund:,.2f}**",
                    inline=True
                )
            
            # User balance
            user_diff = user_after - user_before
            diff_str = f"+${user_diff:,.2f}" if user_diff >= 0 else f"-${abs(user_diff):,.2f}"
            embed.add_field(
                name="👤 User Balance",
                value=f"Before: ${user_before:,.2f}\nAfter: ${user_after:,.2f}\nChange: **{diff_str}**",
                inline=True
            )
            
            # Server budget
            budget_diff = budget_after - budget_before
            budget_diff_str = f"+${budget_diff:,.2f}" if budget_diff >= 0 else f"-${abs(budget_diff):,.2f}"
            embed.add_field(
                name="🏦 Server Budget",
                value=f"Before: ${budget_before:,.2f}\nAfter: ${budget_after:,.2f}\nChange: **{budget_diff_str}**",
                inline=True
            )
            
            embed.set_footer(text=f"Shop | Economy Tracker v1.0")
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"[EconomyLogger] ERROR logging shop: {e}")


# Singleton instance
economy_logger = EconomyLogger()

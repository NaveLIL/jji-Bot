"""
Economy Cog - Balance, transactions, case, pay commands
"""

import random
import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands

from src.services.database import db
from src.services.economy_logger import economy_logger, EconomyAction
from src.models.database import TransactionType
from src.utils.helpers import format_balance, calculate_tax, load_config
from src.utils.security import rate_limited
from src.utils.metrics import metrics


class EconomyCog(commands.Cog):
    """Economy commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    @app_commands.command(name="balance", description="Check your current balance")
    @rate_limited("economy", limit=5, window=60)
    async def balance(self, interaction: discord.Interaction):
        """Show user's balance"""
        user = await db.get_or_create_user(interaction.user.id)
        
        # Get rank on leaderboard
        all_users = await db.get_leaderboard("balance", limit=1000)
        rank = next((i + 1 for i, u in enumerate(all_users) if u.discord_id == interaction.user.id), None)
        rank_text = f"#{rank}" if rank else "Unranked"
        
        # Get role count separately to avoid DetachedInstanceError
        user_roles = await db.get_user_roles(interaction.user.id)
        role_count = len(user_roles) if user_roles else 0
        
        embed = discord.Embed(
            title="",
            color=0x2B2D31
        )
        
        # Header with balance
        embed.description = f"""
## 💰 YOUR BALANCE
━━━━━━━━━━━━━━━━━━━━━━━━━━
```diff\n+ {format_balance(user.balance)}\n```
"""
        
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        
        sb_hours = user.total_pb_time // 3600
        sb_mins = (user.total_pb_time % 3600) // 60
        
        embed.add_field(name="📊 Rank", value=f"`{rank_text}`", inline=True)
        embed.add_field(name="⏱️ SB Time", value=f"`{sb_hours}h {sb_mins}m`", inline=True)
        embed.add_field(name="🎒 Roles", value=f"`{role_count}`", inline=True)
        
        embed.set_footer(text="💎 Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="pay", description="Transfer money to another user")
    @app_commands.describe(
        user="The user to send money to",
        amount="Amount to transfer"
    )
    @rate_limited("economy", limit=5, window=60)
    async def pay(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member, 
        amount: float
    ):
        """Transfer money to another user with tax"""
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ You can't pay yourself!",
                ephemeral=True
            )
            return
        
        if user.bot:
            await interaction.response.send_message(
                "❌ You can't pay bots!",
                ephemeral=True
            )
            return
        
        if amount <= 0:
            await interaction.response.send_message(
                "❌ Amount must be positive!",
                ephemeral=True
            )
            return
        
        sender = await db.get_or_create_user(interaction.user.id)
        
        if sender.balance < amount:
            await interaction.response.send_message(
                f"❌ Insufficient balance! You have {format_balance(sender.balance)}",
                ephemeral=True
            )
            return
        
        # Get tax rate
        economy = await db.get_server_economy()
        net_amount, tax_amount = calculate_tax(amount, economy.tax_rate)
        
        # Process transfer (ATOMICALLY)
        result = await db.transfer_money(
            sender_id=interaction.user.id,
            recipient_id=user.id,
            amount=amount,
            description=f"Transfer from {interaction.user.display_name} to {user.display_name}"
        )
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Transfer failed: {result.get('error', 'Unknown error')}",
                ephemeral=True
            )
            return

        # Log transfer (using result data)
        economy_after = await db.get_server_economy() # Refetch or use result budget
        
        # Use values from result
        before = result["sender_before"]
        after = result["sender_after"]
        recipient_before = result["recipient_before"]
        recipient_after = result["recipient_after"]
        
        await economy_logger.log_transfer(
            sender_id=interaction.user.id,
            sender_name=interaction.user.display_name,
            receiver_id=user.id,
            receiver_name=user.display_name,
            amount=amount,
            tax=tax_amount, # calculated earlier, verified in result
            sender_before=before,
            sender_after=after,
            receiver_before=recipient_before,
            receiver_after=recipient_after,
            budget_before=result["budget_before"],
            budget_after=result["budget_after"],
            source="Pay Command"
        )
        
        # Track metrics
        metrics.track_transaction("transfer")
        if tax_amount > 0:
            metrics.track_tax(tax_amount)
        
        embed = discord.Embed(
            title="",
            color=0x57F287  # Green
        )
        
        embed.description = f"""
## 💸 Transfer Complete

━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        embed.add_field(
            name="📤 Sent", 
            value=f"```\n{format_balance(amount)}\n```", 
            inline=True
        )
        embed.add_field(
            name="💼 Tax", 
            value=f"```\n{format_balance(tax_amount)} ({economy.tax_rate:.0f}%)\n```", 
            inline=True
        )
        embed.add_field(
            name="📥 Received", 
            value=f"```diff\n+ {format_balance(net_amount)}\n```", 
            inline=True
        )
        
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        
        embed.add_field(
            name="👤 Recipient", 
            value=user.mention, 
            inline=True
        )
        embed.add_field(
            name="💰 Your Balance", 
            value=f"`{format_balance(after)}`", 
            inline=True
        )
        
        embed.set_footer(text="💎 Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="case", description="Open a random case (24h cooldown)")
    @rate_limited("economy", limit=3, window=60)
    async def case(self, interaction: discord.Interaction):
        """Open a random case with chance for money"""
        config = self.config.get("case", {})
        cooldown_hours = config.get("cooldown_hours", 24)
        
        # Check cooldown
        can_use, next_time = await db.can_use_case(
            interaction.user.id,
            cooldown_hours
        )
        
        if not can_use:
            time_left = next_time - datetime.utcnow()
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            
            embed = discord.Embed(
                description=(
                    "## ⏳ Case on Cooldown\n\n"
                    f"**Available in:** `{hours}h {minutes}m`\n\n"
                    "*Come back later for your daily reward!*"
                ),
                color=0x5865F2
            )
            embed.set_author(name="📦 Daily Case", icon_url=interaction.user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Record usage BEFORE rolling
        await db.record_case_use(interaction.user.id)
        
        # Show opening animation
        opening_embed = discord.Embed(
            description=(
                "## 📦 Opening Case...\n\n"
                "🎁 **???** 🎁\n\n"
                "*Rolling for reward...*"
            ),
            color=0xFEE75C
        )
        opening_embed.set_author(name=f"📦 {interaction.user.display_name}'s Case", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=opening_embed)
        
        # Small delay for suspense
        await asyncio.sleep(1.5)
        
        # Roll for reward
        empty_chance = config.get("empty_chance", 30)
        roll = random.uniform(0, 100)
        
        if roll < empty_chance:
            # Empty case
            result_embed = discord.Embed(color=0x99AAB5)
            result_embed.description = (
                "## 📦 Empty Case\n\n"
                "💨 *Nothing inside...*\n\n"
                "> Better luck next time!\n"
                "> The case was empty."
            )
            result_embed.set_author(name=f"📦 {interaction.user.display_name}'s Case", icon_url=interaction.user.display_avatar.url)
            result_embed.set_footer(text=f"⏰ Next case in {cooldown_hours}h")
            await interaction.edit_original_response(embed=result_embed)
            return
        
        # Won something!
        weights = config.get("reward_weights", {})
        
        # Weighted random selection
        total_weight = sum(w.get("weight", 0) for w in weights.values())
        rand = random.uniform(0, total_weight)
        
        current = 0
        selected_range = [1, 5]  # Default
        tier_name = "low"
        
        for name, tier_data in weights.items():
            current += tier_data.get("weight", 0)
            if rand <= current:
                selected_range = tier_data.get("range", [1, 5])
                tier_name = name
                break
        
        reward = random.randint(selected_range[0], selected_range[1])
        
        # Apply tax
        economy = await db.get_server_economy()
        net_reward, tax = calculate_tax(reward, economy.tax_rate)
        
        # Pay reward atomically from budget
        result = await db.pay_from_budget_atomic(
            discord_id=interaction.user.id,
            gross_amount=reward,
            net_amount=net_reward,
            tax_amount=tax,
            transaction_type=TransactionType.CASE_REWARD,
            description="Case reward"
        )
        
        if not result["success"]:
            error_embed = discord.Embed(
                description=(
                    "## ❌ Reward Failed\n\n"
                    f"> {result.get('error', 'Server budget depleted')}\n"
                    "> Please try again later."
                ),
                color=0xED4245
            )
            await interaction.edit_original_response(embed=error_embed)
            return
        
        # Log case win
        await economy_logger.log(
            action=EconomyAction.CASE_WIN,
            amount=net_reward,
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            before_balance=result["before_balance"],
            after_balance=result["after_balance"],
            before_budget=result["before_budget"],
            after_budget=result["after_budget"],
            description=f"Case reward: ${reward:,.2f} (gross)",
            details={
                "Gross Reward": f"${reward:,.2f}",
                "Tax": f"${tax:,.2f}",
                "Net Reward": f"${net_reward:,.2f}"
            },
            source="Case Command"
        )
        
        # Build result embed based on tier
        if tier_name == "high" or reward >= 20:
            # JACKPOT!
            result_embed = discord.Embed(color=0xFEE75C)
            result_embed.description = (
                "# 🎉 JACKPOT!\n\n"
                f"## 💎 ${reward:,.0f}\n\n"
                f"**Gross:** `{format_balance(reward)}`\n"
                f"**Tax ({economy.tax_rate:.0f}%):** `-{format_balance(tax)}`\n"
                f"**Net:** `{format_balance(net_reward)}`\n\n"
                f"───────────────────\n"
                f"💰 **New Balance:** `{format_balance(result['after_balance'])}`"
            )
        elif tier_name == "medium" or reward >= 10:
            # Medium win
            result_embed = discord.Embed(color=0x57F287)
            result_embed.description = (
                "## 🎁 Winner!\n\n"
                f"### 💵 ${reward:,.0f}\n\n"
                f"**Gross:** `{format_balance(reward)}`\n"
                f"**Tax:** `-{format_balance(tax)}`\n"
                f"**Net:** `{format_balance(net_reward)}`"
            )
        else:
            # Low win
            result_embed = discord.Embed(color=0x3498DB)
            result_embed.description = (
                "## 🎁 Reward!\n\n"
                f"### 💰 ${reward:,.0f}\n\n"
                f"**You won:** `{format_balance(net_reward)}`"
            )
        
        result_embed.set_author(name=f"📦 {interaction.user.display_name}'s Case", icon_url=interaction.user.display_avatar.url)
        result_embed.set_footer(text=f"⏰ Next case in {cooldown_hours}h • Balance: {format_balance(result['after_balance'])}")
        
        metrics.track_transaction("case_win")
        await interaction.edit_original_response(embed=result_embed)
    
    @app_commands.command(name="daily", description="Claim your daily reward")
    @rate_limited("economy", limit=1, window=60)
    async def daily(self, interaction: discord.Interaction):
        """Alias for case command"""
        await self.case.callback(self, interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))

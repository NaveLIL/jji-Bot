"""
Economy Cog - Balance, transactions, case, pay commands
"""

import random
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands

from src.services.database import db
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
        
        # Process transfer
        success, before, after = await db.update_user_balance(
            interaction.user.id,
            -amount,
            TransactionType.TRANSFER_OUT,
            description=f"Transfer to {user.display_name}",
            related_user_id=user.id
        )
        
        if not success:
            await interaction.response.send_message(
                "❌ Transfer failed! Please try again.",
                ephemeral=True
            )
            return
        
        # Add to recipient (net of tax)
        await db.update_user_balance(
            user.id,
            net_amount,
            TransactionType.TRANSFER_IN,
            description=f"Transfer from {interaction.user.display_name}",
            related_user_id=interaction.user.id
        )
        
        # Add tax to server budget
        if tax_amount > 0:
            await db.add_taxes_collected(tax_amount)
        
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
            
            await interaction.response.send_message(
                f"⏳ Case on cooldown! Available in **{hours}h {minutes}m**",
                ephemeral=True
            )
            return
        
        # Record usage
        await db.record_case_use(interaction.user.id)
        
        # Roll for reward
        empty_chance = config.get("empty_chance", 99)
        roll = random.uniform(0, 100)
        
        if roll < empty_chance:
            # Empty case
            reward = 0
            result_text = "📦 **Empty!** Better luck next time!"
            color = discord.Color.dark_gray()
        else:
            # Won something!
            weights = config.get("reward_weights", {})
            
            # Weighted random selection
            total_weight = sum(w.get("weight", 0) for w in weights.values())
            rand = random.uniform(0, total_weight)
            
            current = 0
            selected_range = [2, 5]  # Default
            
            for tier_data in weights.values():
                current += tier_data.get("weight", 0)
                if rand <= current:
                    selected_range = tier_data.get("range", [2, 5])
                    break
            
            reward = random.randint(selected_range[0], selected_range[1])
            
            # Apply tax
            economy = await db.get_server_economy()
            net_reward, tax = calculate_tax(reward, economy.tax_rate)
            
            # Add to balance
            await db.update_user_balance(
                interaction.user.id,
                net_reward,
                TransactionType.CASE_REWARD,
                tax_amount=tax,
                description="Case reward"
            )
            
            if tax > 0:
                await db.add_taxes_collected(tax)
            
            if reward >= 10:
                result_text = f"# 🎉 JACKPOT!\n\n**You won {format_balance(reward)}!**\nAfter tax ({economy.tax_rate:.0f}%): `{format_balance(net_reward)}`"
                color = 0xFEE75C  # Gold
            else:
                result_text = f"## 🎁 Winner!\n\n**You won {format_balance(reward)}!**\nAfter tax: `{format_balance(net_reward)}`"
                color = 0x57F287  # Green
            
            metrics.track_transaction("case_win")
        
        embed = discord.Embed(
            description=result_text,
            color=color
        )
        
        # Add case visual
        if reward == 0:
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1234567890.png")  # Empty box
        
        embed.set_author(name="📦 Daily Case", icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"⏰ Next case in {cooldown_hours}h • 💎 Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="daily", description="Claim your daily reward")
    @rate_limited("economy", limit=1, window=60)
    async def daily(self, interaction: discord.Interaction):
        """Alias for case command"""
        await self.case.callback(self, interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))

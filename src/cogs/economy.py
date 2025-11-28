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
        
        embed = discord.Embed(
            title="💰 Balance",
            color=discord.Color.gold()
        )
        embed.add_field(
            name=interaction.user.display_name,
            value=format_balance(user.balance),
            inline=False
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
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
            title="💸 Transfer Complete",
            color=discord.Color.green()
        )
        embed.add_field(name="Sent", value=format_balance(amount), inline=True)
        embed.add_field(name="Tax", value=f"{format_balance(tax_amount)} ({economy.tax_rate}%)", inline=True)
        embed.add_field(name="Received", value=format_balance(net_amount), inline=True)
        embed.add_field(name="To", value=user.mention, inline=True)
        embed.add_field(name="Your Balance", value=format_balance(after), inline=True)
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
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
            
            result_text = f"🎉 **You won {format_balance(reward)}!**\nAfter tax: {format_balance(net_reward)}"
            color = discord.Color.gold()
            
            metrics.track_transaction("case_win")
        
        embed = discord.Embed(
            title="📦 Case Opened!",
            description=result_text,
            color=color
        )
        embed.set_footer(text=f"Next case available in {cooldown_hours}h • Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="daily", description="Claim your daily reward")
    @rate_limited("economy", limit=1, window=60)
    async def daily(self, interaction: discord.Interaction):
        """Alias for case command"""
        await self.case.callback(self, interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))

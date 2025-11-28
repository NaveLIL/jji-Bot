"""
Admin Cog - Economy panel, channel configs, moderation
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal

from src.services.database import db
from src.models.database import TransactionType, LogType
from src.utils.helpers import format_balance, load_config, save_config
from src.utils.security import admin_only
from src.utils.metrics import metrics


# ==================== MODALS ====================

class TaxRateModal(discord.ui.Modal, title="Set Tax Rate"):
    rate = discord.ui.TextInput(
        label="Tax Rate (%)",
        placeholder="Enter tax rate (0-50)",
        default="10",
        max_length=5
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            rate = float(self.rate.value)
            if rate < 0 or rate > 50:
                await interaction.response.send_message(
                    "❌ Tax rate must be between 0% and 50%",
                    ephemeral=True
                )
                return
            
            await db.set_tax_rate(rate)
            
            # Update config file
            config = load_config()
            config["economy"]["tax_rate"] = rate
            save_config(config)
            
            await interaction.response.send_message(
                f"✅ Tax rate set to **{rate}%**",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )


class SoldierValueModal(discord.ui.Modal, title="Set Soldier Value"):
    value = discord.ui.TextInput(
        label="Soldier Value ($)",
        placeholder="Enter soldier value for budget",
        default="10000",
        max_length=10
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = float(self.value.value)
            if value < 0:
                await interaction.response.send_message(
                    "❌ Value must be positive!",
                    ephemeral=True
                )
                return
            
            await db.set_soldier_value(value)
            
            config = load_config()
            config["economy"]["soldier_value"] = value
            save_config(config)
            
            await interaction.response.send_message(
                f"✅ Soldier value set to **{format_balance(value)}**",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )


class PrimeTimeModal(discord.ui.Modal, title="Set Prime Time Hours"):
    start = discord.ui.TextInput(
        label="Start Hour (UTC)",
        placeholder="14",
        default="14",
        max_length=2
    )
    end = discord.ui.TextInput(
        label="End Hour (UTC)",
        placeholder="22",
        default="22",
        max_length=2
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            start = int(self.start.value)
            end = int(self.end.value)
            
            if start < 0 or start > 23 or end < 0 or end > 23:
                await interaction.response.send_message(
                    "❌ Hours must be 0-23!",
                    ephemeral=True
                )
                return
            
            config = load_config()
            config["prime_time"]["start_hour"] = start
            config["prime_time"]["end_hour"] = end
            save_config(config)
            
            await interaction.response.send_message(
                f"✅ Prime time set to **{start}:00 - {end}:00 UTC**",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )


class SalaryModal(discord.ui.Modal, title="Set Salary Rates"):
    soldier = discord.ui.TextInput(
        label="Soldier ($/10min)",
        placeholder="10",
        default="10",
        max_length=5
    )
    sergeant = discord.ui.TextInput(
        label="Sergeant ($/10min)",
        placeholder="20",
        default="20",
        max_length=5
    )
    officer = discord.ui.TextInput(
        label="Officer ($/10min)",
        placeholder="20",
        default="20",
        max_length=5
    )
    master_bonus = discord.ui.TextInput(
        label="Sergeant Master Bonus ($/day)",
        placeholder="50",
        default="50",
        max_length=5
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            config = load_config()
            config["salaries"]["soldier_per_10min"] = float(self.soldier.value)
            config["salaries"]["sergeant_per_10min"] = float(self.sergeant.value)
            config["salaries"]["officer_per_10min"] = float(self.officer.value)
            config["salaries"]["sergeant_master_bonus"] = float(self.master_bonus.value)
            save_config(config)
            
            await interaction.response.send_message(
                f"✅ Salary rates updated:\n"
                f"• Soldier: ${self.soldier.value}/10min\n"
                f"• Sergeant: ${self.sergeant.value}/10min\n"
                f"• Officer: ${self.officer.value}/10min\n"
                f"• Master Bonus: ${self.master_bonus.value}/day",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid numbers!",
                ephemeral=True
            )


class BudgetModal(discord.ui.Modal, title="Set Server Budget"):
    amount = discord.ui.TextInput(
        label="New Budget Amount ($)",
        placeholder="50000",
        max_length=15
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(self.amount.value)
            if amount < 0:
                await interaction.response.send_message(
                    "❌ Budget cannot be negative!",
                    ephemeral=True
                )
                return
            
            # Set budget directly
            async with db.session() as session:
                from sqlalchemy import select, update
                from src.models.database import ServerEconomy
                
                await session.execute(
                    update(ServerEconomy).values(total_budget=amount)
                )
                await session.commit()
            
            await interaction.response.send_message(
                f"✅ Server budget set to **{format_balance(amount)}**",
                ephemeral=True
            )
            
            metrics.update_server_budget(amount)
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )


class AddBudgetModal(discord.ui.Modal, title="Add to Server Budget"):
    amount = discord.ui.TextInput(
        label="Amount to Add ($)",
        placeholder="10000",
        max_length=15
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(self.amount.value)
            
            success, new_budget = await db.update_server_budget(amount, add=True)
            
            if success:
                await interaction.response.send_message(
                    f"✅ Added **{format_balance(amount)}** to budget.\n"
                    f"New budget: **{format_balance(new_budget)}**",
                    ephemeral=True
                )
                metrics.update_server_budget(new_budget)
            else:
                await interaction.response.send_message(
                    "❌ Failed to update budget!",
                    ephemeral=True
                )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )


# ==================== ECONOMY PANEL VIEW ====================

class EconomyPanelView(discord.ui.View):
    """Interactive economy control panel"""
    
    def __init__(self, timeout: float = 600):
        super().__init__(timeout=timeout)
    
    @discord.ui.button(label="Set Tax Rate", style=discord.ButtonStyle.primary, row=0)
    async def tax_rate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(TaxRateModal())
    
    @discord.ui.button(label="Set Soldier Value", style=discord.ButtonStyle.primary, row=0)
    async def soldier_value(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(SoldierValueModal())
    
    @discord.ui.button(label="Set Prime Time", style=discord.ButtonStyle.primary, row=0)
    async def prime_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(PrimeTimeModal())
    
    @discord.ui.button(label="Set Salaries", style=discord.ButtonStyle.secondary, row=1)
    async def salaries(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(SalaryModal())
    
    @discord.ui.button(label="Set Budget", style=discord.ButtonStyle.danger, row=1)
    async def set_budget(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(BudgetModal())
    
    @discord.ui.button(label="Add Budget", style=discord.ButtonStyle.success, row=1)
    async def add_budget(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(AddBudgetModal())
    
    @discord.ui.button(label="🔄 Refresh Stats", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.get_stats_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def get_stats_embed(self) -> discord.Embed:
        """Generate stats embed"""
        economy = await db.get_server_economy()
        config = load_config()
        
        embed = discord.Embed(
            title="⚙️ Economy Control Panel",
            color=discord.Color.gold()
        )
        
        # Budget section
        embed.add_field(
            name="💵 Server Budget",
            value=format_balance(economy.total_budget),
            inline=True
        )
        
        embed.add_field(
            name="📈 Tax Rate",
            value=f"{economy.tax_rate}%",
            inline=True
        )
        
        embed.add_field(
            name="👤 Soldier Value",
            value=format_balance(economy.soldier_value),
            inline=True
        )
        
        # Prime time
        prime = config.get("prime_time", {})
        embed.add_field(
            name="⏰ Prime Time",
            value=f"{prime.get('start_hour', 14)}:00 - {prime.get('end_hour', 22)}:00 UTC",
            inline=True
        )
        
        # Salaries
        salaries = config.get("salaries", {})
        embed.add_field(
            name="💰 Salaries (per 10min)",
            value=f"Soldier: ${salaries.get('soldier_per_10min', 10)}\n"
                  f"Sergeant: ${salaries.get('sergeant_per_10min', 20)}\n"
                  f"Officer: ${salaries.get('officer_per_10min', 20)}",
            inline=True
        )
        
        # Totals
        embed.add_field(
            name="🏦 Taxes Collected",
            value=format_balance(economy.total_taxes_collected),
            inline=True
        )
        
        embed.add_field(
            name="💸 Rewards Paid",
            value=format_balance(economy.total_rewards_paid),
            inline=True
        )
        
        total_users = await db.get_total_users()
        embed.add_field(
            name="👥 Total Users",
            value=str(total_users),
            inline=True
        )
        
        embed.set_footer(text="Click buttons below to modify settings • Developed by NaveL for JJI in 2025")
        
        return embed


class AdminCog(commands.Cog):
    """Administration commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    @app_commands.command(name="economy_panel", description="Open economy control panel (Admin)")
    @admin_only()
    async def economy_panel(self, interaction: discord.Interaction):
        """Display economy control panel"""
        view = EconomyPanelView()
        embed = await view.get_stats_embed()
        
        await interaction.response.send_message(embed=embed, view=view)
    
    @app_commands.command(name="setbalance", description="Set a user's balance (Admin)")
    @app_commands.describe(
        user="The user to modify",
        amount="New balance amount"
    )
    @admin_only()
    async def setbalance(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: float
    ):
        """Set user balance"""
        if amount < 0:
            await interaction.response.send_message(
                "❌ Balance cannot be negative!",
                ephemeral=True
            )
            return
        
        success, before, after = await db.set_user_balance(
            user.id,
            amount,
            f"Set by {interaction.user.display_name}"
        )
        
        if success:
            await interaction.response.send_message(
                f"✅ Set **{user.display_name}**'s balance to **{format_balance(amount)}**\n"
                f"Previous: {format_balance(before)}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to update balance!",
                ephemeral=True
            )
    
    @app_commands.command(name="addbalance", description="Add to a user's balance (Admin)")
    @app_commands.describe(
        user="The user to modify",
        amount="Amount to add (can be negative)"
    )
    @admin_only()
    async def addbalance(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: float
    ):
        """Add to user balance"""
        success, before, after = await db.update_user_balance(
            user.id,
            amount,
            TransactionType.ADMIN_ADD,
            description=f"Added by {interaction.user.display_name}"
        )
        
        if success:
            await interaction.response.send_message(
                f"✅ Added **{format_balance(amount)}** to **{user.display_name}**\n"
                f"Before: {format_balance(before)} → After: {format_balance(after)}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to update balance! (Would go negative?)",
                ephemeral=True
            )
    
    @app_commands.command(name="fine", description="Fine a user (Admin)")
    @app_commands.describe(
        user="The user to fine",
        amount="Fine amount"
    )
    @admin_only()
    async def fine(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: float
    ):
        """Fine a user"""
        if amount <= 0:
            await interaction.response.send_message(
                "❌ Fine amount must be positive!",
                ephemeral=True
            )
            return
        
        db_user = await db.get_or_create_user(user.id)
        
        if db_user.balance < amount:
            await interaction.response.send_message(
                f"❌ User only has {format_balance(db_user.balance)}!",
                ephemeral=True
            )
            return
        
        success, before, after = await db.update_user_balance(
            user.id,
            -amount,
            TransactionType.FINE,
            description=f"Fine by {interaction.user.display_name}"
        )
        
        if success:
            # Add to server budget
            await db.update_server_budget(amount, add=True)
            
            await interaction.response.send_message(
                f"✅ Fined **{user.display_name}** for **{format_balance(amount)}**\n"
                f"Their balance: {format_balance(before)} → {format_balance(after)}\n"
                f"Added to server budget.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to apply fine!",
                ephemeral=True
            )
    
    @app_commands.command(name="confiscate", description="Confiscate a user's entire balance (Admin)")
    @app_commands.describe(user="The user to confiscate from")
    @admin_only()
    async def confiscate(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):
        """Confiscate entire balance"""
        db_user = await db.get_or_create_user(user.id)
        amount = db_user.balance
        
        if amount <= 0:
            await interaction.response.send_message(
                f"❌ User has no balance to confiscate!",
                ephemeral=True
            )
            return
        
        success, before, after = await db.update_user_balance(
            user.id,
            -amount,
            TransactionType.CONFISCATE,
            description=f"Confiscated by {interaction.user.display_name}"
        )
        
        if success:
            await db.update_server_budget(amount, add=True)
            
            await interaction.response.send_message(
                f"✅ Confiscated **{format_balance(amount)}** from **{user.display_name}**\n"
                f"Added to server budget.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to confiscate!",
                ephemeral=True
            )
    
    @app_commands.command(name="set_log_channel", description="Set a logging channel (Admin)")
    @app_commands.describe(
        channel_type="Type of log channel",
        channel="The channel to use"
    )
    @admin_only()
    async def set_log_channel(
        self,
        interaction: discord.Interaction,
        channel_type: Literal["officer", "recruit", "economy", "games", "server", "security"],
        channel: discord.TextChannel
    ):
        """Set logging channel"""
        log_type = LogType(channel_type)
        await db.set_channel_config(log_type, channel.id)
        
        # Update config file
        config = load_config()
        config["channels"][f"log_{channel_type}"] = channel.id
        save_config(config)
        
        await interaction.response.send_message(
            f"✅ Set **{channel_type}** log channel to {channel.mention}",
            ephemeral=True
        )
    
    @app_commands.command(name="set_master_channel", description="Set master voice channel (Admin)")
    @app_commands.describe(channel="The master voice channel")
    @admin_only()
    async def set_master_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel
    ):
        """Set master voice channel"""
        config = load_config()
        config["channels"]["master_voice"] = channel.id
        save_config(config)
        
        await interaction.response.send_message(
            f"✅ Set master voice channel to **{channel.name}**",
            ephemeral=True
        )
    
    @app_commands.command(name="set_ping_channel", description="Set sergeant ping channel (Admin)")
    @app_commands.describe(channel="The channel for sergeant pings")
    @admin_only()
    async def set_ping_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        """Set ping channel"""
        config = load_config()
        config["channels"]["ping_sergeant"] = channel.id
        save_config(config)
        
        await interaction.response.send_message(
            f"✅ Set sergeant ping channel to {channel.mention}",
            ephemeral=True
        )
    
    @app_commands.command(name="set_role", description="Set a system role (Admin)")
    @app_commands.describe(
        role_type="Type of role",
        role="The Discord role"
    )
    @admin_only()
    async def set_role(
        self,
        interaction: discord.Interaction,
        role_type: Literal["soldier", "sergeant", "officer", "admin"],
        role: discord.Role
    ):
        """Set system role"""
        config = load_config()
        config["roles"][role_type] = role.id
        save_config(config)
        
        await interaction.response.send_message(
            f"✅ Set **{role_type}** role to {role.mention}",
            ephemeral=True
        )
    
    @app_commands.command(name="about", description="About this bot")
    async def about(self, interaction: discord.Interaction):
        """Display bot information"""
        embed = discord.Embed(
            title="🤖 JJI Regiment Bot",
            description="A production-grade Discord bot for military gaming community management.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name="📋 Features",
            value="• Economy system with salaries\n"
                  "• Role shop & marketplace\n"
                  "• Games (Blackjack, Coinflip)\n"
                  "• Officer recruitment system\n"
                  "• Prime time PB tracking",
            inline=True
        )
        
        embed.add_field(
            name="⚙️ Commands",
            value="`/balance` - Check balance\n"
                  "`/profile` - View profile\n"
                  "`/shop` - Role shop\n"
                  "`/blackjack` - Play blackjack\n"
                  "`/coinflip` - Flip a coin",
            inline=True
        )
        
        embed.add_field(
            name="👮 Officer Commands",
            value="`/accept` - Accept recruit\n"
                  "`/officer_stats` - View stats\n"
                  "`/recruits` - View recruits",
            inline=True
        )
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="botstats", description="View bot statistics")
    async def botstats(self, interaction: discord.Interaction):
        """Display bot statistics"""
        import datetime
        
        uptime = datetime.datetime.utcnow() - self.bot.start_time if hasattr(self.bot, 'start_time') else None
        
        economy = await db.get_server_economy()
        total_users = await db.get_total_users()
        total_balance = await db.get_total_balance()
        
        embed = discord.Embed(
            title="📊 Bot Statistics",
            color=discord.Color.green()
        )
        
        # Bot info
        embed.add_field(
            name="🤖 Bot",
            value=f"Latency: {round(self.bot.latency * 1000)}ms\n"
                  f"Guilds: {len(self.bot.guilds)}\n"
                  f"Uptime: {str(uptime).split('.')[0] if uptime else 'N/A'}",
            inline=True
        )
        
        # Economy
        embed.add_field(
            name="💰 Economy",
            value=f"Budget: {format_balance(economy.total_budget)}\n"
                  f"Tax Rate: {economy.tax_rate}%\n"
                  f"Total User Balance: {format_balance(total_balance)}",
            inline=True
        )
        
        # Users
        embed.add_field(
            name="👥 Users",
            value=f"Total: {total_users}\n"
                  f"Taxes Collected: {format_balance(economy.total_taxes_collected)}\n"
                  f"Rewards Paid: {format_balance(economy.total_rewards_paid)}",
            inline=True
        )
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))

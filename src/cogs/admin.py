"""
Admin Cog - Economy panel, channel configs, moderation
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal

from src.services.database import db
from src.services.economy_logger import economy_logger, EconomyAction
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
            
            old_value, new_value, soldier_count = await db.set_soldier_value(value)
            
            config = load_config()
            config["economy"]["soldier_value"] = value
            save_config(config)
            
            # Calculate budget change
            budget_change = (new_value - old_value) * soldier_count
            change_str = f"+{format_balance(budget_change)}" if budget_change >= 0 else format_balance(budget_change)
            
            await interaction.response.send_message(
                f"✅ Soldier value updated!\n\n"
                f"**Old Value:** {format_balance(old_value)}\n"
                f"**New Value:** {format_balance(new_value)}\n"
                f"**Soldiers:** {soldier_count}\n"
                f"**Budget Change:** {change_str}",
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
            new_soldier = float(self.soldier.value)
            new_sergeant = float(self.sergeant.value)
            new_officer = float(self.officer.value)
            new_bonus = float(self.master_bonus.value)

            config = load_config()

            # Calculate budget impact
            active_users = await db.get_all_active_users()
            soldier_count = len([u for u in active_users if u.is_soldier])
            sergeant_count = len([u for u in active_users if u.is_sergeant])
            officer_count = len([u for u in active_users if u.is_officer])

            old_salaries = config.get("salaries", {})
            old_soldier = old_salaries.get("soldier_per_10min", 10)
            old_sergeant = old_salaries.get("sergeant_per_10min", 20)
            old_officer = old_salaries.get("officer_per_10min", 20)

            # Cost per hour
            old_hourly_cost = (soldier_count * old_soldier * 6) + \
                              (sergeant_count * old_sergeant * 6) + \
                              (officer_count * old_officer * 6)

            new_hourly_cost = (soldier_count * new_soldier * 6) + \
                              (sergeant_count * new_sergeant * 6) + \
                              (officer_count * new_officer * 6)

            hourly_diff = new_hourly_cost - old_hourly_cost
            daily_diff = hourly_diff * 24  # Show 24h impact as requested

            # Update config
            config["salaries"]["soldier_per_10min"] = new_soldier
            config["salaries"]["sergeant_per_10min"] = new_sergeant
            config["salaries"]["officer_per_10min"] = new_officer
            config["salaries"]["sergeant_master_bonus"] = new_bonus
            save_config(config)
            
            # Log changes
            economy = await db.get_server_economy()
            async with db.session() as session:
                from src.models.database import SalaryChange
                change = SalaryChange(
                    soldier_rate=new_soldier,
                    sergeant_rate=new_sergeant,
                    officer_rate=new_officer,
                    budget_before=economy.total_budget,
                    budget_after=economy.total_budget,  # Budget doesn't change immediately
                    changed_by=interaction.user.id
                )
                session.add(change)

            warning = ""
            if daily_diff > 0:
                warning = f"\n⚠️ **Budget Impact:** Costs increase by **{format_balance(daily_diff)}/day** (est)"
            elif daily_diff < 0:
                warning = f"\n📉 **Budget Impact:** Savings of **{format_balance(abs(daily_diff))}/day** (est)"

            await interaction.response.send_message(
                f"✅ Salary rates updated:\n"
                f"• Soldier: ${new_soldier}/10min\n"
                f"• Sergeant: ${new_sergeant}/10min\n"
                f"• Officer: ${new_officer}/10min\n"
                f"• Master Bonus: ${new_bonus}/day"
                f"{warning}",
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
            
            economy_before = await db.get_server_economy()
            budget_before = economy_before.total_budget
            
            success, new_budget = await db.update_server_budget(amount, add=True)
            
            if success:
                # Log admin budget change
                await economy_logger.log(
                    action=EconomyAction.ADMIN_ADD,
                    amount=amount,
                    user_id=interaction.user.id,
                    user_name=interaction.user.display_name,
                    before_budget=budget_before,
                    after_budget=new_budget,
                    description=f"Admin added to server budget",
                    details={"Admin": f"<@{interaction.user.id}>"},
                    source="Admin AddBudget"
                )
                
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
    """Interactive economy control panel - persistent view"""
    
    def __init__(self):
        super().__init__(timeout=None)  # Never timeout
    
    @discord.ui.button(label="Set Tax Rate", style=discord.ButtonStyle.primary, row=0, custom_id="economy_panel:tax_rate")
    async def tax_rate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(TaxRateModal())
    
    @discord.ui.button(label="Set Soldier Value", style=discord.ButtonStyle.primary, row=0, custom_id="economy_panel:soldier_value")
    async def soldier_value(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(SoldierValueModal())
    
    @discord.ui.button(label="Set Prime Time", style=discord.ButtonStyle.primary, row=0, custom_id="economy_panel:prime_time")
    async def prime_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(PrimeTimeModal())
    
    @discord.ui.button(label="Set Salaries", style=discord.ButtonStyle.secondary, row=1, custom_id="economy_panel:salaries")
    async def salaries(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(SalaryModal())
    
    @discord.ui.button(label="Set Budget", style=discord.ButtonStyle.danger, row=1, custom_id="economy_panel:set_budget")
    async def set_budget(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(BudgetModal())
    
    @discord.ui.button(label="Add Budget", style=discord.ButtonStyle.success, row=1, custom_id="economy_panel:add_budget")
    async def add_budget(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(AddBudgetModal())
    
    @discord.ui.button(label="🔄 Refresh Stats", style=discord.ButtonStyle.secondary, row=2, custom_id="economy_panel:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.get_stats_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def get_stats_embed(self) -> discord.Embed:
        """Generate stats embed"""
        economy = await db.get_server_economy()
        config = load_config()
        
        embed = discord.Embed(color=0xFFD700)
        
        embed.description = """
## ⚙️ ECONOMY CONTROL PANEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Budget section
        embed.add_field(
            name="🏦 Server Budget",
            value=f"```diff\n+ {format_balance(economy.total_budget)}\n```",
            inline=True
        )
        
        embed.add_field(
            name="📈 Tax Rate",
            value=f"```\n{economy.tax_rate}%\n```",
            inline=True
        )
        
        embed.add_field(
            name="👤 Soldier Value",
            value=f"```\n{format_balance(economy.soldier_value)}\n```",
            inline=True
        )
        
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        
        # Prime time
        prime = config.get("prime_time", {})
        embed.add_field(
            name="⏰ Prime Time",
            value=f"`{prime.get('start_hour', 14)}:00 - {prime.get('end_hour', 22)}:00 UTC`",
            inline=True
        )
        
        # Salaries
        salaries = config.get("salaries", {})
        embed.add_field(
            name="💰 Salaries (/10min)",
            value=f"⚔️ `${salaries.get('soldier_per_10min', 10)}`\n"
                  f"🎖️ `${salaries.get('sergeant_per_10min', 20)}`\n"
                  f"👮 `${salaries.get('officer_per_10min', 20)}`",
            inline=True
        )
        
        # Totals
        total_users = await db.get_total_users()
        embed.add_field(
            name="👥 Total Users",
            value=f"```\n{total_users:,}\n```",
            inline=True
        )
        
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        
        embed.add_field(
            name="🏛️ Taxes Collected",
            value=f"`{format_balance(economy.total_taxes_collected)}`",
            inline=True
        )
        
        embed.add_field(
            name="💸 Rewards Paid",
            value=f"`{format_balance(economy.total_rewards_paid)}`",
            inline=True
        )
        
        total_balance = await db.get_total_balance()
        embed.add_field(
            name="💰 User Balances",
            value=f"`{format_balance(total_balance)}`",
            inline=True
        )
        
        embed.set_footer(text="💎 Click buttons to modify • Developed by NaveL for JJI in 2025")
        
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
        """Add to user balance - deducts from server budget"""
        # Check server budget if adding money
        economy = await db.get_server_economy()
        budget_before = economy.total_budget
        
        if amount > 0:
            if economy.total_budget < amount:
                await interaction.response.send_message(
                    f"❌ Server budget too low! Budget: **{format_balance(economy.total_budget)}**, Need: **{format_balance(amount)}**",
                    ephemeral=True
                )
                return
        
        success, before, after = await db.update_user_balance(
            user.id,
            amount,
            TransactionType.ADMIN_ADD,
            description=f"Added by {interaction.user.display_name}"
        )
        
        if success:
            # Deduct from server budget if adding, add to budget if removing
            if amount > 0:
                await db.add_rewards_paid(amount)  # This deducts from budget and tracks stats
            elif amount < 0:
                await db.update_server_budget(-amount, add=True)  # Return money to budget
            
            # Log admin action
            economy_after = await db.get_server_economy()
            await economy_logger.log(
                action=EconomyAction.ADMIN_ADD,
                amount=amount,
                user_id=user.id,
                user_name=user.display_name,
                before_balance=before,
                after_balance=after,
                before_budget=budget_before,
                after_budget=economy_after.total_budget,
                description=f"Admin balance adjustment by {interaction.user.display_name}",
                details={"Admin": f"<@{interaction.user.id}>"},
                source="Admin AddMoney"
            )
            
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
        economy = await db.get_server_economy()
        budget_before = economy.total_budget
        
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
            
            # Log admin action
            economy_after = await db.get_server_economy()
            await economy_logger.log(
                action=EconomyAction.ADMIN_REMOVE,
                amount=amount,
                user_id=user.id,
                user_name=user.display_name,
                before_balance=before,
                after_balance=after,
                before_budget=budget_before,
                after_budget=economy_after.total_budget,
                description=f"Fine issued by {interaction.user.display_name}",
                details={"Admin": f"<@{interaction.user.id}>", "Reason": "Fine"},
                source="Admin Fine"
            )
            
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
        economy = await db.get_server_economy()
        budget_before = economy.total_budget
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
            
            # Log admin action
            economy_after = await db.get_server_economy()
            await economy_logger.log(
                action=EconomyAction.ADMIN_REMOVE,
                amount=amount,
                user_id=user.id,
                user_name=user.display_name,
                before_balance=before,
                after_balance=after,
                before_budget=budget_before,
                after_budget=economy_after.total_budget,
                description=f"Full confiscation by {interaction.user.display_name}",
                details={"Admin": f"<@{interaction.user.id}>", "Reason": "Confiscation"},
                source="Admin Confiscate"
            )
            
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
    
    @app_commands.command(name="set_user_rank", description="Set a user's rank (soldier/sergeant/officer) (Admin)")
    @app_commands.describe(
        user="The user to modify",
        rank="The rank to assign"
    )
    @admin_only()
    async def set_user_rank(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        rank: Literal["soldier", "sergeant", "officer", "none"]
    ):
        """Set user's rank in the system"""
        is_soldier = rank in ["soldier", "sergeant", "officer"]
        is_sergeant = rank in ["sergeant", "officer"]
        is_officer = rank == "officer"
        
        await db.update_user_roles(
            user.id,
            is_soldier=is_soldier,
            is_sergeant=is_sergeant,
            is_officer=is_officer
        )
        
        rank_emoji = {"soldier": "⚔️", "sergeant": "🎖️", "officer": "👮", "none": "❌"}
        
        await interaction.response.send_message(
            f"✅ Set **{user.display_name}** rank to {rank_emoji.get(rank, '')} **{rank.upper()}**\n"
            f"• Soldier: {'✅' if is_soldier else '❌'}\n"
            f"• Sergeant: {'✅' if is_sergeant else '❌'}\n"
            f"• Officer: {'✅' if is_officer else '❌'}",
            ephemeral=True
        )
    
    @app_commands.command(name="about", description="About this bot")
    async def about(self, interaction: discord.Interaction):
        """Display bot information"""
        embed = discord.Embed(color=0x5865F2)
        
        embed.description = """
## 🤖 JJI SQUAD BOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
*Discord bot for gaming community*
"""
        
        embed.add_field(
            name="📋 Features",
            value="```\n"
                  "• Economy & Salaries\n"
                  "• Role Marketplace\n"
                  "• Casino Games\n"
                  "• Officer System\n"
                  "• SB Time Tracking\n"
                  "```",
            inline=True
        )
        
        embed.add_field(
            name="🎮 Game Commands",
            value="`/blackjack` Solo or PvP\n"
                  "`/blackjack_pvp` PvP Mode\n"
                  "`/coinflip` Flip coins\n"
                  "`/case` Daily reward",
            inline=True
        )
        
        embed.add_field(
            name="💼 Economy Commands",
            value="`/balance` Check wallet\n"
                  "`/pay` Send money\n"
                  "`/shop` Browse roles\n"
                  "`/myroles` Inventory",
            inline=True
        )
        
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        
        embed.add_field(
            name="👮 Officer Commands",
            value="`/accept` Accept recruit\n"
                  "`/officer_stats` View stats\n"
                  "`/recruits` Track recruits",
            inline=True
        )
        
        embed.add_field(
            name="📊 Profile Commands",
            value="`/profile` View profile\n"
                  "`/leaderboard` Rankings\n"
                  "`/stats` Server economy",
            inline=True
        )
        
        embed.set_footer(text="💎 Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="botstats", description="View bot statistics")
    async def botstats(self, interaction: discord.Interaction):
        """Display bot statistics"""
        import datetime
        
        uptime = datetime.datetime.utcnow() - self.bot.start_time if hasattr(self.bot, 'start_time') else None
        
        economy = await db.get_server_economy()
        total_users = await db.get_total_users()
        total_balance = await db.get_total_balance()
        
        embed = discord.Embed(color=0x00FF00)
        
        embed.description = """
## 📊 BOT STATISTICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Bot info
        latency = round(self.bot.latency * 1000)
        latency_color = "+" if latency < 100 else ""
        
        embed.add_field(
            name="🤖 Bot Status",
            value=f"```diff\n{latency_color} {latency}ms latency\n```\n"
                  f"**Guilds:** `{len(self.bot.guilds)}`\n"
                  f"**Uptime:** `{str(uptime).split('.')[0] if uptime else 'N/A'}`",
            inline=True
        )
        
        # Economy
        embed.add_field(
            name="💰 Economy",
            value=f"**Budget:** `{format_balance(economy.total_budget)}`\n"
                  f"**Tax Rate:** `{economy.tax_rate}%`\n"
                  f"**User Balance:** `{format_balance(total_balance)}`",
            inline=True
        )
        
        # Users
        embed.add_field(
            name="👥 Community",
            value=f"**Users:** `{total_users:,}`\n"
                  f"**Taxes:** `{format_balance(economy.total_taxes_collected)}`\n"
                  f"**Rewards:** `{format_balance(economy.total_rewards_paid)}`",
            inline=True
        )
        
        # Total money in circulation
        total_money = economy.total_budget + total_balance
        embed.add_field(
            name="💎 Total Economy",
            value=f"```\n{format_balance(total_money)}\n```",
            inline=False
        )
        
        embed.set_footer(text="💎 Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    # Register persistent view so buttons work after bot restart
    bot.add_view(EconomyPanelView())
    await bot.add_cog(AdminCog(bot))

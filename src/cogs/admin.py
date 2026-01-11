"""
Admin Cog - Economy panel, channel configs, moderation
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal
from datetime import datetime, timezone, timedelta

from src.services.database import db
from src.services.economy_logger import economy_logger, EconomyAction
from src.models.database import TransactionType, LogType
from src.utils.helpers import format_balance, load_config, save_config, is_prime_time
from src.utils.security import admin_only
from src.utils.metrics import metrics


# ==================== ABOUT VIEW ====================

class AboutView(discord.ui.View):
    """Interactive About panel with category buttons"""
    
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=300)
        self.bot = bot
        self.current_page = "main"
    
    def get_main_embed(self) -> discord.Embed:
        """Main overview embed"""
        uptime = datetime.now(timezone.utc) - self.bot.start_time if hasattr(self.bot, 'start_time') else None
        uptime_str = str(uptime).split('.')[0] if uptime else "N/A"
        latency = round(self.bot.latency * 1000)
        latency_status = "🟢" if latency < 100 else "🟡" if latency < 200 else "🔴"
        
        embed = discord.Embed(color=0x5865F2)
        embed.set_author(
            name="jji SQUAD BOT",
            icon_url=self.bot.user.display_avatar.url if self.bot.user else None
        )
        
        embed.description = (
            "## ⚡ Discord Economy System\n"
            "*Bot for jji gaming community*\n\n"
            "───────────────────────────\n"
            "💎 **Closed-loop economy** — all money stays in the system\n"
            "📊 **Real-time tracking** — every transaction logged\n"
            "🔒 **Secure** — atomic operations & rate limiting\n"
            "───────────────────────────"
        )
        
        embed.add_field(
            name="📡 System Status",
            value=f"{latency_status} **Ping:** `{latency}ms`\n"
                  f"⏱️ **Uptime:** `{uptime_str}`\n"
                  f"🌐 **Servers:** `{len(self.bot.guilds)}`",
            inline=True
        )
        
        embed.add_field(
            name="🎯 Features",
            value="💰 Economy & Salaries\n"
                  "🎮 Casino Games\n"
                  "🛒 Role Marketplace\n"
                  "👮 Officer System\n"
                  "📈 SB Time Tracking",
            inline=True
        )
        
        embed.set_footer(
            text="💎 Developed by NaveL for JJI • v1.0 • Use buttons to explore"
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)
        
        return embed
    
    def get_economy_embed(self) -> discord.Embed:
        """Economy commands embed"""
        embed = discord.Embed(
            title="💰 Economy System",
            description=(
                "*All money circulates within the server budget*\n"
                "*Taxes return to budget • No inflation • Balanced system*\n"
                "─────────────────────────────────"
            ),
            color=0x57F287
        )
        
        embed.add_field(
            name="📋 Basic Commands",
            value=">>> `/balance` — Check your wallet\n"
                  "`/pay` — Transfer money to user\n"
                  "`/case` — Daily case (24h cooldown)\n"
                  "`/daily` — Alias for case",
            inline=True
        )
        embed.add_field(
            name="🛒 Shop Commands",
            value=">>> `/shop` — Browse role marketplace\n"
                  "`/buy_role` — Purchase a role\n"
                  "`/sell_role` — Sell owned role\n"
                  "`/myroles` — View your roles",
            inline=True
        )
        embed.add_field(
            name="📊 Statistics",
            value=">>> `/stats` — Server economy overview\n"
                  "`/leaderboard` — Top players ranking\n"
                  "`/profile` — View any user's profile",
            inline=False
        )
        embed.set_footer(text="💡 All rewards are taxed • Tax returns to server budget")
        return embed
    
    def get_games_embed(self) -> discord.Embed:
        """Games commands embed"""
        embed = discord.Embed(
            title="🎮 Casino Games",
            description=(
                "*Fair games • House edge goes to server budget*\n"
                "*All winnings taxed • 100% closed-loop*\n"
                "─────────────────────────────────"
            ),
            color=0xFEE75C
        )
        
        embed.add_field(
            name="🃏 Blackjack",
            value=">>> **Command:** `/blackjack [bet]`\n"
                  "Classic 21 card game\n"
                  "Hit, Stand, Double, Split\n"
                  "Blackjack pays 1.5x",
            inline=True
        )
        embed.add_field(
            name="🪙 Coinflip",
            value=">>> **Command:** `/coinflip [bet] [side]`\n"
                  "Pick heads or tails\n"
                  "50/50 chance\n"
                  "Instant results",
            inline=True
        )
        embed.add_field(
            name="⚔️ PvP Blackjack",
            value=">>> **Command:** `/blackjack_pvp [@user] [bet]`\n"
                  "Challenge other players • Winner takes all (minus tax)",
            inline=False
        )
        embed.set_footer(text="⚠️ Gamble responsibly • Bets limited by balance & config")
        return embed
    
    def get_officer_embed(self) -> discord.Embed:
        """Officer system embed"""
        config = load_config()
        officer_config = config.get("officer_system", {})
        salaries = config.get("salaries", {})
        
        accept_reward = officer_config.get("accept_reward", 50)
        pb_bonus = officer_config.get("pb_10h_bonus", 50)
        master_bonus = salaries.get("sergeant_master_bonus", 50)
        
        embed = discord.Embed(
            title="👮 Officer System",
            description=(
                "*Officers earn rewards for recruiting new members*\n"
                "*Track your recruits • Earn bonuses • Build your team*\n"
                "─────────────────────────────────"
            ),
            color=0x5865F2
        )
        
        embed.add_field(
            name="📝 Recruitment",
            value=">>> `/accept` — Accept a new recruit\n"
                  "`/recruits` — View your recruit list\n"
                  "`/officer_stats` — Your statistics",
            inline=True
        )
        embed.add_field(
            name="📈 SB Tracking",
            value=">>> `/sb_start` — Start SB session\n"
                  "`/sb_stop` — End SB session\n"
                  "`/sb_stats` — View SB statistics",
            inline=True
        )
        embed.add_field(
            name="💰 Rewards",
            value=f"```diff\n"
                  f"+ Per recruit accepted: ${accept_reward}\n"
                  f"+ 10h SB bonus: ${pb_bonus}\n"
                  f"+ Sergeant master bonus: ${master_bonus}/day\n"
                  f"```",
            inline=False
        )
        embed.set_footer(text="👮 Officers keep the community growing!")
        return embed
    
    def get_admin_embed(self) -> discord.Embed:
        """Admin commands embed"""
        embed = discord.Embed(
            title="⚙️ Administration",
            description=(
                "*Commands require administrator permissions*\n"
                "*Use responsibly • All actions are logged*\n"
                "─────────────────────────────────"
            ),
            color=0xED4245
        )
        
        embed.add_field(
            name="💰 Economy Control",
            value=">>> `/economy_panel` — Full dashboard\n"
                  "`/addbalance` — Add money to user\n"
                  "`/fine` — Remove money (penalty)\n"
                  "`/confiscate` — Take money (no budget)",
            inline=True
        )
        embed.add_field(
            name="⚙️ Configuration",
            value=">>> `/set_channel` — Configure channels\n"
                  "`/sync_commands` — Resync commands\n"
                  "`/botstats` — Bot statistics",
            inline=True
        )
        embed.add_field(
            name="🛡️ Security Features",
            value="• All admin actions logged\n"
                  "• Rate limiting active\n"
                  "• Atomic transactions\n"
                  "• Budget integrity checks",
            inline=False
        )
        embed.set_footer(text="🔒 Admin actions are logged to security channel")
        return embed
    
    @discord.ui.button(label="Overview", style=discord.ButtonStyle.primary, emoji="🏠", row=0)
    async def main_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = "main"
        await interaction.response.edit_message(embed=self.get_main_embed(), view=self)
    
    @discord.ui.button(label="Economy", style=discord.ButtonStyle.success, emoji="💰", row=0)
    async def economy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = "economy"
        await interaction.response.edit_message(embed=self.get_economy_embed(), view=self)
    
    @discord.ui.button(label="Games", style=discord.ButtonStyle.secondary, emoji="🎮", row=0)
    async def games_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = "games"
        await interaction.response.edit_message(embed=self.get_games_embed(), view=self)
    
    @discord.ui.button(label="Officers", style=discord.ButtonStyle.primary, emoji="👮", row=1)
    async def officer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = "officer"
        await interaction.response.edit_message(embed=self.get_officer_embed(), view=self)
    
    @discord.ui.button(label="Admin", style=discord.ButtonStyle.danger, emoji="⚙️", row=1)
    async def admin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = "admin"
        await interaction.response.edit_message(embed=self.get_admin_embed(), view=self)
    
    async def on_timeout(self):
        """Disable buttons on timeout"""
        for item in self.children:
            item.disabled = True


# ==================== MODALS ====================

class TaxRateModal(discord.ui.Modal, title="Set Tax Rate"):
    rate = discord.ui.TextInput(
        label="Tax Rate (%)",
        placeholder="Enter tax rate (0-100)",
        default="10",
        max_length=5
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            rate = float(self.rate.value)
            if rate < 0 or rate > 100:
                await interaction.response.send_message(
                    "❌ Tax rate must be between 0% and 100%",
                    ephemeral=True
                )
                return
            
            # Get old rate
            economy = await db.get_server_economy()
            old_rate = economy.tax_rate
            
            await db.set_tax_rate(rate)
            
            # Update config file
            config = load_config()
            config["economy"]["tax_rate"] = rate
            save_config(config)
            
            await interaction.response.send_message(
                f"✅ Tax rate updated!\n\n"
                f"**Old Rate:** {old_rate}%\n"
                f"**New Rate:** {rate}%",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )
        except Exception as e:
            import logging
            logging.error(f"TaxRateModal error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import logging
        logging.error(f"TaxRateModal on_error: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except Exception:
            pass


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
            
            await interaction.response.send_message(
                f"✅ Soldier value updated!\n\n"
                f"**Old Value:** {format_balance(old_value)}\n"
                f"**New Value:** {format_balance(new_value)}\n"
                f"**Current Soldiers:** {soldier_count}\n\n"
                f"📝 *This value is added to budget when soldiers are accepted via /accept*\n"
                f"*and deducted when they lose the soldier role or leave the server.*",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )
        except Exception as e:
            import logging
            logging.error(f"SoldierValueModal error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import logging
        logging.error(f"SoldierValueModal on_error: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except Exception:
            pass


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
        except Exception as e:
            import logging
            logging.error(f"PrimeTimeModal error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import logging
        logging.error(f"PrimeTimeModal on_error: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except Exception:
            pass


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
        except Exception as e:
            import logging
            logging.error(f"SalaryModal error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import logging
        logging.error(f"SalaryModal on_error: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except Exception:
            pass


class OfficerRewardsModal(discord.ui.Modal, title="Set Officer Rewards"):
    accept_reward = discord.ui.TextInput(
        label="Accept Reward ($)",
        placeholder="50",
        default="50",
        max_length=5
    )
    pb_10h_bonus = discord.ui.TextInput(
        label="10h SB Bonus ($)",
        placeholder="50",
        default="50",
        max_length=5
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_accept_reward = float(self.accept_reward.value)
            new_pb_bonus = float(self.pb_10h_bonus.value)
            
            if new_accept_reward < 0 or new_pb_bonus < 0:
                await interaction.response.send_message(
                    "❌ Rewards must be non-negative!",
                    ephemeral=True
                )
                return
            
            config = load_config()
            old_accept = config.get("officer_system", {}).get("accept_reward", 20)
            old_pb = config.get("officer_system", {}).get("pb_10h_bonus", 50)
            
            # Update config
            if "officer_system" not in config:
                config["officer_system"] = {}
            config["officer_system"]["accept_reward"] = new_accept_reward
            config["officer_system"]["pb_10h_bonus"] = new_pb_bonus
            save_config(config)
            
            await interaction.response.send_message(
                f"✅ Officer rewards updated:\n"
                f"• Accept Reward: ${old_accept} → **${new_accept_reward}**\n"
                f"• 10h SB Bonus: ${old_pb} → **${new_pb_bonus}**",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid numbers!",
                ephemeral=True
            )
        except Exception as e:
            import logging
            logging.error(f"OfficerRewardsModal error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import logging
        logging.error(f"OfficerRewardsModal on_error: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except Exception:
            pass


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
            
            # Get old budget before changing
            economy_before = await db.get_server_economy()
            old_budget = economy_before.total_budget
            
            # Set budget directly
            async with db.session() as session:
                from sqlalchemy import select, update
                from src.models.database import ServerEconomy
                
                await session.execute(
                    update(ServerEconomy).values(total_budget=amount)
                )
                await session.commit()
            
            # Log the change
            await economy_logger.log(
                action=EconomyAction.ADMIN_ADD,
                amount=amount - old_budget,
                user_id=interaction.user.id,
                user_name=interaction.user.display_name,
                before_budget=old_budget,
                after_budget=amount,
                description=f"Admin set server budget",
                details={
                    "Admin": f"<@{interaction.user.id}>",
                    "Old Budget": f"{format_balance(old_budget)}",
                    "New Budget": f"{format_balance(amount)}"
                },
                source="Admin SetBudget"
            )
            
            change = amount - old_budget
            change_str = f"+{format_balance(change)}" if change >= 0 else format_balance(change)
            
            await interaction.response.send_message(
                f"✅ Server budget updated!\n\n"
                f"**Old:** {format_balance(old_budget)}\n"
                f"**New:** {format_balance(amount)}\n"
                f"**Change:** {change_str}",
                ephemeral=True
            )
            
            metrics.update_server_budget(amount)
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number!",
                ephemeral=True
            )
        except Exception as e:
            import logging
            logging.error(f"BudgetModal error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import logging
        logging.error(f"BudgetModal on_error: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except Exception:
            pass


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
        except Exception as e:
            import logging
            logging.error(f"AddBudgetModal error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import logging
        logging.error(f"AddBudgetModal on_error: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except Exception:
            pass


# ==================== ECONOMY PANEL VIEW ====================

class EconomyPanelView(discord.ui.View):
    """Interactive economy control panel - persistent view"""
    
    def __init__(self):
        super().__init__(timeout=None)  # Never timeout
    
    @discord.ui.button(label="Tax Rate", style=discord.ButtonStyle.primary, row=0, custom_id="economy_panel:tax_rate")
    async def tax_rate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(TaxRateModal())
    
    @discord.ui.button(label="Soldier Value", style=discord.ButtonStyle.primary, row=0, custom_id="economy_panel:soldier_value")
    async def soldier_value(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(SoldierValueModal())
    
    @discord.ui.button(label="Prime Time", style=discord.ButtonStyle.primary, row=0, custom_id="economy_panel:prime_time")
    async def prime_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(PrimeTimeModal())
    
    @discord.ui.button(label="Salaries", style=discord.ButtonStyle.primary, row=0, custom_id="economy_panel:salaries")
    async def salaries(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(SalaryModal())
    
    @discord.ui.button(label="Rewards", style=discord.ButtonStyle.success, row=1, custom_id="economy_panel:rewards")
    async def officer_rewards(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(OfficerRewardsModal())
    
    @discord.ui.button(label="Set Budget", style=discord.ButtonStyle.danger, row=1, custom_id="economy_panel:set_budget")
    async def set_budget(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(BudgetModal())
    
    @discord.ui.button(label="Add Budget", style=discord.ButtonStyle.success, row=2, custom_id="economy_panel:add_budget")
    async def add_budget(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(AddBudgetModal())
    
    @discord.ui.button(label="📜 History", style=discord.ButtonStyle.secondary, row=2, custom_id="economy_panel:history")
    async def history(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        embed = await self.get_history_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=3, custom_id="economy_panel:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.get_stats_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="🎮 Games", style=discord.ButtonStyle.secondary, row=3, custom_id="economy_panel:games")
    async def games_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only!", ephemeral=True)
            return
        embed = await self.get_games_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def get_history_embed(self) -> discord.Embed:
        """Get recent admin actions history"""
        stats = await db.get_economy_stats()
        admin_actions = stats["admin_actions"]
        
        embed = discord.Embed(
            title="📜 Recent Admin Actions",
            color=0x5865F2
        )
        
        if not admin_actions:
            embed.description = "*No admin actions recorded*"
        else:
            lines = []
            for tx in admin_actions[:10]:
                timestamp = f"<t:{int(tx.timestamp.timestamp())}:R>"
                action_type = tx.transaction_type.value.replace("_", " ").title()
                amount_str = f"+{format_balance(tx.amount)}" if tx.amount > 0 else format_balance(tx.amount)
                user_mention = f"<@{tx.user.discord_id}>" if tx.user else "Unknown"
                lines.append(f"{timestamp} | **{action_type}** | {amount_str} | {user_mention}")
            
            embed.description = "\n".join(lines)
        
        embed.set_footer(text="Last 10 admin actions")
        return embed
    
    async def get_games_embed(self) -> discord.Embed:
        """Get games statistics"""
        stats = await db.get_economy_stats()
        economy = await db.get_server_economy()
        
        embed = discord.Embed(
            title="🎮 Games Statistics (Today)",
            color=0xFEE75C
        )
        
        # Calculate house profit
        house_profit = stats["game_losses_amount"] - stats["game_wins_amount"]
        profit_sign = "+" if house_profit >= 0 else ""
        profit_color = "diff\n+" if house_profit >= 0 else "diff\n-"
        
        embed.add_field(
            name="🎰 Games Played",
            value=f"**Wins:** {stats['game_wins_today']}\n**Losses:** {stats['game_losses_today']}",
            inline=True
        )
        
        embed.add_field(
            name="💵 Amounts",
            value=f"**Won:** {format_balance(stats['game_wins_amount'])}\n**Lost:** {format_balance(stats['game_losses_amount'])}",
            inline=True
        )
        
        embed.add_field(
            name="🏦 House Profit",
            value=f"```{profit_color}{format_balance(abs(house_profit))}\n```",
            inline=True
        )
        
        # Win rate
        total_games = stats['game_wins_today'] + stats['game_losses_today']
        win_rate = (stats['game_wins_today'] / total_games * 100) if total_games > 0 else 0
        
        embed.add_field(
            name="📊 Player Win Rate",
            value=f"`{win_rate:.1f}%` ({stats['game_wins_today']}/{total_games})",
            inline=False
        )
        
        embed.set_footer(text="Statistics reset daily at 00:00 UTC")
        return embed
    
    async def get_stats_embed(self) -> discord.Embed:
        """Generate comprehensive stats embed"""
        economy = await db.get_server_economy()
        config = load_config()
        stats = await db.get_economy_stats()
        total_balance = await db.get_total_balance()
        
        # Get 24h changes
        budget_24h_change = await db.get_24h_budget_change()
        balance_24h_change = await db.get_24h_balance_change()
        
        # Prime time calculation
        prime = config.get("prime_time", {})
        start_hour = prime.get("start_hour", 14)
        end_hour = prime.get("end_hour", 22)
        is_prime = is_prime_time(start_hour, end_hour)
        
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        
        if is_prime:
            hours_left = end_hour - current_hour if end_hour > current_hour else 24 - current_hour + end_hour
            prime_indicator = f"🟢 ACTIVE"
            prime_time_info = f"ends in ~{hours_left}h"
        else:
            if current_hour < start_hour:
                hours_until = start_hour - current_hour
            else:
                hours_until = 24 - current_hour + start_hour
            prime_indicator = f"🔴 OFF"
            prime_time_info = f"starts in ~{hours_until}h"
        
        # Salary rates
        salaries = config.get("salaries", {})
        soldier_rate = salaries.get("soldier_per_10min", 10) / 10
        sergeant_rate = salaries.get("sergeant_per_10min", 20) / 10
        officer_rate = salaries.get("officer_per_10min", 20) / 10
        
        if is_prime:
            soldier_rate *= 2
            sergeant_rate *= 2
            officer_rate *= 2
        
        # Budget forecast
        current_burn = (
            stats['soldiers_in_voice'] * soldier_rate +
            stats['sergeants_in_voice'] * sergeant_rate +
            stats['officers_in_voice'] * officer_rate
        )
        burn_per_hour = current_burn * 60
        
        if current_burn > 0:
            hours_runway = economy.total_budget / current_burn / 60
            if hours_runway > 48:
                runway = f"{hours_runway/24:.0f}d"
            else:
                runway = f"{hours_runway:.0f}h"
        else:
            runway = "∞"
        
        total_money = economy.total_budget + total_balance
        
        # Build embed
        embed = discord.Embed(color=0x2b2d31, timestamp=datetime.now(timezone.utc))
        
        embed.title = "ECONOMY CONTROL PANEL"
        
        # Header with prime time
        embed.description = f"```\nPrime Time: {prime_indicator}  ({start_hour}:00-{end_hour}:00 UTC) • {prime_time_info}\n```"
        
        # Format 24h budget change indicator
        if budget_24h_change >= 0:
            budget_24h_str = f"+{format_balance(budget_24h_change)}"
        else:
            budget_24h_str = f"-{format_balance(abs(budget_24h_change))}"
        
        # Row 1: Core settings
        embed.add_field(
            name="BUDGET",
            value=f"```yml\n{format_balance(economy.total_budget)}\n24h: {budget_24h_str}\n```",
            inline=True
        )
        embed.add_field(
            name="TAX RATE",
            value=f"```ini\n[{economy.tax_rate}%]\n```",
            inline=True
        )
        embed.add_field(
            name="SOLDIER VALUE",
            value=f"```ini\n[{format_balance(economy.soldier_value)}]\n```",
            inline=True
        )
        
        # Row 2: Activity
        voice_text = (
            f"```yml\n"
            f"Total:     {stats['active_sessions']}\n"
            f"Soldiers:  {stats['soldiers_in_voice']}\n"
            f"Sergeants: {stats['sergeants_in_voice']}\n"
            f"Officers:  {stats['officers_in_voice']}\n"
            f"```"
        )
        embed.add_field(name="IN VOICE", value=voice_text, inline=True)
        
        rates_text = (
            f"```yml\n"
            f"Soldier:  ${soldier_rate:.1f}/min\n"
            f"Sergeant: ${sergeant_rate:.1f}/min\n"
            f"Officer:  ${officer_rate:.1f}/min\n"
            f"{'[2x PRIME]' if is_prime else '[base]':>14}\n"
            f"```"
        )
        embed.add_field(name="RATES", value=rates_text, inline=True)
        
        forecast_text = (
            f"```yml\n"
            f"Burn:    {format_balance(burn_per_hour)}/h\n"
            f"Runway:  ~{runway}\n"
            f" \n \n"
            f"```"
        )
        embed.add_field(name="FORECAST", value=forecast_text, inline=True)
        
        # Row 3: Totals
        users_text = (
            f"```yml\n"
            f"Soldiers:  {stats['total_soldiers']}\n"
            f"Sergeants: {stats['total_sergeants']}\n"
            f"Officers:  {stats['total_officers']}\n"
            f"```"
        )
        embed.add_field(name="USERS", value=users_text, inline=True)
        
        stats_text = (
            f"```yml\n"
            f"Taxes:   {format_balance(economy.total_taxes_collected)}\n"
            f"Rewards: {format_balance(economy.total_rewards_paid)}\n"
            f" \n"
            f"```"
        )
        embed.add_field(name="ALL-TIME", value=stats_text, inline=True)
        
        # Format 24h balance change indicator
        if balance_24h_change >= 0:
            balance_24h_str = f"+{format_balance(balance_24h_change)}"
        else:
            balance_24h_str = f"-{format_balance(abs(balance_24h_change))}"
        
        balances_text = (
            f"```yml\n"
            f"Users:  {format_balance(total_balance)}\n"
            f"Budget: {format_balance(economy.total_budget)}\n"
            f"24h:    {balance_24h_str}\n"
            f"```"
        )
        embed.add_field(name="BALANCES", value=balances_text, inline=True)
        
        # Footer: Total system money
        embed.add_field(
            name="",
            value=f"**TOTAL SYSTEM:** `{format_balance(total_money)}` ─ Budget + User Balances",
            inline=False
        )
        
        embed.set_footer(text="Use buttons below to configure")
        
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
        """Add to user balance - deducts from server budget (atomic)"""
        result = await db.admin_adjust_balance_atomic(
            user.id,
            amount,
            TransactionType.ADMIN_ADD,
            description=f"Added by {interaction.user.display_name}"
        )
        
        if not result["success"]:
            error = result.get("error", "Unknown error")
            if "budget" in error.lower():
                economy = await db.get_server_economy()
                await interaction.response.send_message(
                    f"❌ Server budget too low! Budget: **{format_balance(economy.total_budget)}**, Need: **{format_balance(amount)}**",
                    ephemeral=True
                )
            elif "user balance" in error.lower():
                await interaction.response.send_message(
                    f"❌ User balance insufficient! Cannot remove more than they have.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ Failed to update balance: {error}",
                    ephemeral=True
                )
            return
        
        # Log admin action
        await economy_logger.log(
            action=EconomyAction.ADMIN_ADD,
            amount=amount,
            user_id=user.id,
            user_name=user.display_name,
            before_balance=result["before_balance"],
            after_balance=result["after_balance"],
            before_budget=result["before_budget"],
            after_budget=result["after_budget"],
            description=f"Admin balance adjustment by {interaction.user.display_name}",
            details={"Admin": f"<@{interaction.user.id}>"},
            source="Admin AddMoney"
        )
        
        await interaction.response.send_message(
            f"✅ Added **{format_balance(amount)}** to **{user.display_name}**\n"
            f"Before: {format_balance(result['before_balance'])} → After: {format_balance(result['after_balance'])}",
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
        """Fine a user (atomic)"""
        if amount <= 0:
            await interaction.response.send_message(
                "❌ Fine amount must be positive!",
                ephemeral=True
            )
            return
        
        result = await db.admin_adjust_balance_atomic(
            user.id,
            -amount,  # Negative because we're taking money
            TransactionType.FINE,
            description=f"Fine by {interaction.user.display_name}"
        )
        
        if not result["success"]:
            error = result.get("error", "Unknown error")
            if "user balance" in error.lower():
                db_user = await db.get_or_create_user(user.id)
                await interaction.response.send_message(
                    f"❌ User only has {format_balance(db_user.balance)}!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ Failed to apply fine: {error}",
                    ephemeral=True
                )
            return
        
        # Log admin action
        await economy_logger.log(
            action=EconomyAction.ADMIN_REMOVE,
            amount=amount,
            user_id=user.id,
            user_name=user.display_name,
            before_balance=result["before_balance"],
            after_balance=result["after_balance"],
            before_budget=result["before_budget"],
            after_budget=result["after_budget"],
            description=f"Fine issued by {interaction.user.display_name}",
            details={"Admin": f"<@{interaction.user.id}>", "Reason": "Fine"},
            source="Admin Fine"
        )
        
        await interaction.response.send_message(
            f"✅ Fined **{user.display_name}** for **{format_balance(amount)}**\n"
            f"Their balance: {format_balance(result['before_balance'])} → {format_balance(result['after_balance'])}\n"
            f"Added to server budget.",
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
        """Confiscate entire balance (atomic)"""
        db_user = await db.get_or_create_user(user.id)
        amount = db_user.balance
        
        if amount <= 0:
            await interaction.response.send_message(
                f"❌ User has no balance to confiscate!",
                ephemeral=True
            )
            return
        
        result = await db.admin_adjust_balance_atomic(
            user.id,
            -amount,  # Take entire balance
            TransactionType.CONFISCATE,
            description=f"Confiscated by {interaction.user.display_name}"
        )
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Failed to confiscate: {result.get('error', 'Unknown error')}",
                ephemeral=True
            )
            return
        
        # Log admin action
        await economy_logger.log(
            action=EconomyAction.ADMIN_REMOVE,
            amount=amount,
            user_id=user.id,
            user_name=user.display_name,
            before_balance=result["before_balance"],
            after_balance=result["after_balance"],
            before_budget=result["before_budget"],
            after_budget=result["after_budget"],
            description=f"Full confiscation by {interaction.user.display_name}",
            details={"Admin": f"<@{interaction.user.id}>", "Reason": "Confiscation"},
            source="Admin Confiscate"
        )
        
        await interaction.response.send_message(
            f"✅ Confiscated **{format_balance(amount)}** from **{user.display_name}**\n"
            f"Added to server budget.",
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
        """Display interactive bot information panel"""
        view = AboutView(self.bot)
        embed = view.get_main_embed()
        await interaction.response.send_message(embed=embed, view=view)
    
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
    
    @app_commands.command(name="sync_commands", description="Sync bot commands (Admin)")
    @admin_only()
    async def sync_commands(self, interaction: discord.Interaction):
        """Sync commands to current guild"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Copy global commands to this guild and sync
            self.bot.tree.copy_global_to(guild=interaction.guild)
            synced = await self.bot.tree.sync(guild=interaction.guild)
            
            await interaction.followup.send(
                f"✅ Commands synced!\n"
                f"Registered **{len(synced)}** commands.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error: {str(e)}",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    # Register persistent view so buttons work after bot restart
    bot.add_view(EconomyPanelView())
    await bot.add_cog(AdminCog(bot))

"""
Profile Cog - User profiles and leaderboards
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal

from src.services.database import db
from src.utils.helpers import format_balance, format_pb_time, get_rank_emoji
from src.utils.security import rate_limited


class LeaderboardView(discord.ui.View):
    """Paginated leaderboard view"""
    
    def __init__(
        self, 
        order_by: str,
        page: int = 0,
        per_page: int = 10,
        timeout: float = 180
    ):
        super().__init__(timeout=timeout)
        self.order_by = order_by
        self.page = page
        self.per_page = per_page
        self.total_pages = 1
        self.bot = None
    
    async def update_buttons(self):
        """Update button states based on current page"""
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1
        self.page_indicator.label = f"Page {self.page + 1}/{self.total_pages}"
    
    async def generate_embed(self, guild: discord.Guild) -> discord.Embed:
        """Generate leaderboard embed"""
        total_users = await db.get_total_users()
        self.total_pages = max(1, (total_users + self.per_page - 1) // self.per_page)
        
        users = await db.get_leaderboard(
            order_by=self.order_by,
            limit=self.per_page,
            offset=self.page * self.per_page
        )
        
        if self.order_by == "balance":
            title = "💰 Balance Leaderboard"
            color = discord.Color.gold()
        else:
            title = "⏱️ PB Time Leaderboard"
            color = discord.Color.blue()
        
        embed = discord.Embed(title=title, color=color)
        
        if not users:
            embed.description = "No users found."
        else:
            lines = []
            for i, user in enumerate(users):
                position = self.page * self.per_page + i + 1
                rank_emoji = get_rank_emoji(position)
                
                # Try to get member
                member = guild.get_member(user.discord_id)
                name = member.display_name if member else f"User {user.discord_id}"
                
                if self.order_by == "balance":
                    value = format_balance(user.balance)
                else:
                    value = format_pb_time(user.total_pb_time)
                
                lines.append(f"{rank_emoji} **{name}** — {value}")
            
            embed.description = "\n".join(lines)
        
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages} • Developed by NaveL for JJI in 2025")
        
        await self.update_buttons()
        return embed
    
    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="leaderboard:prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        embed = await self.generate_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.primary, disabled=True, custom_id="leaderboard:page")
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass
    
    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="leaderboard:next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        embed = await self.generate_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.success, custom_id="leaderboard:refresh")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.generate_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)


class ProfileCog(commands.Cog):
    """Profile and leaderboard commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="profile", description="View your or another user's profile")
    @app_commands.describe(user="The user to view (defaults to you)")
    @rate_limited("profile", limit=5, window=60)
    async def profile(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member = None
    ):
        """Display user profile"""
        target = user or interaction.user
        
        db_user = await db.get_or_create_user(target.id)
        
        # Get role count
        user_roles = await db.get_user_roles(target.id)
        active_roles = sum(1 for r in user_roles if r.is_active)
        
        embed = discord.Embed(
            title=f"👤 {target.display_name}'s Profile",
            color=target.color if target.color.value else discord.Color.blurple()
        )
        
        embed.set_thumbnail(url=target.display_avatar.url)
        
        # Balance
        embed.add_field(
            name="💰 Balance",
            value=format_balance(db_user.balance),
            inline=True
        )
        
        # PB Time
        embed.add_field(
            name="⏱️ PB Time",
            value=format_pb_time(db_user.total_pb_time),
            inline=True
        )
        
        # Roles
        embed.add_field(
            name="🎨 Owned Roles",
            value=f"{len(user_roles)} total, {active_roles} active",
            inline=True
        )
        
        # Role status
        status_parts = []
        if db_user.is_officer:
            status_parts.append("👮 Officer")
        if db_user.is_sergeant:
            status_parts.append("🎖️ Sergeant")
        if db_user.is_soldier:
            status_parts.append("⚔️ Soldier")
        
        if status_parts:
            embed.add_field(
                name="🏅 Status",
                value=" | ".join(status_parts),
                inline=False
            )
        
        # Join date
        embed.add_field(
            name="📅 Joined",
            value=f"<t:{int(db_user.join_date.timestamp())}:R>",
            inline=True
        )
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="leaderboard", description="View the server leaderboard")
    @app_commands.describe(type="Type of leaderboard to view")
    @rate_limited("profile", limit=3, window=60)
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        type: Literal["balance", "pb_time"] = "balance"
    ):
        """Display leaderboard"""
        view = LeaderboardView(order_by=type)
        view.bot = self.bot
        
        embed = await view.generate_embed(interaction.guild)
        
        await interaction.response.send_message(embed=embed, view=view)
    
    @app_commands.command(name="stats", description="View server economy statistics")
    @rate_limited("profile", limit=3, window=60)
    async def stats(self, interaction: discord.Interaction):
        """Display server economy stats"""
        economy = await db.get_server_economy()
        total_users = await db.get_total_users()
        total_balance = await db.get_total_balance()
        
        embed = discord.Embed(
            title="📊 Server Economy Statistics",
            color=discord.Color.blurple()
        )
        
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
            name="💰 Total User Balance",
            value=format_balance(total_balance),
            inline=True
        )
        
        embed.add_field(
            name="👥 Total Users",
            value=str(total_users),
            inline=True
        )
        
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
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))

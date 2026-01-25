"""
Profile Cog - User profiles and leaderboards
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal

from src.services.database import db
from src.utils.helpers import format_balance, format_sqb_time, get_rank_emoji, get_standard_footer
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
            title = "💰 BALANCE LEADERBOARD"
            color = 0xFEE75C  # Gold
            icon = "💵"
        else:
            title = "⏱️ SQB TIME LEADERBOARD"
            color = 0x5865F2  # Blurple
            icon = "🕐"
        
        embed = discord.Embed(color=color)
        embed.description = f"## {title}\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        if not users:
            embed.description += "\n*No users found.*"
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
                    value = format_sqb_time(user.total_pb_time)
                
                # Special formatting for top 3
                if position <= 3:
                    lines.append(f"{rank_emoji} **{name}**\n　　{icon} `{value}`")
                else:
                    lines.append(f"`#{position:02d}` {name} — {value}")
            
            embed.description += "\n".join(lines)
        
        embed.set_footer(text=f"📄 Page {self.page + 1}/{self.total_pages} • {get_standard_footer()}")
        
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
        
        # Get leaderboard positions
        balance_lb = await db.get_leaderboard("balance", limit=1000)
        sb_lb = await db.get_leaderboard("pb_time", limit=1000)
        balance_rank = next((i + 1 for i, u in enumerate(balance_lb) if u.discord_id == target.id), None)
        sb_rank = next((i + 1 for i, u in enumerate(sb_lb) if u.discord_id == target.id), None)
        
        embed = discord.Embed(color=target.color if target.color.value else 0x5865F2)
        
        # Header
        embed.set_author(
            name=f"{target.display_name}'s Profile",
            icon_url=target.display_avatar.url
        )
        
        embed.set_thumbnail(url=target.display_avatar.url)
        
        # Status badges
        status_badges = []
        if db_user.is_officer:
            status_badges.append("👮 `OFFICER`")
        if db_user.is_sergeant:
            status_badges.append("🎖️ `SERGEANT`")
        if db_user.is_soldier:
            status_badges.append("⚔️ `SOLDIER`")
        
        if status_badges:
            embed.description = " ".join(status_badges) + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        else:
            embed.description = "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        # Main stats in a nice format
        embed.add_field(
            name="💰 Balance",
            value=f"```\n{format_balance(db_user.balance)}\n```\n`Rank #{balance_rank if balance_rank else '?'}`",
            inline=True
        )
        
        embed.add_field(
            name="⏱️ SQB Time",
            value=f"```\n{format_sqb_time(db_user.total_pb_time)}\n```\n`Rank #{sb_rank if sb_rank else '?'}`",
            inline=True
        )
        
        embed.add_field(
            name="🎨 Roles",
            value=f"```\n{len(user_roles)} owned\n```\n`{active_roles} equipped`",
            inline=True
        )
        
        # Additional info
        embed.add_field(
            name="📅 Member Since",
            value=f"<t:{int(db_user.join_date.timestamp())}:D>",
            inline=True
        )
        
        embed.set_footer(text=get_standard_footer())
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="leaderboard", description="View the server leaderboard")
    @app_commands.describe(type="Type of leaderboard to view")
    @rate_limited("profile", limit=3, window=60)
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        type: Literal["balance", "sqb_time"] = "balance"
    ):
        """Display leaderboard"""
        view = LeaderboardView(order_by=type if type == "balance" else "pb_time")
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
        
        embed = discord.Embed(color=0x5865F2)
        
        embed.description = """
## 📊 SERVER ECONOMY
━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Budget section
        embed.add_field(
            name="🏦 Treasury",
            value=f"```diff\n+ {format_balance(economy.total_budget)}\n```",
            inline=True
        )
        
        embed.add_field(
            name="📈 Tax Rate",
            value=f"```\n{economy.tax_rate:.1f}%\n```",
            inline=True
        )
        
        embed.add_field(
            name="👥 Users",
            value=f"```\n{total_users:,}\n```",
            inline=True
        )
        
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        
        # Money flow
        embed.add_field(
            name="💰 Total User Balance",
            value=f"`{format_balance(total_balance)}`",
            inline=True
        )
        
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
        
        # Calculate money in circulation
        total_money = economy.total_budget + total_balance
        embed.add_field(
            name="💎 Total Economy",
            value=f"```\n{format_balance(total_money)}\n```",
            inline=False
        )
        
        embed.set_footer(text=get_standard_footer())
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))

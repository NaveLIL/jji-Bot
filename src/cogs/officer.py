"""
Officer Cog - Recruitment system, /accept, officer stats
"""

import discord
from discord import app_commands
from discord.ext import commands

from src.services.database import db
from src.services.economy_logger import economy_logger, EconomyAction
from src.models.database import TransactionType
from src.utils.helpers import format_balance, format_pb_time, load_config, calculate_tax, get_standard_footer
from src.utils.security import rate_limited, officer_only
from src.utils.metrics import metrics
from src.utils.logger import DiscordLogger


class OfficerCog(commands.Cog):
    """Officer recruitment commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
        self.discord_logger = DiscordLogger(bot)
    
    @app_commands.command(name="accept", description="Accept a new recruit (Officer only)")
    @app_commands.describe(recruit="The new member to accept")
    @rate_limited("officer", limit=10, window=60)
    @officer_only()
    async def accept(self, interaction: discord.Interaction, recruit: discord.Member):
        """Accept a new recruit"""
        if recruit.bot:
            await interaction.response.send_message(
                "❌ You can't recruit bots!",
                ephemeral=True
            )
            return
        
        if recruit.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ You can't recruit yourself!",
                ephemeral=True
            )
            return
        
        # Check if recruit already has soldier role
        config = self.config
        soldier_role_id = config.get("roles", {}).get("soldier")
        
        if soldier_role_id:
            soldier_role = interaction.guild.get_role(soldier_role_id)
            if soldier_role and soldier_role in recruit.roles:
                await interaction.response.send_message(
                    "❌ This member is already a soldier!",
                    ephemeral=True
                )
                return
        
        # Get officer reward amount
        officer_config = config.get("officer_system", {})
        accept_reward = officer_config.get("accept_reward", 20)
        
        # Check server budget
        economy = await db.get_server_economy()
        if economy.total_budget < accept_reward:
            await interaction.response.send_message(
                "❌ Server budget is too low to give recruitment reward!",
                ephemeral=True
            )
            return
        
        # Give soldier role and remove guest role
        if soldier_role_id:
            soldier_role = interaction.guild.get_role(soldier_role_id)
            if soldier_role:
                try:
                    await recruit.add_roles(soldier_role, reason=f"Accepted by {interaction.user.display_name}")
                except discord.Forbidden:
                    await interaction.response.send_message(
                        "❌ I don't have permission to assign the soldier role!",
                        ephemeral=True
                    )
                    return
        
        # Remove guest role if exists
        guest_role_id = config.get("roles", {}).get("guest")
        if guest_role_id:
            guest_role = interaction.guild.get_role(guest_role_id)
            if guest_role and guest_role in recruit.roles:
                try:
                    await recruit.remove_roles(guest_role, reason=f"Promoted to soldier by {interaction.user.display_name}")
                except discord.Forbidden:
                    pass  # Non-critical, continue anyway
        
        # Update recruit's database entry
        await db.update_user_roles(recruit.id, is_soldier=True)
        
        # Log the recruitment
        await db.log_officer_accept(interaction.user.id, recruit.id)
        
        # Calculate tax on officer reward
        economy = await db.get_server_economy()
        officer = await db.get_or_create_user(interaction.user.id)
        officer_before = officer.balance
        budget_before = economy.total_budget
        net_reward, tax = calculate_tax(accept_reward, economy.tax_rate)
        
        # Atomically pay officer reward from budget
        # Budget pays gross amount, officer receives net (after tax), tax stays in budget
        result = await db.pay_from_budget_atomic(
            discord_id=interaction.user.id,
            gross_amount=accept_reward,
            net_amount=net_reward,
            tax_amount=tax,
            transaction_type=TransactionType.OFFICER_REWARD,
            description=f"Recruitment reward for {recruit.display_name}"
        )
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Failed to pay reward: {result.get('error', 'Unknown error')}",
                ephemeral=True
            )
            return
        
        # Log recruitment reward
        officer_after = await db.get_or_create_user(interaction.user.id)
        economy_after = await db.get_server_economy()
        await economy_logger.log(
            action=EconomyAction.USER_REWARD,
            amount=net_reward,
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            before_balance=officer_before,
            after_balance=officer_after.balance,
            before_budget=budget_before,
            after_budget=economy_after.total_budget,
            description=f"Recruitment reward for accepting {recruit.display_name}",
            details={
                "Recruit": f"<@{recruit.id}>",
                "Gross Reward": f"${accept_reward:,.2f}",
                "Tax": f"${tax:,.2f}",
                "Net Reward": f"${net_reward:,.2f}"
            },
            source="Officer Accept"
        )
        
        # Update soldier count
        economy = await db.get_server_economy()
        
        # Log to officer channel
        log_channel_id = config.get("channels", {}).get("log_officer")
        if log_channel_id:
            await self.discord_logger.log_officer_action(
                log_channel_id,
                interaction.user,
                recruit,
                "accept"
            )
        
        metrics.track_transaction("officer_accept")
        
        embed = discord.Embed(color=0x00FF00)
        
        embed.description = """
## 🎖️ RECRUIT ACCEPTED
━━━━━━━━━━━━━━━━━━━━━━━━━━
*A new soldier has joined our ranks!*
"""
        embed.add_field(name="👮 Officer", value=interaction.user.mention, inline=True)
        embed.add_field(name="⚔️ Recruit", value=recruit.mention, inline=True)
        
        # Show reward with tax info
        if tax > 0:
            embed.add_field(
                name="💰 Reward", 
                value=f"```diff\n+ {format_balance(net_reward)}\n```\n`Gross: {format_balance(accept_reward)} | Tax: {format_balance(tax)}`", 
                inline=False
            )
        else:
            embed.add_field(name="💰 Reward", value=f"```diff\n+ {format_balance(net_reward)}\n```", inline=False)
        
        embed.set_footer(text=f"💎 Track their 10h SB for bonus • {get_standard_footer()}")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="officer_stats", description="View recruitment statistics")
    @app_commands.describe(officer="Officer to view stats for (leave empty for yourself)")
    @rate_limited("officer", limit=5, window=60)
    async def officer_stats(
        self,
        interaction: discord.Interaction,
        officer: discord.Member = None
    ):
        """View officer recruitment stats"""
        # Reload config to get latest role IDs
        self.config = load_config()
        config = self.config
        
        # Check permissions if viewing another user
        target = officer if officer else interaction.user

        if target.id != interaction.user.id:
            guest_admin_role_id = config.get("roles", {}).get("guest_admin")
            is_guest_admin = guest_admin_role_id and any(r.id == guest_admin_role_id for r in interaction.user.roles)

            # Check if regular admin
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_guest_admin or is_admin):
                await interaction.response.send_message(
                    "❌ Only Guest Admins can view other officers' stats!",
                    ephemeral=True
                )
                return
        else:
            # Viewing own stats - check if officer
            officer_role_id = config.get("roles", {}).get("officer")
            is_officer = officer_role_id and any(r.id == officer_role_id for r in interaction.user.roles)

            if not is_officer:
                await interaction.response.send_message(
                    "❌ This command is for officers only.",
                    ephemeral=True
                )
                return

        stats = await db.get_officer_stats(target.id)

        officer_config = config.get("officer_system", {})
        accept_reward = officer_config.get("accept_reward", 20)
        pb_bonus = officer_config.get("pb_10h_bonus", 50)
        
        embed = discord.Embed(color=0x3498DB)
        
        embed.description = f"""
## 👮 OFFICER STATISTICS
━━━━━━━━━━━━━━━━━━━━━━━━━━
**{target.display_name}**
"""
        
        embed.add_field(
            name="📊 Total Recruits",
            value=f"```\n{stats['total_recruits']}\n```",
            inline=True
        )
        
        embed.add_field(
            name="⏳ Pending Bonuses",
            value=f"```\n{stats['pending_rewards']}\n```",
            inline=True
        )
        
        embed.add_field(
            name="✅ Claimed Bonuses",
            value=f"```\n{stats['claimed_rewards']}\n```",
            inline=True
        )
        
        # Calculate lifetime earnings
        accept_earnings = stats["total_recruits"] * accept_reward
        bonus_earnings = stats["claimed_rewards"] * pb_bonus
        total_earnings = accept_earnings + bonus_earnings
        
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        
        embed.add_field(
            name="💰 Lifetime Earnings",
            value=f"📋 Accept Rewards: `{format_balance(accept_earnings)}`\n"
                  f"🎁 10h Bonuses: `{format_balance(bonus_earnings)}`\n"
                  f"**💎 Total: {format_balance(total_earnings)}**",
            inline=False
        )
        
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=get_standard_footer())
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="recruits", description="View your recruits and their progress (Officer only)")
    @rate_limited("officer", limit=5, window=60)
    @officer_only()
    async def recruits(self, interaction: discord.Interaction):
        """View recruits and their 10h progress"""
        user = await db.get_or_create_user(interaction.user.id)
        
        # Get recruit logs
        async with db.session() as session:
            from sqlalchemy import select
            from src.models.database import OfficerLog, User
            
            result = await session.execute(
                select(OfficerLog)
                .where(OfficerLog.officer_id == user.id)
                .order_by(OfficerLog.accepted_at.desc())
                .limit(10)
            )
            logs = list(result.scalars().all())
        
        if not logs:
            await interaction.response.send_message(
                "📭 You haven't recruited anyone yet!",
                ephemeral=True
            )
            return
        
        config = self.config.get("officer_system", {})
        tracking_hours = config.get("tracking_hours", 10)
        required_seconds = tracking_hours * 3600
        
        embed = discord.Embed(color=0x3498DB)
        
        embed.description = f"""
## 📋 YOUR RECRUITS
━━━━━━━━━━━━━━━━━━━━━━━━━━
*Showing last 10 recruits*
💎 Bonus awarded at **{tracking_hours}h** SB time
"""
        
        for log in logs:
            # Get recruit's current PB time
            recruit = await db.get_user_by_id(log.recruit_id)
            
            if recruit:
                member = interaction.guild.get_member(recruit.discord_id)
                name = member.display_name if member else f"User {recruit.discord_id}"
                
                pb_time = recruit.total_pb_time
                pb_display = format_pb_time(pb_time)
                
                # Calculate progress
                progress = min(100, (pb_time / required_seconds) * 100)
                
                if log.pb_10h_rewarded:
                    status = "✅ Bonus claimed"
                elif pb_time >= required_seconds:
                    status = "🎁 Bonus ready!"
                else:
                    status = f"⏳ {progress:.1f}% ({pb_display})"
                
                embed.add_field(
                    name=f"⚔️ {name}",
                    value=f"{status}\n<t:{int(log.accepted_at.timestamp())}:R>",
                    inline=True
                )
        
        embed.set_footer(text=get_standard_footer())
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(OfficerCog(bot))

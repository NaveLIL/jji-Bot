"""
Marketplace Cog - Role Shop with Color and Name roles
Two-page shop: Colors tab and Names tab
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List
import logging

from ..models.database import RoleType, Role, TransactionType
from ..services.database import db
from ..services.economy_logger import economy_logger
from ..utils.helpers import format_balance, calculate_tax
from ..utils.security import rate_limited


logger = logging.getLogger(__name__)


MAX_COLOR_ROLES = 1
MAX_NAME_ROLES = 5


class RoleBuySelect(discord.ui.Select):
    """Dropdown for selecting a role to buy"""
    
    def __init__(self, cog: "MarketplaceCog", roles: List[Role], owned_ids: set, role_type: RoleType, owned_count: int):
        self.cog = cog
        self.role_type = role_type
        self.available = [r for r in roles if r.discord_id not in owned_ids]
        
        options = []
        for role in self.available[:25]:
            options.append(discord.SelectOption(
                label=role.name[:100],
                value=str(role.discord_id),
                description=f"💰 {format_balance(role.price)}"
            ))
        
        if role_type == RoleType.COLOR:
            max_allowed = MAX_COLOR_ROLES
            emoji = "🎨"
            if not options:
                placeholder = "No color roles available"
            else:
                placeholder = "🎨 Select a color role to buy..."
        else:
            max_allowed = MAX_NAME_ROLES
            emoji = "📛"
            if not options:
                placeholder = "No name roles available"
            elif owned_count >= MAX_NAME_ROLES:
                placeholder = f"❌ Max {MAX_NAME_ROLES} roles reached"
            else:
                placeholder = f"📛 Select name role ({owned_count}/{MAX_NAME_ROLES})..."
        
        disabled = not options or (role_type == RoleType.NAME and owned_count >= MAX_NAME_ROLES)
        
        if not options:
            options = [discord.SelectOption(label="None available", value="none")]
        
        super().__init__(
            placeholder=placeholder,
            options=options,
            disabled=disabled
        )
    
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return
        
        role_id = int(self.values[0])
        
        if self.role_type == RoleType.COLOR:
            await self.cog._buy_color_role(interaction, role_id)
        else:
            await self.cog._buy_name_role(interaction, role_id)


class ShopView(discord.ui.View):
    """Two-page shop with tabs for Colors and Names"""
    
    def __init__(
        self, 
        cog: "MarketplaceCog",
        user_id: int,
        color_roles: List[Role],
        name_roles: List[Role],
        user_roles: List,
        user_balance: float,
        tax_rate: float,
        current_tab: str = "color"
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.color_roles = color_roles
        self.name_roles = name_roles
        self.user_roles = user_roles
        self.user_balance = user_balance
        self.tax_rate = tax_rate
        self.current_tab = current_tab
        
        self.owned_ids = {ur.role.discord_id for ur in user_roles}
        self.owned_color = [ur for ur in user_roles if ur.role.role_type == RoleType.COLOR]
        self.owned_name = [ur for ur in user_roles if ur.role.role_type == RoleType.NAME]
        
        self._build_view()
    
    def _build_view(self):
        """Build view based on current tab"""
        self.clear_items()
        
        # Tab buttons (row 0)
        color_btn = discord.ui.Button(
            label="🎨 Colors",
            style=discord.ButtonStyle.primary if self.current_tab == "color" else discord.ButtonStyle.secondary,
            row=0
        )
        color_btn.callback = self._switch_to_color
        self.add_item(color_btn)
        
        name_btn = discord.ui.Button(
            label="📛 Names", 
            style=discord.ButtonStyle.primary if self.current_tab == "name" else discord.ButtonStyle.secondary,
            row=0
        )
        name_btn.callback = self._switch_to_name
        self.add_item(name_btn)
        
        # Inventory button (row 0)
        inv_btn = discord.ui.Button(
            label="🎒 Inventory",
            style=discord.ButtonStyle.secondary,
            row=0
        )
        inv_btn.callback = self._open_inventory
        self.add_item(inv_btn)
        
        # Role select based on tab (row 1)
        if self.current_tab == "color":
            select = RoleBuySelect(
                self.cog,
                self.color_roles,
                self.owned_ids,
                RoleType.COLOR,
                len(self.owned_color)
            )
        else:
            select = RoleBuySelect(
                self.cog,
                self.name_roles,
                self.owned_ids,
                RoleType.NAME,
                len(self.owned_name)
            )
        self.add_item(select)
        
        # Refresh button (row 2)
        refresh_btn = discord.ui.Button(
            label="🔄 Refresh",
            style=discord.ButtonStyle.secondary,
            row=2
        )
        refresh_btn.callback = self._refresh
        self.add_item(refresh_btn)
    
    def build_embed(self) -> discord.Embed:
        """Build embed for current tab"""
        if self.current_tab == "color":
            title = "🎨 Color Roles"
            current = self.owned_color[0].role.name if self.owned_color else "None"
            description = f"**Current:** {current}\n*Buying a new color role replaces your current one.*"
            roles = self.color_roles
            max_roles = MAX_COLOR_ROLES
            owned_count = len(self.owned_color)
        else:
            title = "📛 Name Roles"
            description = f"**Owned:** {len(self.owned_name)}/{MAX_NAME_ROLES}\n*You can have up to {MAX_NAME_ROLES} name roles.*"
            roles = self.name_roles
            max_roles = MAX_NAME_ROLES
            owned_count = len(self.owned_name)
        
        embed = discord.Embed(title=title, color=discord.Color.gold())
        embed.description = f"**Balance:** {format_balance(self.user_balance)} • **Tax:** {self.tax_rate:.0f}%\n\n{description}"
        
        # List roles
        if roles:
            role_list = ""
            for role in roles[:15]:
                if role.discord_id in self.owned_ids:
                    role_list += f"✅ ~~{role.name}~~ - Owned\n"
                else:
                    total = role.price * (1 + self.tax_rate / 100)
                    role_list += f"💰 **{role.name}** - {format_balance(total)}\n"
            
            embed.add_field(name="Available Roles", value=role_list, inline=False)
        else:
            embed.add_field(name="Available Roles", value="*No roles in this category*", inline=False)
        
        embed.set_footer(text="Select a role from dropdown to purchase")
        return embed
    
    async def _switch_to_color(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your shop!", ephemeral=True)
        
        self.current_tab = "color"
        self._build_view()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
    
    async def _switch_to_name(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your shop!", ephemeral=True)
        
        self.current_tab = "name"
        self._build_view()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
    
    async def _open_inventory(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your shop!", ephemeral=True)
        
        view = InventoryView(self.cog, interaction.user.id, self.user_roles)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)
    
    async def _refresh(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your shop!", ephemeral=True)
        
        # Reload data
        all_roles = await db.get_all_roles(available_only=True)
        self.user_roles = await db.get_user_roles(self.user_id)
        user = await db.get_user(self.user_id)
        economy = await db.get_server_economy()
        
        self.color_roles = [r for r in all_roles if r.role_type == RoleType.COLOR]
        self.name_roles = [r for r in all_roles if r.role_type == RoleType.NAME]
        self.user_balance = user.balance if user else 0
        self.tax_rate = economy.tax_rate if economy else 10.0
        self.owned_ids = {ur.role.discord_id for ur in self.user_roles}
        self.owned_color = [ur for ur in self.user_roles if ur.role.role_type == RoleType.COLOR]
        self.owned_name = [ur for ur in self.user_roles if ur.role.role_type == RoleType.NAME]
        
        self._build_view()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
    
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class InventorySellSelect(discord.ui.Select):
    """Dropdown to sell a role"""
    
    def __init__(self, cog: "MarketplaceCog", user_roles: List):
        self.cog = cog
        
        options = []
        for ur in user_roles[:25]:
            emoji = "🎨" if ur.role.role_type == RoleType.COLOR else "📛"
            refund = ur.role.price * 0.1
            options.append(discord.SelectOption(
                label=ur.role.name[:100],
                value=str(ur.role.discord_id),
                description=f"Sell for {format_balance(refund)} (10%)",
                emoji=emoji
            ))
        
        if not options:
            options = [discord.SelectOption(label="No roles to sell", value="none")]
        
        super().__init__(
            placeholder="Select a role to sell...",
            options=options,
            disabled=not user_roles
        )
    
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return
        
        role_id = int(self.values[0])
        await self.cog._sell_role(interaction, role_id)


class InventoryView(discord.ui.View):
    """Inventory view showing owned roles"""
    
    def __init__(self, cog: "MarketplaceCog", user_id: int, user_roles: List):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.user_roles = user_roles
        
        self._build_view()
    
    def _build_view(self):
        self.clear_items()
        
        # Back to shop button
        back_btn = discord.ui.Button(
            label="🛒 Back to Shop",
            style=discord.ButtonStyle.primary,
            row=0
        )
        back_btn.callback = self._back_to_shop
        self.add_item(back_btn)
        
        # Refresh button
        refresh_btn = discord.ui.Button(
            label="🔄 Refresh",
            style=discord.ButtonStyle.secondary,
            row=0
        )
        refresh_btn.callback = self._refresh
        self.add_item(refresh_btn)
        
        # Sell select
        self.add_item(InventorySellSelect(self.cog, self.user_roles))
    
    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎒 Your Inventory", color=discord.Color.blue())
        
        color_roles = [ur for ur in self.user_roles if ur.role.role_type == RoleType.COLOR]
        name_roles = [ur for ur in self.user_roles if ur.role.role_type == RoleType.NAME]
        
        # Color section
        if color_roles:
            text = "\n".join([f"• **{ur.role.name}**" for ur in color_roles])
        else:
            text = "*None*"
        embed.add_field(name=f"🎨 Color Roles ({len(color_roles)}/{MAX_COLOR_ROLES})", value=text, inline=False)
        
        # Name section
        if name_roles:
            text = "\n".join([f"• **{ur.role.name}**" for ur in name_roles])
        else:
            text = "*None*"
        embed.add_field(name=f"📛 Name Roles ({len(name_roles)}/{MAX_NAME_ROLES})", value=text, inline=False)
        
        embed.set_footer(text="Select a role to sell (10% refund)")
        return embed
    
    async def _back_to_shop(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your inventory!", ephemeral=True)
        
        await self.cog._show_shop(interaction, self.user_id, edit=True)
    
    async def _refresh(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your inventory!", ephemeral=True)
        
        self.user_roles = await db.get_user_roles(self.user_id)
        self._build_view()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class MarketplaceCog(commands.Cog):
    """Role Shop"""
    
    def __init__(self, bot):
        self.bot = bot
    
    async def _show_shop(self, interaction: discord.Interaction, user_id: int, edit: bool = False, tab: str = "color"):
        """Display shop"""
        all_roles = await db.get_all_roles(available_only=True)
        user_roles = await db.get_user_roles(user_id)
        user = await db.get_user(user_id)
        economy = await db.get_server_economy()
        
        view = ShopView(
            cog=self,
            user_id=user_id,
            color_roles=[r for r in all_roles if r.role_type == RoleType.COLOR],
            name_roles=[r for r in all_roles if r.role_type == RoleType.NAME],
            user_roles=user_roles,
            user_balance=user.balance if user else 0,
            tax_rate=economy.tax_rate if economy else 10.0,
            current_tab=tab
        )
        
        if edit:
            await interaction.response.edit_message(embed=view.build_embed(), view=view)
        else:
            await interaction.followup.send(embed=view.build_embed(), view=view)
    
    async def _buy_color_role(self, interaction: discord.Interaction, role_id: int):
        """Buy a color role - replaces existing"""
        await interaction.response.defer(ephemeral=True)
        
        role = await db.get_role(discord_id=role_id)
        if not role:
            return await interaction.followup.send("❌ Role not found in shop!", ephemeral=True)
        
        # VALIDATION FIRST: Check Discord role exists and bot can assign it
        member = interaction.guild.get_member(interaction.user.id)
        discord_role = interaction.guild.get_role(role_id)
        
        if not discord_role:
            return await interaction.followup.send(
                "❌ This role no longer exists on the server. Please contact an admin.",
                ephemeral=True
            )
        
        if not member:
            return await interaction.followup.send("❌ Could not find your member data.", ephemeral=True)
        
        # Check bot can assign the role (role hierarchy)
        bot_member = interaction.guild.get_member(interaction.client.user.id)
        if bot_member and discord_role >= bot_member.top_role:
            return await interaction.followup.send(
                "❌ Bot cannot assign this role (role hierarchy issue). Contact an admin.",
                ephemeral=True
            )
        
        user = await db.get_user(interaction.user.id)
        economy = await db.get_server_economy()
        user_before = user.balance if user else 0
        budget_before = economy.total_budget
        tax = role.price * (economy.tax_rate / 100)
        total = role.price + tax
        
        if not user or user.balance < total:
            return await interaction.followup.send(
                f"❌ Need **{format_balance(total)}**, you have **{format_balance(user.balance if user else 0)}**",
                ephemeral=True
            )
        
        # Buy new role with tax atomically FIRST (before removing old one)
        success, msg, actual_tax = await db.purchase_role_with_tax(
            interaction.user.id, 
            role_id,
            economy.tax_rate
        )
        if not success:
            return await interaction.followup.send(f"❌ {msg}", ephemeral=True)
        
        # Purchase succeeded - now remove old color role (no refund, just removal)
        user_roles = await db.get_user_roles(interaction.user.id)
        replaced_role = None
        
        for ur in user_roles:
            if ur.role.role_type == RoleType.COLOR and ur.role.discord_id != role_id:
                replaced_role = ur.role.name
                old_discord_role = interaction.guild.get_role(ur.role.discord_id)
                if old_discord_role and old_discord_role in member.roles:
                    try:
                        await member.remove_roles(old_discord_role)
                    except Exception as e:
                        logger.warning(f"Failed to remove old color role: {e}")
                # Remove from DB (no refund since they're replacing, not selling)
                await db.sell_role(interaction.user.id, ur.role.discord_id, refund_percentage=0)
        
        # Assign new Discord role
        try:
            await member.add_roles(discord_role)
            await db.toggle_role_active(interaction.user.id, role_id)
        except discord.Forbidden:
            logger.error(f"Failed to assign role {role.name} - permission denied")
            # Role purchase is in DB but Discord assignment failed
            # We still log it but warn the user
            await interaction.followup.send(
                f"⚠️ Purchased **{role.name}** but failed to assign it. Contact an admin to fix.",
                ephemeral=True
            )
            return
        except Exception as e:
            logger.error(f"Failed to assign role {role.name}: {e}")
        
        # Log shop purchase
        user_after = await db.get_user(interaction.user.id)
        economy_after = await db.get_server_economy()
        await economy_logger.log_shop(
            action="purchase",
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            role_name=role.name,
            role_price=role.price,
            tax=tax,
            refund=0,
            user_before=user_before,
            user_after=user_after.balance,
            budget_before=budget_before,
            budget_after=economy_after.total_budget,
            replaced_role=replaced_role
        )
        
        await interaction.followup.send(f"✅ Bought **{role.name}** for **{format_balance(total)}**!", ephemeral=True)
    
    async def _buy_name_role(self, interaction: discord.Interaction, role_id: int):
        """Buy a name role"""
        await interaction.response.defer(ephemeral=True)
        
        role = await db.get_role(discord_id=role_id)
        if not role:
            return await interaction.followup.send("❌ Role not found in shop!", ephemeral=True)
        
        # VALIDATION FIRST: Check Discord role exists and bot can assign it
        member = interaction.guild.get_member(interaction.user.id)
        discord_role = interaction.guild.get_role(role_id)
        
        if not discord_role:
            return await interaction.followup.send(
                "❌ This role no longer exists on the server. Please contact an admin.",
                ephemeral=True
            )
        
        if not member:
            return await interaction.followup.send("❌ Could not find your member data.", ephemeral=True)
        
        # Check bot can assign the role (role hierarchy)
        bot_member = interaction.guild.get_member(interaction.client.user.id)
        if bot_member and discord_role >= bot_member.top_role:
            return await interaction.followup.send(
                "❌ Bot cannot assign this role (role hierarchy issue). Contact an admin.",
                ephemeral=True
            )
        
        user = await db.get_user(interaction.user.id)
        economy = await db.get_server_economy()
        user_before = user.balance if user else 0
        budget_before = economy.total_budget
        user_roles = await db.get_user_roles(interaction.user.id)
        
        # Check limit
        owned_name = [ur for ur in user_roles if ur.role.role_type == RoleType.NAME]
        if len(owned_name) >= MAX_NAME_ROLES:
            return await interaction.followup.send(f"❌ Max {MAX_NAME_ROLES} name roles!", ephemeral=True)
        
        tax = role.price * (economy.tax_rate / 100)
        total = role.price + tax
        
        if not user or user.balance < total:
            return await interaction.followup.send(
                f"❌ Need **{format_balance(total)}**, you have **{format_balance(user.balance if user else 0)}**",
                ephemeral=True
            )
        
        # Buy role with tax atomically
        success, msg, actual_tax = await db.purchase_role_with_tax(
            interaction.user.id, 
            role_id,
            economy.tax_rate
        )
        if not success:
            return await interaction.followup.send(f"❌ {msg}", ephemeral=True)
        
        # Assign Discord role
        try:
            await member.add_roles(discord_role)
            await db.toggle_role_active(interaction.user.id, role_id)
        except discord.Forbidden:
            logger.error(f"Failed to assign role {role.name} - permission denied")
            await interaction.followup.send(
                f"⚠️ Purchased **{role.name}** but failed to assign it. Contact an admin to fix.",
                ephemeral=True
            )
            return
        except Exception as e:
            logger.error(f"Failed to assign role {role.name}: {e}")
        
        # Log shop purchase
        user_after = await db.get_user(interaction.user.id)
        economy_after = await db.get_server_economy()
        await economy_logger.log_shop(
            action="purchase",
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            role_name=role.name,
            role_price=role.price,
            tax=tax,
            refund=0,
            user_before=user_before,
            user_after=user_after.balance,
            budget_before=budget_before,
            budget_after=economy_after.total_budget
        )
        
        await interaction.followup.send(f"✅ Bought **{role.name}** for **{format_balance(total)}**!", ephemeral=True)
    
    async def _sell_role(self, interaction: discord.Interaction, role_id: int):
        """Sell a role"""
        await interaction.response.defer(ephemeral=True)
        
        role = await db.get_role(discord_id=role_id)
        if not role:
            return await interaction.followup.send("❌ Role not found!", ephemeral=True)
        
        user = await db.get_user(interaction.user.id)
        economy = await db.get_server_economy()
        user_before = user.balance if user else 0
        budget_before = economy.total_budget
        
        # Remove Discord role
        member = interaction.guild.get_member(interaction.user.id)
        discord_role = interaction.guild.get_role(role_id)
        if member and discord_role and discord_role in member.roles:
            try:
                await member.remove_roles(discord_role)
            except:
                pass
        
        success, msg, refund = await db.sell_role(interaction.user.id, role_id, refund_percentage=10)
        if not success:
            return await interaction.followup.send(f"❌ {msg}", ephemeral=True)
        
        # Log shop sale
        user_after = await db.get_user(interaction.user.id)
        economy_after = await db.get_server_economy()
        await economy_logger.log_shop(
            action="sale",
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            role_name=role.name,
            role_price=role.price,
            tax=0,
            refund=refund,
            user_before=user_before,
            user_after=user_after.balance,
            budget_before=budget_before,
            budget_after=economy_after.total_budget
        )
        
        await interaction.followup.send(f"Sold **{role.name}** for **{format_balance(refund)}**!", ephemeral=True)
    
    # === COMMANDS ===
    
    @app_commands.command(name="shop", description="Open the role shop")
    @rate_limited("shop", limit=5, window=60)
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._show_shop(interaction, interaction.user.id)
    
    @app_commands.command(name="inventory", description="View your roles")
    @rate_limited("shop", limit=5, window=60)
    async def inventory(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_roles = await db.get_user_roles(interaction.user.id)
        view = InventoryView(self, interaction.user.id, user_roles)
        await interaction.followup.send(embed=view.build_embed(), view=view)
    
    @app_commands.command(name="myroles", description="View your roles")
    @rate_limited("shop", limit=5, window=60)
    async def myroles(self, interaction: discord.Interaction):
        await self.inventory(interaction)
    
    @app_commands.command(name="sellrole", description="Sell a role (10% refund)")
    @app_commands.describe(role="Role to sell")
    @rate_limited("shop", limit=3, window=60)
    async def sellrole(self, interaction: discord.Interaction, role: discord.Role):
        user_roles = await db.get_user_roles(interaction.user.id)
        owned = next((ur for ur in user_roles if ur.role.discord_id == role.id), None)
        
        if not owned:
            return await interaction.response.send_message(f"❌ You don't own **{role.name}**!", ephemeral=True)
        
        await self._sell_role(interaction, role.id)
    
    @app_commands.command(name="addrole", description="Add role to shop (Admin)")
    @app_commands.describe(role="Discord role", price="Price", role_type="Type")
    @app_commands.choices(role_type=[
        app_commands.Choice(name="Color", value="color"),
        app_commands.Choice(name="Name", value="name")
    ])
    @app_commands.default_permissions(administrator=True)
    async def addrole(self, interaction: discord.Interaction, role: discord.Role, price: float, role_type: str):
        if price < 0:
            return await interaction.response.send_message("❌ Price must be positive!", ephemeral=True)
        
        existing = await db.get_role(discord_id=role.id)
        if existing:
            return await interaction.response.send_message(f"❌ **{role.name}** already in shop!", ephemeral=True)
        
        rt = RoleType.COLOR if role_type == "color" else RoleType.NAME
        color_hex = f"#{role.color.value:06x}" if role.color.value else None
        
        await db.add_shop_role(role.id, role.name, rt, price, color_hex)
        
        emoji = "🎨" if rt == RoleType.COLOR else "📛"
        await interaction.response.send_message(f"✅ Added {emoji} **{role.name}** for **{format_balance(price)}**!")
    
    @app_commands.command(name="removerole", description="Remove role from shop (Admin)")
    @app_commands.describe(role="Role to remove")
    @app_commands.default_permissions(administrator=True)
    async def removerole(self, interaction: discord.Interaction, role: discord.Role):
        existing = await db.get_role(discord_id=role.id)
        if not existing:
            return await interaction.response.send_message(f"❌ **{role.name}** not in shop!", ephemeral=True)
        
        await db.remove_shop_role(role.id)
        await interaction.response.send_message(f"✅ Removed **{role.name}** from shop!")


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketplaceCog(bot))

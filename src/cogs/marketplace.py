"""
Marketplace Cog - Role shop, buy, sell, inventory
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from src.services.database import db
from src.models.database import RoleType, TransactionType
from src.utils.helpers import format_balance, load_config, parse_color_hex, calculate_tax
from src.utils.security import rate_limited, admin_only
from src.utils.metrics import metrics


class BuyRoleButton(discord.ui.Button):
    """Button to buy a specific role"""
    
    def __init__(self, role_data, row: int = 0):
        self.role_data = role_data
        super().__init__(
            label=f"${role_data.price:.0f}",
            style=discord.ButtonStyle.success,
            custom_id=f"buy_role:{role_data.discord_id}",
            row=row
        )
    
    async def callback(self, interaction: discord.Interaction):
        role_id = self.role_data.discord_id
        price = self.role_data.price
        role_name = self.role_data.name
        
        # Check if user already owns this role
        user_roles = await db.get_user_roles(interaction.user.id)
        if any(ur.role.discord_id == role_id for ur in user_roles):
            await interaction.response.send_message(
                f"❌ You already own **{role_name}**!",
                ephemeral=True
            )
            return
        
        # Check balance
        user = await db.get_or_create_user(interaction.user.id)
        if user.balance < price:
            await interaction.response.send_message(
                f"❌ Insufficient balance! You need **{format_balance(price)}** but only have **{format_balance(user.balance)}**",
                ephemeral=True
            )
            return
        
        # Purchase
        success, message = await db.purchase_role(interaction.user.id, role_id)
        
        if success:
            # Try to add the Discord role
            role = interaction.guild.get_role(role_id)
            role_added = False
            if role:
                try:
                    await interaction.user.add_roles(role, reason="Role purchased from shop")
                    role_added = True
                except discord.Forbidden:
                    pass
                except Exception:
                    pass
            
            embed = discord.Embed(
                title="✅ PURCHASE SUCCESSFUL",
                description=f"You bought **{role_name}** for **{format_balance(price)}**!",
                color=0x00FF00
            )
            
            if role_added:
                embed.add_field(name="📌 Status", value="Role equipped automatically!", inline=False)
            else:
                embed.add_field(name="📌 Status", value="Use `/myroles` to equip it.", inline=False)
            
            new_balance = user.balance - price
            embed.add_field(name="💰 New Balance", value=f"`{format_balance(new_balance)}`", inline=True)
            embed.set_footer(text="💎 Developed by NaveL for JJI in 2025")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            metrics.track_transaction("role_purchase")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)


class ShopView(discord.ui.View):
    """Paginated shop view with buy buttons"""
    
    def __init__(self, roles: list, guild: discord.Guild, page: int = 0, per_page: int = 5, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.roles = roles
        self.guild = guild
        self.page = page
        self.per_page = per_page
        self.total_pages = max(1, (len(roles) + per_page - 1) // per_page)
        self._build_view()
    
    def _build_view(self):
        """Build the view with current page roles"""
        self.clear_items()
        
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        # Add buy buttons for each role (row 0-3)
        for i, role in enumerate(page_roles[:4]):  # Max 4 buttons per row
            self.add_item(BuyRoleButton(role, row=0))
        
        # Navigation buttons (row 4)
        prev_btn = discord.ui.Button(
            label="◀ Previous",
            style=discord.ButtonStyle.secondary,
            custom_id="shop:prev",
            disabled=self.page <= 0,
            row=4
        )
        prev_btn.callback = self.prev_page
        self.add_item(prev_btn)
        
        next_btn = discord.ui.Button(
            label="Next ▶",
            style=discord.ButtonStyle.secondary,
            custom_id="shop:next",
            disabled=self.page >= self.total_pages - 1,
            row=4
        )
        next_btn.callback = self.next_page
        self.add_item(next_btn)
        
        refresh_btn = discord.ui.Button(
            label="🔄 Refresh",
            style=discord.ButtonStyle.primary,
            custom_id="shop:refresh",
            row=4
        )
        refresh_btn.callback = self.refresh
        self.add_item(refresh_btn)
    
    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
        self._build_view()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.total_pages - 1:
            self.page += 1
        self._build_view()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    async def refresh(self, interaction: discord.Interaction):
        # Reload roles from database
        self.roles = await db.get_all_roles(available_only=True)
        self.total_pages = max(1, (len(self.roles) + self.per_page - 1) // self.per_page)
        if self.page >= self.total_pages:
            self.page = self.total_pages - 1
        self._build_view()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(color=0x9B59B6)
        
        embed.description = """
## 🛒 ROLE MARKETPLACE
━━━━━━━━━━━━━━━━━━━━━━━━━━
*Click a button below to purchase!*
"""
        
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        if not page_roles:
            embed.add_field(
                name="📭 Empty Shop",
                value="```\nNo roles available!\n```",
                inline=False
            )
        else:
            for i, role in enumerate(page_roles):
                type_emoji = "🎨" if role.role_type == RoleType.COLOR else "⭐"
                
                # Get Discord role for preview
                discord_role = self.guild.get_role(role.discord_id) if self.guild else None
                color_preview = ""
                if discord_role and discord_role.color.value:
                    color_preview = f" • {discord_role.mention}"
                elif role.color_hex:
                    color_preview = f" `{role.color_hex}`"
                
                embed.add_field(
                    name=f"{type_emoji} {role.name}",
                    value=f"**{format_balance(role.price)}**{color_preview}",
                    inline=True
                )
        
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages} • 💎 Developed by NaveL for JJI in 2025")
        return embed


class InventoryView(discord.ui.View):
    """User inventory with role management"""
    
    def __init__(self, user_roles: list, discord_user: discord.Member, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.user_roles = user_roles
        self.discord_user = discord_user
        self.selected_role_id = None
        
        if user_roles:
            self.add_role_select()
    
    def add_role_select(self):
        """Add role selection dropdown"""
        options = []
        for ur in self.user_roles[:25]:  # Discord limit
            status = "✅" if ur.is_active else "❌"
            options.append(discord.SelectOption(
                label=f"{status} {ur.role.name}",
                value=str(ur.role.discord_id),
                description=f"Price: ${ur.role.price:.2f}"
            ))
        
        select = discord.ui.Select(
            placeholder="Select a role to manage...",
            options=options,
            custom_id="inventory:select"
        )
        select.callback = self.on_select
        self.add_item(select)
    
    async def on_select(self, interaction: discord.Interaction):
        """Handle role selection"""
        self.selected_role_id = int(interaction.data["values"][0])
        
        # Find the selected role
        selected_ur = None
        for ur in self.user_roles:
            if ur.role.discord_id == self.selected_role_id:
                selected_ur = ur
                break
        
        if selected_ur:
            # Update buttons based on selected role
            self.clear_items()
            self.add_role_select()
            
            # Equip/Unequip button
            if selected_ur.is_active:
                unequip_btn = discord.ui.Button(
                    label="Unequip",
                    style=discord.ButtonStyle.secondary,
                    custom_id="inventory:unequip"
                )
                unequip_btn.callback = self.unequip_role
                self.add_item(unequip_btn)
            else:
                equip_btn = discord.ui.Button(
                    label="Equip",
                    style=discord.ButtonStyle.success,
                    custom_id="inventory:equip"
                )
                equip_btn.callback = self.equip_role
                self.add_item(equip_btn)
            
            # Sell button
            sell_btn = discord.ui.Button(
                label="Sell",
                style=discord.ButtonStyle.danger,
                custom_id="inventory:sell"
            )
            sell_btn.callback = self.sell_role
            self.add_item(sell_btn)
        
        await interaction.response.edit_message(view=self)
    
    async def equip_role(self, interaction: discord.Interaction):
        """Equip selected role"""
        if interaction.user.id != self.discord_user.id:
            await interaction.response.send_message("Not your inventory!", ephemeral=True)
            return
        
        config = load_config()
        max_active = config.get("role_shop", {}).get("max_active_roles", 5)
        
        success, message, new_state = await db.toggle_role_active(
            interaction.user.id,
            self.selected_role_id,
            max_active
        )
        
        if success:
            # Actually add the Discord role
            role = interaction.guild.get_role(self.selected_role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                except Exception:
                    pass
            
            await interaction.response.send_message(f"✅ {message}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    
    async def unequip_role(self, interaction: discord.Interaction):
        """Unequip selected role"""
        if interaction.user.id != self.discord_user.id:
            await interaction.response.send_message("Not your inventory!", ephemeral=True)
            return
        
        success, message, new_state = await db.toggle_role_active(
            interaction.user.id,
            self.selected_role_id,
            max_active=5
        )
        
        if success:
            # Remove the Discord role
            role = interaction.guild.get_role(self.selected_role_id)
            if role:
                try:
                    await interaction.user.remove_roles(role)
                except Exception:
                    pass
            
            await interaction.response.send_message(f"✅ {message}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    
    async def sell_role(self, interaction: discord.Interaction):
        """Sell selected role"""
        if interaction.user.id != self.discord_user.id:
            await interaction.response.send_message("Not your inventory!", ephemeral=True)
            return
        
        config = load_config()
        refund_pct = config.get("role_shop", {}).get("sell_refund_percentage", 10)
        
        # First unequip if active
        role = interaction.guild.get_role(self.selected_role_id)
        if role and role in interaction.user.roles:
            try:
                await interaction.user.remove_roles(role)
            except Exception:
                pass
        
        success, message, refund = await db.sell_role(
            interaction.user.id,
            self.selected_role_id,
            refund_pct
        )
        
        if success:
            # Apply tax to role sale refund
            economy = await db.get_server_economy()
            net_refund, tax = calculate_tax(refund, economy.tax_rate)
            
            # Tax was not applied in db.sell_role, we need to adjust
            # Deduct tax from user and add to server budget
            if tax > 0:
                await db.update_user_balance(
                    interaction.user.id,
                    -tax,
                    TransactionType.TAX,
                    description="Tax on role sale"
                )
                await db.add_taxes_collected(tax)
            
            if tax > 0:
                await interaction.response.send_message(
                    f"✅ {message}\nGross: {format_balance(refund)} | Tax: {format_balance(tax)}\n**Net received: {format_balance(net_refund)}**",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"✅ {message}\nYou received {format_balance(refund)}",
                    ephemeral=True
                )
            metrics.track_transaction("role_sell")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    
    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(color=0x9B59B6)
        
        embed.description = f"""
## 🎒 INVENTORY
━━━━━━━━━━━━━━━━━━━━━━━━━━
**{self.discord_user.display_name}**'s Role Collection
"""
        
        if not self.user_roles:
            embed.add_field(
                name="📭 Empty Inventory",
                value="```\nNo roles owned!\n```\nVisit `/shop` to browse roles.",
                inline=False
            )
        else:
            active = [ur for ur in self.user_roles if ur.is_active]
            inactive = [ur for ur in self.user_roles if not ur.is_active]
            
            if active:
                active_lines = []
                for ur in active:
                    active_lines.append(f"• **{ur.role.name}**")
                embed.add_field(
                    name=f"✅ Equipped ({len(active)})",
                    value="\n".join(active_lines) or "None",
                    inline=True
                )
            
            if inactive:
                inactive_lines = []
                for ur in inactive:
                    inactive_lines.append(f"• {ur.role.name}")
                embed.add_field(
                    name=f"❌ Unequipped ({len(inactive)})",
                    value="\n".join(inactive_lines) or "None",
                    inline=True
                )
            
            embed.add_field(
                name="",
                value=f"📊 **Total Roles:** {len(self.user_roles)}",
                inline=False
            )
        
        embed.set_footer(text="Select a role below to manage • Developed by NaveL for JJI in 2025")
        return embed


class MarketplaceCog(commands.Cog):
    """Marketplace commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    @app_commands.command(name="shop", description="View the role shop")
    @rate_limited("economy", limit=5, window=60)
    async def shop(self, interaction: discord.Interaction):
        """Display role shop with buy buttons"""
        roles = await db.get_all_roles(available_only=True)
        
        view = ShopView(roles, interaction.guild)
        await interaction.response.send_message(embed=view.get_embed(), view=view)
    
    @app_commands.command(name="buyrole", description="Purchase a role from the shop")
    @app_commands.describe(role="The role to purchase")
    @rate_limited("economy", limit=5, window=60)
    async def buyrole(self, interaction: discord.Interaction, role: discord.Role):
        """Purchase a role"""
        # Check if role is in shop
        shop_role = await db.get_role(discord_id=role.id)
        
        if not shop_role or not shop_role.is_available:
            await interaction.response.send_message(
                "❌ This role is not available for purchase!",
                ephemeral=True
            )
            return
        
        # Check balance
        user = await db.get_or_create_user(interaction.user.id)
        
        if user.balance < shop_role.price:
            await interaction.response.send_message(
                f"❌ Insufficient balance! You need {format_balance(shop_role.price)} "
                f"but only have {format_balance(user.balance)}",
                ephemeral=True
            )
            return
        
        # Purchase
        success, message = await db.purchase_role(interaction.user.id, role.id)
        
        if success:
            await interaction.response.send_message(
                f"✅ {message}\nUse /myroles to manage your roles.",
                ephemeral=True
            )
            metrics.track_transaction("role_purchase")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    
    @app_commands.command(name="myroles", description="View and manage your purchased roles")
    @rate_limited("economy", limit=5, window=60)
    async def myroles(self, interaction: discord.Interaction):
        """Display user's role inventory"""
        user_roles = await db.get_user_roles(interaction.user.id)
        
        view = InventoryView(user_roles, interaction.user)
        await interaction.response.send_message(embed=view.get_embed(), view=view)
    
    @app_commands.command(name="sellrole", description="Sell a role back to the shop")
    @app_commands.describe(role="The role to sell")
    @rate_limited("economy", limit=5, window=60)
    async def sellrole(self, interaction: discord.Interaction, role: discord.Role):
        """Sell a role"""
        config = self.config.get("role_shop", {})
        refund_pct = config.get("sell_refund_percentage", 10)
        
        # Check ownership
        user_roles = await db.get_user_roles(interaction.user.id)
        owned = any(ur.role.discord_id == role.id for ur in user_roles)
        
        if not owned:
            await interaction.response.send_message(
                "❌ You don't own this role!",
                ephemeral=True
            )
            return
        
        # Remove Discord role if equipped
        if role in interaction.user.roles:
            try:
                await interaction.user.remove_roles(role)
            except Exception:
                pass
        
        # Sell
        success, message, refund = await db.sell_role(
            interaction.user.id,
            role.id,
            refund_pct
        )
        
        if success:
            await interaction.response.send_message(
                f"✅ {message}",
                ephemeral=True
            )
            metrics.track_transaction("role_sell")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    
    # Admin commands
    @app_commands.command(name="addrole", description="Add a role to the shop (Admin)")
    @app_commands.describe(
        role="The Discord role to add",
        price="Price for the role",
        role_type="Type of role (color/custom)"
    )
    @admin_only()
    async def addrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        price: float,
        role_type: str = "color"
    ):
        """Add a role to the shop"""
        if price < 0:
            await interaction.response.send_message(
                "❌ Price must be positive!",
                ephemeral=True
            )
            return
        
        # Check if already exists
        existing = await db.get_role(discord_id=role.id)
        if existing:
            await interaction.response.send_message(
                "❌ This role is already in the shop!",
                ephemeral=True
            )
            return
        
        r_type = RoleType.COLOR if role_type.lower() == "color" else RoleType.CUSTOM
        color_hex = f"#{role.color.value:06x}" if role.color.value else None
        
        await db.add_shop_role(
            discord_id=role.id,
            name=role.name,
            role_type=r_type,
            price=price,
            color_hex=color_hex,
            description=None
        )
        
        await interaction.response.send_message(
            f"✅ Added **{role.name}** to the shop for {format_balance(price)}!",
            ephemeral=True
        )
    
    @app_commands.command(name="removerole", description="Remove a role from the shop (Admin)")
    @app_commands.describe(role="The role to remove")
    @admin_only()
    async def removerole(self, interaction: discord.Interaction, role: discord.Role):
        """Remove a role from the shop"""
        success = await db.remove_shop_role(role.id)
        
        if success:
            await interaction.response.send_message(
                f"✅ Removed **{role.name}** from the shop!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Role not found in shop!",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketplaceCog(bot))

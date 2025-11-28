"""
Marketplace Cog - Role shop, buy, sell, inventory
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from src.services.database import db
from src.models.database import RoleType
from src.utils.helpers import format_balance, load_config, parse_color_hex
from src.utils.security import rate_limited, admin_only
from src.utils.metrics import metrics


class ShopView(discord.ui.View):
    """Paginated shop view"""
    
    def __init__(self, roles: list, page: int = 0, per_page: int = 5, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.roles = roles
        self.page = page
        self.per_page = per_page
        self.total_pages = max(1, (len(roles) + per_page - 1) // per_page)
        self.update_buttons()
    
    def update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1
    
    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🛒 Role Shop",
            description="Purchase roles to customize your profile!",
            color=discord.Color.purple()
        )
        
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        if not page_roles:
            embed.add_field(
                name="No Roles Available",
                value="The shop is empty!",
                inline=False
            )
        else:
            for role in page_roles:
                type_emoji = "🎨" if role.role_type == RoleType.COLOR else "⭐"
                color_info = f" ({role.color_hex})" if role.color_hex else ""
                
                embed.add_field(
                    name=f"{type_emoji} {role.name}{color_info}",
                    value=f"**Price:** {format_balance(role.price)}\n**ID:** `{role.discord_id}`",
                    inline=True
                )
        
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages} • Use /buyrole <role_id> to purchase")
        return embed
    
    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="shop:prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="shop:next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


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
            await interaction.response.send_message(
                f"✅ {message}\nYou received {format_balance(refund)}",
                ephemeral=True
            )
            metrics.track_transaction("role_sell")
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    
    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎒 {self.discord_user.display_name}'s Inventory",
            color=discord.Color.purple()
        )
        
        if not self.user_roles:
            embed.description = "Your inventory is empty! Visit /shop to buy roles."
        else:
            active = [ur for ur in self.user_roles if ur.is_active]
            inactive = [ur for ur in self.user_roles if not ur.is_active]
            
            if active:
                active_text = "\n".join(f"✅ {ur.role.name}" for ur in active)
                embed.add_field(name="Equipped", value=active_text, inline=True)
            
            if inactive:
                inactive_text = "\n".join(f"❌ {ur.role.name}" for ur in inactive)
                embed.add_field(name="Unequipped", value=inactive_text, inline=True)
        
        embed.set_footer(text="Select a role below to manage it")
        return embed


class MarketplaceCog(commands.Cog):
    """Marketplace commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    @app_commands.command(name="shop", description="View the role shop")
    @rate_limited("economy", limit=5, window=60)
    async def shop(self, interaction: discord.Interaction):
        """Display role shop"""
        roles = await db.get_all_roles(available_only=True)
        
        view = ShopView(roles)
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

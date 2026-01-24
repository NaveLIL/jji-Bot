"""
FAQ Cog - Interactive Reference System
Persistent FAQ panels with searchable selectors that work after bot restart
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List
from datetime import datetime

from src.services.database import db
from src.utils.helpers import load_config, get_standard_footer
from src.utils.security import rate_limited


# ═══════════════════════════════════════════════════════════════════════════════
# FAQ VIEWS - Persistent interactive components
# ═══════════════════════════════════════════════════════════════════════════════

class FAQSelectMenu(discord.ui.Select):
    """Searchable dropdown for FAQ entries"""
    
    def __init__(self, panel_id: int, entries: list, placeholder: str = "Select a topic..."):
        options = []
        for entry in entries[:25]:  # Discord limit is 25 options
            option = discord.SelectOption(
                label=entry["label"][:100],  # Limit label length
                value=str(entry["id"]),
                description=entry.get("content", "")[:100] if entry.get("content") else None,
                emoji=entry.get("emoji") if entry.get("emoji") else None
            )
            options.append(option)
        
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"faq_select:{panel_id}"
        )
        self.panel_id = panel_id
    
    async def callback(self, interaction: discord.Interaction):
        entry_id = int(self.values[0])
        
        # Fetch entry content from database
        entry = await db.get_faq_entry(entry_id)
        
        if not entry:
            await interaction.response.send_message(
                "❌ This entry no longer exists.",
                ephemeral=True
            )
            return
        
        # Create ephemeral response with entry content
        embed = discord.Embed(
            title=f"📖 {entry['label']}",
            description=entry["content"],
            color=0x3498DB,
            timestamp=datetime.utcnow()
        )
        
        if entry.get("emoji"):
            embed.title = f"{entry['emoji']} {entry['label']}"
        
        embed.set_footer(text=f"FAQ • {get_standard_footer()}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class FAQPanelView(discord.ui.View):
    """Persistent view for FAQ panels"""
    
    def __init__(self, panel_id: int, entries: list, placeholder: str = "Select a topic..."):
        super().__init__(timeout=None)  # Persistent view
        
        if entries:
            self.add_item(FAQSelectMenu(panel_id, entries, placeholder))


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class CreatePanelModal(discord.ui.Modal, title="Create FAQ Panel"):
    """Modal for creating a new FAQ panel"""
    
    panel_name = discord.ui.TextInput(
        label="Panel Name (unique identifier)",
        placeholder="e.g., rules, commands, economy",
        required=True,
        max_length=100
    )
    
    panel_title = discord.ui.TextInput(
        label="Panel Title (displayed in embed)",
        placeholder="e.g., Server Rules & Guidelines",
        required=True,
        max_length=256
    )
    
    panel_description = discord.ui.TextInput(
        label="Panel Description",
        placeholder="Description shown in the embed body",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000
    )
    
    panel_color = discord.ui.TextInput(
        label="Embed Color (hex, e.g., #3498DB)",
        placeholder="#3498DB",
        required=False,
        max_length=7,
        default="#3498DB"
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        # Parse color
        color_str = self.panel_color.value.strip()
        if color_str.startswith("#"):
            color_str = color_str[1:]
        try:
            color = int(color_str, 16)
        except ValueError:
            color = 0x3498DB
        
        # Create panel in database
        result = await db.create_faq_panel(
            name=self.panel_name.value.strip().lower().replace(" ", "_"),
            title=self.panel_title.value.strip(),
            description=self.panel_description.value.strip() if self.panel_description.value else None,
            color=color,
            guild_id=interaction.guild_id,
            created_by=interaction.user.id
        )
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ {result.get('error', 'Failed to create panel')}",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="✅ FAQ Panel Created",
            description=f"Panel **{self.panel_name.value}** created successfully!",
            color=0x00FF00
        )
        embed.add_field(name="Name", value=f"`{result['panel']['name']}`", inline=True)
        embed.add_field(name="ID", value=f"`{result['panel']['id']}`", inline=True)
        embed.add_field(
            name="Next Steps",
            value="1. Use `/faq entry add` to add entries\n"
                  "2. Use `/faq publish` to publish the panel\n"
                  "3. Use `/faq edit` to modify settings",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class AddEntryModal(discord.ui.Modal, title="Add FAQ Entry"):
    """Modal for adding a new FAQ entry"""
    
    def __init__(self, panel_name: str):
        super().__init__()
        self.panel_name = panel_name
    
    entry_label = discord.ui.TextInput(
        label="Entry Label (shown in dropdown)",
        placeholder="e.g., How to earn money?",
        required=True,
        max_length=100
    )
    
    entry_emoji = discord.ui.TextInput(
        label="Emoji (optional)",
        placeholder="💰",
        required=False,
        max_length=64
    )
    
    entry_content = discord.ui.TextInput(
        label="Entry Content (markdown supported)",
        placeholder="The detailed answer or information...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        # Get panel first
        panel = await db.get_faq_panel_by_name(self.panel_name, interaction.guild_id)
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{self.panel_name}` not found!",
                ephemeral=True
            )
            return
        
        # Add entry
        result = await db.add_faq_entry(
            panel_id=panel["id"],
            label=self.entry_label.value.strip(),
            content=self.entry_content.value.strip(),
            emoji=self.entry_emoji.value.strip() if self.entry_emoji.value else None
        )
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ {result.get('error', 'Failed to add entry')}",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="✅ Entry Added",
            description=f"Entry **{self.entry_label.value}** added to panel **{self.panel_name}**!",
            color=0x00FF00
        )
        embed.add_field(name="Entry ID", value=f"`{result['entry']['id']}`", inline=True)
        embed.add_field(name="Panel", value=f"`{self.panel_name}`", inline=True)
        
        # Remind to republish if already published
        if panel.get("message_id"):
            embed.add_field(
                name="⚠️ Note",
                value="Panel is already published. Use `/faq publish` to update it with new entries.",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EditPanelModal(discord.ui.Modal, title="Edit FAQ Panel"):
    """Modal for editing FAQ panel settings"""
    
    def __init__(self, panel: dict):
        super().__init__()
        self.panel_id = panel["id"]
        self.panel_name = panel["name"]
        
        self.panel_title.default = panel["title"]
        self.panel_description.default = panel.get("description") or ""
        self.panel_footer.default = panel.get("footer_text") or ""
        self.panel_color.default = f"#{panel.get('color', 0x3498DB):06X}"
    
    panel_title = discord.ui.TextInput(
        label="Panel Title",
        required=True,
        max_length=256
    )
    
    panel_description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000
    )
    
    panel_footer = discord.ui.TextInput(
        label="Footer Text (optional)",
        required=False,
        max_length=256
    )
    
    panel_color = discord.ui.TextInput(
        label="Embed Color (hex)",
        required=False,
        max_length=7
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        # Parse color
        color = None
        if self.panel_color.value:
            color_str = self.panel_color.value.strip()
            if color_str.startswith("#"):
                color_str = color_str[1:]
            try:
                color = int(color_str, 16)
            except ValueError:
                pass
        
        result = await db.update_faq_panel(
            panel_id=self.panel_id,
            title=self.panel_title.value.strip(),
            description=self.panel_description.value.strip() if self.panel_description.value else None,
            footer_text=self.panel_footer.value.strip() if self.panel_footer.value else None,
            color=color
        )
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ {result.get('error', 'Failed to update panel')}",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="✅ Panel Updated",
            description=f"Panel **{self.panel_name}** has been updated!",
            color=0x00FF00
        )
        
        if result.get("panel", {}).get("message_id"):
            embed.add_field(
                name="⚠️ Note",
                value="Use `/faq publish` to update the published message.",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EditEntryModal(discord.ui.Modal, title="Edit FAQ Entry"):
    """Modal for editing a FAQ entry"""
    
    def __init__(self, entry: dict):
        super().__init__()
        self.entry_id = entry["id"]
        
        self.entry_label.default = entry["label"]
        self.entry_emoji.default = entry.get("emoji") or ""
        self.entry_content.default = entry["content"]
    
    entry_label = discord.ui.TextInput(
        label="Entry Label",
        required=True,
        max_length=100
    )
    
    entry_emoji = discord.ui.TextInput(
        label="Emoji (optional)",
        required=False,
        max_length=64
    )
    
    entry_content = discord.ui.TextInput(
        label="Entry Content",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        result = await db.update_faq_entry(
            entry_id=self.entry_id,
            label=self.entry_label.value.strip(),
            content=self.entry_content.value.strip(),
            emoji=self.entry_emoji.value.strip() if self.entry_emoji.value else None
        )
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ {result.get('error', 'Failed to update entry')}",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="✅ Entry Updated",
            description=f"Entry **{self.entry_label.value}** has been updated!",
            color=0x00FF00
        )
        embed.add_field(
            name="⚠️ Note",
            value="Use `/faq publish` to refresh the published panel.",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
# FAQ COG
# ═══════════════════════════════════════════════════════════════════════════════

class FAQCog(commands.Cog):
    """Interactive FAQ/Reference System"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    async def cog_load(self):
        """Register persistent views on cog load"""
        # Get all published panels and register their views
        panels = await db.get_all_published_faq_panels()
        
        for panel in panels:
            entries = await db.get_faq_entries(panel["id"])
            if entries:
                view = FAQPanelView(panel["id"], entries)
                self.bot.add_view(view)
        
        print(f"Registered {len(panels)} persistent FAQ views")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # COMMAND GROUP
    # ═══════════════════════════════════════════════════════════════════════════
    
    faq_group = app_commands.Group(name="faq", description="FAQ/Reference system commands")
    entry_group = app_commands.Group(name="entry", description="Manage FAQ entries", parent=faq_group)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PANEL COMMANDS
    # ═══════════════════════════════════════════════════════════════════════════
    
    @faq_group.command(name="create", description="Create a new FAQ panel")
    @app_commands.default_permissions(administrator=True)
    async def faq_create(self, interaction: discord.Interaction):
        """Create a new FAQ panel"""
        modal = CreatePanelModal()
        await interaction.response.send_modal(modal)
    
    @faq_group.command(name="list", description="List all FAQ panels")
    @app_commands.default_permissions(administrator=True)
    async def faq_list(self, interaction: discord.Interaction):
        """List all FAQ panels in this server"""
        panels = await db.get_all_faq_panels(interaction.guild_id)
        
        if not panels:
            await interaction.response.send_message(
                "📭 No FAQ panels found. Use `/faq create` to create one!",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="📋 FAQ Panels",
            description=f"Found **{len(panels)}** panel(s)",
            color=0x3498DB
        )
        
        for panel in panels:
            status = "🟢 Published" if panel.get("message_id") else "⚪ Draft"
            entry_count = panel.get("entry_count", 0)
            
            embed.add_field(
                name=f"{status} {panel['name']}",
                value=f"**Title:** {panel['title']}\n"
                      f"**Entries:** {entry_count}\n"
                      f"**ID:** `{panel['id']}`",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @faq_group.command(name="edit", description="Edit a FAQ panel's settings")
    @app_commands.describe(panel_name="Name of the panel to edit")
    @app_commands.default_permissions(administrator=True)
    async def faq_edit(self, interaction: discord.Interaction, panel_name: str):
        """Edit a FAQ panel"""
        panel = await db.get_faq_panel_by_name(panel_name.lower(), interaction.guild_id)
        
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` not found!",
                ephemeral=True
            )
            return
        
        modal = EditPanelModal(panel)
        await interaction.response.send_modal(modal)
    
    @faq_group.command(name="delete", description="Delete a FAQ panel")
    @app_commands.describe(panel_name="Name of the panel to delete")
    @app_commands.default_permissions(administrator=True)
    async def faq_delete(self, interaction: discord.Interaction, panel_name: str):
        """Delete a FAQ panel"""
        panel = await db.get_faq_panel_by_name(panel_name.lower(), interaction.guild_id)
        
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` not found!",
                ephemeral=True
            )
            return
        
        # Delete from Discord if published
        if panel.get("message_id") and panel.get("channel_id"):
            try:
                channel = self.bot.get_channel(panel["channel_id"])
                if channel:
                    message = await channel.fetch_message(panel["message_id"])
                    await message.delete()
            except:
                pass
        
        result = await db.delete_faq_panel(panel["id"])
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ {result.get('error', 'Failed to delete panel')}",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            f"✅ Panel `{panel_name}` has been deleted!",
            ephemeral=True
        )
    
    @faq_group.command(name="publish", description="Publish or update a FAQ panel")
    @app_commands.describe(
        panel_name="Name of the panel to publish",
        channel="Channel to publish in (default: current channel)"
    )
    @app_commands.default_permissions(administrator=True)
    async def faq_publish(
        self,
        interaction: discord.Interaction,
        panel_name: str,
        channel: discord.TextChannel = None
    ):
        """Publish a FAQ panel to a channel"""
        target_channel = channel or interaction.channel
        
        panel = await db.get_faq_panel_by_name(panel_name.lower(), interaction.guild_id)
        
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` not found!",
                ephemeral=True
            )
            return
        
        entries = await db.get_faq_entries(panel["id"])
        
        if not entries:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` has no entries! Add entries first with `/faq entry add`.",
                ephemeral=True
            )
            return
        
        # Build embed
        embed = discord.Embed(
            title=panel["title"],
            description=panel.get("description") or "Select a topic from the dropdown below:",
            color=panel.get("color", 0x3498DB)
        )
        
        if panel.get("thumbnail_url"):
            embed.set_thumbnail(url=panel["thumbnail_url"])
        
        footer_text = panel.get("footer_text") or f"FAQ • {len(entries)} topics available"
        embed.set_footer(text=footer_text)
        
        # Build view
        view = FAQPanelView(panel["id"], entries, placeholder="📖 Select a topic...")
        
        # Send new message FIRST to ensure delivery
        message = await target_channel.send(embed=embed, view=view)
        
        # Old message is kept to allow multiple instances (as per request)
        # Note: Only the latest message ID is stored in DB for future 'edits', 
        # but all interactive views remain functional.
        
        # Update panel with message info
        await db.update_faq_panel_message(
            panel_id=panel["id"],
            message_id=message.id,
            channel_id=target_channel.id
        )
        
        # Register view for persistence
        self.bot.add_view(view)
        
        await interaction.response.send_message(
            f"✅ Panel `{panel_name}` published to {target_channel.mention}!",
            ephemeral=True
        )
    
    @faq_group.command(name="preview", description="Preview a FAQ panel before publishing")
    @app_commands.describe(panel_name="Name of the panel to preview")
    @app_commands.default_permissions(administrator=True)
    async def faq_preview(self, interaction: discord.Interaction, panel_name: str):
        """Preview a FAQ panel"""
        panel = await db.get_faq_panel_by_name(panel_name.lower(), interaction.guild_id)
        
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` not found!",
                ephemeral=True
            )
            return
        
        entries = await db.get_faq_entries(panel["id"])
        
        if not entries:
            await interaction.response.send_message(
                f"⚠️ Panel `{panel_name}` has no entries yet.",
                ephemeral=True
            )
            return
        
        # Build preview embed
        embed = discord.Embed(
            title=f"📋 Preview: {panel['title']}",
            description=panel.get("description") or "Select a topic from the dropdown below:",
            color=panel.get("color", 0x3498DB)
        )
        
        if panel.get("thumbnail_url"):
            embed.set_thumbnail(url=panel["thumbnail_url"])
        
        footer_text = panel.get("footer_text") or f"FAQ • {len(entries)} topics available"
        embed.set_footer(text=f"PREVIEW MODE • {footer_text}")
        
        # Build preview view (still functional)
        view = FAQPanelView(panel["id"], entries, placeholder="📖 Select a topic...")
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ENTRY COMMANDS
    # ═══════════════════════════════════════════════════════════════════════════
    
    @entry_group.command(name="add", description="Add an entry to a FAQ panel")
    @app_commands.describe(panel_name="Name of the panel to add entry to")
    @app_commands.default_permissions(administrator=True)
    async def entry_add(self, interaction: discord.Interaction, panel_name: str):
        """Add an entry to a FAQ panel"""
        panel = await db.get_faq_panel_by_name(panel_name.lower(), interaction.guild_id)
        
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` not found! Create it first with `/faq create`.",
                ephemeral=True
            )
            return
        
        modal = AddEntryModal(panel_name.lower())
        await interaction.response.send_modal(modal)
    
    @entry_group.command(name="list", description="List entries in a FAQ panel")
    @app_commands.describe(panel_name="Name of the panel")
    @app_commands.default_permissions(administrator=True)
    async def entry_list(self, interaction: discord.Interaction, panel_name: str):
        """List entries in a FAQ panel"""
        panel = await db.get_faq_panel_by_name(panel_name.lower(), interaction.guild_id)
        
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` not found!",
                ephemeral=True
            )
            return
        
        entries = await db.get_faq_entries(panel["id"])
        
        if not entries:
            await interaction.response.send_message(
                f"📭 Panel `{panel_name}` has no entries. Use `/faq entry add` to add some!",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title=f"📋 Entries in `{panel_name}`",
            description=f"Found **{len(entries)}** entry(ies)",
            color=0x3498DB
        )
        
        for i, entry in enumerate(entries, 1):
            emoji = entry.get("emoji", "📄")
            content_preview = entry["content"][:100] + "..." if len(entry["content"]) > 100 else entry["content"]
            
            embed.add_field(
                name=f"{i}. {emoji} {entry['label']}",
                value=f"```\n{content_preview}\n```\n**ID:** `{entry['id']}`",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @entry_group.command(name="edit", description="Edit a FAQ entry")
    @app_commands.describe(entry_id="ID of the entry to edit")
    @app_commands.default_permissions(administrator=True)
    async def entry_edit(self, interaction: discord.Interaction, entry_id: int):
        """Edit a FAQ entry"""
        entry = await db.get_faq_entry(entry_id)
        
        if not entry:
            await interaction.response.send_message(
                f"❌ Entry with ID `{entry_id}` not found!",
                ephemeral=True
            )
            return
        
        # Verify guild ownership
        panel = await db.get_faq_panel_by_id(entry["panel_id"])
        if not panel or panel.get("guild_id") != interaction.guild_id:
            await interaction.response.send_message(
                "❌ Entry not found in this server!",
                ephemeral=True
            )
            return
        
        modal = EditEntryModal(entry)
        await interaction.response.send_modal(modal)
    
    @entry_group.command(name="delete", description="Delete a FAQ entry")
    @app_commands.describe(entry_id="ID of the entry to delete")
    @app_commands.default_permissions(administrator=True)
    async def entry_delete(self, interaction: discord.Interaction, entry_id: int):
        """Delete a FAQ entry"""
        entry = await db.get_faq_entry(entry_id)
        
        if not entry:
            await interaction.response.send_message(
                f"❌ Entry with ID `{entry_id}` not found!",
                ephemeral=True
            )
            return
        
        # Verify guild ownership
        panel = await db.get_faq_panel_by_id(entry["panel_id"])
        if not panel or panel.get("guild_id") != interaction.guild_id:
            await interaction.response.send_message(
                "❌ Entry not found in this server!",
                ephemeral=True
            )
            return
        
        result = await db.delete_faq_entry(entry_id)
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ {result.get('error', 'Failed to delete entry')}",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="✅ Entry Deleted",
            description=f"Entry **{entry['label']}** has been deleted!",
            color=0x00FF00
        )
        embed.add_field(
            name="⚠️ Note",
            value="Use `/faq publish` to update the published panel.",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @entry_group.command(name="reorder", description="Reorder FAQ entries")
    @app_commands.describe(
        panel_name="Name of the panel",
        entry_id="ID of the entry to move",
        new_position="New position (1-based)"
    )
    @app_commands.default_permissions(administrator=True)
    async def entry_reorder(
        self,
        interaction: discord.Interaction,
        panel_name: str,
        entry_id: int,
        new_position: int
    ):
        """Reorder FAQ entries"""
        panel = await db.get_faq_panel_by_name(panel_name.lower(), interaction.guild_id)
        
        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{panel_name}` not found!",
                ephemeral=True
            )
            return
        
        result = await db.reorder_faq_entry(entry_id, new_position - 1)  # Convert to 0-based
        
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ {result.get('error', 'Failed to reorder entry')}",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            f"✅ Entry moved to position {new_position}! Use `/faq publish` to update the published panel.",
            ephemeral=True
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # AUTOCOMPLETE
    # ═══════════════════════════════════════════════════════════════════════════
    
    @faq_edit.autocomplete("panel_name")
    @faq_delete.autocomplete("panel_name")
    @faq_publish.autocomplete("panel_name")
    @faq_preview.autocomplete("panel_name")
    @entry_add.autocomplete("panel_name")
    @entry_list.autocomplete("panel_name")
    @entry_reorder.autocomplete("panel_name")
    async def panel_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for panel names"""
        panels = await db.get_all_faq_panels(interaction.guild_id)
        
        choices = []
        for panel in panels:
            if current.lower() in panel["name"].lower():
                choices.append(app_commands.Choice(
                    name=f"{panel['name']} - {panel['title'][:40]}",
                    value=panel["name"]
                ))
        
        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(FAQCog(bot))

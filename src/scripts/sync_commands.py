"""
Emergency command sync script
Use this to restore commands after they were cleared
"""

import asyncio
import discord
from discord.ext import commands
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# Load environment variables
load_dotenv()

# Load config
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = config.get("guild_id")

if not TOKEN:
    print("❌ Error: DISCORD_TOKEN not found in environment variables!")
    print("Make sure you have a .env file with DISCORD_TOKEN=your_token")
    exit(1)

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def load_and_sync():
    async with bot:
        # Load all cogs
        cogs = [
            "src.cogs.economy",
            "src.cogs.profile",
            "src.cogs.games",
            "src.cogs.marketplace",
            "src.cogs.officer",
            "src.cogs.admin",
        ]
        
        for cog in cogs:
            try:
                await bot.load_extension(cog)
                print(f"✅ Loaded: {cog}")
            except Exception as e:
                print(f"❌ Failed: {cog} - {e}")
        
        @bot.event
        async def on_ready():
            print(f"\n🤖 Logged in as {bot.user}")
            
            try:
                if GUILD_ID:
                    guild = discord.Object(id=GUILD_ID)
                    # Copy all global commands to guild
                    bot.tree.copy_global_to(guild=guild)
                    synced = await bot.tree.sync(guild=guild)
                    print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")
                else:
                    synced = await bot.tree.sync()
                    print(f"✅ Synced {len(synced)} commands globally")
                
                print("\n📋 Commands registered:")
                for cmd in synced:
                    print(f"   /{cmd.name}")
                
            except Exception as e:
                print(f"❌ Sync error: {e}")
            
            print("\n✅ Done! You can now restart the main bot.")
            await bot.close()
        
        await bot.start(TOKEN)


if __name__ == "__main__":
    print("🔄 Emergency Command Sync Tool")
    print("=" * 40)
    asyncio.run(load_and_sync())

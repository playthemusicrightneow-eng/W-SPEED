import os
import discord
from discord.ext import commands
import asyncio
import traceback

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

async def load_extensions():
    try:
        await bot.load_extension("commands")
        print("✅ commands.py loaded")
    except Exception:
        traceback.print_exc()

async def main():
    async with bot:
        await load_extensions()
        await bot.start(os.getenv("DISCORD_BOT_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())

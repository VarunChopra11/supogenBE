import logging
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import os
from api.v1.services.discord_services.discord_auth import (
    authenticate_server, 
    ServerAlreadyRegisteredError,
    TokenAlreadyUsedError,
    UserNotFoundError,
    InvalidTokenError,
    DatabaseError,
    AuthenticationError
)

load_dotenv(override=True)
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logging.info(f"✅ Synced {len(synced)} slash command(s).")
    except Exception as e:
        logging.error(f"❌ Failed to sync commands: {e}")


# --- /Authenticate Command for Bot-Server Mapping ---
@bot.tree.command(name="authenticate", description="Authenticate server to bot")
@app_commands.describe(token="Your JWT token")
async def authenticate(interaction: discord.Interaction, token: str):
    await interaction.response.defer(ephemeral=True)
    
    # Get server (guild) and permission information
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command can only be used in a server (guild) context.", ephemeral=True)
        return

    bot_member = guild.me
    owner = guild.owner or await bot.fetch_user(guild.owner_id)

    auth_data = {
        "token": token,
        "server_id": str(guild.id),
        "server_name": guild.name,
        "owner_id": str(owner.id),
        "owner_username": owner.name,
        "member_count": guild.member_count,
        "bot_permissions": {
            "permissions_value": interaction.app_permissions.value if interaction.app_permissions else None,
            "is_authenticated": False,  # Will be set to True upon successful authentication
            "admin": bot_member.guild_permissions.administrator if bot_member else False,
        }
    }

    logging.info(f"Authentication attempt for server: {guild.name} (ID: {guild.id})")

    try:
        authenticated: bool = await authenticate_server(auth_data)
        if authenticated:
            await interaction.followup.send(
                "✅ Authentication successful! The bot is now linked to your Discord server.", 
                ephemeral=True
            )
        else:
            await interaction.followup.send("❌ Authentication failed due to an unknown error.", ephemeral=True)
    
    except ServerAlreadyRegisteredError as e:
        logging.warning(f"Server already registered: {e}")
        await interaction.followup.send("❌ This server is already registered with the bot. Please contact support if this is an error.", ephemeral=True)
    
    except TokenAlreadyUsedError as e:
        logging.warning(f"Token already used: {e}")
        await interaction.followup.send("❌ This token has already been used. Please generate a new token from the web dashboard.", ephemeral=True)
    
    except UserNotFoundError as e:
        logging.warning(f"User not found: {e}")
        await interaction.followup.send("❌ User account not found. Please make sure you're using a valid token from your account.", ephemeral=True)
    
    except InvalidTokenError as e:
        logging.warning(f"Invalid token: {e}")
        await interaction.followup.send("❌ Invalid or expired token. Please generate a new token from the web dashboard.", ephemeral=True)
    
    except DatabaseError as e:
        logging.error(f"Database error during authentication: {e}")
        await interaction.followup.send("❌ Database connection error. Please try again later.", ephemeral=True)
    
    except AuthenticationError as e:
        logging.error(f"Authentication error: {e}")
        await interaction.followup.send(f"❌ Authentication failed: {str(e)}", ephemeral=True)
    
    except Exception as e:
        logging.error(f"Unexpected error during authentication: {e}")
        await interaction.followup.send("❌ An unexpected error occurred. Please try again later.", ephemeral=True)


async def run_discord_bot_async():
    """Start the Discord bot within an existing asyncio event loop.

    Using bot.start avoids creating a separate event loop/thread so that
    awaits inside command handlers (e.g., Motor/Mongo calls) run on the
    same loop as the rest of the app, preventing cross-loop Future errors.
    """
    if not TOKEN:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN in .env")
    await bot.start(TOKEN)
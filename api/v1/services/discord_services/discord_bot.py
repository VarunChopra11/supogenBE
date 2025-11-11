import logging
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import os

import asyncio
from api.v1.services.discord_services.discord import (
    authenticate_server, 
    ServerAlreadyRegisteredError,
    TokenAlreadyUsedError,
    UserNotFoundError,
    InvalidTokenError,
    DatabaseError,
    AuthenticationError,
    send_message,
)

from api.v1.db.session import DatabaseSession

load_dotenv(override=True)
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

def message_to_dict(message: discord.Message):
    return {
        "id": message.id,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "channel": {
            "id": message.channel.id,
            "name": getattr(message.channel, "name", None),
            "type": str(message.channel.type),
        },
        "author": {
            "id": message.author.id,
            "name": message.author.name,
            "global_name": getattr(message.author, "global_name", None),
            "display_name": message.author.display_name,
            "bot": message.author.bot,
        },
        "guild": {
            "id": message.guild.id if message.guild else None,
            "name": message.guild.name if message.guild else None,
            "member_count": message.guild.member_count if message.guild else None,
        } if message.guild else None,
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "size": a.size,
                "url": a.url,
                "content_type": a.content_type,
            }
            for a in message.attachments
        ],
        "mentions": [m.id for m in message.mentions],
        "role_mentions": [r.id for r in message.role_mentions],
        "type": str(message.type),
        "flags": message.flags.value,
    }

@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logging.info(f"✅ Synced {len(synced)} slash command(s).")
    except Exception as e:
        logging.error(f"❌ Failed to sync commands: {e}")


@bot.event
async def on_message(message: discord.Message):
    
    if message.author.bot:
        return

    if (
        bot.user not in message.mentions
        and not (message.reference and message.reference.resolved and message.reference.resolved.author.id == bot.user.id)
        and not (isinstance(message.channel, discord.Thread) and message.channel.owner_id == bot.user.id)
    ):
        return

    content = message.content.replace(f"<@{bot.user.id}>", "").strip()
    if not content:
        await message.reply("👋 Hi! Mention me with a message to chat.")
        return
    
    try:
        db = DatabaseSession.get_db()

        server_id = str(message.guild.id) if message.guild else None

        # Search server for user_id
        server = await db["discord_servers"].find_one({"server_id": server_id}) if server_id else None
        if not server:
            await message.reply(
                "❌ This server is not authenticated. Please ask the server admin to authenticate the bot using the `/authenticate` command."
            )
            return
        
        user_id = server.get("user_id") if server else None
        if not user_id:
            await message.reply("❌ Unable to identify server owner. Please contact support.")
            return
        
        async with message.channel.typing():
            # Determine thread_id and channel_id for chat history
            thread_id = None
            channel_id = str(message.channel.id)
            created_thread = None
            
            if isinstance(message.channel, discord.Thread):
                thread_id = str(message.channel.id)
                # For threads, the parent channel is different from the thread itself
                if hasattr(message.channel, 'parent_id') and message.channel.parent_id:
                    channel_id = str(message.channel.parent_id)
            else:
                # Not in a thread - create one BEFORE processing to get thread_id
                try:
                    created_thread = await message.create_thread(
                        name=f"Chat Thread {message.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    thread_id = str(created_thread.id)
                    channel_id = str(message.channel.id)
                    logging.info(f"Created new thread {thread_id} for message {message.id}")
                except discord.HTTPException as e:
                    if e.code == 160004:  # Thread already exists
                        logging.info(f"Thread already exists for message {message.id}")
                    else:
                        logging.warning(f"Failed to create thread (code: {e.code}): {e}")
            
            response = await asyncio.wait_for(
                send_message(
                    [{"type": "text", "text": content}], 
                    user_id=user_id, 
                    server_id=server_id,
                    thread_id=thread_id,
                    channel_id=channel_id,
                ),
                timeout=30,
            )

        if not response or not isinstance(response, str):
            response = "⚠️ Sorry, I couldn't process that."

        # Add info message at the end of bot response
        response += "\n\n💡 *React to let us know if the bot resolved your query or not.*"

        # Send response and add reactions
        bot_reply = None
        if isinstance(message.channel, discord.Thread):
            bot_reply = await message.reply(response)
        elif created_thread:
            bot_reply = await created_thread.send(response)
        else:
            bot_reply = await message.reply(response)

        # Add thumbs up/down reactions
        if bot_reply:
            try:
                await bot_reply.add_reaction("👍")
                await bot_reply.add_reaction("👎")
            except Exception as e:
                logging.warning(f"Failed to add reactions: {e}")

    except asyncio.TimeoutError:
        await message.reply("⏱️ The model took too long to respond.")
    except Exception as e:
        logging.error(f"Error handling message: {e}", exc_info=True)
        await message.reply("❌ Something went wrong while processing your request.")

    await bot.process_commands(message)


@bot.event
async def on_reaction_add(reaction, user):
    """Handle thumbs up/down reactions on bot messages."""
    if user.bot:
        return

    message = reaction.message
    if message.author.id != bot.user.id:
        return  # Only track reactions on bot's own messages

    if str(reaction.emoji) == "👍":
        await message.channel.send(f"✅ Glad it helped, {user.mention}!")
    elif str(reaction.emoji) == "👎":
        await message.channel.send(f"❌ Sorry it didn't help, {user.mention}. We'll try to improve!")


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
                "✅ Authentication successful! The bot is now linked to your Discord server.", ephemeral=True
            )
        else:
            await interaction.followup.send("❌ Authentication failed due to an unknown error.", ephemeral=True)
    
    except ServerAlreadyRegisteredError as e:
        logging.warning(f"Server already registered: {e}")
        await interaction.followup.send(
            "❌ This server is already registered with the bot. Please contact support if this is an error.", ephemeral=True
        )
    except TokenAlreadyUsedError as e:
        logging.warning(f"Token already used: {e}")
        await interaction.followup.send(
            "❌ This token has already been used. Please generate a new token from the web dashboard.", ephemeral=True
        )
    except UserNotFoundError as e:
        logging.warning(f"User not found: {e}")
        await interaction.followup.send(
            "❌ User account not found. Please make sure you're using a valid token from your account.", ephemeral=True
        )
    except InvalidTokenError as e:
        logging.warning(f"Invalid token: {e}")
        await interaction.followup.send(
            "❌ Invalid or expired token. Please generate a new token from the web dashboard.", ephemeral=True
        )
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
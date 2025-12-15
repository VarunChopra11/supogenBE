import logging
import discord
from discord.ext import commands
from discord import app_commands, ChannelType
from dotenv import load_dotenv
import os

import asyncio
from api.v1.utils.exceptions import (
    AuthenticationError,
    ServerAlreadyRegisteredError,
    TokenAlreadyUsedError,
    UserNotFoundError,
    InvalidTokenError,
    DatabaseError,
)
from api.v1.services.discord_services.discord import (
    authenticate_server,
    send_message,
    refresh_forums_list,
    remove_forum_from_selected,
    track_forum_message,
    fetch_forum_tags_from_guild,
    sync_forum_tags,
)
from api.v1.services.discord_services.tags import auto_tag_forum_thread
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

    # Check if bot should respond
    if (
        bot.user not in message.mentions
        and not (message.reference and message.reference.resolved and message.reference.resolved.author.id == bot.user.id)
        and not (isinstance(message.channel, discord.Thread) and message.channel.owner_id == bot.user.id)
    ):
        # Message doesn't need bot response, track forum message if applicable
        try:
            db = DatabaseSession.get_db()
            server_id = str(message.guild.id) if message.guild else None
            server = await db["discord_servers"].find_one({"server_id": server_id}) if server_id else None
            
            if server:
                await track_forum_message(message, server, db)
        except Exception as e:
            logging.error(f"Error tracking forum message in non-response flow: {e}", exc_info=True)
        
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

    # Determine the thread_id based on the channel type
    thread_id = None
    if isinstance(message.channel, discord.Thread):
        thread_id = str(message.channel.id)
    elif message.reference and message.reference.message_id:
        # If this is a reply, there might be a thread created
        try:
            # Try to find if a thread was created from the referenced message
            original_message = await message.channel.fetch_message(message.reference.message_id)
            if hasattr(original_message, 'thread') and original_message.thread:
                thread_id = str(original_message.thread.id)
        except Exception:
            pass

    # Handle resolution status based on reaction
    if str(reaction.emoji) == "👍":
        if thread_id:
            try:
                from api.v1.services.chats import chat_service
                success = await chat_service.mark_discord_chat_resolved(thread_id=thread_id, is_resolved=True)
                if success:
                    logging.info(f"✅ Marked thread {thread_id} as resolved (thumbs up)")
                    await message.channel.send(f"✅ Glad it helped, {user.mention}! This query has been marked as resolved.")
                else:
                    await message.channel.send(f"✅ Glad it helped, {user.mention}!")
            except Exception as e:
                logging.error(f"Error marking chat as resolved: {e}", exc_info=True)
                await message.channel.send(f"✅ Glad it helped, {user.mention}!")
        else:
            await message.channel.send(f"✅ Glad it helped, {user.mention}!")
            
    elif str(reaction.emoji) == "👎":
        if thread_id:
            try:
                from api.v1.services.chats import chat_service
                success = await chat_service.mark_discord_chat_resolved(thread_id=thread_id, is_resolved=False)
                if success:
                    logging.info(f"❌ Marked thread {thread_id} as pending (thumbs down)")
                    await message.channel.send(f"❌ Sorry it didn't help, {user.mention}. We'll try to improve! This query has been marked as pending.")
                else:
                    await message.channel.send(f"❌ Sorry it didn't help, {user.mention}. We'll try to improve!")
            except Exception as e:
                logging.error(f"Error marking chat as pending: {e}", exc_info=True)
                await message.channel.send(f"❌ Sorry it didn't help, {user.mention}. We'll try to improve!")
        else:
            await message.channel.send(f"❌ Sorry it didn't help, {user.mention}. We'll try to improve!")


@bot.event
async def on_thread_create(thread):
    """
    Handle forum thread creation events. Automatically categorizes and tags new forum posts.
    
    This event is triggered when a new thread is created in a forum channel.
    """
    await auto_tag_forum_thread(thread)


@bot.event
async def on_guild_channel_create(channel):
    """
    Handle channel creation events. Refreshes the forums list and syncs tags 
    when a forum channel is created.
    """
    try:
        # Only process if it's a forum channel
        if channel.type != ChannelType.forum:
            return
        
        guild = channel.guild
        if not guild:
            return
        
        server_id = str(guild.id)
        
        # Refresh the complete forums list
        refresh_success = await refresh_forums_list(server_id, guild)
        
        # Sync tags (new forum may have tags)
        tags_sync_success = await sync_forum_tags(server_id, guild)
        
        if refresh_success:
            logging.info(f"✅ Refreshed forums list for server {server_id} after channel creation: {channel.name}")
        else:
            logging.warning(f"⚠️ Failed to refresh forums list for server {server_id}")
            
        if tags_sync_success:
            logging.info(f"✅ Synced forum tags for server {server_id} after channel creation")
            
    except Exception as e:
        logging.error(f"Error handling channel creation: {e}", exc_info=True)


@bot.event
async def on_guild_channel_delete(channel):
    """
    Handle channel deletion events. Refreshes the forums list and removes the forum 
    from selected_forums if it was a forum channel.
    """
    try:
        # Only process if it's a forum channel
        if channel.type != ChannelType.forum:
            return
        
        guild = channel.guild
        if not guild:
            return
        
        server_id = str(guild.id)
        forum_id = str(channel.id)
        
        # Refresh the complete forums list
        refresh_success = await refresh_forums_list(server_id, guild)
        
        # Remove from selected_forums if present
        remove_success = await remove_forum_from_selected(server_id, forum_id)
        
        # Sync tags after forum deletion (tags may have been removed)
        tags_sync_success = await sync_forum_tags(server_id, guild)
        
        if refresh_success:
            logging.info(f"✅ Refreshed forums list for server {server_id} after channel deletion: {channel.name}")
        else:
            logging.warning(f"⚠️ Failed to refresh forums list for server {server_id}")
            
        if remove_success:
            logging.info(f"✅ Removed forum {forum_id} from selected_forums for server {server_id}")
            
        if tags_sync_success:
            logging.info(f"✅ Synced forum tags for server {server_id} after channel deletion")
            
    except Exception as e:
        logging.error(f"Error handling channel deletion: {e}", exc_info=True)


@bot.event
async def on_guild_channel_update(before, after):
    """
    Handle channel update events. Syncs forum tags when they are added, removed, or modified
    in forum channels.
    
    This event is triggered when any channel property changes, including:
    - Forum channel tags being added or removed
    - Tag names, emojis, or moderation status being updated
    - Any other channel property changes
    """
    try:
        # Only process if it's a forum channel
        if after.type != ChannelType.forum:
            return
        
        guild = after.guild
        if not guild:
            return
        
        server_id = str(guild.id)
        
        # Check if the server is registered
        db = DatabaseSession.get_db()
        if db is None:
            logging.warning("Database connection is None")
            return
            
        server = await db["discord_servers"].find_one({"server_id": server_id})
        if not server:
            # Server not registered, no need to sync
            return
        
        # Check if forum tags have changed by comparing available_tags
        before_tags = set()
        after_tags = set()
        tags_changed = False
        
        if hasattr(before, 'available_tags') and before.available_tags:
            for tag in before.available_tags:
                before_tags.add((str(tag.id), tag.name, str(tag.emoji) if tag.emoji else None, tag.moderated))
        
        if hasattr(after, 'available_tags') and after.available_tags:
            for tag in after.available_tags:
                after_tags.add((str(tag.id), tag.name, str(tag.emoji) if tag.emoji else None, tag.moderated))
        
        # Determine if tags have changed
        if before_tags != after_tags:
            tags_changed = True
            
            # Log the changes
            added_tags = after_tags - before_tags
            removed_tags = before_tags - after_tags
            
            if added_tags:
                logging.info(f"📌 Forum tags added in {after.name} (Server: {server_id}): {[tag[1] for tag in added_tags]}")
            if removed_tags:
                logging.info(f"🗑️ Forum tags removed from {after.name} (Server: {server_id}): {[tag[1] for tag in removed_tags]}")
        
        # Sync tags if they changed
        if tags_changed:
            success = await sync_forum_tags(server_id, guild)
            if success:
                logging.info(f"✅ Successfully synced forum tags for server {server_id} after update to {after.name}")
            else:
                logging.warning(f"⚠️ Failed to sync forum tags for server {server_id}")
                
    except Exception as e:
        logging.error(f"Error handling channel update: {e}", exc_info=True)


# --- /Authenticate Command for Bot-Server Mapping ---
@bot.tree.command(name="authenticate", description="Authenticate server to bot")
@app_commands.describe(token="Your secret token")
async def authenticate(interaction: discord.Interaction, token: str):
    await interaction.response.defer(ephemeral=True)
    
    # Get server (guild) and permission information
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command can only be used in a server (guild) context.", ephemeral=True)
        return

    bot_member = guild.me
    owner = guild.owner or await bot.fetch_user(guild.owner_id)

    forums = []
    for channel in guild.channels:
        if channel.type == ChannelType.forum:
            forums.append({
                "forum_id": str(channel.id),
                "forum_name": channel.name,
            })

    # Fetch all forum tags from the guild
    tags = await fetch_forum_tags_from_guild(guild)

    auth_data = {
        "token": token,
        "server_id": str(guild.id),
        "server_name": guild.name,
        "owner_id": str(owner.id),
        "owner_username": owner.name,
        "member_count": guild.member_count,
        "forums": forums,
        "selected_forums": [],
        "tags": tags,  # Include forum tags
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
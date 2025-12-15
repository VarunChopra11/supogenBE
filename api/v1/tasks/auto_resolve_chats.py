"""
Background task to auto-resolve old Discord chats.

This task runs daily at 12:00 AM (midnight) and marks all Discord chats
as resolved if they haven't been updated in 4 days.
"""
import logging
import asyncio
from datetime import datetime, time, timedelta, timezone
from api.v1.services.chats import chat_service
from api.v1.services.forum_chats import forum_chat_service

logger = logging.getLogger(__name__)


async def auto_resolve_task():
    """
    Background task that auto-resolves Discord chats older than 4 days.
    Runs continuously and executes at midnight (00:00) every day.
    """
    logger.info("🕐 Auto-resolve task started")
    
    while True:
        try:
            # Calculate time until next midnight
            now = datetime.now(timezone.utc)
            target_time = datetime.combine(
                now.date() + timedelta(days=1),
                time(0, 0, 0),
                tzinfo=timezone.utc
            )
            
            # If it's already past midnight today, schedule for midnight tomorrow
            if now.time() >= time(0, 0, 0):
                sleep_seconds = (target_time - now).total_seconds()
            else:
                # Schedule for today's midnight
                target_time = datetime.combine(
                    now.date(),
                    time(0, 0, 0),
                    tzinfo=timezone.utc
                )
                sleep_seconds = (target_time - now).total_seconds()
                
                # If the result is negative, schedule for next midnight
                if sleep_seconds < 0:
                    target_time = datetime.combine(
                        now.date() + timedelta(days=1),
                        time(0, 0, 0),
                        tzinfo=timezone.utc
                    )
                    sleep_seconds = (target_time - now).total_seconds()
            
            logger.info(f"⏰ Next auto-resolve scheduled for {target_time.isoformat()} (in {sleep_seconds/3600:.2f} hours)")
            
            # Wait until midnight
            await asyncio.sleep(sleep_seconds)
            
            # Execute auto-resolve
            logger.info("🔄 Running auto-resolve for old Discord chats...")
            resolved_count = await chat_service.auto_resolve_old_chats(days_threshold=4)
            logger.info(f"✅ Auto-resolved {resolved_count} Discord chat(s)")

            try:
                stale_chats = await forum_chat_service.get_stale_forum_chats(days_threshold=4)
                
                if not stale_chats:
                    logger.info("✅ No stale forum chats found")
                    continue
                
                logger.info(f"📋 Found {len(stale_chats)} stale forum chat(s) to process")
                
                results = {
                    "total": len(stale_chats),
                    "resolved": 0,
                    "not_resolved": 0,
                    "saved_to_rag": 0,
                    "errors": 0
                }
                
                for chat in stale_chats:
                    result = await forum_chat_service.process_forum_chat(chat)
                    
                    # Update statistics
                    if result["status"] == "resolved":
                        results["resolved"] += 1
                    elif result["status"] == "not_resolved":
                        results["not_resolved"] += 1
                    elif result["status"] in ["error", "partial"]:
                        results["errors"] += 1
                    
                    if "saved_to_rag" in result.get("action_taken", []):
                        results["saved_to_rag"] += 1
                    
                    # Small delay to avoid overwhelming the system
                    await asyncio.sleep(0.5)
                
                # Log summary
                logger.info(
                    f"✅ Auto-resolve forum chats completed:\n"
                    f"   Total processed: {results['total']}\n"
                    f"   Resolved & deleted: {results['resolved']}\n"
                    f"   Not resolved (kept): {results['not_resolved']}\n"
                    f"   Saved to RAG: {results['saved_to_rag']}\n"
                    f"   Errors: {results['errors']}"
                )
                
            except Exception as e:
                logger.error(f"❌ Error during forum auto-resolve execution: {e}", exc_info=True)
            
            
        except Exception as e:
            logger.error(f"❌ Error in auto-resolve task: {e}", exc_info=True)
            # Wait 1 hour before retrying on error
            await asyncio.sleep(3600)


async def start_auto_resolve_task():
    """Start the auto-resolve background task."""
    asyncio.create_task(auto_resolve_task())
    logger.info("✅ Auto-resolve background task initialized")

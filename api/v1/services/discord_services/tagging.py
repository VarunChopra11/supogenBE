import asyncio
import requests
from api.v1.db.session import DatabaseSession
from pydantic import BaseModel
from typing import List , Dict , Optional
from api.v1.services.embed import get_openai_chat_completion
from fastapi import HTTPException, Request
class ApplyModel(BaseModel):
    thread_id: str = None
    thread_title: str = None
    thread_desc: Optional[str] = None
    guild_id: str = None
    token:str =None
    
async def get_tags_discord(guild_id:str , discord_token:str):
    db = DatabaseSession.get_db()
    # ---- DISCORD TAGS ----
    discord_url = f"https://discord.com/api/v10/guilds/{guild_id}/channels"
    discord_res = await request_async(
        "GET",
        discord_url,
        headers={"Authorization": f"Bot {discord_token}"}
    )

    if discord_res.status_code != 200:
        raise HTTPException(500, "Failed to fetch Discord channels")

    forum_tags = {}

    for ch in discord_res.json():
        if ch.get("available_tags"):
            for tag in ch["available_tags"]:
                forum_tags[tag["id"]] = tag["name"]
    result = await db["discord_servers"].update_one(
        {"server_id": guild_id},          
        {"$set": {"server_tags": forum_tags}}
            )
    return result



async def apply_tags(data: ApplyModel):
    final_chunk=[]
    chunk=""
    db = DatabaseSession.get_db()
    result = await db["discord_servers"].find_one(
        {"server_id": data.guild_id}
            )
    url = f"https://discord.com/api/v10/channels/{data.thread_id}"
    

    prompt = f"You are a classifier agent I will provide you a thread content title and description you have to classify it in given labels {result["server_tags"]}  thread title -> {data.thread_title}  thread description -> {data.thread_desc} only give output of final one label id like this label_id"
    
    stream =  get_openai_chat_completion(prompt)
    async for particle in stream:
        chunk += particle
    final_chunk.append(chunk)
        
    res = await request_async(
            "PATCH",
            url,
            json={"applied_tags": final_chunk},
            headers={"Authorization": f"Bot {data.token}"}
        )

    if res.status_code != 200:
            raise HTTPException(500, f"Discord error: {res.text}")

    return {"status": "Discord tags applied"}

    raise HTTPException(400, "Invalid platform")


async def request_async(method: str, url: str, **kwargs):
    return await asyncio.to_thread(lambda: requests.request(method, url, **kwargs))

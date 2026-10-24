import asyncio
import json
from app.services.elevenlabs_service import list_recent_conversations, get_conversation

async def run():
    recent = await list_recent_conversations(page_size=3)
    for c in recent:
        cid = c.get("conversation_id")
        conv = await get_conversation(cid)
        analysis = conv.get("analysis", {})
        dcr = analysis.get("data_collection_results", {})
        
        print(f"--- Conversation {cid} ---")
        print("Data Collection Results (RAW):")
        print(json.dumps(dcr, indent=2))

asyncio.run(run())

import asyncio
import json
from app.services.elevenlabs_service import list_recent_conversations, get_conversation

async def test():
    try:
        convos = await list_recent_conversations(page_size=1)
        if not convos:
            print("No recent conversations found.")
            return
        
        latest_id = convos[0].get("conversation_id")
        latest = await get_conversation(latest_id)
        
        print("Latest Conversation ID:", latest_id)
        print("Duration (s):", latest.get("metadata", {}).get("call_duration_secs"))
        print("Termination Reason:", latest.get("metadata", {}).get("termination_reason"))
        print("Status:", latest.get("status"))
        
        print("\nTranscript:")
        transcript = latest.get("transcript", [])
        if isinstance(transcript, list):
            for t in transcript:
                print(f"[{t.get('role')}]: {t.get('message')}")
        else:
            print(transcript)
            
    except Exception as e:
        print("Error fetching recent conversation:", e)

asyncio.run(test())

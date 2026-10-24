import asyncio
import httpx
from app.core.config import settings

async def test():
    # Try the new endpoint with the user's payload
    url = "https://api.elevenlabs.io/v1/convai/phone/create-outbound-call"
    headers = {"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"}
    payload = {
        "agent_id": settings.elevenlabs_agent_id,
        "phone_number": "+918431362088",
        "dynamic_variables": {"reason": "testing new api"}
    }
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=payload, headers=headers)
        print("Status", res.status_code)
        print("Body", res.text)
        
asyncio.run(test())

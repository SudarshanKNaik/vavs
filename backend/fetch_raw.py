import asyncio
from app.services.elevenlabs_service import get_conversation
import json

async def run():
    res = await get_conversation("conv_1301kmf4enyyf11rvrbfxsxv26rc")
    analysis = res.get("analysis", {})
    print(json.dumps(analysis, indent=2))

asyncio.run(run())

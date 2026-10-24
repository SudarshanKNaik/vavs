import asyncio
from app.services.elevenlabs_service import get_conversation

async def test():
    try:
        res = await get_conversation("conv_3201kmb93tpwf5maydbt13ke3kt9")
        print("ElevenLabs Convo!", res)
    except Exception as e:
        print("ElevenLabs Error!", e)

asyncio.run(test())

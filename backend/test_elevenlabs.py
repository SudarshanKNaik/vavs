import asyncio
from app.services.elevenlabs_service import initiate_outbound_call
from app.core.config import settings

async def test():
    try:
        res = await initiate_outbound_call(
            patient_phone="8431362088", 
            patient_name="Test",
            doctor_name="Doctor",
        )
        print("ElevenLabs Success! Response:", res)
    except Exception as e:
        print("ElevenLabs Error!", e)

asyncio.run(test())

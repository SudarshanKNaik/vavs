from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = ""

    # Twilio (optional — only needed for Call Patient action)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # ElevenLabs Conversational AI
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_phone_number_id: str = ""
    elevenlabs_webhook_secret: str = ""  # wsec_... from ElevenLabs dashboard

    # SMTP email delivery (OTP + notifications)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""

    # Google Calendar direct API token
    google_calendar_access_token: str = ""

    # Gemini extraction (Vision + text fallback)
    google_gemini_api_key: str = ""
    google_gemini_model: str = "gemini-2.0-flash"

    # OpenRouter workflow AI builder
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-v3.2"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Deepgram speech-to-text
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"

    # App
    app_base_url: str = "http://localhost:8000"
    clinic_timezone: str = "Asia/Kolkata"

    # Follow-up cron scheduler
    follow_up_cron_enabled: bool = True
    follow_up_cron_delay_minutes: int = 1
    follow_up_cron_poll_interval_seconds: int = 15
    follow_up_cron_max_attempts: int = 3
    follow_up_cron_batch_size: int = 10


settings = Settings()
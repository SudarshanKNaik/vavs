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
    elevenlabs_blood_agent_id: str = ""  # optional; blood campaigns fall back to elevenlabs_agent_id
    # Shared secret ElevenLabs sends (X-Tool-Secret header) when the agent calls
    # our live slot tools mid-call. The tool endpoints refuse requests without it.
    elevenlabs_tool_secret: str = ""

    # SMTP email delivery (OTP + notifications)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""

    # Google Calendar direct API token
    google_calendar_access_token: str = ""

    # Google Calendar via OAuth: each doctor connects their own calendar.
    # Create a "Web application" OAuth client in Google Cloud and register
    # google_oauth_redirect_uri as an authorized redirect URI.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/google/oauth/callback"
    # Where the browser lands after connecting (the doctor's Settings page).
    frontend_base_url: str = "http://localhost:3000"

    # Video consultations (browser-to-browser WebRTC). STUN finds a direct
    # route; a TURN relay is only needed on networks that block direct
    # connections. Leave TURN empty to use STUN only.
    webrtc_stun_urls: str = "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302"
    webrtc_turn_url: str = ""
    webrtc_turn_username: str = ""
    webrtc_turn_credential: str = ""

    # Gemini extraction (Vision + text fallback)
    google_gemini_api_key: str = ""
    google_gemini_model: str = "gemini-2.5-flash"

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

    # Patient SMS (Twilio) + email notifications for bookings, reschedules
    # and cancellations. Each channel also needs its credentials above.
    notify_patients_sms: bool = True
    notify_patients_email: bool = True

    # NGO portal
    ngo_session_ttl_hours: int = 12
    ngo_csv_max_bytes: int = 2 * 1024 * 1024
    ngo_csv_max_rows: int = 2000
    ngo_import_preview_ttl_hours: int = 24


settings = Settings()
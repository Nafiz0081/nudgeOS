from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # WhatsApp
    wa_token: str
    wa_phone_id: str
    wa_app_secret: str
    wa_verify_token: str
    wa_api_version: str = "v21.0"

    # LLM
    google_api_key: str = ""
    parser_model: str = "gemini-2.5-flash-lite"
    groq_api_key: str = ""

    # Infra
    database_url: str
    default_tz: str = "Asia/Dhaka"
    log_level: str = "INFO"
    port: int = 8010
    echo_mode: bool = False          # Part F milestone: reply "You said: ..." with no AI


settings = Settings()

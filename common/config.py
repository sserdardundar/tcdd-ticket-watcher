import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_CHAT_ID: str = ""
    ADMIN_TOKEN: str = ""
    GCP_PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT", "tcdd-ticket-watcher")
    
    TCDD_JWT_AUTH: str = ""
    TCDD_JWT_USER_AUTH: str = ""
    
    # Defaults
    CHECK_INTERVAL_MIN: int = 5
    CHECK_INTERVAL_SEC: int = 300
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

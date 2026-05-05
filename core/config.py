import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Central API (Classroom & Finance)"
    PROJECT_VERSION: str = "1.0.0"
    
    DATABASE_URL: str
    API_KEY: str
    SECRET_KEY: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
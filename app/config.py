from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Load settings from .env file"""

    discord_token: str
    notion_api_key: str
    gemini_api_key: str
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

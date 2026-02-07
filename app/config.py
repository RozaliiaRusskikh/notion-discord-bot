from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Load settings from .env file"""

    discord_token: str
    notion_api_key: str
    gemini_api_key: str
    github_token: str
    database_id: str
    standup_channel_id: int
    github_repos: str | None = None
    github_user: str  # Filter commits by GitHub username (required)
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:////app/data/audiobook_organizer.db"
    default_output_pattern: str = "{Author}/{Series}/{SeriesPosition} - {Title} ({Year})"
    default_output_root: str = "/library"
    google_books_api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

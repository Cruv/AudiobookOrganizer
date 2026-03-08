from pydantic import BaseModel


class SettingsResponse(BaseModel):
    output_pattern: str
    output_root: str
    google_books_api_key: str | None


class SettingsUpdate(BaseModel):
    output_pattern: str | None = None
    output_root: str | None = None
    google_books_api_key: str | None = None


class PatternPreview(BaseModel):
    pattern: str
    preview: str

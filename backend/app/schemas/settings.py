from pydantic import BaseModel


class SettingsResponse(BaseModel):
    output_pattern: str
    output_root: str
    google_books_api_key: str | None
    audible_locale: str | None = None


class SettingsUpdate(BaseModel):
    output_pattern: str | None = None
    output_root: str | None = None
    google_books_api_key: str | None = None
    audible_locale: str | None = None


class PatternPreview(BaseModel):
    pattern: str
    preview: str


class AudibleStatus(BaseModel):
    connected: bool
    locale: str | None = None


class AudibleAuthorize(BaseModel):
    response_url: str
    locale: str = "us"
    session_token: str = ""

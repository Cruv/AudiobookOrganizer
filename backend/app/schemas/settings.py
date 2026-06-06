from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    output_pattern: str
    output_root: str
    google_books_api_key: str | None
    audible_locale: str | None = None
    registration_open: str | None = None


class SettingsUpdate(BaseModel):
    # registration_open was missing here, so the admin toggle's PUT body was
    # silently dropped by Pydantic and never persisted. Length caps keep any
    # single setting from storing an unbounded blob.
    output_pattern: str | None = Field(default=None, max_length=512)
    output_root: str | None = Field(default=None, max_length=4096)
    google_books_api_key: str | None = Field(default=None, max_length=256)
    audible_locale: str | None = Field(default=None, max_length=8)
    registration_open: str | None = Field(default=None, max_length=8)


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

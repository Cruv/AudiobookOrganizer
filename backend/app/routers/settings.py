import logging
import os
import secrets
import stat
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import get_db
from app.models.settings import UserSetting
from app.schemas.settings import (
    AudibleAuthorize,
    AudibleStatus,
    PatternPreview,
    SettingsResponse,
    SettingsUpdate,
)
from app.services.organizer import sanitize_path_component

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTINGS_KEYS = ["output_pattern", "output_root", "google_books_api_key", "audible_locale"]

AUDIBLE_AUTH_FILE = "/config/audible_auth.json"

# Allowed domains for Audible OAuth response URLs
AUDIBLE_ALLOWED_REDIRECT_DOMAINS = {
    "www.amazon.com",
    "amazon.com",
    "www.amazon.co.uk",
    "amazon.co.uk",
    "www.amazon.ca",
    "amazon.ca",
    "www.amazon.com.au",
    "amazon.com.au",
    "www.amazon.de",
    "amazon.de",
    "www.amazon.fr",
    "amazon.fr",
    "www.amazon.it",
    "amazon.it",
    "www.amazon.in",
    "amazon.in",
    "www.amazon.co.jp",
    "amazon.co.jp",
    "www.amazon.es",
    "amazon.es",
}

# Per-session storage for pending login flow, keyed by CSRF token
# Each entry: {"locale": str, "login_url": str}
_pending_audible_logins: dict[str, dict] = {}


@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    """Get all settings."""
    settings_map: dict[str, str | None] = {}
    for setting in db.query(UserSetting).filter(UserSetting.key.in_(SETTINGS_KEYS)).all():
        settings_map[setting.key] = setting.value

    # Mask API key — only show last 4 chars so the frontend knows if one is set
    raw_key = settings_map.get("google_books_api_key")
    masked_key = f"****{raw_key[-4:]}" if raw_key and len(raw_key) > 4 else raw_key

    return SettingsResponse(
        output_pattern=settings_map.get(
            "output_pattern", app_settings.default_output_pattern
        ),
        output_root=settings_map.get("output_root", app_settings.default_output_root),
        google_books_api_key=masked_key,
        audible_locale=settings_map.get("audible_locale", "us"),
    )


@router.put("", response_model=SettingsResponse)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    """Update settings."""
    update_data = body.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key not in SETTINGS_KEYS:
            continue

        # Don't overwrite a real API key with the masked version sent back from GET
        if key == "google_books_api_key" and value and value.startswith("****"):
            continue

        existing = db.query(UserSetting).filter(UserSetting.key == key).first()
        if existing:
            if value is not None:
                existing.value = value
            else:
                db.delete(existing)
        elif value is not None:
            db.add(UserSetting(key=key, value=value))

    db.commit()
    return get_settings(db)


@router.get("/preview-pattern", response_model=PatternPreview)
def preview_pattern(pattern: str = Query(...)):
    """Preview a naming pattern with sample data."""
    sample_tokens = {
        "{NarratorBraced}": "{Michael Kramer}",
        "{EditionBracketed}": "[Graphic Audio]",
        "{Author}": "Brandon Sanderson",
        "{Series}": "Mistborn",
        "{SeriesPosition}": "1",
        "{Title}": "The Final Empire",
        "{Year}": "2006",
        "{Narrator}": "Michael Kramer",
        "{Edition}": "Graphic Audio",
    }

    preview = pattern
    for token, value in sample_tokens.items():
        preview = preview.replace(token, value)

    # Clean up empty segments
    import re
    preview = re.sub(r"\(\s*\)", "", preview)
    preview = re.sub(r"\{\s*\}", "", preview)
    preview = re.sub(r"\[\s*\]", "", preview)
    preview = re.sub(r"^\s*[-–—]\s*|\s*[-–—]\s*$", "", preview)
    preview = re.sub(r"\s+", " ", preview).strip()

    return PatternPreview(pattern=pattern, preview=preview)


# --- Audible Auth Endpoints ---


@router.get("/audible/status", response_model=AudibleStatus)
def audible_status(db: Session = Depends(get_db)):
    """Check if Audible is connected."""
    connected = os.path.exists(AUDIBLE_AUTH_FILE)
    locale_setting = db.query(UserSetting).filter(UserSetting.key == "audible_locale").first()
    locale = locale_setting.value if locale_setting else "us"
    return AudibleStatus(connected=connected, locale=locale)


class AudibleLoginUrlResponse(BaseModel):
    login_url: str
    session_token: str


@router.post("/audible/login-url", response_model=AudibleLoginUrlResponse)
def audible_login_url(locale: str = "us"):
    """Generate Audible login URL for external browser authorization."""
    # Validate locale
    valid_locales = {"us", "uk", "ca", "au", "de", "fr", "it", "in", "jp", "es"}
    if locale not in valid_locales:
        raise HTTPException(status_code=400, detail="Invalid locale")

    try:
        import audible

        login_url = None

        def capture_url(url: str) -> str:
            nonlocal login_url
            login_url = url
            # Return a placeholder — we'll complete auth in the authorize endpoint
            return "https://placeholder.invalid/pending"

        try:
            audible.Authenticator.from_login_external(
                locale=locale,
                login_url_callback=capture_url,
            )
        except Exception:
            # Expected — the callback returns a fake URL which causes auth to fail
            # But we've captured the login_url
            pass

        if not login_url:
            raise HTTPException(status_code=500, detail="Failed to generate login URL")

        # Generate a CSRF token to tie this login flow to the authorize step
        session_token = secrets.token_urlsafe(32)

        # Clean up old pending logins (limit to 10 to prevent memory leak)
        if len(_pending_audible_logins) > 10:
            _pending_audible_logins.clear()

        _pending_audible_logins[session_token] = {
            "locale": locale,
            "login_url": login_url,
        }

        logger.info("Audible login URL generated for locale=%s", locale)
        return AudibleLoginUrlResponse(login_url=login_url, session_token=session_token)

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="audible package not installed",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Audible login URL generation failed: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Failed to generate login URL")


@router.post("/audible/authorize", response_model=AudibleStatus)
def audible_authorize(body: AudibleAuthorize, db: Session = Depends(get_db)):
    """Complete Audible authorization with the redirect URL from browser."""
    # Validate session token (CSRF protection)
    if not body.session_token or body.session_token not in _pending_audible_logins:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired session. Please restart the Audible connection process.",
        )

    # Validate response_url — must be a valid Amazon domain
    try:
        parsed = urlparse(body.response_url.strip())
        if parsed.scheme not in ("https", "http"):
            raise ValueError("Invalid URL scheme")
        if parsed.hostname not in AUDIBLE_ALLOWED_REDIRECT_DOMAINS:
            raise ValueError(f"Unexpected redirect domain: {parsed.hostname}")
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid redirect URL. Expected an Amazon URL from the login redirect.",
        )

    pending = _pending_audible_logins.pop(body.session_token)
    locale = body.locale or pending.get("locale", "us")

    try:
        import audible

        def return_response_url(url: str) -> str:
            return body.response_url.strip()

        auth = audible.Authenticator.from_login_external(
            locale=locale,
            login_url_callback=return_response_url,
        )

        # Ensure /config directory exists
        os.makedirs(os.path.dirname(AUDIBLE_AUTH_FILE), exist_ok=True)

        # Save auth to persistent file with restrictive permissions
        auth.to_file(AUDIBLE_AUTH_FILE)
        os.chmod(AUDIBLE_AUTH_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        logger.info("Audible authentication saved successfully (permissions: 0600)")

        # Save locale to settings
        existing = db.query(UserSetting).filter(UserSetting.key == "audible_locale").first()
        if existing:
            existing.value = locale
        else:
            db.add(UserSetting(key="audible_locale", value=locale))
        db.commit()

        return AudibleStatus(connected=True, locale=locale)

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="audible package not installed",
        )
    except Exception as e:
        logger.error("Audible authorization failed: %s", type(e).__name__)
        raise HTTPException(status_code=400, detail="Authorization failed. Please try again.")


@router.delete("/audible/disconnect")
def audible_disconnect():
    """Disconnect Audible by removing auth file."""
    if os.path.exists(AUDIBLE_AUTH_FILE):
        os.remove(AUDIBLE_AUTH_FILE)
        logger.info("Audible auth file removed (disconnected)")
    # Clear any pending login sessions
    _pending_audible_logins.clear()
    return {"detail": "Audible disconnected"}

import logging
import os
import secrets
import stat
import threading
import time
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

AUDIBLE_AUTH_FILE = "/app/data/audible_auth.json"

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

# Per-session storage for pending Audible login flows, keyed by session token.
# Each session holds threading events + shared state so a single from_login_external()
# call can span the login-url and authorize HTTP endpoints.
_audible_sessions: dict[str, dict] = {}


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
#
# The audible package's from_login_external() generates internal state (serial,
# code_verifier) that MUST be consistent between the login URL and the response
# URL. We cannot call it twice. Instead, we call it ONCE in a background thread:
#
#   1. login-url endpoint: starts from_login_external() in a background thread.
#      The callback captures the login URL and then BLOCKS waiting for the
#      response URL from the authorize endpoint.
#   2. authorize endpoint: provides the response URL, which unblocks the
#      background thread to complete the OAuth flow in a single call.
#


def _cleanup_stale_sessions() -> None:
    """Remove sessions older than 10 minutes to prevent memory/thread leaks."""
    now = time.monotonic()
    stale = [
        token for token, session in _audible_sessions.items()
        if now - session.get("created_at", 0) > 600
    ]
    for token in stale:
        session = _audible_sessions.pop(token, None)
        if session:
            # Signal the waiting thread so it can exit
            session["response_url_ready"].set()
            logger.info("Cleaned up stale Audible login session")


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
    """Generate Audible login URL for external browser authorization.

    Starts from_login_external() in a background thread. The thread's callback
    captures the login URL, then blocks until the authorize endpoint provides
    the response URL.
    """
    # Validate locale
    valid_locales = {"us", "uk", "ca", "au", "de", "fr", "it", "in", "jp", "es"}
    if locale not in valid_locales:
        raise HTTPException(status_code=400, detail="Invalid locale")

    # Clean up any stale sessions first
    _cleanup_stale_sessions()

    try:
        import audible  # noqa: F401 — verify package is installed
    except ImportError:
        raise HTTPException(status_code=500, detail="audible package not installed")

    # Generate CSRF session token
    session_token = secrets.token_urlsafe(32)

    # Threading events for coordination between login-url and authorize endpoints
    login_url_ready = threading.Event()
    response_url_ready = threading.Event()

    session = {
        "locale": locale,
        "login_url": None,
        "response_url": None,
        "auth": None,
        "error": None,
        "login_url_ready": login_url_ready,
        "response_url_ready": response_url_ready,
        "created_at": time.monotonic(),
    }

    def _login_url_callback(url: str) -> str:
        """Called by from_login_external with the Amazon login URL.

        Captures the URL, signals the login-url endpoint, then blocks
        until the authorize endpoint provides the response URL.
        """
        session["login_url"] = url
        login_url_ready.set()

        # Block until authorize endpoint provides the response URL (10 min timeout)
        response_url_ready.wait(timeout=600)

        if not session.get("response_url"):
            raise RuntimeError("Audible authorization timed out — no response URL received")

        return session["response_url"]

    def _run_auth_flow():
        """Background thread: runs the full from_login_external() flow."""
        try:
            import audible as _audible

            auth = _audible.Authenticator.from_login_external(
                locale=locale,
                login_url_callback=_login_url_callback,
            )
            session["auth"] = auth
            logger.info("Audible from_login_external completed successfully")
        except Exception as e:
            session["error"] = str(e)
            logger.error("Audible auth thread failed: %s", type(e).__name__)
        finally:
            # Ensure login_url_ready is set even on early failure
            login_url_ready.set()

    # Start the auth flow in a background thread
    thread = threading.Thread(target=_run_auth_flow, daemon=True, name="audible-auth")
    thread.start()

    # Wait for the login URL to be captured (up to 30 seconds)
    login_url_ready.wait(timeout=30)

    if not session["login_url"]:
        error = session.get("error", "Unknown error")
        logger.error("Failed to generate Audible login URL: %s", error)
        raise HTTPException(status_code=500, detail="Failed to generate login URL")

    # Store session for the authorize endpoint
    _audible_sessions[session_token] = session

    logger.info("Audible login URL generated for locale=%s (thread waiting for response URL)", locale)
    return AudibleLoginUrlResponse(login_url=session["login_url"], session_token=session_token)


@router.post("/audible/authorize", response_model=AudibleStatus)
def audible_authorize(body: AudibleAuthorize, db: Session = Depends(get_db)):
    """Complete Audible authorization with the redirect URL from browser.

    Provides the response URL to the waiting background thread, which completes
    the from_login_external() OAuth flow.
    """
    # Validate session token (CSRF protection)
    if not body.session_token or body.session_token not in _audible_sessions:
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
            raise ValueError("Unexpected redirect domain")
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid redirect URL. Expected an Amazon URL from the login redirect.",
        )

    session = _audible_sessions.pop(body.session_token)

    # Provide the response URL to the waiting background thread
    session["response_url"] = body.response_url.strip()
    session["response_url_ready"].set()

    # Wait for the background thread to complete the auth flow (up to 60 seconds)
    for _ in range(120):
        if session.get("auth") is not None or session.get("error") is not None:
            break
        time.sleep(0.5)

    if session.get("error"):
        logger.error("Audible authorization failed: %s", session["error"])
        raise HTTPException(status_code=400, detail="Authorization failed. Please try again.")

    if session.get("auth") is None:
        raise HTTPException(status_code=408, detail="Authorization timed out. Please try again.")

    auth = session["auth"]
    locale = body.locale or session.get("locale", "us")

    try:
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

    except Exception as e:
        logger.error("Failed to save Audible auth file: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Failed to save Audible credentials.")


@router.delete("/audible/disconnect")
def audible_disconnect():
    """Disconnect Audible by removing auth file."""
    if os.path.exists(AUDIBLE_AUTH_FILE):
        os.remove(AUDIBLE_AUTH_FILE)
        logger.info("Audible auth file removed (disconnected)")
    # Clear any pending login sessions and signal waiting threads
    for session in _audible_sessions.values():
        session["response_url_ready"].set()
    _audible_sessions.clear()
    return {"detail": "Audible disconnected"}

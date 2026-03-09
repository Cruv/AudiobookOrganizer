import logging
import os

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

# In-memory storage for pending login flow
_pending_audible_login: dict = {}


@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    """Get all settings."""
    settings_map: dict[str, str | None] = {}
    for setting in db.query(UserSetting).filter(UserSetting.key.in_(SETTINGS_KEYS)).all():
        settings_map[setting.key] = setting.value

    return SettingsResponse(
        output_pattern=settings_map.get(
            "output_pattern", app_settings.default_output_pattern
        ),
        output_root=settings_map.get("output_root", app_settings.default_output_root),
        google_books_api_key=settings_map.get("google_books_api_key"),
        audible_locale=settings_map.get("audible_locale", "us"),
    )


@router.put("", response_model=SettingsResponse)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    """Update settings."""
    update_data = body.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key not in SETTINGS_KEYS:
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


@router.post("/audible/login-url", response_model=AudibleLoginUrlResponse)
def audible_login_url(locale: str = "us"):
    """Generate Audible login URL for external browser authorization."""
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

        # Store locale for the authorize step
        _pending_audible_login["locale"] = locale
        _pending_audible_login["login_url"] = login_url

        return AudibleLoginUrlResponse(login_url=login_url)

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="audible package not installed",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Audible login URL generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/audible/authorize", response_model=AudibleStatus)
def audible_authorize(body: AudibleAuthorize, db: Session = Depends(get_db)):
    """Complete Audible authorization with the redirect URL from browser."""
    try:
        import audible

        locale = body.locale or _pending_audible_login.get("locale", "us")

        def return_response_url(url: str) -> str:
            return body.response_url

        auth = audible.Authenticator.from_login_external(
            locale=locale,
            login_url_callback=return_response_url,
        )

        # Ensure /config directory exists
        os.makedirs(os.path.dirname(AUDIBLE_AUTH_FILE), exist_ok=True)

        # Save auth to persistent file
        auth.to_file(AUDIBLE_AUTH_FILE)
        logger.info("Audible authentication saved successfully")

        # Save locale to settings
        existing = db.query(UserSetting).filter(UserSetting.key == "audible_locale").first()
        if existing:
            existing.value = locale
        else:
            db.add(UserSetting(key="audible_locale", value=locale))
        db.commit()

        # Clear pending state
        _pending_audible_login.clear()

        return AudibleStatus(connected=True, locale=locale)

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="audible package not installed",
        )
    except Exception as e:
        logger.error(f"Audible authorization failed: {e}")
        raise HTTPException(status_code=400, detail=f"Authorization failed: {e}")


@router.delete("/audible/disconnect")
def audible_disconnect():
    """Disconnect Audible by removing auth file."""
    if os.path.exists(AUDIBLE_AUTH_FILE):
        os.remove(AUDIBLE_AUTH_FILE)
        logger.info("Audible auth file removed")
    return {"detail": "Audible disconnected"}

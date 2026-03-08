from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import get_db
from app.models.settings import UserSetting
from app.schemas.settings import PatternPreview, SettingsResponse, SettingsUpdate
from app.services.organizer import sanitize_path_component

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTINGS_KEYS = ["output_pattern", "output_root", "google_books_api_key"]


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

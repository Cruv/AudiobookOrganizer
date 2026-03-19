"""Placeholder test to verify pytest runs."""


def test_import_app():
    """Verify the FastAPI app module can be imported."""
    from app.services.parser import clean_query  # noqa: F401
    from app.services.organizer import sanitize_path_component  # noqa: F401

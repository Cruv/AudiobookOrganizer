import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.settings import UserSetting
from app.models.user import (
    ApiToken,
    Invite,
    User,
    UserSession,
    hash_password,
    verify_password,
)
from app.schemas.auth import AuthStatus, InviteResponse, LoginRequest, RegisterRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Simple in-memory rate limiter for login attempts per IP
_login_attempts: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _get_client_ip(request: Request) -> str:
    """Get real client IP, safely trusting X-Real-IP only from local nginx proxy."""
    if request.client and request.client.host in ("127.0.0.1", "::1"):
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def _check_rate_limit(client_ip: str) -> None:
    """Raise 429 if too many failed login attempts from this IP.

    Prunes empty entries so the dict doesn't accumulate one key per
    unique attacker IP forever.
    """
    now = time.monotonic()
    attempts = _login_attempts.get(client_ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW_SECONDS]
    if attempts:
        _login_attempts[client_ip] = attempts
    else:
        _login_attempts.pop(client_ip, None)
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")


def _record_failed_attempt(client_ip: str) -> None:
    """Record a failed login attempt for rate limiting."""
    now = time.monotonic()
    if client_ip not in _login_attempts:
        _login_attempts[client_ip] = []
    _login_attempts[client_ip].append(now)


MAX_SESSIONS_PER_USER = 10


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Set session cookie with Secure flag when behind HTTPS."""
    is_https = request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=7 * 24 * 60 * 60,
        path="/",
    )


def _enforce_session_limit(db: Session, user_id: int) -> None:
    """Delete oldest sessions if user exceeds the limit."""
    sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .order_by(UserSession.expires_at.desc())
        .all()
    )
    if len(sessions) >= MAX_SESSIONS_PER_USER:
        for old_session in sessions[MAX_SESSIONS_PER_USER - 1:]:
            db.delete(old_session)


def _registration_open(db: Session) -> bool:
    """Check if open registration is enabled (default: True)."""
    setting = db.query(UserSetting).filter(UserSetting.key == "registration_open").first()
    if setting is None:
        return True
    return setting.value.lower() in ("true", "1", "yes")


def _get_current_user(db: Session, session_token: str | None) -> User | None:
    """Get the current user from session cookie."""
    if not session_token:
        return None
    session = (
        db.query(UserSession)
        .filter(
            UserSession.token == session_token,
            UserSession.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if not session:
        return None
    return db.query(User).filter(User.id == session.user_id).first()


@router.get("/status", response_model=AuthStatus)
def auth_status(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    """Check authentication status."""
    has_users = db.query(User).first() is not None
    user = _get_current_user(db, session_token)
    return AuthStatus(
        logged_in=user is not None,
        username=user.username if user else None,
        is_admin=user.is_admin if user else False,
        registration_open=_registration_open(db),
        has_users=has_users,
    )


@router.post("/register")
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Register a new user account."""
    # Validate username
    username = body.username.strip()
    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(username) > 50:
        raise HTTPException(status_code=400, detail="Username must be 50 characters or less")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Check if username taken
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    # Check if this is the first user
    has_users = db.query(User).first() is not None

    # If not first user, check registration is allowed
    invite = None
    if has_users:
        reg_open = _registration_open(db)
        if not reg_open:
            # Must have a valid invite
            if not body.invite_token:
                raise HTTPException(status_code=403, detail="Registration is closed. An invite is required.")
            invite = (
                db.query(Invite)
                .filter(
                    Invite.token == body.invite_token,
                    Invite.used_by.is_(None),
                    Invite.expires_at > datetime.now(timezone.utc),
                )
                .first()
            )
            if not invite:
                raise HTTPException(status_code=403, detail="Invalid or expired invite")

    # Create user
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        is_admin=not has_users,  # First user is admin
    )
    db.add(user)
    db.flush()

    # Invalidate the auth middleware cache so it knows users exist
    from app.main import invalidate_has_users_cache
    invalidate_has_users_cache()

    # Mark invite as used
    if invite:
        invite.used_by = user.id

    # Create session
    session = UserSession(
        user_id=user.id,
        token=UserSession.create_token(),
        expires_at=UserSession.default_expiry(),
    )
    db.add(session)
    db.commit()

    logger.info("User registered: %s (admin=%s)", username, user.is_admin)

    _set_session_cookie(response, request, session.token)
    return {"detail": "Account created", "username": user.username, "is_admin": user.is_admin}


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Log in with username and password."""
    client_ip = _get_client_ip(request)
    _check_rate_limit(client_ip)

    user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user or not verify_password(body.password, user.password_hash):
        _record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Enforce session limit before creating new session
    _enforce_session_limit(db, user.id)

    # Create session
    session = UserSession(
        user_id=user.id,
        token=UserSession.create_token(),
        expires_at=UserSession.default_expiry(),
    )
    db.add(session)
    db.commit()

    _set_session_cookie(response, request, session.token)
    return {"detail": "Logged in", "username": user.username, "is_admin": user.is_admin}


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    """Log out and clear session."""
    if session_token:
        db.query(UserSession).filter(UserSession.token == session_token).delete()
        db.commit()
    response.delete_cookie(key="session_token", path="/")
    return {"detail": "Logged out"}


# --- Invite management (admin only) ---


def _require_admin(db: Session, session_token: str | None = Cookie(None)) -> User:
    user = _get_current_user(db, session_token)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_admin(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
) -> User:
    """FastAPI dependency that enforces admin access.

    Use as `Depends(require_admin)` on any endpoint that mutates global
    state (settings, Audible auth, scan deletion). The auth middleware
    only validates the session — admin status is per-route.

    Importantly: when no users exist yet (first-run before initial
    registration), the auth middleware lets all /api/* requests through
    so the AuthGate can render. To prevent privilege escalation in that
    window, this dep also rejects when no users exist.
    """
    if not db.query(User).first():
        raise HTTPException(status_code=403, detail="Admin access required")
    return _require_admin(db, session_token)


@router.post("/invites", response_model=InviteResponse)
def create_invite(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    """Generate an invite token (admin only)."""
    admin = _require_admin(db, session_token)

    invite = Invite(
        token=Invite.create_token(),
        created_by=admin.id,
        expires_at=Invite.default_expiry(),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    logger.info("Invite created by %s: %s", admin.username, invite.token)
    return InviteResponse(
        id=invite.id,
        token=invite.token,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used=False,
    )


@router.get("/invites", response_model=list[InviteResponse])
def list_invites(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    """List all invites (admin only)."""
    _require_admin(db, session_token)

    invites = db.query(Invite).order_by(Invite.created_at.desc()).all()
    return [
        InviteResponse(
            id=inv.id,
            token=inv.token,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
            used=inv.used_by is not None,
        )
        for inv in invites
    ]


@router.delete("/invites/{invite_id}")
def delete_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    """Revoke an invite (admin only)."""
    _require_admin(db, session_token)

    invite = db.query(Invite).filter(Invite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    db.delete(invite)
    db.commit()
    return {"detail": "Invite revoked"}


# --- API tokens (per-user, long-lived) ---


class ApiTokenItem(BaseModel):
    id: int
    name: str
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class ApiTokenCreatedResponse(BaseModel):
    id: int
    name: str
    token_prefix: str
    token: str  # plaintext — shown ONCE on creation


class CreateApiTokenRequest(BaseModel):
    name: str


@router.post("/tokens", response_model=ApiTokenCreatedResponse)
def create_api_token(
    body: CreateApiTokenRequest,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    """Create a new API token for the current user.

    Returns the plaintext token in the response — this is the ONLY
    time it's exposed. After this, the DB stores a SHA-256 hash plus
    the first 8 chars for display.
    """
    user = _get_current_user(db, session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Token name required")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Token name too long")

    plaintext = ApiToken.create_plaintext()
    token = ApiToken(
        user_id=user.id,
        name=name,
        token_hash=ApiToken.hash_token(plaintext),
        # First 8 chars after the "ao_" prefix — enough to disambiguate
        # in the UI without being useful to an attacker.
        token_prefix=plaintext[:11],
    )
    db.add(token)
    db.commit()
    db.refresh(token)

    logger.info("API token created for %s: %s (prefix=%s)", user.username, name, token.token_prefix)
    return ApiTokenCreatedResponse(
        id=token.id,
        name=token.name,
        token_prefix=token.token_prefix,
        token=plaintext,
    )


@router.get("/tokens", response_model=list[ApiTokenItem])
def list_api_tokens(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    user = _get_current_user(db, session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    rows = (
        db.query(ApiToken)
        .filter(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
        .all()
    )
    return [
        ApiTokenItem(
            id=t.id, name=t.name, token_prefix=t.token_prefix,
            created_at=t.created_at, last_used_at=t.last_used_at,
            revoked=t.revoked,
        )
        for t in rows
    ]


@router.delete("/tokens/{token_id}")
def revoke_api_token(
    token_id: int,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(None),
):
    user = _get_current_user(db, session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = (
        db.query(ApiToken)
        .filter(ApiToken.id == token_id, ApiToken.user_id == user.id)
        .first()
    )
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    token.revoked = True
    db.commit()
    return {"detail": "Token revoked"}

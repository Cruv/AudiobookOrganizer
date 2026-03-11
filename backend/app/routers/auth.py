import logging
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.settings import UserSetting
from app.models.user import Invite, User, UserSession, hash_password, verify_password
from app.schemas.auth import AuthStatus, InviteResponse, LoginRequest, RegisterRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
            UserSession.expires_at > datetime.utcnow(),
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
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

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
                    Invite.expires_at > datetime.utcnow(),
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

    response.set_cookie(
        key="session_token",
        value=session.token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    return {"detail": "Account created", "username": user.username, "is_admin": user.is_admin}


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Log in with username and password."""
    user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Create session
    session = UserSession(
        user_id=user.id,
        token=UserSession.create_token(),
        expires_at=UserSession.default_expiry(),
    )
    db.add(session)
    db.commit()

    response.set_cookie(
        key="session_token",
        value=session.token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
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

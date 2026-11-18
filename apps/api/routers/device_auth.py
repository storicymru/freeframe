"""Connecting a desktop helper (Adborth for Mac) to an account.

The helper never sees a password or an emailed code. It opens the site in the
browser, where the person is usually signed in already, and they approve the
connection there. The site hands the helper a one-time code through its own
URL scheme, and the helper exchanges that code for a long-lived session.

The exchange is bound to the helper that started it (PKCE, RFC 7636): the
helper sends the hash of a secret when it starts and the secret itself when it
exchanges, so another app that catches the code on its way back cannot use it.
"""
import base64
import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..middleware.rate_limit import rate_limit
from ..models.user import User, UserStatus
from ..schemas.auth import TokenResponse
from ..services.auth_service import create_access_token, create_refresh_token, get_user_by_id
from ..services.redis_service import store_device_code, take_device_code

router = APIRouter(prefix="/auth/device", tags=["device-auth"])

# base64url of a SHA-256 digest is 43 characters; a verifier is 43 to 128.
_B64URL = r"^[A-Za-z0-9_-]+$"


class DeviceApproval(BaseModel):
    code_challenge: str = Field(min_length=43, max_length=64, pattern=_B64URL)
    device_name: str | None = Field(default=None, max_length=120)


class DeviceApprovalResponse(BaseModel):
    code: str
    expires_in: int


class DeviceTokenRequest(BaseModel):
    code: str = Field(min_length=20, max_length=128, pattern=_B64URL)
    code_verifier: str = Field(min_length=43, max_length=128, pattern=_B64URL)


def challenge_for(verifier: str) -> str:
    """The S256 challenge of a PKCE verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@router.post("/approve", response_model=DeviceApprovalResponse)
def approve_device(
    body: DeviceApproval,
    current_user: User = Depends(get_current_user),
):
    """Called by the site once the signed-in person agrees to connect a helper.
    Returns the one-time code the site passes back to it."""
    if current_user.is_client is True:
        raise HTTPException(status_code=403, detail="The desktop app is for team accounts")
    code = secrets.token_urlsafe(32)
    store_device_code(code, json.dumps({
        "user_id": str(current_user.id),
        "challenge": body.code_challenge,
        "name": body.device_name,
    }))
    from ..services.redis_service import DEVICE_CODE_EXPIRY_SECONDS
    return DeviceApprovalResponse(code=code, expires_in=DEVICE_CODE_EXPIRY_SECONDS)


@router.post(
    "/token",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("device_token", 10, 600))],
)
def exchange_device_code(body: DeviceTokenRequest, db: Session = Depends(get_db)):
    """Called by the helper: the one-time code and the secret it started with,
    for a session that lasts. One failure answer for every way it can fail."""
    refused = HTTPException(status_code=400, detail="This sign-in has expired. Start again from the app.")
    stored = take_device_code(body.code)
    if not stored:
        raise refused
    try:
        grant = json.loads(stored)
        challenge = str(grant["challenge"])
        user_id = str(grant["user_id"])
    except (ValueError, KeyError, TypeError):
        raise refused
    if not hmac.compare_digest(challenge_for(body.code_verifier), challenge):
        raise refused
    import uuid as _uuid
    user = get_user_by_id(db, _uuid.UUID(user_id))
    if not user or user.status == UserStatus.deactivated or user.is_client is True:
        raise refused
    return TokenResponse(
        access_token=create_access_token(str(user.id), token_version=user.token_version),
        refresh_token=create_refresh_token(str(user.id), token_version=user.token_version, device=True),
        needs_password=False,
    )

"""Connecting a desktop helper through the browser, and its long session."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from apps.api.models.user import User, UserStatus
from apps.api.routers.device_auth import challenge_for
from apps.api.services.auth_service import create_refresh_token, decode_token

VERIFIER = "v" * 64
CHALLENGE = challenge_for(VERIFIER)


@pytest.fixture
def mock_user():
    """Signs every request in as this team account."""
    from apps.api.main import app
    from apps.api.middleware.auth import get_current_user
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_client = False
    user.is_superadmin = False
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield user
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _user(**over):
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.status = UserStatus.active
    user.is_client = False
    user.token_version = 3
    user.password_hash = "x"
    for key, value in over.items():
        setattr(user, key, value)
    return user


@pytest.fixture
def codes():
    """A stand-in for the one-time code store in Redis."""
    held = {}

    def take(code):
        return held.pop(code, None)

    with patch("apps.api.routers.device_auth.store_device_code", side_effect=held.__setitem__), \
         patch("apps.api.routers.device_auth.take_device_code", side_effect=take):
        yield held


def test_challenge_is_the_s256_of_the_verifier():
    # RFC 7636, appendix B.
    assert challenge_for("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_approve_stores_a_code_for_the_signed_in_user(client, codes, mock_user):
    mock_user.is_client = False
    response = client.post("/auth/device/approve", json={"code_challenge": CHALLENGE, "device_name": "Edit suite"})
    assert response.status_code == 200
    code = response.json()["code"]
    grant = json.loads(codes[code])
    assert grant["user_id"] == str(mock_user.id)
    assert grant["challenge"] == CHALLENGE


def test_a_client_account_cannot_connect_a_helper(client, codes, mock_user):
    mock_user.is_client = True
    response = client.post("/auth/device/approve", json={"code_challenge": CHALLENGE})
    assert response.status_code == 403
    assert codes == {}


def test_approve_refuses_a_malformed_challenge(client, codes, mock_user):
    assert client.post("/auth/device/approve", json={"code_challenge": "short"}).status_code == 422


def test_exchange_gives_a_device_session_once(client, codes):
    user = _user()
    codes["c" * 43] = json.dumps({"user_id": str(user.id), "challenge": CHALLENGE, "name": None})
    with patch("apps.api.routers.device_auth.get_user_by_id", return_value=user):
        first = client.post("/auth/device/token", json={"code": "c" * 43, "code_verifier": VERIFIER})
        second = client.post("/auth/device/token", json={"code": "c" * 43, "code_verifier": VERIFIER})
    assert first.status_code == 200
    payload = decode_token(first.json()["refresh_token"])
    assert payload["dev"] is True and payload["sub"] == str(user.id) and payload["ver"] == 3
    # Far longer than an ordinary session.
    days = (datetime.fromtimestamp(payload["exp"], timezone.utc) - datetime.now(timezone.utc)).days
    assert days >= 170
    assert second.status_code == 400


def test_exchange_refuses_the_wrong_verifier_and_spends_the_code(client, codes):
    user = _user()
    codes["c" * 43] = json.dumps({"user_id": str(user.id), "challenge": CHALLENGE, "name": None})
    with patch("apps.api.routers.device_auth.get_user_by_id", return_value=user):
        wrong = client.post("/auth/device/token", json={"code": "c" * 43, "code_verifier": "w" * 64})
        retry = client.post("/auth/device/token", json={"code": "c" * 43, "code_verifier": VERIFIER})
    assert wrong.status_code == 400
    assert retry.status_code == 400


@pytest.mark.parametrize("change", [{"status": UserStatus.deactivated}, {"is_client": True}])
def test_exchange_refuses_an_account_that_may_not_use_a_helper(client, codes, change):
    user = _user(**change)
    codes["c" * 43] = json.dumps({"user_id": str(user.id), "challenge": CHALLENGE, "name": None})
    with patch("apps.api.routers.device_auth.get_user_by_id", return_value=user):
        response = client.post("/auth/device/token", json={"code": "c" * 43, "code_verifier": VERIFIER})
    assert response.status_code == 400


def test_refresh_keeps_a_device_session_long_and_an_ordinary_one_short(client):
    user = _user()
    with patch("apps.api.routers.auth.get_user_by_id", return_value=user):
        device = client.post("/auth/refresh", json={"refresh_token": create_refresh_token(str(user.id), 3, device=True)})
        plain = client.post("/auth/refresh", json={"refresh_token": create_refresh_token(str(user.id), 3)})
    assert device.status_code == 200 and plain.status_code == 200
    assert decode_token(device.json()["refresh_token"]).get("dev") is True
    assert "dev" not in decode_token(plain.json()["refresh_token"])

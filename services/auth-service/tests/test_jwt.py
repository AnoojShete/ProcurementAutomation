import time

import jwt as pyjwt
import pytest

from shared.auth.jwt_tokens import create_access_token, create_refresh_token, decode_token, TokenError
from shared.auth.config import JWT_SECRET, JWT_ALGORITHM


class TestJWT:
    def test_access_token_round_trip(self):
        token = create_access_token("user-1", "a@b.com", "approver")
        claims = decode_token(token)
        assert claims["sub"] == "user-1"
        assert claims["email"] == "a@b.com"
        assert claims["role"] == "approver"
        assert claims["type"] == "access"

    def test_refresh_token_has_refresh_type(self):
        token = create_refresh_token("user-1", "a@b.com", "approver")
        claims = decode_token(token)
        assert claims["type"] == "refresh"

    def test_invalid_token_raises_token_error(self):
        with pytest.raises(TokenError):
            decode_token("not-a-real-token")

    def test_expired_token_raises_token_error(self):
        expired = pyjwt.encode(
            {"sub": "u", "email": "a@b.com", "role": "admin", "type": "access", "exp": time.time() - 10},
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        with pytest.raises(TokenError):
            decode_token(expired)

    def test_token_signed_with_wrong_secret_rejected(self):
        forged = pyjwt.encode(
            {"sub": "u", "email": "a@b.com", "role": "admin", "type": "access"},
            "wrong-secret",
            algorithm=JWT_ALGORITHM,
        )
        with pytest.raises(TokenError):
            decode_token(forged)

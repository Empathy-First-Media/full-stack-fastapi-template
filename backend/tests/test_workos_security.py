"""Signed-token fixtures only: these do not establish production WorkOS readiness."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import InvalidTokenError, PyJWK

from app.core.config import Settings
from app.core.security import AccessTokenVerifier


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        _env_file=None,
        PROJECT_NAME="API auth fixture",
        FRONTEND_HOST="http://localhost:5173",
        FASTAPI_ENV="development",
        DATABASE_URL="postgresql+psycopg://fixture:fixture@localhost/api_fixture",
        WORKOS_CLIENT_ID="client_fixture",
        WORKOS_ISSUER="https://auth.fixture.test/",
        WORKOS_JWKS_URL="https://auth.fixture.test/sso/jwks/client_fixture",
        WORKOS_API_HOSTNAME="auth.fixture.test",
    )


@pytest.fixture
def signed_token(auth_settings: Settings):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = PyJWK.from_json(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    now = datetime.now(UTC)
    claims = {
        "iss": auth_settings.WORKOS_ISSUER,
        "client_id": auth_settings.WORKOS_CLIENT_ID,
        "sub": "user_fixture",
        "sid": "session_fixture",
        "org_id": "org_fixture",
        "role": "authenticated",
        "user_role": "member",
        "permissions": ["org:projects:read"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }

    class FixtureKeys:
        def get_signing_key_from_jwt(self, _token: str) -> PyJWK:
            return jwk

    verifier = AccessTokenVerifier(auth_settings, jwks_client=FixtureKeys())

    def encode(**changes):
        payload = claims | changes
        return jwt.encode(
            {k: v for k, v in payload.items() if v is not None},
            key,
            algorithm="RS256",
            headers={"kid": "fixture"},
        )

    return verifier, encode


def test_signed_selected_organization_token(signed_token):
    verifier, encode = signed_token
    token = verifier.verify(encode())
    assert token.subject == "user_fixture"
    assert token.organization_id == "org_fixture"
    assert token.permissions == frozenset({"org:projects:read"})


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://other.fixture.test/"},
        {"iss": None},
        {"client_id": "client_foreign"},
        {"client_id": None},
        {"exp": 1},
        {"exp": None},
        {"exp": "9999999999"},
        {"sub": None},
        {"sub": " "},
        {"sid": None},
        {"org_id": None},
        {"role": "admin"},
        {"user_role": None},
        {"permissions": "org:projects:write"},
        {"permissions": [1]},
        {"o": {"id": "org_foreign"}},
        {"aud": "client_foreign"},
        {"roles": ["member", "admin"]},
    ],
)
def test_rejects_unbound_or_confused_token(signed_token, changes):
    verifier, encode = signed_token
    with pytest.raises(InvalidTokenError):
        verifier.verify(encode(**changes))


def test_rejects_token_signed_by_another_key(signed_token):
    verifier, _ = signed_token
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(InvalidTokenError):
        verifier.verify(jwt.encode({"sub": "user_fixture"}, other, algorithm="RS256"))


def test_production_browser_requires_custom_auth_domain(auth_settings):
    values = auth_settings.model_dump()
    values.update(
        FASTAPI_ENV=None,
        FRONTEND_HOST="https://api.fixture.test",
        WORKOS_API_HOSTNAME="api.workos.com",
        WORKOS_ISSUER="https://api.workos.com/",
        WORKOS_JWKS_URL="https://api.workos.com/sso/jwks/client_fixture",
    )
    with pytest.raises(ValueError, match="custom"):
        Settings(_env_file=None, **values)


def test_production_accepts_custom_api_with_explicit_vendor_jwks(auth_settings):
    values = auth_settings.model_dump()
    values.update(
        FASTAPI_ENV=None,
        FRONTEND_HOST="https://api.fixture.com",
        WORKOS_API_HOSTNAME="auth.fixture.com",
        WORKOS_ISSUER="https://auth.fixture.com/",
        WORKOS_JWKS_URL="https://api.workos.com/sso/jwks/client_fixture",
    )
    config = Settings(_env_file=None, **values)
    assert config.WORKOS_API_HOSTNAME == "auth.fixture.com"


def test_native_jwks_cache_and_key_rotation_require_tls_and_timeout(
    auth_settings, monkeypatch
):
    import io
    import json
    import ssl
    from urllib.request import HTTPSHandler

    first = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = [first]
    calls = []
    clock = [100.0]
    monkeypatch.setattr("jwt.jwks_client.time.monotonic", lambda: clock[0])

    def fetch(request, *, timeout):
        calls.append(request.full_url)
        assert request.full_url == auth_settings.WORKOS_JWKS_URL
        assert timeout == 5
        documents = []
        for index, key in enumerate(keys):
            documents.append(
                json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
                | {
                    "kid": f"fixture-{index}",
                    "use": "sig",
                    "alg": "RS256",
                }
            )
        return io.BytesIO(json.dumps({"keys": documents}).encode())

    class FixtureOpener:
        open = staticmethod(fetch)

    def build_opener(*handlers):
        tls = next(handler for handler in handlers if isinstance(handler, HTTPSHandler))
        assert tls._context.verify_mode == ssl.CERT_REQUIRED
        assert tls._context.check_hostname
        return FixtureOpener()

    monkeypatch.setattr("urllib.request.build_opener", build_opener)
    verifier = AccessTokenVerifier(auth_settings)
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "iss": auth_settings.WORKOS_ISSUER,
        "client_id": auth_settings.WORKOS_CLIENT_ID,
        "sub": "user_fixture",
        "sid": "session_fixture",
        "org_id": "org_fixture",
        "role": "authenticated",
        "user_role": "member",
        "permissions": [],
        "iat": now,
        "exp": now + 300,
    }
    first_token = jwt.encode(
        payload, first, algorithm="RS256", headers={"kid": "fixture-0"}
    )
    verifier.verify(first_token)
    verifier.verify(first_token)
    assert len(calls) == 1
    keys.append(second)
    clock[0] += 31  # Native unknown-kid cooldown; cached known keys stay usable.
    verifier.verify(
        jwt.encode(payload, second, algorithm="RS256", headers={"kid": "fixture-1"})
    )
    assert len(calls) == 2

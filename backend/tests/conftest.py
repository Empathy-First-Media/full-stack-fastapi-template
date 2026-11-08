"""Explicit fixture configuration; never import a production runtime environment.

SQL integration cases require a preprovisioned isolated product baseline, the API
namespace branch, and API_TEST_ACTORS (JSON fixture actors). No schema creation,
canonical identity seed, or global table cleanup is performed by this suite.
"""

import json
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from sqlmodel import Session, delete

# Always isolate auth/settings even for tests not requiring PostgreSQL. A real
# integration target is selected ONLY by the dedicated fixture below.
os.environ.update(
    {
        "PROJECT_NAME": "API fixture",
        "DATABASE_URL": "postgresql+psycopg://fixture:fixture@localhost/api_test_unconfigured",
        "FRONTEND_HOST": "http://localhost:5173",
        "FASTAPI_ENV": "development",
        "WORKOS_CLIENT_ID": "client_fixture",
        "WORKOS_ISSUER": "https://auth.fixture.test/",
        "WORKOS_JWKS_URL": "https://auth.fixture.test/sso/jwks/client_fixture",
        "WORKOS_API_HOSTNAME": "auth.fixture.test",
    }
)

from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import settings
from app.core.security import AccessTokenVerifier
from app.main import app
from app.models import Item, User
from tests.test_data_namespace import isolated_data_engine


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app) as value:
        yield value


@pytest.fixture
def fixture_claims():
    def build(actor, **overrides):
        now = datetime.now(UTC)
        return {
            "iss": settings.WORKOS_ISSUER,
            "client_id": settings.WORKOS_CLIENT_ID,
            "sub": actor["subject"],
            "sid": "session_fixture",
            "org_id": actor["organization_id"],
            "role": "authenticated",
            "user_role": actor["user_role"],
            "permissions": ["org:projects:read", "org:projects:write"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        } | overrides

    return build


@pytest.fixture
def issue_token(monkeypatch, fixture_claims):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = PyJWK.from_json(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))

    class FixtureKeys:
        def get_signing_key_from_jwt(self, _token: str) -> PyJWK:
            return jwk

    verifier = AccessTokenVerifier(settings, jwks_client=FixtureKeys())
    monkeypatch.setattr(deps, "get_token_verifier", lambda: verifier)

    def issue(actor, **overrides):
        claims = fixture_claims(actor, **overrides)
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {k: v for k, v in claims.items() if v is not None},
                key,
                algorithm="RS256",
                headers={"kid": "fixture"},
            )
        }

    return issue


@pytest.fixture
def runtime_engine(monkeypatch):
    engine = isolated_data_engine("API_TEST_DATABASE_URL")
    monkeypatch.setattr(deps, "engine", engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def canonical_actors():
    raw = os.environ.get("API_TEST_ACTORS")
    if not raw:
        pytest.fail(
            "API_TEST_ACTORS must provide admin, member, foreign_admin, unprofiled, revoked fixture actors from the isolated canonical baseline"
        )
    return json.loads(raw)


@pytest.fixture
def fixture_actors(request: pytest.FixtureRequest, canonical_actors):
    """Use existing fixture-only canonical actors; create only API-local profiles."""
    request.getfixturevalue("runtime_engine")
    actors = canonical_actors
    admin_engine = isolated_data_engine("API_TEST_ADMIN_DATABASE_URL")
    created_ids = []
    with Session(admin_engine) as session:
        for name in ("admin", "member", "foreign_admin"):
            actor = actors[name]
            user_id = uuid4()
            actor["id"] = str(user_id)
            session.add(
                User(
                    id=user_id,
                    tenant_id=actor["tenant_id"],
                    identity_entity_id=UUID(actor["identity_entity_id"]),
                    email=f"{user_id}@fixture.example.com",
                    full_name=f"Fixture {name}",
                )
            )
            created_ids.append(user_id)
        session.commit()
    try:
        yield actors
    finally:
        with Session(admin_engine) as session:
            # Explicit fixture targets may gain local profiles, never memberships.
            session.exec(delete(Item).where(Item.owner_id.in_(created_ids)))
            session.exec(delete(User).where(User.id.in_(created_ids)))
            for name in ("unprofiled", "revoked"):
                session.exec(
                    delete(User).where(
                        User.tenant_id == actors[name]["tenant_id"],
                        User.identity_entity_id
                        == UUID(actors[name]["identity_entity_id"]),
                    )
                )
            session.commit()
        admin_engine.dispose()


@pytest.fixture
def db(runtime_engine):
    with Session(runtime_engine) as session:
        yield session

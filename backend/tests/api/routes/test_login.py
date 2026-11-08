import pytest

from app.core.config import settings

FIXTURE_ACTOR = {
    "subject": "user_fixture",
    "organization_id": "org_fixture",
    "user_role": "member",
}


def test_auth_config_is_public_and_safe(client):
    response = client.get("/api/v1/auth/config")
    assert response.status_code == 200
    assert response.json() == {
        "client_id": "client_fixture",
        "api_hostname": "auth.fixture.test",
        "redirect_uri": "http://localhost:5173",
    }


@pytest.mark.parametrize(
    "path,method",
    [
        ("/login/access-token", "post"),
        ("/login/test-token", "post"),
        ("/password-recovery/fixture@example.com", "post"),
        ("/reset-password/", "post"),
        ("/users/signup", "post"),
        ("/users/me/password", "patch"),
    ],
)
def test_password_authentication_surface_is_retired(client, path, method):
    response = getattr(client, method)(
        f"{settings.API_V1_STR}{path}", json={"password": "fixture"}
    )
    assert response.status_code in (404, 405)


def test_missing_token_denied_before_sql(client):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://foreign.fixture.test/"},
        {"client_id": "client_foreign"},
        {"exp": 1},
        {"sid": None},
        {"org_id": None},
        {"role": "admin"},
        {"user_role": None},
        {"permissions": [True]},
    ],
)
def test_invalid_signed_token_denied_before_sql(client, issue_token, claims):
    response = client.get(
        "/api/v1/users/me", headers=issue_token(FIXTURE_ACTOR, **claims)
    )
    assert response.status_code == 401


def test_jwks_network_failure_denies_before_sql(client, issue_token, monkeypatch):
    from urllib.error import URLError

    from app.api import deps
    from app.core.security import AccessTokenVerifier

    headers = issue_token(FIXTURE_ACTOR)

    def unavailable(*_args, **_kwargs):
        raise URLError("Fixture JWKS unavailable")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", unavailable)
    monkeypatch.setattr(
        deps, "get_token_verifier", lambda: AccessTokenVerifier(settings)
    )
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Unable to verify access token"

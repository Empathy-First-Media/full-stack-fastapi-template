from uuid import uuid4

import pytest


def test_me_preserves_local_actor_and_exposes_verified_role(
    client, fixture_actors, issue_token
):
    actor = fixture_actors["admin"]
    response = client.get("/api/v1/users/me", headers=issue_token(actor))
    assert response.status_code == 200
    assert response.json()["id"] == actor["id"]
    assert response.json()["tenant_id"] == actor["tenant_id"]
    assert response.json()["identity_entity_id"] == actor["identity_entity_id"]
    assert response.json()["user_role"] == "admin"
    assert response.json()["is_tenant_admin"] is True
    assert "is_superuser" not in response.json()
    assert "hashed_password" not in response.json()


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_admin_cannot_access_foreign_tenant_profile(
    client, fixture_actors, issue_token, method
):
    url = f"/api/v1/users/{fixture_actors['foreign_admin']['id']}"
    kwargs = {"json": {"full_name": "Forbidden"}} if method == "patch" else {}
    response = getattr(client, method)(
        url, headers=issue_token(fixture_actors["admin"]), **kwargs
    )
    assert response.status_code == 404


def test_admin_list_is_selected_tenant_only(client, fixture_actors, issue_token):
    response = client.get(
        "/api/v1/users/", headers=issue_token(fixture_actors["admin"])
    )
    assert response.status_code == 200
    assert {user["tenant_id"] for user in response.json()["data"]} == {
        fixture_actors["admin"]["tenant_id"]
    }
    assert fixture_actors["foreign_admin"]["id"] not in {
        u["id"] for u in response.json()["data"]
    }


@pytest.mark.parametrize(
    "actor_name,overrides",
    [
        ("revoked", {}),
        ("admin", {"org_id": "org_unmapped_fixture"}),
        ("admin", {"org_id": "FOREIGN"}),
        ("admin", {"sub": "user_unknown_fixture"}),
        ("member", {"user_role": "admin"}),
    ],
)
def test_unknown_revoked_or_confused_identity_denied(
    client, fixture_actors, issue_token, actor_name, overrides
):
    if overrides.get("org_id") == "FOREIGN":
        overrides = {"org_id": fixture_actors["foreign_admin"]["organization_id"]}
    response = client.get(
        "/api/v1/users/me", headers=issue_token(fixture_actors[actor_name], **overrides)
    )
    assert response.status_code == 403


def test_email_never_autoprovisions_or_links_actor(client, fixture_actors, issue_token):
    response = client.get(
        "/api/v1/users/me",
        headers=issue_token(
            fixture_actors["admin"],
            sub="user_unknown_fixture",
            email=f"{fixture_actors['admin']['id']}@fixture.example.com",
        ),
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "foreign_fixture"),
        ("identity_entity_id", str(uuid4())),
        ("is_superuser", True),
        ("password", "not-a-local-password"),
    ],
)
def test_profile_attribution_and_global_role_are_not_mutable(
    client, fixture_actors, issue_token, field, value
):
    response = client.patch(
        "/api/v1/users/me",
        headers=issue_token(fixture_actors["admin"]),
        json={field: value},
    )
    assert response.status_code == 422


def test_profile_admin_cannot_grant_membership_or_role(
    client, fixture_actors, issue_token
):
    admin = fixture_actors["admin"]
    response = client.patch(
        f"/api/v1/users/{fixture_actors['member']['id']}",
        headers=issue_token(admin),
        json={"user_role": "admin"},
    )
    assert response.status_code == 422


def test_admin_create_requires_existing_same_tenant_canonical_actor(
    client, fixture_actors, issue_token
):
    headers = issue_token(fixture_actors["admin"])
    unknown = client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": "unknown@fixture.example.com",
            "identity_entity_id": str(uuid4()),
        },
    )
    assert unknown.status_code == 403
    foreign = client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": "foreign@fixture.example.com",
            "identity_entity_id": fixture_actors["foreign_admin"]["identity_entity_id"],
        },
    )
    assert foreign.status_code == 403
    revoked = client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": "revoked@fixture.example.com",
            "identity_entity_id": fixture_actors["revoked"]["identity_entity_id"],
        },
    )
    assert revoked.status_code == 200
    # A local profile does not grant or reactivate provider membership.
    assert (
        client.get(
            "/api/v1/users/me", headers=issue_token(fixture_actors["revoked"])
        ).status_code
        == 403
    )
    actor = fixture_actors["unprofiled"]
    response = client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": "new-profile@fixture.example.com",
            "identity_entity_id": actor["identity_entity_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["identity_entity_id"] == actor["identity_entity_id"]
    assert response.json()["tenant_id"] == actor["tenant_id"]
    assert response.json()["id"] != actor["identity_entity_id"]
    me = client.get("/api/v1/users/me", headers=issue_token(actor))
    assert me.status_code == 200
    assert me.json()["id"] == response.json()["id"]


def test_ordinary_member_cannot_administer_accounts(
    client, fixture_actors, issue_token
):
    response = client.get(
        "/api/v1/users/", headers=issue_token(fixture_actors["member"])
    )
    assert response.status_code == 403


def test_admin_without_business_permission_cannot_administer_accounts(
    client, fixture_actors, issue_token
):
    response = client.get(
        "/api/v1/users/", headers=issue_token(fixture_actors["admin"], permissions=[])
    )
    assert response.status_code == 403


def test_self_profile_roundtrip_survives_commit(client, fixture_actors, issue_token):
    headers = issue_token(fixture_actors["member"])
    changed = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"full_name": "Changed fixture profile"},
    )
    assert changed.status_code == 200
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["full_name"] == "Changed fixture profile"


def test_caller_tenant_header_does_not_select_identity(
    client, fixture_actors, issue_token
):
    actor = fixture_actors["admin"]
    headers = issue_token(actor) | {
        "X-Tenant-ID": fixture_actors["foreign_admin"]["tenant_id"]
    }
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == actor["tenant_id"]
    assert response.json()["id"] == actor["id"]


def test_deactivated_local_actor_cannot_authenticate(
    client, fixture_actors, issue_token
):
    actor = fixture_actors["member"]
    response = client.patch(
        f"/api/v1/users/{actor['id']}",
        headers=issue_token(fixture_actors["admin"]),
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/users/me", headers=issue_token(actor)).status_code == 403


@pytest.mark.parametrize("operation", ["self_update", "admin_update", "create"])
def test_same_tenant_profile_email_collision_returns_existing_conflict(
    client, fixture_actors, issue_token, operation
):
    admin_headers = issue_token(fixture_actors["admin"])
    member_headers = issue_token(fixture_actors["member"])
    admin = client.get("/api/v1/users/me", headers=admin_headers).json()
    member_before = client.get("/api/v1/users/me", headers=member_headers).json()
    if operation == "self_update":
        # RLS deliberately hides the administrator's profile from this member.
        response = client.patch(
            "/api/v1/users/me", headers=member_headers, json={"email": admin["email"]}
        )
    elif operation == "admin_update":
        response = client.patch(
            f"/api/v1/users/{fixture_actors['member']['id']}",
            headers=admin_headers,
            json={"email": admin["email"]},
        )
    else:
        response = client.post(
            "/api/v1/users/",
            headers=admin_headers,
            json={
                "email": admin["email"],
                "identity_entity_id": fixture_actors["unprofiled"][
                    "identity_entity_id"
                ],
            },
        )
    assert response.status_code == 409
    assert response.json() == {
        "detail": "User with this email already exists in this tenant"
    }
    # The failed native write must roll back, leaving the actor and pooled
    # connection usable without widening member profile visibility.
    member_after = client.get("/api/v1/users/me", headers=member_headers)
    assert member_after.status_code == 200
    assert member_after.json()["email"] == member_before["email"]


@pytest.mark.parametrize("operation", ["self_update", "admin_update", "create"])
def test_profile_email_uniqueness_allows_existing_foreign_tenant_email(
    client, fixture_actors, issue_token, operation
):
    admin_headers = issue_token(fixture_actors["admin"])
    foreign = client.get(
        "/api/v1/users/me", headers=issue_token(fixture_actors["foreign_admin"])
    ).json()
    if operation == "self_update":
        response = client.patch(
            "/api/v1/users/me",
            headers=issue_token(fixture_actors["member"]),
            json={"email": foreign["email"]},
        )
    elif operation == "admin_update":
        response = client.patch(
            f"/api/v1/users/{fixture_actors['member']['id']}",
            headers=admin_headers,
            json={"email": foreign["email"]},
        )
    else:
        response = client.post(
            "/api/v1/users/",
            headers=admin_headers,
            json={
                "email": foreign["email"],
                "identity_entity_id": fixture_actors["unprofiled"][
                    "identity_entity_id"
                ],
            },
        )
    assert response.status_code == 200
    assert response.json()["email"] == foreign["email"]
    assert response.json()["tenant_id"] == fixture_actors["admin"]["tenant_id"]
    assert response.json()["tenant_id"] != foreign["tenant_id"]


def test_admin_self_deactivation_returns_committed_state(
    client, fixture_actors, issue_token
):
    actor = fixture_actors["admin"]
    headers = issue_token(actor)
    response = client.patch(
        f"/api/v1/users/{actor['id']}",
        headers=headers,
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert client.get("/api/v1/users/me", headers=headers).status_code == 403


def test_concurrent_canonical_profile_creation_returns_existing_conflict(
    client, fixture_actors, issue_token, runtime_engine, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlmodel import create_engine

    from app import crud
    from app.api import deps

    engine = create_engine(runtime_engine.url, pool_size=2, max_overflow=0)
    monkeypatch.setattr(deps, "engine", engine)
    headers = issue_token(fixture_actors["admin"])
    original_lookup = crud.get_user_by_email
    both_prechecks_complete = Barrier(2)

    def synchronized_lookup(**kwargs):
        result = original_lookup(**kwargs)
        both_prechecks_complete.wait(timeout=30)
        return result

    monkeypatch.setattr(crud, "get_user_by_email", synchronized_lookup)

    def create_profile(email):
        return client.post(
            "/api/v1/users/",
            headers=headers,
            json={
                "email": email,
                "identity_entity_id": fixture_actors["unprofiled"][
                    "identity_entity_id"
                ],
            },
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    create_profile,
                    ["first@fixture.example.com", "second@fixture.example.com"],
                )
            )
        assert sorted(response.status_code for response in responses) == [200, 409]
        conflict = next(
            response for response in responses if response.status_code == 409
        )
        assert conflict.json() == {"detail": "Local actor profile already exists"}
    finally:
        engine.dispose()

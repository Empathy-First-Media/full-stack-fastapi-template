import pytest


def test_same_tenant_crud_and_post_commit_identity(client, fixture_actors, issue_token):
    actor = fixture_actors["member"]
    headers = issue_token(actor)
    created = client.post(
        "/api/v1/items/",
        headers=headers,
        json={"title": "Fixture item", "description": "Original"},
    )
    assert created.status_code == 200
    item = created.json()
    assert item["owner_id"] == actor["id"]
    assert item["tenant_id"] == actor["tenant_id"]
    url = f"/api/v1/items/{item['id']}"
    assert client.get(url, headers=headers).json()["title"] == "Fixture item"
    updated = client.put(url, headers=headers, json={"title": "Changed"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Changed"
    assert updated.json()["owner_id"] == item["owner_id"]
    assert updated.json()["tenant_id"] == item["tenant_id"]
    deleted = client.delete(url, headers=headers)
    assert deleted.status_code == 200
    assert client.get(url, headers=headers).status_code == 404


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_foreign_tenant_admin_cannot_access_item(
    client, fixture_actors, issue_token, method
):
    owner = issue_token(fixture_actors["member"])
    created = client.post(
        "/api/v1/items/", headers=owner, json={"title": "Private tenant fixture"}
    )
    assert created.status_code == 200
    url = f"/api/v1/items/{created.json()['id']}"
    kwargs = {"json": {"title": "Forbidden"}} if method == "put" else {}
    response = getattr(client, method)(
        url, headers=issue_token(fixture_actors["foreign_admin"]), **kwargs
    )
    assert response.status_code == 404
    assert client.get(url, headers=owner).json()["title"] == "Private tenant fixture"


def test_selected_tenant_admin_can_read_member_item(
    client, fixture_actors, issue_token
):
    created = client.post(
        "/api/v1/items/",
        headers=issue_token(fixture_actors["member"]),
        json={"title": "Member fixture"},
    )
    assert created.status_code == 200
    response = client.get(
        f"/api/v1/items/{created.json()['id']}",
        headers=issue_token(fixture_actors["admin"]),
    )
    assert response.status_code == 200


def test_member_cannot_read_another_owner_item(client, fixture_actors, issue_token):
    created = client.post(
        "/api/v1/items/",
        headers=issue_token(fixture_actors["admin"]),
        json={"title": "Other owner fixture"},
    )
    assert created.status_code == 200
    response = client.get(
        f"/api/v1/items/{created.json()['id']}",
        headers=issue_token(fixture_actors["member"]),
    )
    assert response.status_code == 404


def test_selected_tenant_list_does_not_leak_foreign_items(
    client, fixture_actors, issue_token
):
    for name in ("member", "foreign_admin"):
        assert (
            client.post(
                "/api/v1/items/",
                headers=issue_token(fixture_actors[name]),
                json={"title": name},
            ).status_code
            == 200
        )
    response = client.get(
        "/api/v1/items/", headers=issue_token(fixture_actors["admin"])
    )
    assert response.status_code == 200
    assert {item["tenant_id"] for item in response.json()["data"]} == {
        fixture_actors["admin"]["tenant_id"]
    }


@pytest.mark.parametrize("field", ["owner_id", "tenant_id"])
def test_item_attribution_cannot_be_created_or_changed(
    client, fixture_actors, issue_token, field
):
    headers = issue_token(fixture_actors["member"])
    foreign = fixture_actors["foreign_admin"]
    value = foreign["id"] if field == "owner_id" else foreign["tenant_id"]
    denied = client.post(
        "/api/v1/items/",
        headers=headers,
        json={"title": "Injected fixture", field: value},
    )
    assert denied.status_code == 422
    created = client.post(
        "/api/v1/items/", headers=headers, json={"title": "Owned fixture"}
    )
    assert created.status_code == 200
    assert (
        client.put(
            f"/api/v1/items/{created.json()['id']}",
            headers=headers,
            json={field: value},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("actor_name", ["admin", "member"])
def test_write_right_is_explicit_even_for_tenant_admin(
    client, fixture_actors, issue_token, actor_name
):
    headers = issue_token(fixture_actors[actor_name], permissions=["org:projects:read"])
    assert client.get("/api/v1/items/", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/v1/items/", headers=headers, json={"title": "Denied"}
        ).status_code
        == 403
    )


def test_consecutive_tenant_requests_reuse_pool_without_leaking_identity(
    client, fixture_actors, issue_token
):
    for name in ("admin", "foreign_admin", "member", "admin"):
        response = client.get(
            "/api/v1/users/me", headers=issue_token(fixture_actors[name])
        )
        assert response.status_code == 200
        assert response.json()["tenant_id"] == fixture_actors[name]["tenant_id"]
        assert response.json()["id"] == fixture_actors[name]["id"]

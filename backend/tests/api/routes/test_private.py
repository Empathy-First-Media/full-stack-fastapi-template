def test_unauthenticated_private_provisioning_is_retired(client):
    response = client.post(
        "/api/v1/private/users/",
        json={
            "email": "fixture@example.com",
            "password": "not-supported",
            "full_name": "Untrusted fixture",
        },
    )
    assert response.status_code in (404, 405)

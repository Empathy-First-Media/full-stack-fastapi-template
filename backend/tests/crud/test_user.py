import json
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.api import deps
from app.core.auth import VerifiedSession, resolve_principal
from app.models import Item, User


def verified_session(runtime_engine, issue_token, actor, **claims):
    encoded = issue_token(actor, **claims)["Authorization"].removeprefix("Bearer ")
    token = deps.get_token_verifier().verify(encoded)
    return VerifiedSession(runtime_engine, info={"verified_token": token}), token


def test_identity_reinstalled_on_every_transaction_and_cleared_on_pool_return(
    runtime_engine, fixture_actors, issue_token
):
    actor = fixture_actors["admin"]
    session, token = verified_session(runtime_engine, issue_token, actor)
    with session:
        principal = resolve_principal(session, token)
        for _ in range(3):
            session.commit()
            claims = json.loads(
                session.execute(
                    text("SELECT current_setting('request.jwt.claims')")
                ).scalar_one()
            )
            assert claims["sub"] == actor["subject"]
            assert claims["org_id"] == actor["organization_id"]
            assert claims["api_tenant_id"] == actor["tenant_id"]
            assert claims["api_user_id"] == str(principal.user.id)
            assert (
                session.execute(text("SELECT current_user")).scalar_one()
                == "authenticated"
            )
            # Post-commit ORM expiry uses the same actual listener boundary.
            assert session.get(User, UUID(actor["id"])).tenant_id == actor["tenant_id"]
    with runtime_engine.connect() as connection:
        current, original, claims = connection.execute(
            text(
                "SELECT current_user, session_user, current_setting('request.jwt.claims', true)"
            )
        ).one()
        assert current == original
        assert claims in (None, "")


def test_signed_api_claims_cannot_spoof_local_actor(
    runtime_engine, fixture_actors, issue_token
):
    actor = fixture_actors["member"]
    foreign = fixture_actors["foreign_admin"]
    session, token = verified_session(
        runtime_engine,
        issue_token,
        actor,
        api_user_id=foreign["id"],
        api_tenant_id=foreign["tenant_id"],
        api_identity_entity_id=foreign["identity_entity_id"],
    )
    with session:
        principal = resolve_principal(session, token)
        assert str(principal.user.id) == actor["id"]
        claims = json.loads(
            session.execute(
                text("SELECT current_setting('request.jwt.claims')")
            ).scalar_one()
        )
        assert claims["api_user_id"] == actor["id"]
        assert claims["api_tenant_id"] == actor["tenant_id"]


def test_direct_sql_does_not_bypass_tenant_rls(
    runtime_engine, fixture_actors, issue_token, client
):
    owner = fixture_actors["foreign_admin"]
    created = client.post(
        "/api/v1/items/",
        headers=issue_token(owner),
        json={"title": "Foreign direct SQL fixture"},
    )
    assert created.status_code == 200
    session, token = verified_session(
        runtime_engine, issue_token, fixture_actors["admin"]
    )
    with session:
        resolve_principal(session, token)
        assert (
            session.exec(
                select(Item).where(Item.id == UUID(created.json()["id"]))
            ).first()
            is None
        )
        assert (
            session.exec(select(User).where(User.id == UUID(owner["id"]))).first()
            is None
        )


def test_database_rejects_item_tenant_or_owner_reassignment(
    runtime_engine, fixture_actors, issue_token, client
):
    actor = fixture_actors["member"]
    created = client.post(
        "/api/v1/items/",
        headers=issue_token(actor),
        json={"title": "Immutable direct SQL fixture"},
    )
    assert created.status_code == 200
    session, token = verified_session(runtime_engine, issue_token, actor)
    with session:
        resolve_principal(session, token)
        item = session.get(Item, UUID(created.json()["id"]))
        assert item is not None
        item.tenant_id = fixture_actors["foreign_admin"]["tenant_id"]
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
    session, token = verified_session(
        runtime_engine, issue_token, fixture_actors["admin"]
    )
    with session:
        resolve_principal(session, token)
        item = session.get(Item, UUID(created.json()["id"]))
        assert item is not None
        item.owner_id = UUID(fixture_actors["admin"]["id"])
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()

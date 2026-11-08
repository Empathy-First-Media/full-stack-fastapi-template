"""Behavioral RLS acceptance input for an explicitly admitted PostgreSQL fixture.

Canonical tenants, actors, WorkOS projections and the cutover gate must already
exist under their fixture owner. Nothing here establishes production readiness.
"""

import json
import uuid

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import Item, User, get_datetime_utc
from tests.test_data_namespace import isolated_data_engine


@pytest.fixture
def rls_fixture(canonical_actors, fixture_claims):
    migration = isolated_data_engine("API_TEST_MIGRATION_DATABASE_URL")
    runtime = isolated_data_engine("API_TEST_DATABASE_URL")
    assert migration.url.username != runtime.url.username
    with runtime.connect() as connection:
        login_authority = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = session_user"
            )
        ).one()
        assert login_authority == (False, False)
    user_id, foreign_user_id, item_id, foreign_item_id = (
        uuid.uuid4() for _ in range(4)
    )
    tenant_id = canonical_actors["admin"]["tenant_id"]
    foreign_tenant = canonical_actors["foreign_admin"]["tenant_id"]
    actor = uuid.UUID(canonical_actors["admin"]["identity_entity_id"])
    foreign_actor = uuid.UUID(canonical_actors["foreign_admin"]["identity_entity_id"])
    claims = fixture_claims(canonical_actors["admin"])
    claims.update(
        api_user_id=str(user_id),
        api_identity_entity_id=str(actor),
        api_tenant_id=tenant_id,
    )
    with migration.begin() as connection:
        connection.execute(
            insert(User),
            [
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "identity_entity_id": actor,
                    "email": "rls-a@example.com",
                    "is_active": True,
                    "created_at": get_datetime_utc(),
                },
                {
                    "id": foreign_user_id,
                    "tenant_id": foreign_tenant,
                    "identity_entity_id": foreign_actor,
                    "email": "rls-b@example.com",
                    "is_active": True,
                    "created_at": get_datetime_utc(),
                },
            ],
        )
        connection.execute(
            insert(Item),
            [
                {
                    "id": item_id,
                    "owner_id": user_id,
                    "tenant_id": tenant_id,
                    "title": "fixture-a",
                    "created_at": get_datetime_utc(),
                },
                {
                    "id": foreign_item_id,
                    "owner_id": foreign_user_id,
                    "tenant_id": foreign_tenant,
                    "title": "fixture-b",
                    "created_at": get_datetime_utc(),
                },
            ],
        )
    try:
        yield {
            "migration": migration,
            "runtime": runtime,
            "claims": claims,
            "user_id": user_id,
            "foreign_user_id": foreign_user_id,
            "item_id": item_id,
            "foreign_item_id": foreign_item_id,
            "tenant_id": tenant_id,
            "foreign_tenant": foreign_tenant,
        }
    finally:
        with migration.begin() as connection:
            connection.execute(
                delete(Item).where(Item.id.in_([item_id, foreign_item_id]))
            )
            connection.execute(
                delete(User).where(User.id.in_([user_id, foreign_user_id]))
            )
        runtime.dispose()
        migration.dispose()


def install_claims(connection, claims):
    connection.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": json.dumps(claims)},
    )
    connection.execute(text("SET LOCAL ROLE authenticated"))


def test_rls_same_tenant_crud_and_admin_cross_tenant_denial(rls_fixture):
    fixture = rls_fixture
    claims = dict(
        fixture["claims"],
        user_role="admin",
        permissions=["org:projects:read", "org:projects:write"],
    )
    with fixture["runtime"].connect() as connection, connection.begin():
        install_claims(connection, claims)
        role = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        assert role == (False, False)
        flags = connection.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class AS c JOIN pg_namespace AS n ON n.oid=c.relnamespace WHERE n.nspname='api' AND c.relname IN ('user', 'item')"
            )
        ).all()
        assert len(flags) == 2 and all(enabled and forced for enabled, forced in flags)
        assert connection.execute(select(Item.id)).scalars().all() == [
            fixture["item_id"]
        ]
        assert connection.execute(select(User.id)).scalars().all() == [
            fixture["user_id"]
        ]
        assert (
            connection.execute(
                update(Item)
                .where(Item.id == fixture["foreign_item_id"])
                .values(title="forbidden")
            ).rowcount
            == 0
        )
        assert (
            connection.execute(
                update(Item)
                .where(Item.id == fixture["item_id"])
                .values(title="updated")
            ).rowcount
            == 1
        )
        item_id = uuid.uuid4()
        connection.execute(
            insert(Item).values(
                id=item_id,
                tenant_id=fixture["tenant_id"],
                owner_id=fixture["user_id"],
                title="new",
                created_at=get_datetime_utc(),
            )
        )
        assert connection.execute(delete(Item).where(Item.id == item_id)).rowcount == 1
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                insert(Item).values(
                    id=uuid.uuid4(),
                    tenant_id=fixture["foreign_tenant"],
                    owner_id=fixture["foreign_user_id"],
                    title="forbidden",
                    created_at=get_datetime_utc(),
                )
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "foreign-fixture"),
        ("owner_id", uuid.uuid4()),
        ("created_at", get_datetime_utc()),
    ],
)
def test_rls_attribution_cannot_be_rewritten(rls_fixture, field, value):
    fixture = rls_fixture
    claims = dict(
        fixture["claims"], user_role="admin", permissions=["org:projects:write"]
    )
    with fixture["runtime"].connect() as connection, connection.begin():
        install_claims(connection, claims)
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                update(Item).where(Item.id == fixture["item_id"]).values({field: value})
            )


@pytest.mark.parametrize(
    "override",
    [
        {"role": "admin"},
        {"client_id": "foreign-fixture-client"},
        {"iss": "https://foreign-fixture.invalid"},
        {"org_id": "org_foreign_fixture"},
        {"api_identity_entity_id": str(uuid.uuid4())},
        {"api_user_id": None},
        {"api_user_id": str(uuid.uuid4())},
        {"permissions": []},
    ],
)
def test_rls_claim_confusion_and_foreign_binding_deny(rls_fixture, override):
    fixture = rls_fixture
    claims = dict(
        fixture["claims"],
        user_role="admin",
        permissions=["org:projects:read", "org:projects:write"],
    )
    claims.update(override)
    with fixture["runtime"].connect() as connection, connection.begin():
        install_claims(connection, claims)
        assert connection.execute(select(Item.id)).scalars().all() == []


def test_rls_transaction_identity_does_not_survive_commit(rls_fixture):
    fixture = rls_fixture
    with fixture["runtime"].connect() as connection:
        with connection.begin():
            install_claims(
                connection, dict(fixture["claims"], permissions=["org:projects:read"])
            )
            assert connection.execute(select(Item.id)).scalars().all() == [
                fixture["item_id"]
            ]
        with connection.begin():
            connection.execute(text("SET LOCAL ROLE authenticated"))
            assert connection.execute(select(Item.id)).scalars().all() == []


def test_rls_revoked_projected_membership_denies_previous_claims(rls_fixture):
    fixture = rls_fixture
    claims = dict(fixture["claims"], permissions=["org:projects:read"])
    parameters = {"subject": claims["sub"], "organization": claims["org_id"]}
    with fixture["migration"].connect() as owner, owner.begin():
        statuses = owner.execute(
            text(
                "SELECT id, status FROM workos.workosorganizationmembership WHERE user_id=:subject AND organization_id=:organization"
            ),
            parameters,
        ).all()
        assert statuses and all(
            status.strip().lower() == "active" for _, status in statuses
        )
        # Exercise revocation in one fixture-owned transaction, using the same
        # connection under the non-bypass runtime role; rollback preserves owner data.
        owner.execute(
            text(
                "UPDATE workos.workosorganizationmembership SET status='inactive' WHERE user_id=:subject AND organization_id=:organization"
            ),
            parameters,
        )
        install_claims(owner, claims)
        assert owner.execute(select(Item.id)).scalars().all() == []
        owner.execute(text("RESET ROLE"))
        for membership_id, status in statuses:
            owner.execute(
                text(
                    "UPDATE workos.workosorganizationmembership SET status=:status WHERE id=:id"
                ),
                {"id": membership_id, "status": status},
            )


def test_disabled_admin_cached_claims_cannot_mutate_another_profile(
    rls_fixture, canonical_actors
):
    fixture = rls_fixture
    target_id = uuid.uuid4()
    target_actor = uuid.UUID(canonical_actors["member"]["identity_entity_id"])
    claims = dict(
        fixture["claims"],
        user_role="admin",
        permissions=["org:projects:read", "org:projects:write"],
    )
    with fixture["migration"].begin() as owner:
        owner.execute(
            insert(User).values(
                id=target_id,
                tenant_id=fixture["tenant_id"],
                identity_entity_id=target_actor,
                email="revocation-target@example.com",
                is_active=True,
                created_at=get_datetime_utc(),
            )
        )
    try:
        with fixture["runtime"].connect() as connection, connection.begin():
            install_claims(connection, claims)
            assert (
                connection.execute(
                    update(User)
                    .where(User.id == target_id)
                    .values(full_name="before revocation")
                ).rowcount
                == 1
            )
            with fixture["migration"].begin() as owner:
                owner.execute(
                    update(User)
                    .where(User.id == fixture["user_id"])
                    .values(is_active=False)
                )
            assert (
                connection.execute(select(User.id).where(User.id == target_id))
                .scalars()
                .all()
                == []
            )
            assert (
                connection.execute(
                    update(User)
                    .where(User.id == target_id)
                    .values(full_name="forbidden")
                ).rowcount
                == 0
            )
            assert (
                connection.execute(delete(User).where(User.id == target_id)).rowcount
                == 0
            )
    finally:
        with fixture["migration"].begin() as owner:
            owner.execute(
                update(User).where(User.id == fixture["user_id"]).values(is_active=True)
            )
            owner.execute(delete(User).where(User.id == target_id))


def test_tenant_email_uniqueness_survives_member_visibility_boundaries(
    rls_fixture, canonical_actors
):
    fixture = rls_fixture
    target_actor = uuid.UUID(canonical_actors["member"]["identity_entity_id"])
    with fixture["migration"].connect() as owner, owner.begin():
        email = owner.execute(
            select(User.email).where(User.id == fixture["user_id"])
        ).scalar_one()
        with pytest.raises(IntegrityError) as error, owner.begin_nested():
            owner.execute(
                insert(User).values(
                    id=uuid.uuid4(),
                    tenant_id=fixture["tenant_id"],
                    identity_entity_id=target_actor,
                    email=email,
                    is_active=True,
                    created_at=get_datetime_utc(),
                )
            )
        assert error.value.orig.diag.constraint_name == "uq_user_tenant_email"
        assert (
            owner.execute(
                update(User)
                .where(User.id == fixture["foreign_user_id"])
                .values(email=email)
            ).rowcount
            == 1
        )


def test_native_policy_preserves_exact_permission_identity(rls_fixture):
    fixture = rls_fixture
    item_id = uuid.uuid4()
    claims = dict(
        fixture["claims"], user_role="member", permissions=["org:projects:write"]
    )
    with fixture["runtime"].connect() as connection, connection.begin():
        install_claims(connection, claims)
        assert connection.scalar(
            text("SELECT public.has_workos_permission(:permission)"),
            {"permission": "org:projects:write"},
        )
        connection.execute(
            insert(Item).values(
                id=item_id,
                tenant_id=fixture["tenant_id"],
                owner_id=fixture["user_id"],
                title="exact permission",
                created_at=get_datetime_utc(),
            )
        )
        assert (
            connection.execute(select(Item.id).where(Item.id == item_id)).scalar_one()
            == item_id
        )
        install_claims(connection, dict(claims, permissions=[]))
        assert (
            connection.execute(
                update(Item).where(Item.id == item_id).values(title="forbidden")
            ).rowcount
            == 0
        )
        # Keep fixture cleanup independent of which policy a failed assertion reached.
        connection.rollback()

"""Run only on the explicitly admitted isolated PostgreSQL acceptance branch.

The caller supplies existing canonical fixture UUIDs. These tests never create
canonical objects, create a stack, apply migrations, or use a production URL.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import Item, User
from tests.test_data_namespace import isolated_data_engine


@pytest.fixture
def isolated_data_session():
    engine = isolated_data_engine("API_TEST_MIGRATION_DATABASE_URL")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        transaction.rollback()
    engine.dispose()


def test_postgresql_rejects_foreign_tenant_item_owner(
    isolated_data_session, canonical_actors
):
    session = isolated_data_session
    tenant_id = canonical_actors["admin"]["tenant_id"]
    foreign_tenant = canonical_actors["foreign_admin"]["tenant_id"]
    actor = uuid.UUID(canonical_actors["admin"]["identity_entity_id"])
    user = User(
        email="constraint-fixture@example.com",
        tenant_id=tenant_id,
        identity_entity_id=actor,
    )
    session.add(user)
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                Item(title="foreign", owner_id=user.id, tenant_id=foreign_tenant)
            )
            session.flush()
    item = Item(title="same tenant", owner_id=user.id, tenant_id=tenant_id)
    session.add(item)
    session.flush()
    assert (
        session.exec(select(Item).where(Item.id == item.id)).scalar_one().tenant_id
        == tenant_id
    )
    session.refresh(item)
    assert item.created_at.utcoffset() is not None

"""API-owned model contracts; fixtures are not production identity evidence."""

import os
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.models import (
    ItemCreate,
    ItemUpdate,
    UserCreate,
    UserUpdate,
    UserUpdateMe,
)


def isolated_data_engine(variable: str):
    """Admit a real isolated target before fixture data writes are possible."""
    value = os.environ.get(variable)
    if not value:
        pytest.fail(f"{variable} must explicitly select an isolated PostgreSQL target")
    url = make_url(value)
    known_estate_refs = {"irlknjrfypumpsqbeaqi", "mflwqmffctzvwyjiafyj"}
    host = (url.host or "").lower()
    username = (url.username or "").lower()
    if url.get_backend_name() != "postgresql" or any(
        reference in host or reference in username for reference in known_estate_refs
    ):
        pytest.fail(f"{variable} cannot target an estate production/staging project")
    branch = os.environ.get("API_TEST_SUPABASE_BRANCH_REF")
    preview = bool(
        branch
        and branch not in known_estate_refs
        and (host == f"db.{branch}.supabase.co" or username.endswith(f".{branch}"))
    )
    dedicated = bool(url.database and url.database.startswith("api_test_"))
    if not dedicated and not preview:
        pytest.fail(
            f"{variable} requires an api_test_* database or explicitly selected Supabase preview branch"
        )
    engine = create_engine(
        url, pool_size=1, max_overflow=0, pool_reset_on_return="rollback"
    )
    try:
        with engine.connect() as connection:
            actual_database = connection.scalar(text("SELECT current_database()"))
            if actual_database != url.database:
                pytest.fail(
                    f"{variable} selected database does not match PostgreSQL current_database()"
                )
    except BaseException:
        engine.dispose()
        raise
    return engine


def test_user_creation_requires_canonical_actor_without_authority_inputs() -> None:
    actor = uuid.uuid4()
    profile = UserCreate(email="fixture@example.com", identity_entity_id=actor)
    assert profile.identity_entity_id == actor
    for field, value in [
        ("password", "unsafe-password"),
        ("is_superuser", True),
        ("tenant_id", str(uuid.uuid4())),
    ]:
        with pytest.raises(ValidationError):
            UserCreate.model_validate({**profile.model_dump(), field: value})


def test_profile_update_cannot_change_actor_or_tenant() -> None:
    for field in ("tenant_id", "identity_entity_id", "is_superuser", "password"):
        with pytest.raises(ValidationError):
            UserUpdate.model_validate({field: str(uuid.uuid4())})


def test_item_input_cannot_override_attribution() -> None:
    for field in ("tenant_id", "owner_id"):
        with pytest.raises(ValidationError):
            ItemCreate.model_validate({"title": "fixture", field: str(uuid.uuid4())})


@pytest.mark.parametrize(
    "model,field",
    [
        (UserUpdate, "email"),
        (UserUpdate, "is_active"),
        (UserUpdateMe, "email"),
        (ItemUpdate, "title"),
    ],
)
def test_partial_update_rejects_null_required_fields_but_accepts_omission(
    model, field
) -> None:
    assert model.model_validate({}).model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        model.model_validate({field: None})


def test_partial_update_preserves_explicit_nullable_field_clearing() -> None:
    assert UserUpdateMe(full_name=None).model_dump(exclude_unset=True) == {
        "full_name": None
    }
    assert ItemUpdate(description=None).model_dump(exclude_unset=True) == {
        "description": None
    }


@pytest.mark.parametrize(
    "url,branch",
    [
        (
            "postgresql+psycopg://postgres@db.irlknjrfypumpsqbeaqi.supabase.co/postgres",
            "irlknjrfypumpsqbeaqi",
        ),
        (
            "postgresql+psycopg://postgres@db.mflwqmffctzvwyjiafyj.supabase.co/api_test_named",
            "fixturebranchreference",
        ),
        ("postgresql+psycopg://postgres@localhost/postgres", ""),
        (
            "postgresql+psycopg://postgres.irlknjrfypumpsqbeaqi@pooler.supabase.com/api_test_named",
            "",
        ),
    ],
)
def test_data_fixture_refuses_unisolated_or_estate_targets(
    monkeypatch, url, branch
) -> None:
    monkeypatch.setenv("API_TEST_TARGET_GUARD", url)
    monkeypatch.setenv("API_TEST_SUPABASE_BRANCH_REF", branch)
    monkeypatch.setenv("API_TEST_ISOLATED_BRANCH_APPROVED", "true")
    with pytest.raises(pytest.fail.Exception):
        isolated_data_engine("API_TEST_TARGET_GUARD")


if __name__ == "__main__":
    for variable in (
        "API_TEST_MIGRATION_DATABASE_URL",
        "API_TEST_DATABASE_URL",
        "API_TEST_ADMIN_DATABASE_URL",
    ):
        isolated_data_engine(variable).dispose()

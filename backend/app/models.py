import uuid
from datetime import UTC, datetime

from pydantic import EmailStr, field_validator
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlmodel import Field, Relationship, SQLModel

# Reference targets are external contracts, deliberately absent from API metadata.
_external_metadata = MetaData()
_tenant = Table(
    "tenants", _external_metadata, Column("id", Text, primary_key=True), schema="public"
)
_identity_entity = Table(
    "identity_entity",
    _external_metadata,
    Column("id", Uuid, primary_key=True),
    schema="public",
)


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


def reject_explicit_null(value: object) -> object:
    if value is None:
        raise ValueError("This field cannot be null")
    return value


class UserBase(SQLModel):
    email: EmailStr = Field(max_length=255)
    is_active: bool = True
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    model_config = SQLModel.model_config.copy()
    model_config["extra"] = "forbid"
    identity_entity_id: uuid.UUID


class UserUpdate(SQLModel):
    model_config = SQLModel.model_config.copy()
    model_config["extra"] = "forbid"
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)

    _non_null_fields = field_validator("email", "is_active", mode="before")(
        reject_explicit_null
    )


class UserUpdateMe(SQLModel):
    model_config = SQLModel.model_config.copy()
    model_config["extra"] = "forbid"
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)

    _non_null_fields = field_validator("email", mode="before")(reject_explicit_null)


class User(UserBase, table=True):
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_user_id_tenant"),
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        UniqueConstraint(
            "tenant_id", "identity_entity_id", name="uq_user_tenant_actor"
        ),
        {"schema": "api"},
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: str = Field(
        sa_column=Column(
            Text,
            ForeignKey(_tenant.c.id, name="fk_user_tenant"),
            nullable=False,
            index=True,
        )
    )
    identity_entity_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey(_identity_entity.c.id, name="fk_user_identity_entity"),
            nullable=False,
        )
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime
    tenant_id: str
    identity_entity_id: uuid.UUID


class CurrentUserPublic(UserPublic):
    user_role: str
    permissions: list[str]
    is_tenant_admin: bool


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


class ItemCreate(ItemBase):
    """Item creation accepts content, never caller-supplied attribution."""

    model_config = SQLModel.model_config.copy()
    model_config["extra"] = "forbid"


class ItemUpdate(SQLModel):
    model_config = SQLModel.model_config.copy()
    model_config["extra"] = "forbid"
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)

    _non_null_fields = field_validator("title", mode="before")(reject_explicit_null)


class Item(ItemBase, table=True):
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "tenant_id"],
            ["api.user.id", "api.user.tenant_id"],
            name="fk_item_owner_tenant",
            ondelete="CASCADE",
        ),
        {"schema": "api"},
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    owner_id: uuid.UUID = Field(nullable=False)
    tenant_id: str = Field(sa_type=Text, nullable=False, index=True)
    owner: User | None = Relationship(back_populates="items")


class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    tenant_id: str
    created_at: datetime


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


class Message(SQLModel):
    message: str

from fastapi import HTTPException
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.auth import (
    Principal,
    require_canonical_actor,
    require_permission,
    require_tenant_admin,
)
from app.models import Item, ItemCreate, User, UserCreate, UserPublic, UserUpdate

_PROFILE_CONFLICT_DETAILS = {
    "uq_user_tenant_email": "User with this email already exists in this tenant",
    "uq_user_tenant_actor": "Local actor profile already exists",
}


def commit_user_profile(session: Session, profile: User) -> UserPublic:
    """Return flushed state only after commit, without a post-revocation read."""
    try:
        session.flush()
        response = UserPublic.model_validate(profile)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if isinstance(error.orig, UniqueViolation) and error.orig.sqlstate == "23505":
            constraint_name = error.orig.diag.constraint_name
            if (
                constraint_name is not None
                and constraint_name in _PROFILE_CONFLICT_DETAILS
            ):
                raise HTTPException(
                    status_code=409,
                    detail=_PROFILE_CONFLICT_DETAILS[constraint_name],
                ) from error
        raise
    return response


def create_user(
    *, session: Session, principal: Principal, user_create: UserCreate
) -> UserPublic:
    require_tenant_admin(principal, write=True)
    require_canonical_actor(session, principal, user_create.identity_entity_id)
    existing = session.exec(
        select(User).where(
            User.tenant_id == principal.tenant_id,
            User.identity_entity_id == user_create.identity_entity_id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="Local actor profile already exists"
        )
    if get_user_by_email(
        session=session, tenant_id=principal.tenant_id, email=user_create.email
    ):
        raise HTTPException(
            status_code=409, detail="User with this email already exists in this tenant"
        )
    user = User.model_validate(user_create, update={"tenant_id": principal.tenant_id})
    session.add(user)
    return commit_user_profile(session, user)


def update_user(
    *, session: Session, principal: Principal, db_user: User, user_in: UserUpdate
) -> UserPublic:
    require_tenant_admin(principal, write=True)
    if db_user.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.sqlmodel_update(user_in.model_dump(exclude_unset=True))
    session.add(db_user)
    return commit_user_profile(session, db_user)


def get_user_by_email(*, session: Session, tenant_id: str, email: str) -> User | None:
    # Profile uniqueness only: email never resolves or links an authenticated actor.
    return session.exec(
        select(User).where(User.tenant_id == tenant_id, User.email == email)
    ).first()


def create_item(*, session: Session, principal: Principal, item_in: ItemCreate) -> Item:
    require_permission(principal, write=True)
    item = Item.model_validate(
        item_in,
        update={
            "owner_id": principal.user.id,
            "tenant_id": principal.tenant_id,
        },
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item

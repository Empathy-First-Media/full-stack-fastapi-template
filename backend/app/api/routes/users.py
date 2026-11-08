import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, delete, func, select

from app import crud
from app.api.deps import CurrentPrincipal, SessionDep
from app.core.auth import Principal, require_permission, require_tenant_admin
from app.models import (
    CurrentUserPublic,
    Item,
    Message,
    User,
    UserCreate,
    UserPublic,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)

router = APIRouter(prefix="/users", tags=["users"])


def tenant_user(session: SessionDep, principal: Principal, user_id: uuid.UUID) -> User:
    user = session.exec(
        select(User).where(User.id == user_id, User.tenant_id == principal.tenant_id)
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def check_profile_email(
    session: SessionDep, principal: Principal, user: User, email: str | None
) -> None:
    if email:
        existing = crud.get_user_by_email(
            session=session, tenant_id=principal.tenant_id, email=email
        )
        if existing and existing.id != user.id:
            raise HTTPException(
                status_code=409,
                detail="User with this email already exists in this tenant",
            )


@router.get("/", response_model=UsersPublic)
def read_users(
    session: SessionDep,
    principal: CurrentPrincipal,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
) -> UsersPublic:
    require_tenant_admin(principal)
    scope = col(User.tenant_id) == principal.tenant_id
    count = session.exec(select(func.count()).select_from(User).where(scope)).one()
    users = session.exec(
        select(User)
        .where(scope)
        .order_by(col(User.created_at).desc(), col(User.id))
        .offset(skip)
        .limit(limit)
    ).all()
    return UsersPublic(
        data=[UserPublic.model_validate(user) for user in users], count=count
    )


@router.post("/", response_model=UserPublic)
def create_user(
    *, session: SessionDep, principal: CurrentPrincipal, user_in: UserCreate
) -> UserPublic:
    """Create a local profile for an existing tenant-bound canonical actor."""
    return crud.create_user(session=session, principal=principal, user_create=user_in)


@router.get("/me", response_model=CurrentUserPublic)
def read_user_me(principal: CurrentPrincipal) -> CurrentUserPublic:
    return CurrentUserPublic.model_validate(
        principal.user,
        update={
            "user_role": principal.user_role,
            "permissions": sorted(principal.permissions),
            "is_tenant_admin": principal.is_tenant_admin,
        },
    )


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, principal: CurrentPrincipal, user_in: UserUpdateMe
) -> UserPublic:
    require_permission(principal, write=True)
    check_profile_email(session, principal, principal.user, user_in.email)
    principal.user.sqlmodel_update(user_in.model_dump(exclude_unset=True))
    session.add(principal.user)
    return crud.commit_user_profile(session, principal.user)


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, principal: CurrentPrincipal) -> Message:
    require_permission(principal, write=True)
    session.exec(
        delete(Item).where(
            col(Item.tenant_id) == principal.tenant_id,
            col(Item.owner_id) == principal.user.id,
        )
    )
    session.delete(principal.user)
    session.commit()
    return Message(message="Local user profile deleted successfully")


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal
) -> User:
    require_permission(principal)
    if user_id != principal.user.id:
        require_tenant_admin(principal)
    return tenant_user(session, principal, user_id)


@router.patch("/{user_id}", response_model=UserPublic)
def update_user(
    *,
    session: SessionDep,
    principal: CurrentPrincipal,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> UserPublic:
    require_tenant_admin(principal, write=True)
    user = tenant_user(session, principal, user_id)
    check_profile_email(session, principal, user, user_in.email)
    return crud.update_user(
        session=session, principal=principal, db_user=user, user_in=user_in
    )


@router.delete("/{user_id}", response_model=Message)
def delete_user(
    session: SessionDep, principal: CurrentPrincipal, user_id: uuid.UUID
) -> Message:
    require_tenant_admin(principal, write=True)
    user = tenant_user(session, principal, user_id)
    session.exec(
        delete(Item).where(
            col(Item.owner_id) == user_id,
            col(Item.tenant_id) == principal.tenant_id,
        )
    )
    session.delete(user)
    session.commit()
    return Message(message="Local user profile deleted successfully")

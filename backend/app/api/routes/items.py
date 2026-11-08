import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import ColumnElement
from sqlmodel import col, func, select

from app import crud
from app.api.deps import CurrentPrincipal, SessionDep
from app.core.auth import Principal, require_permission
from app.models import Item, ItemCreate, ItemPublic, ItemsPublic, ItemUpdate, Message

router = APIRouter(prefix="/items", tags=["items"])


def item_scope(principal: Principal) -> list[ColumnElement[bool]]:
    scope: list[ColumnElement[bool]] = [col(Item.tenant_id) == principal.tenant_id]
    if not principal.is_tenant_admin:
        scope.append(col(Item.owner_id) == principal.user.id)
    return scope


def scoped_item(session: SessionDep, principal: Principal, item_id: uuid.UUID) -> Item:
    item = session.exec(
        select(Item).where(Item.id == item_id, *item_scope(principal))
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/", response_model=ItemsPublic)
def read_items(
    session: SessionDep,
    principal: CurrentPrincipal,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
) -> ItemsPublic:
    require_permission(principal)
    scope = item_scope(principal)
    count = session.exec(select(func.count()).select_from(Item).where(*scope)).one()
    items = session.exec(
        select(Item)
        .where(*scope)
        .order_by(col(Item.created_at).desc(), col(Item.id))
        .offset(skip)
        .limit(limit)
    ).all()
    return ItemsPublic(
        data=[ItemPublic.model_validate(item) for item in items], count=count
    )


@router.get("/{id}", response_model=ItemPublic)
def read_item(session: SessionDep, principal: CurrentPrincipal, id: uuid.UUID) -> Item:
    require_permission(principal)
    return scoped_item(session, principal, id)


@router.post("/", response_model=ItemPublic)
def create_item(
    *, session: SessionDep, principal: CurrentPrincipal, item_in: ItemCreate
) -> Item:
    return crud.create_item(session=session, principal=principal, item_in=item_in)


@router.put("/{id}", response_model=ItemPublic)
def update_item(
    *,
    session: SessionDep,
    principal: CurrentPrincipal,
    id: uuid.UUID,
    item_in: ItemUpdate,
) -> Item:
    require_permission(principal, write=True)
    item = scoped_item(session, principal, id)
    item.sqlmodel_update(item_in.model_dump(exclude_unset=True))
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{id}", response_model=Message)
def delete_item(
    session: SessionDep, principal: CurrentPrincipal, id: uuid.UUID
) -> Message:
    require_permission(principal, write=True)
    item = scoped_item(session, principal, id)
    session.delete(item)
    session.commit()
    return Message(message="Item deleted successfully")

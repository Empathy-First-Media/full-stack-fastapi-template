"""Request SQL identity and read-only access to the canonical product owners."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import UUID
from weakref import WeakKeyDictionary

from fastapi import HTTPException
from sqlalchemy import MetaData, String, Table, cast, event, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import SessionTransaction
from sqlmodel import Session, col
from sqlmodel import select as model_select

from app.core.security import VerifiedAccessToken
from app.models import User


class VerifiedSession(Session):
    """A request session: identity is reinstalled on EVERY autobegin, not only once."""


@event.listens_for(VerifiedSession, "after_begin")
def install_transaction_identity(
    session: VerifiedSession, _transaction: SessionTransaction, connection: Connection
) -> None:
    token: VerifiedAccessToken | None = session.info.get("verified_token")
    if token is None:
        raise RuntimeError("SQL access requires a verified WorkOS token")
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Verified SQL sessions require PostgreSQL RLS")
    if token.claims["exp"] <= datetime.now(UTC).timestamp():
        raise HTTPException(status_code=401, detail="Access token expired")
    runtime_role = connection.execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = session_user"
        )
    ).one()
    if runtime_role.rolsuper or runtime_role.rolbypassrls:
        raise RuntimeError("API runtime role must be non-superuser and NOBYPASSRLS")
    connection.execute(text("SET LOCAL ROLE authenticated"))
    claims = session.info.get("request_claims")
    if claims is None:
        claims = {
            name: value
            for name, value in token.claims.items()
            if not name.startswith("api_")
        }
        session.info["request_claims"] = claims
    connection.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": json.dumps(claims, separators=(",", ":"))},
    )
    # SET LOCAL + the pool's rollback-on-return removes role and claims on both
    # success and failure. No request identity is stored on a pooled Connection.


@dataclass(frozen=True)
class Principal:
    user: User
    tenant_id: str
    organization_id: str
    subject: str
    user_role: str
    permissions: frozenset[str]
    is_tenant_admin: bool


class CanonicalIdentity:
    def __init__(self, connection: Connection):
        # Reflect, never redeclare or create the product's tables in API metadata.
        metadata = MetaData()
        self.tenants = Table(
            "tenants",
            metadata,
            schema="public",
            autoload_with=connection,
            resolve_fks=False,
        )
        self.entities = Table(
            "identity_entity",
            metadata,
            schema="public",
            autoload_with=connection,
            resolve_fks=False,
        )
        self.external = Table(
            "identity_external",
            metadata,
            schema="public",
            autoload_with=connection,
            resolve_fks=False,
        )
        self.memberships = Table(
            "workosorganizationmembership",
            metadata,
            schema="workos",
            autoload_with=connection,
            resolve_fks=False,
        )


_contracts: WeakKeyDictionary[Engine, CanonicalIdentity] = WeakKeyDictionary()
_contract_lock = Lock()


def canonical_identity(session: Session) -> CanonicalIdentity:
    connection = session.connection()
    engine = connection.engine
    with _contract_lock:
        contract = _contracts.get(engine)
        if contract is None:
            contract = CanonicalIdentity(connection)
            _contracts[engine] = contract
        return contract


def deny_mapping() -> HTTPException:
    return HTTPException(
        status_code=403, detail="No active tenant identity association"
    )


def active_membership(
    session: Session, contract: CanonicalIdentity, subject: str, organization_id: str
) -> Any:
    m = contract.memberships.c
    rows = (
        session.connection()
        .execute(
            select(m.role, m.roles, m.status).where(
                m.user_id == subject,
                m.organization_id == organization_id,
            )
        )
        .all()
    )
    if len(rows) != 1:
        raise deny_mapping()
    membership = rows[0]
    if (
        not isinstance(membership.status, str)
        or membership.status.strip().lower() != "active"
    ):
        raise deny_mapping()
    if (
        not isinstance(membership.role, str)
        or not membership.role
        or membership.roles not in ([], [membership.role])
    ):
        raise deny_mapping()
    return membership


def resolve_principal(session: Session, token: VerifiedAccessToken) -> Principal:
    # Existing SECURITY DEFINER helper owns private issuer/client/enabled state.
    # No alternate gate, private-table read or fallback to a catalog environment.
    if (
        session.connection()
        .execute(text("SELECT public.current_workos_org_id()"))
        .scalar_one()
        != token.organization_id
    ):
        raise deny_mapping()
    contract = canonical_identity(session)
    membership = active_membership(
        session, contract, token.subject, token.organization_id
    )
    if membership.role != token.user_role:
        raise deny_mapping()
    t, e, x = contract.tenants.c, contract.entities.c, contract.external.c
    matches = (
        session.connection()
        .execute(
            select(t.id, e.id.label("identity_entity_id"))
            .select_from(
                contract.tenants.join(
                    contract.entities, cast(e.tenant_id, String) == cast(t.id, String)
                ).join(contract.external, x.entity_id == e.id)
            )
            .where(
                t.workos_org_id == token.organization_id,
                e.kind == "user",
                x.provider == "workos",
                x.external_id == token.subject,
            )
        )
        .all()
    )
    if len(matches) != 1:
        raise deny_mapping()
    match = matches[0]
    tenant_id = str(match.id)
    claims = session.info["request_claims"]
    claims.update(
        api_tenant_id=tenant_id, api_identity_entity_id=str(match.identity_entity_id)
    )
    session.connection().execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": json.dumps(claims, separators=(",", ":"))},
    )
    users = session.exec(
        model_select(User).where(
            col(User.tenant_id) == tenant_id,
            col(User.identity_entity_id) == match.identity_entity_id,
        )
    ).all()
    if len(users) != 1 or not users[0].is_active:
        raise deny_mapping()
    claims["api_user_id"] = str(users[0].id)
    session.connection().execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": json.dumps(claims, separators=(",", ":"))},
    )
    return Principal(
        user=users[0],
        tenant_id=tenant_id,
        organization_id=token.organization_id,
        subject=token.subject,
        user_role=token.user_role,
        permissions=token.permissions,
        is_tenant_admin=token.user_role == "admin",
    )


def require_canonical_actor(
    session: Session, principal: Principal, entity_id: UUID
) -> None:
    """Verify the existing tenant-bound crosswalk, not private target membership.

    A local profile grants no WorkOS membership or role. The target must pass
    the ordinary active-membership/claim checks independently on authentication.
    """
    contract = canonical_identity(session)
    e, x = contract.entities.c, contract.external.c
    rows = (
        session.connection()
        .execute(
            select(x.external_id)
            .select_from(contract.entities.join(contract.external, x.entity_id == e.id))
            .where(
                e.id == entity_id,
                cast(e.tenant_id, String) == str(principal.tenant_id),
                e.kind == "user",
                x.provider == "workos",
            )
        )
        .all()
    )
    if len(rows) != 1:
        raise deny_mapping()


def require_permission(principal: Principal, *, write: bool = False) -> None:
    required = (
        {"org:projects:write"} if write else {"org:projects:read", "org:projects:write"}
    )
    if not principal.permissions.intersection(required):
        raise HTTPException(status_code=403, detail="Not enough permissions")


def require_tenant_admin(principal: Principal, *, write: bool = False) -> None:
    require_permission(principal, write=write)
    if not principal.is_tenant_admin:
        raise HTTPException(status_code=403, detail="Tenant administrator required")

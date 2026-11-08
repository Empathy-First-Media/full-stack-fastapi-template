"""API-owned security declarations consumed by native Alembic generators.

Canonical identity, memberships and the issuer/client gate are external owners.
"""
from alembic_utils.pg_function import PGFunction
from alembic_utils.pg_grant_table import PGGrantTable
from alembic_utils.pg_policy import PGPolicy
from alembic_utils.pg_trigger import PGTrigger


# Claims with api_ names are installed only after the backend resolves the
# canonical actor; incoming token fields with those names are discarded.
SCOPE = """
    (SELECT auth.jwt()->>'role') = 'authenticated'
    AND {row}.tenant_id = (SELECT auth.jwt()->>'api_tenant_id')
    AND (SELECT public.is_workos_token_bound())
    AND (SELECT public.has_active_workos_membership())
    AND EXISTS (
        SELECT 1 FROM public.tenants AS t
        WHERE t.id = {row}.tenant_id
          AND t.workos_org_id = (SELECT public.current_workos_org_id())
    )
    AND 1 = (
        SELECT count(*) FROM public.identity_external AS x
        JOIN public.identity_entity AS e ON e.id = x.entity_id
        WHERE x.provider = 'workos'
          AND x.external_id = (SELECT auth.jwt()->>'sub')
          AND e.kind = 'user' AND e.tenant_id = {row}.tenant_id
          AND e.id::text = (SELECT auth.jwt()->>'api_identity_entity_id')
    )
"""
RESOLVED = "(SELECT NULLIF(auth.jwt()->>'api_user_id', '')) IS NOT NULL"
LIVE_ACTOR = "(SELECT api.current_actor_is_active())"
ADMIN = "(SELECT public.current_workos_user_role()) = 'admin'"
READ = "((SELECT public.has_workos_permission('org:projects:read')) OR (SELECT public.has_workos_permission('org:projects:write')))"
WRITE = "(SELECT public.has_workos_permission('org:projects:write'))"
USER_SELF = "identity_entity_id::text = (SELECT auth.jwt()->>'api_identity_entity_id')"
TARGET_ACTOR = """EXISTS (
    SELECT 1 FROM public.identity_entity AS target
    JOIN public.identity_external AS target_external
      ON target_external.entity_id = target.id AND target_external.provider = 'workos'
    WHERE target.id = {row}.identity_entity_id AND target.kind = 'user'
      AND target.tenant_id = {row}.tenant_id
)"""
ITEM_OWNER = "(owner_id::text = (SELECT auth.jwt()->>'api_user_id') OR " + ADMIN + ")"
ITEM_ACTOR = """EXISTS (
    SELECT 1 FROM api."user" AS actor
    WHERE actor.id::text = (SELECT auth.jwt()->>'api_user_id')
      AND actor.identity_entity_id::text = (SELECT auth.jwt()->>'api_identity_entity_id')
      AND actor.tenant_id = api.item.tenant_id AND actor.is_active
)"""


def policy(table: str, action: str, condition: str) -> PGPolicy:
    clauses = f"AS PERMISSIVE FOR {action} TO authenticated "
    if action != "INSERT":
        clauses += f"USING ({condition}) "
    if action in {"INSERT", "UPDATE"}:
        clauses += f"WITH CHECK ({condition})"
    return PGPolicy(schema="api", signature=f"{table}_{action.lower()}", on_entity=f'api."{table}"', definition=clauses)


user_scope = "(" + SCOPE.format(row='api."user"') + ") AND (" + TARGET_ACTOR.format(row='api."user"') + ")"
user_select = f"{user_scope} AND (({USER_SELF} AND is_active) OR ({RESOLVED} AND {LIVE_ACTOR} AND {ADMIN} AND {READ}))"
user_mutation = f"{user_scope} AND {RESOLVED} AND {LIVE_ACTOR} AND {WRITE} AND ({USER_SELF} OR {ADMIN})"
item_scope = "(" + SCOPE.format(row="api.item") + f") AND {RESOLVED} AND {ITEM_OWNER} AND ({ITEM_ACTOR})"

# User policies cannot recursively query User under RLS. This boolean-only helper
# uses the separately verified migration owner; native ACLs deny PUBLIC execution.
# STABLE uses each statement's snapshot, not a cached principal's earlier state.
entities = [
    PGFunction(
        schema="api", signature="current_actor_is_active()",
        definition="""RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = '' SET row_security = off AS $$
            SELECT EXISTS (
                SELECT 1 FROM api."user" AS actor
                WHERE actor.id::text = (SELECT auth.jwt()->>'api_user_id')
                  AND actor.identity_entity_id::text = (SELECT auth.jwt()->>'api_identity_entity_id')
                  AND actor.tenant_id = (SELECT auth.jwt()->>'api_tenant_id')
                  AND actor.is_active
            )
        $$""",
    ),
    policy("user", "SELECT", user_select),
    policy("user", "INSERT", f"{user_scope} AND {RESOLVED} AND {LIVE_ACTOR} AND {ADMIN} AND {WRITE}"),
    policy("user", "UPDATE", user_mutation),
    policy("user", "DELETE", user_mutation),
    policy("item", "SELECT", f"{item_scope} AND {READ}"),
    policy("item", "INSERT", f"{item_scope} AND {WRITE} AND owner_id::text = (SELECT auth.jwt()->>'api_user_id')"),
    policy("item", "UPDATE", f"{item_scope} AND {WRITE}"),
    policy("item", "DELETE", f"{item_scope} AND {WRITE}"),
]

# Column grants complement triggers: attribution cannot be reassigned through
# direct SQL even when a tenant administrator has row-level mutation authority.
for table, insert_columns, update_columns in (
    ("user", ["id", "tenant_id", "identity_entity_id", "email", "is_active", "full_name", "created_at"], ["email", "is_active", "full_name"]),
    ("item", ["id", "tenant_id", "owner_id", "title", "description", "created_at"], ["title", "description"]),
):
    entities.append(PGGrantTable(schema="api", table=table, role="authenticated", grant="SELECT", columns=insert_columns))
    entities.append(PGGrantTable(schema="api", table=table, role="authenticated", grant="DELETE"))
    entities.append(PGGrantTable(schema="api", table=table, role="authenticated", grant="INSERT", columns=insert_columns))
    entities.append(PGGrantTable(schema="api", table=table, role="authenticated", grant="UPDATE", columns=update_columns))

for table, attribution in (
    ("user", "id, tenant_id, identity_entity_id, created_at"),
    ("item", "id, tenant_id, owner_id, created_at"),
):
    old = ", ".join(f"OLD.{column.strip()}" for column in attribution.split(","))
    new = ", ".join(f"NEW.{column.strip()}" for column in attribution.split(","))
    entities.append(PGFunction(
        schema="api", signature=f"protect_{table}_attribution()",
        definition=f"""RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        BEGIN
            IF ROW({old}) IS DISTINCT FROM ROW({new}) THEN
                RAISE EXCEPTION 'API attribution is immutable' USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END;
        $$""",
    ))
    entities.append(PGTrigger(
        schema="api", signature=f"protect_{table}_attribution", on_entity=f'api."{table}"',
        definition=f'BEFORE UPDATE ON api."{table}" FOR EACH ROW EXECUTE FUNCTION api.protect_{table}_attribution()',
    ))

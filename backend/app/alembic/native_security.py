"""Native PostgreSQL AST generation for grammar absent from alembic-utils.

Alembic owns revision emission; pglast owns PostgreSQL syntax rendering. This
hook adds API schema usage, ENABLE/FORCE RLS and restricted helper execution.
Policies, table/column grants and immutable-attribution triggers use alembic-utils.
"""
from alembic.autogenerate import rewriter
from alembic.operations import ops
from alembic_utils.pg_function import PGFunction
from alembic_utils.replaceable_entity import ReplaceableEntity
from alembic_utils.reversible_op import CreateOp, DropOp, ReplaceOp, RevertOp
from pglast import ast
from pglast.stream import RawStream
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause


def schema_usage(is_grant: bool) -> str:
    return RawStream()(ast.GrantStmt(
        is_grant=is_grant,
        targtype="ACL_TARGET_OBJECT",
        objtype="OBJECT_SCHEMA",
        objects=(ast.String(sval="api"),),
        privileges=(ast.AccessPriv(priv_name="USAGE"),),
        grantees=(ast.RoleSpec(roletype="ROLESPEC_CSTRING", rolename="authenticated"),),
        grant_option=False,
        behavior="DROP_RESTRICT",
    ))


def table_rls(table: str) -> str:
    return RawStream()(ast.AlterTableStmt(
        relation=ast.RangeVar(schemaname="api", relname=table, inh=True, relpersistence="p"),
        cmds=(
            ast.AlterTableCmd(subtype="AT_EnableRowSecurity", behavior="DROP_RESTRICT", missing_ok=False),
            ast.AlterTableCmd(subtype="AT_ForceRowSecurity", behavior="DROP_RESTRICT", missing_ok=False),
        ),
        objtype="OBJECT_TABLE",
        missing_ok=False,
    ))


def actor_helper_execute(is_grant: bool, public: bool) -> str:
    role = ast.RoleSpec(roletype="ROLESPEC_PUBLIC") if public else ast.RoleSpec(
        roletype="ROLESPEC_CSTRING", rolename="authenticated",
    )
    return RawStream()(ast.GrantStmt(
        is_grant=is_grant,
        targtype="ACL_TARGET_OBJECT",
        objtype="OBJECT_FUNCTION",
        objects=(ast.ObjectWithArgs(
            objname=(ast.String(sval="api"), ast.String(sval="current_actor_is_active")),
            objargs=(), args_unspecified=False,
        ),),
        privileges=(ast.AccessPriv(priv_name="EXECUTE"),),
        grantees=(role,),
        grant_option=False,
        behavior="DROP_RESTRICT",
    ))


entity_writer = rewriter.Rewriter()


@entity_writer.rewrites(CreateOp)
@entity_writer.rewrites(DropOp)
@entity_writer.rewrites(ReplaceOp)
@entity_writer.rewrites(RevertOp)
def lower_entity_sql(context, revision, operation):
    """Select Alembic's native SQL artifact mode without replaying constructors."""
    target = operation.target
    if not isinstance(target, ReplaceableEntity) or target.schema != "api":
        return operation
    if isinstance(operation, RevertOp):
        connection = context.connection
        expected_snapshot = context.opts.get("api_autogen_snapshot")
        if (
            connection is None or not connection.in_transaction()
            or connection.get_isolation_level() != "REPEATABLE READ"
            or expected_snapshot is None
            or connection.scalar(text("SELECT pg_current_snapshot()::text")) != expected_snapshot
        ):
            raise RuntimeError("Entity reversal requires the original autogeneration snapshot")
        # Use only the vendor's public reflection factory under the SAME native
        # transaction snapshot as its comparator, never its private cache.
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            old = [
                candidate for candidate in type(target).from_database(session, target.schema)
                if candidate.identity == target.identity
            ]
        if (
            not connection.in_transaction()
            or connection.scalar(text("SELECT pg_current_snapshot()::text")) != expected_snapshot
        ):
            raise RuntimeError("Vendor reflection changed the original autogeneration snapshot")
        if len(old) != 1:
            raise RuntimeError("Entity reversal snapshot is missing or ambiguous")
        statements = old[0].to_sql_statement_create_or_replace()
    elif isinstance(operation, DropOp):
        statements = [target.to_sql_statement_drop(cascade=operation.cascade)]
    elif isinstance(operation, CreateOp):
        statements = [target.to_sql_statement_create()]
    else:
        statements = target.to_sql_statement_create_or_replace()
    lowered = []
    for statement in statements:
        if not isinstance(statement, TextClause):
            raise TypeError("Vendor entity SQL must be a native TextClause")
        # Preserve vendor emission verbatim. Native SQLAlchemy execution consumes
        # its one bind-colon escape; no extra entity constructor is serialized.
        lowered.append(ops.ExecuteSQLOp(statement.text))
    return lowered


def process_revision_directives(context, revision, directives):
    if not directives:
        return
    migration = directives[0]
    for upgrade in migration.upgrade_ops_list:
        expanded = []
        created = False
        for operation in upgrade.ops:
            expanded.append(operation)
            target = getattr(operation, "target", None)
            if (
                isinstance(operation, (CreateOp, ReplaceOp))
                and isinstance(target, PGFunction) and target.schema == "api"
                and target.signature == "current_actor_is_active()"
            ):
                expanded.append(ops.ExecuteSQLOp(actor_helper_execute(False, public=True)))
                expanded.append(ops.ExecuteSQLOp(actor_helper_execute(True, public=False)))
            if isinstance(operation, ops.CreateTableOp) and operation.schema == "api":
                created = True
                expanded.append(ops.ExecuteSQLOp(table_rls(operation.table_name)))
        if created and not revision:
            expanded.insert(0, ops.ExecuteSQLOp(schema_usage(True)))
        upgrade.ops = expanded
    if not revision:
        for downgrade in migration.downgrade_ops_list:
            downgrade.ops.append(ops.ExecuteSQLOp(schema_usage(False)))
    entity_writer(context, revision, directives)

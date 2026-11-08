"""Native Alembic SQL-artifact fidelity; no policy compiler or vendor patch."""

import ast as python_ast
import uuid

import pytest
from alembic.autogenerate import render_python_code
from alembic.migration import MigrationContext
from alembic.operations import ops
from alembic_utils.pg_function import PGFunction
from alembic_utils.pg_grant_table import PGGrantTable
from alembic_utils.pg_policy import PGPolicy
from alembic_utils.pg_trigger import PGTrigger
from alembic_utils.reversible_op import CreateOp, DropOp, ReplaceOp
from pglast import parse_sql
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.alembic.native_security import entity_writer
from app.alembic.security import entities
from tests.test_data_namespace import isolated_data_engine

PREDICATES = [
    "'org:projects:write' = 'org:projects:write'",
    "':bind_like' = ':bind_like'",
    "'https://example.invalid/a:b' = 'https://example.invalid/a:b'",
    r"'literal\:value' = 'literal\:value'",
    r"'literal\\slash:tail' = 'literal\\slash:tail'",
    "NULL::text IS NULL",
    r"E'line\n:colon' = E'line\n:colon'",
    "$$:bind_like$$ = $$:bind_like$$",
]


def serialized_statements(operation, context=None):
    context = context or MigrationContext.configure(dialect=postgresql.dialect())
    migration = ops.MigrationScript(
        None, ops.UpgradeOps([operation]), ops.DowngradeOps([])
    )
    entity_writer(context, (), [migration])
    rendered = render_python_code(migration.upgrade_ops)
    tree = python_ast.parse("def native_migration():\n" + rendered)
    statements = []
    for call in (
        node for node in python_ast.walk(tree) if isinstance(node, python_ast.Call)
    ):
        assert (
            isinstance(call.func, python_ast.Attribute) and call.func.attr == "execute"
        )
        payload = python_ast.literal_eval(call.args[0])
        compiled = text(payload).compile(dialect=postgresql.dialect())
        assert not compiled.params
        statements.extend(parse_sql(str(compiled)))
    return tuple(statements)


@pytest.mark.parametrize("predicate", PREDICATES)
@pytest.mark.parametrize("kind", ["create", "replace", "drop", "cascade_drop"])
def test_native_policy_artifact_preserves_literal_semantics(predicate, kind):
    definition = f"AS PERMISSIVE FOR SELECT TO authenticated USING ({predicate})"
    policy = PGPolicy(
        schema="api",
        signature="literal_fixture",
        on_entity="api.item",
        definition=definition,
    )
    create = f"CREATE POLICY literal_fixture ON api.item {definition}"
    if kind == "create":
        operation, expected = CreateOp(policy), create
    elif kind == "replace":
        operation = ReplaceOp(policy)
        expected = f"DROP POLICY IF EXISTS literal_fixture ON api.item; {create}"
    else:
        cascade = kind == "cascade_drop"
        operation = DropOp(policy, cascade=cascade)
        expected = "DROP POLICY literal_fixture ON api.item" + (
            " CASCADE" if cascade else ""
        )
    assert serialized_statements(operation) == parse_sql(expected)


@pytest.mark.parametrize(
    "definition",
    [
        "FOR SELECT USING (true)",
        "AS RESTRICTIVE FOR SELECT TO authenticated USING (true)",
    ],
)
def test_native_policy_artifact_preserves_default_role_and_mode(definition):
    policy = PGPolicy(
        schema="api",
        signature="mode_fixture",
        on_entity="api.item",
        definition=definition,
    )
    assert serialized_statements(CreateOp(policy)) == parse_sql(
        f"CREATE POLICY mode_fixture ON api.item {definition}"
    )


def test_revert_without_original_native_snapshot_fails_closed():
    policy = PGPolicy(
        schema="api",
        signature="snapshot_fixture",
        on_entity="api.item",
        definition="FOR SELECT USING (true)",
    )
    with pytest.raises(RuntimeError, match="original autogeneration snapshot"):
        serialized_statements(ReplaceOp(policy).reverse())


@pytest.mark.parametrize("predicate", PREDICATES)
def test_revert_uses_public_factory_in_same_repeatable_read_snapshot(predicate):
    engine = isolated_data_engine("API_TEST_MIGRATION_DATABASE_URL")
    try:
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                snapshot = connection.scalar(text("SELECT pg_current_snapshot()::text"))
                name = "serializer_" + uuid.uuid4().hex
                old = PGPolicy(
                    schema="api",
                    signature=name,
                    on_entity="api.item",
                    definition=f"AS RESTRICTIVE FOR SELECT TO authenticated USING ({predicate})",
                )
                connection.execute(old.to_sql_statement_create())
                actual_clause = connection.scalar(
                    text(
                        "SELECT qual FROM pg_policies WHERE schemaname='api' AND tablename='item' AND policyname=:name"
                    ),
                    {"name": name},
                )
                new = PGPolicy(
                    schema="api",
                    signature=name,
                    on_entity="api.item",
                    definition="FOR SELECT USING (false)",
                )
                context = MigrationContext.configure(
                    connection, opts={"api_autogen_snapshot": snapshot}
                )
                expected = f"DROP POLICY IF EXISTS {name} ON api.item; CREATE POLICY {name} ON api.item AS RESTRICTIVE FOR SELECT TO authenticated USING ({actual_clause})"
                assert serialized_statements(
                    ReplaceOp(new).reverse(), context
                ) == parse_sql(expected)
                assert (
                    connection.scalar(text("SELECT pg_current_snapshot()::text"))
                    == snapshot
                )
                connection.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["create", "replace", "drop", "cascade_drop"])
@pytest.mark.parametrize("entity_kind", ["function", "trigger", "grant"])
def test_generic_entity_artifacts_preserve_native_defaults_and_cascade(
    entity_kind, kind
):
    if entity_kind == "function":
        declaration = "RETURNS text LANGUAGE sql AS $$ SELECT value || ':tail' $$"
        signature = "literal_fixture(value text DEFAULT 'default:tail')"
        entity = PGFunction(schema="api", signature=signature, definition=declaration)
        create = f"CREATE FUNCTION api.{signature} {declaration}"
        replace = f"CREATE OR REPLACE FUNCTION api.{signature} {declaration}"
        drop = "DROP FUNCTION api.literal_fixture(value text)"
    elif entity_kind == "trigger":
        declaration = "BEFORE UPDATE ON api.item FOR EACH ROW EXECUTE FUNCTION api.protect_item_attribution()"
        entity = PGTrigger(
            schema="api",
            signature="literal_fixture",
            on_entity="api.item",
            definition=declaration,
        )
        create = f"CREATE TRIGGER literal_fixture {declaration}"
        replace = f"DROP TRIGGER IF EXISTS literal_fixture ON api.item; {create}"
        drop = "DROP TRIGGER literal_fixture ON api.item"
    else:
        entity = PGGrantTable(
            schema="api",
            table="item",
            role="authenticated",
            grant="UPDATE",
            columns=["title", "description"],
        )
        create = "GRANT UPDATE (description, title) ON api.item TO authenticated"
        drop = "REVOKE UPDATE ON api.item FROM authenticated"
        replace = f"{drop}; {create}"
    if kind == "create":
        operation, expected = CreateOp(entity), create
    elif kind == "replace":
        operation, expected = ReplaceOp(entity), replace
    else:
        operation = DropOp(entity, cascade=kind == "cascade_drop")
        expected = drop + (
            " CASCADE" if kind == "cascade_drop" and entity_kind != "grant" else ""
        )
    assert serialized_statements(operation) == parse_sql(expected)


def test_every_declared_entity_revert_uses_public_snapshot_contract():
    engine = isolated_data_engine("API_TEST_MIGRATION_DATABASE_URL")
    try:
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                snapshot = connection.scalar(text("SELECT pg_current_snapshot()::text"))
                context = MigrationContext.configure(
                    connection, opts={"api_autogen_snapshot": snapshot}
                )
                for entity in entities:
                    with Session(
                        bind=connection, join_transaction_mode="create_savepoint"
                    ) as session:
                        matches = [
                            candidate
                            for candidate in type(entity).from_database(
                                session, entity.schema
                            )
                            if candidate.identity == entity.identity
                        ]
                    assert len(matches) == 1
                    expected = tuple(
                        statement
                        for ddl in matches[0].to_sql_statement_create_or_replace()
                        for statement in parse_sql(
                            str(ddl.compile(dialect=postgresql.dialect()))
                        )
                    )
                    assert (
                        serialized_statements(ReplaceOp(entity).reverse(), context)
                        == expected
                    )
                assert (
                    connection.scalar(text("SELECT pg_current_snapshot()::text"))
                    == snapshot
                )
    finally:
        engine.dispose()

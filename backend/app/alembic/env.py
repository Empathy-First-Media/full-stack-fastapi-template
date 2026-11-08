"""API-only migration ledger; legacy public revisions are historical, not deployable."""
import os
from contextlib import contextmanager
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.script import ScriptDirectory
from alembic_utils.replaceable_entity import register_entities
from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import make_url

from app.alembic.native_security import process_revision_directives
from app.alembic.security import entities
from app.models import SQLModel

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

API_SCHEMA = "api"
target_metadata = SQLModel.metadata
BOOTSTRAP_TABLES = context.get_x_argument(as_dictionary=True).get("api_bootstrap") == "tables"
register_entities([] if BOOTSTRAP_TABLES else entities)


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == API_SCHEMA
    return parent_names.get("schema_name") == API_SCHEMA


def include_object(object_, name, type_, reflected, compare_to):
    if BOOTSTRAP_TABLES and type_ not in {
        "table", "column", "index", "unique_constraint", "foreign_key_constraint", "check_constraint",
    }:
        return False
    if type_ == "grant_table" and getattr(object_, "role", None) != "authenticated":
        return False
    if type_ == "table":
        return object_.schema == API_SCHEMA
    table = getattr(object_, "table", None)
    if table is not None and hasattr(table, "schema"):
        return table.schema == API_SCHEMA
    return getattr(object_, "schema", None) == API_SCHEMA


def migration_url():
    value = os.environ.get("API_MIGRATION_DATABASE_URL")
    if not value:
        raise RuntimeError("API_MIGRATION_DATABASE_URL must explicitly select the isolated/reviewed migration authority")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("API migrations require PostgreSQL, never a substitute database")
    runtime = os.environ.get("DATABASE_URL")
    if runtime and make_url(runtime).username == url.username:
        raise RuntimeError("API migration and runtime users must be distinct")
    return value


def validate_ledger():
    expected = Path(__file__).parent / "api_versions"
    locations = ScriptDirectory.from_config(config).version_locations
    if config.get_main_option("api_namespace") != API_SCHEMA or not locations:
        raise RuntimeError("Legacy migration replay is disabled; use alembic -c alembic-api.ini")
    if len(locations) != 1 or Path(locations[0]).resolve() != expected.resolve():
        raise RuntimeError("Only the API-owned revision directory may be loaded")
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    command = getattr(config.cmd_opts, "cmd", None)
    command_name = getattr(command[0], "__name__", "") if command else ""
    if not revisions and command_name != "revision":
        raise RuntimeError("No reviewed API revision exists; generation is required before application")
    for revision in revisions:
        if "api" not in revision.branch_labels:
            raise RuntimeError("All deployable revisions must belong to the explicit api branch")


@contextmanager
def scoped_migration_connection(connectable):
    with connectable.connect() as connection:
        original_search_path = connection.scalar(text("SHOW search_path"))
        connection.rollback()
        try:
            # Explicit remote-schema reflection must not depend on PUBLIC visibility.
            connection.execute(text("SELECT set_config('search_path', 'pg_catalog', false)"))
            connection.commit()
            yield connection
        finally:
            connection.rollback()
            connection.execute(
                text("SELECT set_config('search_path', :value, false)"),
                {"value": original_search_path},
            )
            connection.commit()


def autogeneration_requested():
    command = getattr(config.cmd_opts, "cmd", None)
    command_name = getattr(command[0], "__name__", "") if command else ""
    return bool(getattr(config.cmd_opts, "autogenerate", False)) or command_name == "check"


def run_migrations_online():
    validate_ledger()
    configuration = config.get_section(config.config_ini_section)
    assert configuration is not None
    configuration["sqlalchemy.url"] = migration_url()
    autogenerating = autogeneration_requested()
    isolation = {"isolation_level": "REPEATABLE READ"} if autogenerating else {}
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool, **isolation,
    )
    with scoped_migration_connection(connectable) as connection:
        if not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'api')")):
            raise RuntimeError("The reviewed native schema owner must provision api before generation/application")
        if not connection.scalar(text(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )):
            raise RuntimeError("API live-actor helper requires a separate privileged migration owner; runtime authority is forbidden")
        helper_owner_can_bypass = connection.scalar(text(
            "SELECT p.prosecdef AND (r.rolsuper OR r.rolbypassrls) "
            "FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid=p.pronamespace "
            "JOIN pg_roles AS r ON r.oid=p.proowner "
            "WHERE n.nspname='api' AND p.proname='current_actor_is_active' AND p.pronargs=0"
        ))
        if helper_owner_can_bypass is False:
            raise RuntimeError("Existing API live-actor helper must retain a verified privileged migration owner")
        # A migration identity owns only api. Runtime role authority is checked by
        # the request-session owner, never inferred from migration credentials.
        # Close the read-only preflight's implicit transaction before Alembic
        # starts its own transactional DDL boundary.
        connection.rollback()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            include_object=include_object,
            version_table_schema=API_SCHEMA,
            version_table="alembic_version",
            compare_type=True,
            compare_server_default=True,
            process_revision_directives=process_revision_directives,
        )
        with context.begin_transaction():
            if autogenerating:
                # Every vendor comparison and downgrade reflection shares this
                # native snapshot; apply/runtime transactions keep their defaults.
                context.get_context().opts["api_autogen_snapshot"] = connection.scalar(
                    text("SELECT pg_current_snapshot()::text")
                )
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migration emission is disabled: native PostgreSQL ownership preflight is required")
run_migrations_online()

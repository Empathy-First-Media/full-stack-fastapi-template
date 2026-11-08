# FastAPI backend

## Runtime contract

The browser uses WorkOS AuthKit React. The API verifies signed access tokens with
PyJWT's native JWKS client; it does not issue tokens, exchange OAuth codes, store
refresh tokens, or accept local passwords. Signup, password recovery, password
changes, private user provisioning and global-superuser authorization are retired.

Configure these variables explicitly for the selected environment/application:

| Variable | Required value |
| --- | --- |
| `PROJECT_NAME` | Application display name |
| `FRONTEND_HOST` | Exact browser origin/SDK redirect destination |
| `DATABASE_URL` | Existing canonical product database, dedicated non-superuser `NOBYPASSRLS` runtime login |
| `WORKOS_CLIENT_ID` | Approved application client ID |
| `WORKOS_ISSUER` | Exact trusted HTTPS issuer |
| `WORKOS_JWKS_URL` | Explicit trusted HTTPS signing-key endpoint |
| `WORKOS_API_HOSTNAME` | Authentication API hostname supplied to AuthKit React |

`FASTAPI_ENV=development` allows local HTTP browser origins. Leave it unset in
production, which requires HTTPS and a custom Authentication API hostname.
Issuer, signing JWKS and browser API hostname are separately owner-configured;
the API does not infer one from another. Missing settings refuse startup. No
catalog/staging credential fallback exists. No WorkOS API key is needed by this
resource server. SMTP and Sentry settings remain optional non-auth utilities.

Public `GET /api/v1/auth/config` returns only `client_id`, `api_hostname` and
`redirect_uri`. `GET /api/v1/users/me` returns the stable local UUID/profile,
canonical TEXT tenant ID, canonical identity UUID, and verified `user_role`,
`permissions`, `is_tenant_admin`. Neither endpoint exposes server credentials.

## Identity and authorization

The existing product owner maintains `public.tenants`, `identity_entity`,
`identity_external`, WorkOS projections and the private issuer/client cutover
gate. The API reflects their real metadata and never creates or copies them.
The verified WorkOS subject resolves through its provider-scoped canonical
crosswalk, the exact enabled issuer/client gate, the selected organization and
one active projected membership. Unknown, ambiguous or mismatched associations
deny access. Email equality is never an identity link or provisioning rule.
Local `User.id` remains a UUID; tenant IDs retain the canonical owner's TEXT type.

Every business action requires `org:projects:read`/`org:projects:write` as
appropriate. Write permission also grants read access in both the API and UI;
read permission alone never grants mutation access. Administrators are
selected-tenant administrators, not global operators. Ordinary users access
their own items; tenant administrators can
access items in their selected tenant only. Account administration also requires
explicit action permission. Profile changes cannot mutate tenant/identity/role;
item changes cannot mutate tenant/owner attribution.

A tenant administrator may create a local profile only for an existing,
same-tenant canonical user with an explicit WorkOS binding. This is not a WorkOS
invite, membership creation, role grant or reactivation. A profile for a revoked
member confers no access: authentication independently checks active membership.
Other users' private membership rows are not exposed for profile creation.

Profile emails are unique within a tenant, not globally. PostgreSQL's
`uq_user_tenant_email` constraint is authoritative when RLS hides another profile
or concurrent writes race. Duplicate canonical profiles likewise return the
existing HTTP 409 conflict. These specific violations roll back; unrelated
constraint errors remain visible. Identical emails in different tenants remain
allowed.

Profile writes flush and capture their public state inside the transaction,
then return it only after commit. They do not re-read a profile after its own
deactivation has revoked access; a successful deactivation response is not
turned into an ambiguous post-commit failure.

`VerifiedSession` installs the fixed `authenticated` role and verified claims with
transaction-local PostgreSQL settings on every actual transaction, including
post-commit ORM reloads. Reserved `api_*` input claims are discarded. Canonical
resolution then adds `api_tenant_id`, `api_identity_entity_id`, and finally
`api_user_id` after the active local actor resolves. RLS owns the matching
bootstrap/read/write distinction. Commit, rollback and pool return cannot retain
a previous request's role or claims.

## Native dependency and development commands

From this upstream repository's root:

```console
uv sync --locked --package app
uv run --package app --directory backend fastapi dev
```

An embedding workspace must set its declared external `UV_PROJECT_ENVIRONMENT`
(for example its API-owned environment) rather than using or modifying the
parent project's environment. Authentication settings must be supplied even for
OpenAPI generation; use explicit fixture settings for nonproduction generation.

## API namespace migrations

Only API-owned entities, policies and the Alembic ledger belong in schema `api`.
Canonical product schemas and cross-owner grants have separate owners. Do not
run the legacy public migration history, `SQLModel.metadata.create_all`, or any
initial/global-superuser seed against the product database.

After native generation, review, isolation, recovery and grant gates, the exact
migration command from `backend/` is:

```console
uv run --no-active --locked --no-sync alembic -c alembic-api.ini upgrade api@head
```

The migration owner requires a separately supplied
`API_MIGRATION_DATABASE_URL`, distinct from the runtime login, an existing
owner-provisioned `api` schema, and an explicit reviewed API revision branch.
`backend/scripts/prestart.sh` invokes only that command, never a seed. It refuses
application when the reviewed branch or prerequisites are absent. Migration
credentials must not be injected into the long-lived backend process.

The narrowly scoped actor-status function uses PostgreSQL `SECURITY DEFINER`
with an empty search path and `row_security=off`. Its migration owner must have
native RLS-bypass authority; generation/application refuse insufficient or
incorrect function ownership. The runtime login never receives that authority.

Policy autogeneration uses Alembic's documented operation rewriter and the
vendor's SQL statements, preserving permission literals in immutable SQL
operations. Old-policy reflection shares the original repeatable-read snapshot;
runtime/application isolation is unchanged. Review both directions. Restoring
an older revision restores its historical policy semantics, not necessarily a
security-ready rollback target.

## Tests and evidence

Token/config/schema tests use explicit signed-token and transport fixtures, not
production credentials. From the upstream root:

```console
uv run --no-active --locked --no-sync --package app --directory backend pytest tests/test_workos_security.py tests/test_data_namespace.py tests/api/routes/test_login.py tests/api/routes/test_private.py
```

SQL/route tests execute real PostgreSQL transactions and RLS. Provision the
approved isolated canonical baseline and reviewed API namespace before running
all tests. Required test inputs are:

- `API_TEST_DATABASE_URL`: non-superuser `NOBYPASSRLS` runtime login.
- `API_TEST_ADMIN_DATABASE_URL`: isolated fixture writer, never production.
- `API_TEST_MIGRATION_DATABASE_URL`: isolated privileged migration authority.
- `API_TEST_ACTORS`: JSON object with `admin`, `member`, `foreign_admin`,
  `unprofiled`, `revoked`; each existing canonical fixture actor supplies
  `subject`, `organization_id`, `user_role`, `tenant_id` (TEXT),
  `identity_entity_id` (UUID). Admin/member/unprofiled/revoked belong to the first
  tenant, foreign_admin to a different tenant; revoked membership is inactive.
- The isolated database name starts `api_test_`, or an approved
  `API_TEST_SUPABASE_BRANCH_REF` matches its connection target. Known production
  and catalog-staging references are rejected even with a test-shaped database
  name; the actual PostgreSQL database must match the selected URI.

The isolated gate must trust `https://auth.fixture.test/` and `client_fixture`.
Tests create/clean only the named fixture actors' API-local profiles/items. They
never create schema, seed canonical identity, grant roles, or delete all data.
Missing infrastructure fails explicitly; it is not silently replaced by SQLite.

```console
uv run --no-active --locked --no-sync --package app --directory backend pytest
```

CI validates all three real targets before applying migrations. Route and RLS
cases share the same canonical actor input and claims producer, rather than
separate copied tenant/identity/claim settings. Docker/browser jobs are public
configuration/UI network-fixture checks, not SQL/RLS or real sign-in evidence.
Run workflow auditing, backend typing/lint, native client regeneration and browser
checks through their owners after all edits land.

Production admission additionally requires recovery/restore evidence, approved
schema/grants, verified WorkOS domain/URLs, real sign-in/sign-out/external login,
and same/cross-tenant direct/gateway operations. Passing fixtures does not satisfy
those gates. See [deployment](../deployment.md).

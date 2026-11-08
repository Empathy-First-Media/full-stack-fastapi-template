# FastAPI Project - Deployment

Deployment is deliberately gated. Do not deploy until the reviewed API namespace,
canonical identity mappings, non-bypass runtime role, isolated tests, recovery and
real WorkOS application-settings readback have passed. Source code and fixtures
are not production admission.

## Configure the application

For FastAPI Cloud, use `backend` as the application directory. Bind the existing
approved product database, not a newly created template database. A provider
integration's automatically supplied administrative URL is not evidence of a
safe runtime role.

Required non-secret settings:

- `PROJECT_NAME`
- `FRONTEND_HOST`: exact HTTPS browser origin/redirect destination
- `WORKOS_CLIENT_ID`: the approved application
- `WORKOS_ISSUER`: exact trusted HTTPS issuer
- `WORKOS_JWKS_URL`: explicit trusted HTTPS signing JWKS
- `WORKOS_API_HOSTNAME`: approved production custom Authentication API hostname

Required secret: `DATABASE_URL`, using the dedicated non-superuser,
`NOBYPASSRLS` runtime login. The resource server needs no WorkOS API key and
contains no local-password/global-superuser seed. Optional SMTP/Sentry settings
are described in [backend configuration](backend/README.md).

Register and read back the effective redirect URI, allowed browser origin,
sign-out default and SDK-backed `/login` Initiate login URI on the selected
WorkOS application. Verify its custom domain and TLS. Browser AuthKit React owns
login, refresh, logout and organization selection; it uses public
`GET /api/v1/auth/config`, not build-time secrets.

## Prepare the API namespace

Provision canonical product schemas/identities through their existing owner and
`api` through the reviewed schema owner. Preserve canonical tenant TEXT IDs and
local actor UUIDs. Do not run the legacy public migration history, create tables
at application startup, or seed identities from email.

Supply `API_MIGRATION_DATABASE_URL` only to the reviewed migration job. It must
use an authority distinct from the runtime login. From `backend/`:

```console
uv run --no-active --locked --no-sync alembic -c alembic-api.ini upgrade api@head
```

`scripts/prestart.sh` invokes this exact branch and no seed. Without a reviewed
API revision and owner-provisioned prerequisites it refuses application.

## Continuous deployment admission

Both deployment workflows are manual-only and select the `production` GitHub
environment. Its required reviewers and environment protection remain UNVERIFIED
until the native GitHub owner reads them back. An environment name alone is not
protection, and a boolean approval flag cannot establish recovery or tenant
conformance. Do not trigger deployment before those protections and every
production prerequisite are verified.

For `.github/workflows/deploy.yml`, configure the non-secret settings above on the
actual FastAPI Cloud application and matching GitHub repository variables.
Configure `DATABASE_URL`, `API_MIGRATION_DATABASE_URL`, `FASTAPI_CLOUD_TOKEN` and
`FASTAPI_CLOUD_APP_ID` as scoped GitHub secrets. Runtime deployment must not retain
the migration credential. Do not place keys, DSNs or tokens in source or logs.

The admitted workflow builds the frontend, runs only the API migration branch,
then invokes the native FastAPI deployment command. This documentation does not
configure credentials, provider settings, schema or a deployment.

Before admission, run the [isolated SQL/token/browser consumers](backend/README.md),
regenerate the native OpenAPI client, and establish real direct/gateway
same-tenant CRUD and cross-tenant denial. Verify durable readback, sign-in,
sign-out, externally initiated login, revoked memberships and pooled transaction
reuse. Keep the application inactive until every required production gate passes.

## URLs

Replace `your-app.fastapicloud.dev` with the URL of your FastAPI Cloud application.

Application (frontend and API): `https://your-app.fastapicloud.dev`

Interactive API docs: `https://your-app.fastapicloud.dev/docs`

## Docker Compose

For deployment to your own server, see the [Docker Compose deployment guide](./deployment-docker-compose.md).

## GitHub Repository Automation

Install the following GitHub Apps to enable the included repository automation:

* [Latest Changes](https://github.com/apps/latest-changes) updates `release-notes.md` when a pull request is merged.
* [PR Push](https://github.com/apps/pr-push) lets the pre-commit workflow push automated fixes to pull request branches.
* [PR Submit](https://github.com/apps/pr-submit) lets the **Bump pre-commit hooks** and **Prepare Release** workflows create pull requests.

To publish code coverage with [Smokeshow](https://github.com/samuelcolvin/smokeshow), add `SMOKESHOW_AUTH_KEY` as a repository secret.

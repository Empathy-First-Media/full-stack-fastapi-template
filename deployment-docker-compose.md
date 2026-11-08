# FastAPI Project - Docker Compose Deployment

Deploy only after the identity, namespace, isolation, recovery and real-provider
acceptance gates in [deployment.md](deployment.md) pass. The Compose profile uses
the existing approved product database; it does not create a parallel template
database or seed a local superuser. Traefik handles HTTPS application routing.

## Preparation

* Have a remote server ready and available.
* Configure DNS for the application and the separately approved WorkOS Authentication API domain.
* Install and configure [Docker](https://docs.docker.com/engine/install/) on the remote server (Docker Engine, not Docker Desktop).

## Copy the Code

```bash
rsync -av --exclude=".git/" --filter=":- .gitignore" ./ root@your-server.example.com:/root/code/app/
```

The `--filter=":- .gitignore"` option tells `rsync` to use the same ignore rules as Git, excluding files such as the Python virtual environment.

## Configure the Application

### Environment Variables

Set `DOMAIN`, `PROJECT_NAME`, `FRONTEND_HOST` and the explicitly approved
`WORKOS_CLIENT_ID`, `WORKOS_ISSUER`, `WORKOS_JWKS_URL`,
`WORKOS_API_HOSTNAME`. Production requires an HTTPS browser origin and custom
Authentication API hostname. These are environment/application-specific values,
not catalog/staging fallbacks.

You can also configure these environment variables as needed:

* `SMTP_HOST`: The SMTP server host from your email provider.
* `SMTP_USER`: The SMTP server user.
* `EMAILS_FROM_EMAIL`: The email account used to send emails.
* `SENTRY_DSN`: The DSN for Sentry.

### Secrets

Supply `DATABASE_URL` through the secret owner for the dedicated non-superuser,
`NOBYPASSRLS` runtime login. Supply a distinct `API_MIGRATION_DATABASE_URL` only
for the reviewed migration invocation; do not put it in the backend runtime.
No WorkOS private key/API key or application password-signing secret is needed.

To use an authenticated email provider, also set `SMTP_PASSWORD`.

## Deploy

```bash
cd /root/code/app/
docker compose -f compose.yml -f compose.deploy.yml build
docker compose -f compose.yml -f compose.deploy.yml run --rm migrate
docker compose -f compose.yml -f compose.deploy.yml up -d
```

The `compose.deploy.yml` file adds HTTPS and automatic certificate handling to the shared `compose.yml` configuration. Explicitly listing both files excludes the local settings from `compose.override.yml`.

The `migrate` maintenance service runs only
`alembic -c alembic-api.ini upgrade api@head`. It refuses missing schema/branch
prerequisites and never replays the legacy public ledger or seeds identities.
The backend receives runtime credentials only. Review and restore-test the
canonical baseline before migration, and read back real same/cross-tenant
operations before admitting traffic.

The backend Docker image builds the frontend, so the server does not need Bun or prebuilt frontend files.

## Deploy with GitHub Actions

The included `.github/workflows/deploy-docker-compose.yml` is manual-only and
selects the `production` GitHub environment. Required reviewers and environment
protection are UNVERIFIED until native owner readback; the name alone is not a
protection. Do not trigger it until protection and all production gates pass.

Use a self-hosted runner only for a repository whose contributors and workflow code you trust. GitHub recommends using self-hosted runners with private repositories because workflows execute directly on the runner machine.

### Configure Repository Variables and Secrets

In the repository, go to **Settings** > **Secrets and variables** > **Actions** and add these repository variables:

* `DOMAIN`
* `PROJECT_NAME`
* `FRONTEND_HOST`
* `WORKOS_CLIENT_ID`
* `WORKOS_ISSUER`
* `WORKOS_JWKS_URL`
* `WORKOS_API_HOSTNAME`

To enable emails, add these optional repository variables:

* `SMTP_HOST`
* `SMTP_USER`
* `EMAILS_FROM_EMAIL`

To enable Sentry, add the optional `SENTRY_DSN` repository variable.

Add these repository secrets:

* `DATABASE_URL` (runtime, non-bypass)
* `API_MIGRATION_DATABASE_URL` (separate migration authority)

To use an authenticated email provider, add the optional `SMTP_PASSWORD` repository secret.

### Install a Self-Hosted Runner

On the server, create a dedicated user and grant it access to Docker:

```bash
sudo adduser github
sudo usermod -aG docker github
sudo su - github
```

In the GitHub repository, go to **Settings** > **Actions** > **Runners**, select **New self-hosted runner**, choose Linux, and follow the commands GitHub provides to download, configure, and register the runner. Install it in `/home/github/actions-runner`.

After registering the runner, exit the `github` user session and install the runner as a system service:

```bash
exit
cd /home/github/actions-runner
sudo ./svc.sh install github
sudo ./svc.sh start
sudo ./svc.sh status
```

See GitHub's guides for [adding a self-hosted runner](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners) and [configuring the runner as a service](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application?platform=linux).

### Run the Deployment

When the runner is online, open the repository's **Actions** tab, select **Deploy with Docker Compose**, and select **Run workflow**.

## URLs

Replace `fastapi-project.example.com` with your domain.

Application (frontend and API): `https://fastapi-project.example.com`

Interactive API docs: `https://fastapi-project.example.com/docs`


# Full Stack FastAPI Template

[![Test Docker Compose](../../actions/workflows/test-docker-compose.yml/badge.svg)](../../actions/workflows/test-docker-compose.yml)
[![Test Backend](../../actions/workflows/test-backend.yml/badge.svg)](../../actions/workflows/test-backend.yml)

## Technology Stack and Features

- ⚡ [**FastAPI**](https://fastapi.tiangolo.com) for the Python backend API.
  - 🧰 [SQLModel](https://sqlmodel.tiangolo.com) for the Python SQL database interactions (ORM).
  - 🔍 [Pydantic](https://docs.pydantic.dev), used by FastAPI, for the data validation and settings management.
  - 💾 [PostgreSQL](https://www.postgresql.org) as the SQL database.
- 🚀 [React](https://react.dev) for the frontend.
  - 🧩 Built into the backend application and served by FastAPI on the same domain as the API.
  - 💃 Using TypeScript, hooks, [Vite](https://vitejs.dev), and other parts of a modern frontend stack.
  - 🎨 [Tailwind CSS](https://tailwindcss.com) and [shadcn/ui](https://ui.shadcn.com) for the frontend components.
  - 🤖 An automatically generated frontend client.
  - 🧪 [Playwright](https://playwright.dev) for end-to-end testing.
  - 🦇 Dark mode support.
- ☁️ [FastAPI Cloud](https://fastapicloud.com) for deployment.
- 🐋 [Docker Compose](https://www.docker.com) for local services and self-hosted deployment.
  - 📞 [Traefik](https://traefik.io) as a reverse proxy with automatic HTTPS.
- WorkOS AuthKit React for browser sessions and organization selection.
- Native PyJWT/JWKS resource-server verification with exact issuer/client binding.
- Canonical product identity crosswalks, tenant-scoped administration and PostgreSQL RLS.
- ✉️ [React Email](https://react.email) for email templates.
- 📬 [Mailpit](https://mailpit.axllent.org) for local email testing during development.
- ✅ Tests with [Pytest](https://pytest.org).
- 🏭 CI (continuous integration) and CD (continuous deployment) based on GitHub Actions.

### Dashboard Login

The screenshots below are historical template illustrations, not the current
WorkOS sign-in UI or evidence of a deployed authentication flow.

![Dashboard login screenshot](img/login.png)

### Dashboard - Admin

![Admin dashboard screenshot](img/dashboard.png)

### Dashboard - Items

![Items dashboard screenshot](img/dashboard-items.png)

### Dashboard - Dark Mode

![Dark mode dashboard screenshot](img/dashboard-dark.png)

### React Email Templates

![Email templates screenshot](img/react-email.png)

### Mailpit - Local Email Testing

![Mailpit screenshot](img/mailpit.png)

### Interactive API Documentation

![API docs](img/docs.png)

## How to Use It

Click the **Use this template** button at the top of this page to create a new repository.

This branch requires an existing canonical product database and explicit WorkOS
application settings; it does not seed a global superuser or accept local
passwords. See [backend configuration and isolated tests](backend/README.md).
Production remains gated by recovery, schema/grant review, real provider settings
and tenant-conformance evidence. The manual deployment workflows select a
`production` environment, whose required reviewers/protection must be verified
through the GitHub owner before use; its name is not itself an approval.

## Backend Development

Backend docs: [backend/README.md](./backend/README.md).

## Frontend Development

Frontend docs: [frontend/README.md](./frontend/README.md).

## Deployment

FastAPI Cloud deployment: [deployment.md](./deployment.md).

Self-hosted deployment with Docker Compose: [deployment-docker-compose.md](./deployment-docker-compose.md).

## Development

General development docs: [development.md](./development.md).

This includes the local FastAPI and Vite workflow, Docker Compose services, `.env` configuration, and more.

### Native hook and branch admission

This repository declares `.pre-commit-config.yaml` for **prek**, not Lefthook.
The estate's `install-git-hooks <absolute-checkout> [install|validate]` owner
validates that versioned declaration before changing Git configuration. The
`validate` mode installs nothing. Linked worktrees retain private hooks and
installation failures restore their previous worktree-local `core.hooksPath`.
Setup and check-in bind a primary submodule or separate-metadata repository to
Git's actual checkout root when its private/common Git directories match;
the metadata directory reported by `worktree list` is not a checkout.

Use the existing estate `api-sync` owner to provision this project's locked
Python workspace in the separate `.venv-api` environment. For native checks,
explicitly select that absolute path with `UV_PROJECT_ENVIRONMENT`; check-in
preserves it after direnv loading and checks the existing frozen profile
without resolution or synchronization. It never substitutes the estate's
Python environment or creates a checkout-local one. JavaScript dependencies
belong to the versioned `bun.lock`: use `bun install --frozen-lockfile`.

From this checkout, run the check-only hook contract with:

```console
prek run --config .pre-commit-config.yaml --all-files --hook-stage pre-commit
```

Biome, Ruff lint/format checks, mypy, ty, spelling and workflow checks do not
rewrite sources. EOF/trailing-whitespace fixers, SDK generation and release-date
updates are manual-only. Select one deliberately, for example:

```console
prek run --config .pre-commit-config.yaml --all-files --hook-stage manual generate-frontend-sdk
```

Manual generation is **not** a freshness check: regenerate from the application's
own exporter, review the resulting client, and commit it before admission.
Neither `--dry-run` nor selecting the manual stage proves the generated files
are current.

`git-branch-check-in` uses this native all-file contract rather than inherited
parent Mise checks. It requires a clean committed branch and the verified
mutation lease, refuses hook skip selectors, and refuses to publish/unlock if
checks fail, move HEAD or leave any tracked/untracked changes. New linked
project bootstrap remains blocked until its environment and direnv ownership
are separately admitted; setup does not copy environments or invent `.envrc`.
Protected CI/merge admission still needs the isolated fixture and explicitly
provisioned CI inputs; local hook success does not waive that boundary.

Vendor contracts: [prek's pinned CLI reference](https://github.com/j178/prek/blob/b7eb6027125de7e3b67dd94039a4f69abf3a5fb0/docs/reference/cli.md)
and [the pinned whitespace hook manifest](https://github.com/pre-commit/pre-commit-hooks/blob/3e8a8703264a2f4a69428a0aa4dcb512790b2c8c/.pre-commit-hooks.yaml).

## Release Notes

Check the file [release-notes.md](./release-notes.md).

## License

The Full Stack FastAPI Template is licensed under the terms of the MIT license.

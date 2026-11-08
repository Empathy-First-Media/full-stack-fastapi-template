from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env", env_ignore_empty=True, extra="ignore"
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str
    FRONTEND_HOST: str
    FASTAPI_ENV: Literal["development"] | None = None
    SENTRY_DSN: HttpUrl | None = None
    DATABASE_URL: PostgresDsn
    WORKOS_CLIENT_ID: str
    WORKOS_ISSUER: str
    WORKOS_JWKS_URL: str
    WORKOS_API_HOSTNAME: str

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str:
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    @model_validator(mode="after")
    def _validate_auth_boundaries(self) -> Self:
        origin = urlsplit(self.FRONTEND_HOST)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
        ):
            raise ValueError("FRONTEND_HOST must be an explicit browser origin")
        if self.FRONTEND_HOST != self.FRONTEND_HOST.strip():
            raise ValueError("FRONTEND_HOST must not contain whitespace")
        if self.FASTAPI_ENV != "development" and origin.scheme != "https":
            raise ValueError("Production FRONTEND_HOST requires HTTPS")
        if (
            not self.WORKOS_CLIENT_ID.startswith("client_")
            or self.WORKOS_CLIENT_ID.strip() != self.WORKOS_CLIENT_ID
        ):
            raise ValueError(
                "WORKOS_CLIENT_ID must identify the explicitly selected application"
            )
        hostname = self.WORKOS_API_HOSTNAME
        if (
            not hostname
            or hostname != hostname.lower()
            or any(c in hostname for c in "/:@?# ")
        ):
            raise ValueError("WORKOS_API_HOSTNAME must be a hostname, not a URL")
        issuer, jwks = urlsplit(self.WORKOS_ISSUER), urlsplit(self.WORKOS_JWKS_URL)
        for value in (issuer, jwks):
            if (
                value.scheme != "https"
                or not value.hostname
                or value.username
                or value.password
                or value.fragment
            ):
                raise ValueError("WorkOS issuer and JWKS require explicit HTTPS URLs")
        # AuthKit React documents a custom Authentication API domain for production.
        # DNS/TLS verification and browser cookie compatibility are admission gates.
        if self.FASTAPI_ENV != "development":
            if hostname == "api.workos.com" or hostname.endswith(".workos.dev"):
                raise ValueError(
                    "Production AuthKit React requires a custom authentication API domain"
                )
            if origin.hostname == hostname:
                raise ValueError(
                    "The WorkOS custom domain cannot also host this application"
                )
        for host in self.DATABASE_URL.hosts():
            if host["password"] == "changethis":
                raise ValueError("DATABASE_URL must not contain template credentials")
        return self

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    # Pydantic documents MyPy's decorated-property limitation.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)


settings = Settings()

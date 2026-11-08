"""WorkOS resource-server verification using PyJWT's native JWKS implementation."""

import ssl
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import jwt
from jwt import InvalidTokenError, PyJWK, PyJWKClient

from app.core.config import Settings, settings


class SigningKeys(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> PyJWK: ...


@dataclass(frozen=True)
class VerifiedAccessToken:
    subject: str
    session_id: str
    organization_id: str
    user_role: str
    permissions: frozenset[str]
    claims: dict[str, Any]


class AccessTokenVerifier:
    def __init__(self, config: Settings, *, jwks_client: SigningKeys | None = None):
        self.config = config
        self.jwks = jwks_client or PyJWKClient(
            config.WORKOS_JWKS_URL,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
            ssl_context=ssl.create_default_context(),
        )

    def verify(self, token: str) -> VerifiedAccessToken:
        key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=self.config.WORKOS_ISSUER,
            options={
                "require": [
                    "iss",
                    "exp",
                    "iat",
                    "sub",
                    "sid",
                    "org_id",
                    "client_id",
                    "role",
                    "user_role",
                    "permissions",
                ],
                # AuthKit's documented client binding is client_id, not Clerk's azp.
                # Audience is optional; when emitted it must match this same client.
                "verify_aud": False,
            },
        )
        for name in ("sub", "sid", "org_id", "client_id", "user_role"):
            value = claims[name]
            if not isinstance(value, str) or not value or value.strip() != value:
                raise InvalidTokenError(f"Invalid {name} claim")
        for name in ("exp", "iat"):
            if type(claims[name]) is not int:
                raise InvalidTokenError(f"Invalid {name} claim")
        if claims["client_id"] != self.config.WORKOS_CLIENT_ID:
            raise InvalidTokenError("Wrong WorkOS application")
        if claims["role"] != "authenticated":
            raise InvalidTokenError("Invalid database role claim")
        if "aud" in claims and claims["aud"] not in (
            self.config.WORKOS_CLIENT_ID,
            [self.config.WORKOS_CLIENT_ID],
        ):
            raise InvalidTokenError("Conflicting audience")
        compact = claims.get("o")
        if compact is not None and (
            not isinstance(compact, dict) or compact.get("id") != claims["org_id"]
        ):
            raise InvalidTokenError("Conflicting organization claims")
        roles = claims.get("roles")
        if roles is not None and roles != [claims["user_role"]]:
            raise InvalidTokenError("Multi-role sessions are not admitted")
        permissions = claims["permissions"]
        if not isinstance(permissions, list) or any(
            not isinstance(p, str) or not p or p.strip() != p for p in permissions
        ):
            raise InvalidTokenError("Invalid permissions claim")
        return VerifiedAccessToken(
            subject=claims["sub"],
            session_id=claims["sid"],
            organization_id=claims["org_id"],
            user_role=claims["user_role"],
            permissions=frozenset(permissions),
            claims=claims,
        )


@lru_cache(maxsize=1)
def get_token_verifier() -> AccessTokenVerifier:
    return AccessTokenVerifier(settings)

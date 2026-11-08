from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError, PyJWKClientError
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import Principal, VerifiedSession, resolve_principal
from app.core.db import engine
from app.core.security import VerifiedAccessToken, get_token_verifier

bearer = HTTPBearer(auto_error=False)


def get_verified_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> VerifiedAccessToken:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return get_token_verifier().verify(credentials.credentials)
    except PyJWKClientError:
        raise HTTPException(
            status_code=401,
            detail="Unable to verify access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError, ValueError, TypeError:
        raise HTTPException(
            status_code=401,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )


VerifiedTokenDep = Annotated[VerifiedAccessToken, Depends(get_verified_token)]


def get_db(token: VerifiedTokenDep) -> Generator[VerifiedSession]:
    with VerifiedSession(engine, info={"verified_token": token}) as session:
        try:
            yield session
        finally:
            try:
                session.rollback()
            finally:
                session.info.clear()


SessionDep = Annotated[VerifiedSession, Depends(get_db)]


def get_current_principal(session: SessionDep, token: VerifiedTokenDep) -> Principal:
    try:
        return resolve_principal(session, token)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Identity data unavailable")


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str
    api_hostname: str
    redirect_uri: str


@router.get("/config")
def read_auth_config() -> AuthConfig:
    """Public browser configuration; no API key or server session credentials."""
    return AuthConfig(
        client_id=settings.WORKOS_CLIENT_ID,
        api_hostname=settings.WORKOS_API_HOSTNAME,
        redirect_uri=settings.FRONTEND_HOST,
    )

"""A settings failure must name the binding it needed, never the credentials it collected.

``app.core.config`` builds the process configuration from the environment and instantiates it at
import time (``settings = Settings()``), so the first malformed deployment is a traceback printed
during container startup. Without ``hide_input_in_errors`` that traceback renders the input mapping
pydantic-settings collected, and the values it collects here are ``SMTP_PASSWORD`` in clear and the
``DATABASE_URL`` with its password inside it. The rest of the estate already carries the binding;
this module is the last settings model that did not.

Both directions are proved: the failure must stop echoing the values (the fix), and the failure must
still name the missing binding while a complete environment still constructs (so the binding cannot
be installed by muting validation).
"""

from collections.abc import Iterator
from importlib import import_module
from typing import Any

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import Settings

_SMTP_CANARY = "smtp-canary-AAAA"  # noqa: S105 - a fixture value, not a credential
_DATABASE_CANARY = "db-canary-BBBB"  # noqa: S105 - a fixture value, not a credential


def _complete_declared_env() -> dict[str, str]:
    """The smallest environment the production entry point is documented to accept.

    Every value is a real shape: ``EmailStr`` rejects a reserved special-use domain, so a fixture
    that used one would fail on the field contract rather than on the binding under test.
    """

    return {
        "PROJECT_NAME": "API fixture",
        "DATABASE_URL": f"postgresql+psycopg://api_user:{_DATABASE_CANARY}@db.example.com:5432/api",
        "FRONTEND_HOST": "https://app.example.com",
        "FASTAPI_ENV": "development",
        "WORKOS_CLIENT_ID": "client_fixture",
        "WORKOS_ISSUER": "https://auth.example.com/",
        "WORKOS_JWKS_URL": "https://auth.example.com/sso/jwks/client_fixture",
        "WORKOS_API_HOSTNAME": "auth.example.com",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "alerts@example.com",
        "SMTP_PASSWORD": _SMTP_CANARY,
        "EMAILS_FROM_EMAIL": "alerts@example.com",
    }


@pytest.fixture(autouse=True)
def declared_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate the settings plane: every variable the class can read is owned by the fixture.

    ``env_prefix`` is absent here, so a bare field name is itself a binding, and an ambient
    ``.env`` would be read through ``env_file="../.env"`` relative to whichever directory pytest
    was started in. Clearing the plane first is what makes a withdrawn binding fail here instead
    of silently resolving from the developer's own shell.
    """

    for name in _complete_declared_env():
        monkeypatch.delenv(name, raising=False)
    for name, value in _complete_declared_env().items():
        monkeypatch.setenv(name, value)
    yield


def test_the_production_entry_point_fails_without_printing_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact construction ``settings = Settings()`` performs, with one binding withdrawn.

    This is the leak: pydantic renders a ``missing`` error with the whole input object it was
    given, and that object is the environment mapping the class collected.
    """

    monkeypatch.delenv("WORKOS_CLIENT_ID", raising=False)

    with pytest.raises(Exception) as caught:
        Settings(_env_file=None)

    text = str(caught.value)
    assert _SMTP_CANARY not in text
    assert _DATABASE_CANARY not in text
    # The operator still learns which binding was missing.
    assert "WORKOS_CLIENT_ID" in text


def test_a_malformed_binding_reports_the_field_and_not_the_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A present-but-invalid binding fails on its own field, without echoing what else was read."""

    monkeypatch.setenv("SMTP_PORT", "not-a-port")

    with pytest.raises(Exception) as caught:
        Settings(_env_file=None)

    text = str(caught.value)
    assert _SMTP_CANARY not in text
    assert _DATABASE_CANARY not in text
    assert "SMTP_PORT" in text


def test_a_complete_declared_environment_still_constructs() -> None:
    """The control that keeps the previous two tests honest.

    A binding that hid the input by suppressing validation, or by dropping the credential fields,
    would pass those two and fail here.
    """

    config = Settings(_env_file=None)

    assert config.SMTP_PASSWORD == _SMTP_CANARY
    assert str(config.DATABASE_URL).startswith("postgresql+psycopg://")
    assert _DATABASE_CANARY in str(config.model_dump()["DATABASE_URL"])


def test_the_binding_is_what_hides_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The negative control: without the binding the same failure does print the credentials.

    This twin is the leak this change removes, written down so the suite says which mechanism it
    depends on. If pydantic ever stops echoing the input by default, that is recorded here rather
    than quietly turning the other three tests into no-ops.
    """

    class UnredactedSettings(BaseSettings):
        model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore")

        WORKOS_CLIENT_ID: str
        SMTP_PASSWORD: str | None = None

    monkeypatch.delenv("WORKOS_CLIENT_ID", raising=False)

    with pytest.raises(Exception) as caught:
        UnredactedSettings()

    assert _SMTP_CANARY in str(caught.value)


def _settings_classes() -> list[type[Any]]:
    """Every BaseSettings subclass the app package declares, through the package's own modules."""

    found: list[type[Any]] = []
    for module_name in ("app.core.config",):
        module = import_module(module_name)
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseSettings)
                and value.__module__ == module.__name__
            ):
                found.append(value)
    return found


def test_every_settings_model_in_the_app_hides_its_input() -> None:
    """The class guard, so a new settings model cannot re-open the same leak.

    One subclass is the whole app today; a second one added without the binding fails here.
    """

    classes = _settings_classes()
    assert classes, "the sweep found no settings model, so it proves nothing"
    for klass in classes:
        assert klass.model_config.get("hide_input_in_errors") is True, klass.__name__

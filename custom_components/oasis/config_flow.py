"""Config flow for the Oasis smart light integration."""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Any

import voluptuous as vol

from aiohttp import ClientTimeout

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OasisAuthError, OasisClient
from .const import (
    AUTH_MODE_OAUTH,
    AUTH_MODE_PASSWORD,
    CLIENT_ID,
    COGNITO_BASE,
    CONF_AUTH_MODE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    OAUTH_SCOPE,
    REDIRECT_URI,
)

_LOGGER = logging.getLogger(__name__)

CONF_REDIRECT_URL = "redirect_url"
CONF_BRIDGE_URL = "bridge_url"


def _read_bridge_default() -> str:
    """Return the bridge URL baked in at download time, if there was one."""
    path = os.path.join(os.path.dirname(__file__), "bridge_default.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get("url", "")
    except (OSError, ValueError):
        return ""


def build_authorize_url(provider: str | None = None) -> str:
    """Build the Cognito hosted-UI URL used for Apple and Google sign-in."""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": OAUTH_SCOPE,
    }
    if provider:
        params["identity_provider"] = provider
    return f"{COGNITO_BASE}/oauth2/authorize?" + urllib.parse.urlencode(params)


def extract_code(pasted: str) -> str:
    """Pull ?code= out of a pasted rainmaker:// URL, or accept a bare code.

    Anything URL-shaped must actually carry a code. A denied sign-in comes back as
    ?error=..., which has no code in it, and treating that as a bare code would
    fail later with a confusing token-exchange error instead of a clear one here.
    """
    pasted = (pasted or "").strip()
    if "://" not in pasted and "?" not in pasted and "code=" not in pasted:
        if not pasted:
            raise ValueError("no_code")
        return pasted
    query = urllib.parse.urlparse(pasted).query or pasted.split("?", 1)[-1]
    params = urllib.parse.parse_qs(query)
    if params.get("error"):
        raise ValueError(params["error"][0])
    code = params.get("code", [None])[0]
    if not code:
        raise ValueError("no_code")
    return code


class OasisConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Oasis config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how the user signs in, since Apple accounts have no password."""
        options = ["apple", "password", "token"]
        if await self.hass.async_add_executor_job(_read_bridge_default):
            options.insert(0, "bridge")
        return self.async_show_menu(step_id="user", menu_options=options)

    async def async_step_bridge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import a working session from an Oasis bridge on the local network.

        Moving a long token by hand is error prone, so when the integration was
        downloaded from a bridge, fetch the credential from it directly instead.
        """
        errors: dict[str, str] = {}
        default_url = await self.hass.async_add_executor_job(_read_bridge_default)

        if user_input is not None:
            base = user_input[CONF_BRIDGE_URL].rstrip("/")
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(f"{base}/credentials", timeout=ClientTimeout(total=20)) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status != 200 or not body.get("refresh_token"):
                        raise OasisAuthError(str(body))
                client = OasisClient(
                    session, auth_mode=AUTH_MODE_OAUTH, refresh_token=body["refresh_token"]
                )
                await client.authenticate()
                lights = await client.async_get_lights()
            except OasisAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"oauth_{client.refresh_token[:12]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Oasis ({len(lights)} lights)",
                    data={
                        CONF_AUTH_MODE: AUTH_MODE_OAUTH,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="bridge",
            data_schema=vol.Schema(
                {vol.Required(CONF_BRIDGE_URL, default=default_url): str}
            ),
            errors=errors,
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Adopt an existing session by pasting its refresh token.

        Signing in repeatedly can produce a session the Oasis API refuses even
        though the credentials are correct, while an already-working session keeps
        renewing fine. This lets a known-good session be moved here directly.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            client = OasisClient(
                async_get_clientsession(self.hass),
                auth_mode=AUTH_MODE_OAUTH,
                refresh_token=user_input[CONF_REFRESH_TOKEN].strip(),
            )
            try:
                await client.authenticate()
                lights = await client.async_get_lights()
            except OasisAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"oauth_{client.refresh_token[:12]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Oasis ({len(lights)} lights)",
                    data={
                        CONF_AUTH_MODE: AUTH_MODE_OAUTH,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required(CONF_REFRESH_TOKEN): str}),
            errors=errors,
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in with an email address and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = OasisClient(
                async_get_clientsession(self.hass),
                auth_mode=AUTH_MODE_PASSWORD,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            try:
                await client.authenticate()
                lights = await client.async_get_lights()
            except OasisAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Oasis ({len(lights)} lights)",
                    data={
                        CONF_AUTH_MODE: AUTH_MODE_PASSWORD,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REFRESH_TOKEN: client.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    async def async_step_apple(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in with Apple or Google via the Cognito hosted UI.

        The redirect target is a private app scheme, so a browser cannot follow it.
        The user signs in, lands on an "address is invalid" error, and pastes that
        URL back here; the authorization code is in it.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                code = extract_code(user_input[CONF_REDIRECT_URL])
                session = async_get_clientsession(self.hass)
                tokens = await OasisClient.exchange_code(session, code)
                client = OasisClient(
                    session,
                    auth_mode=AUTH_MODE_OAUTH,
                    refresh_token=tokens.get("refresh_token"),
                )
                await client.authenticate()
                lights = await client.async_get_lights()
            except ValueError as err:
                errors["base"] = "no_code" if str(err) == "no_code" else "sign_in_refused"
            except OasisAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"oauth_{client.refresh_token[:12]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Oasis ({len(lights)} lights)",
                    data={
                        CONF_AUTH_MODE: AUTH_MODE_OAUTH,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="apple",
            data_schema=vol.Schema({vol.Required(CONF_REDIRECT_URL): str}),
            description_placeholders={
                "apple_url": build_authorize_url("SignInWithApple"),
                "google_url": build_authorize_url("Google"),
                "any_url": build_authorize_url(),
            },
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Re-authenticate when the stored token can no longer be refreshed."""
        self._reauth_mode = entry_data.get(CONF_AUTH_MODE, AUTH_MODE_PASSWORD)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if getattr(self, "_reauth_mode", AUTH_MODE_PASSWORD) == AUTH_MODE_OAUTH:
            return await self.async_step_apple(user_input)
        return await self.async_step_password(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow swapping in a different session without removing the entry."""
        return await self.async_step_user()

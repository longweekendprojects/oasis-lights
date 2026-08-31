"""Async client for the ESP RainMaker deployment behind the Oasis app."""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    AUTH_MODE_OAUTH,
    AUTH_MODE_PASSWORD,
    CLIENT_ID,
    COGNITO_BASE,
    PARAM_BRIGHTNESS,
    PARAM_CCT,
    PARAM_POWER,
    REDIRECT_URI,
)

_LOGGER = logging.getLogger(__name__)


class OasisAuthError(Exception):
    """Credentials were rejected and cannot be recovered by refreshing."""


class OasisApiError(Exception):
    """The Oasis cloud returned an error."""


def resolve_param(names: list[str], candidates: tuple[str, ...]) -> str | None:
    """Find a device's real parameter name from a list of likely spellings."""
    for candidate in candidates:
        for name in names:
            if name and name.lower() == candidate.lower():
                return name
    for candidate in candidates:
        for name in names:
            if name and candidate.lower() in name.lower():
                return name
    return None


class OasisClient:
    """Talks to RainMaker, refreshing its own token as needed."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        auth_mode: str,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self._session = session
        self._auth_mode = auth_mode
        self._username = username
        self._password = password
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._id_token: str | None = None
        self._expires_at: float = 0.0
        # The API Gateway authorizer accepts one of these; remember which.
        self._token_field: str = "access_token"

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    # -- authentication -------------------------------------------------

    async def _store(self, payload: dict[str, Any]) -> None:
        for src, dst in (
            ("access_token", "_access_token"),
            ("accesstoken", "_access_token"),
            ("id_token", "_id_token"),
            ("idtoken", "_id_token"),
        ):
            if payload.get(src):
                setattr(self, dst, payload[src])
        for src in ("refresh_token", "refreshtoken"):
            if payload.get(src):
                self._refresh_token = payload[src]
        self._expires_at = time.time() + int(payload.get("expires_in", 3600))

    async def authenticate(self, force: bool = False) -> None:
        if not force and self._access_token and self._expires_at > time.time() + 60:
            return

        if self._refresh_token:
            try:
                if self._auth_mode == AUTH_MODE_OAUTH:
                    payload = await self._post_form(
                        f"{COGNITO_BASE}/oauth2/token",
                        {
                            "grant_type": "refresh_token",
                            "client_id": CLIENT_ID,
                            "refresh_token": self._refresh_token,
                        },
                    )
                else:
                    payload = await self._post_json(
                        f"{API_BASE}/login2",
                        {"user_name": self._username, "refreshtoken": self._refresh_token},
                    )
                await self._store(payload)
                return
            except OasisApiError as err:
                _LOGGER.debug("Refresh failed, falling back to a full login: %s", err)

        if self._auth_mode == AUTH_MODE_PASSWORD and self._username and self._password:
            payload = await self._post_json(
                f"{API_BASE}/login2",
                {"user_name": self._username, "password": self._password},
            )
            await self._store(payload)
            return

        raise OasisAuthError("Oasis sign-in expired and could not be renewed")

    @staticmethod
    async def exchange_code(
        session: aiohttp.ClientSession, code: str, verifier: str | None = None
    ) -> dict[str, Any]:
        """Redeem an authorization code from the Cognito hosted UI."""
        fields = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }
        if verifier:
            fields["code_verifier"] = verifier
        async with session.post(
            f"{COGNITO_BASE}/oauth2/token",
            data=fields,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                raise OasisAuthError(f"Token exchange failed: {body}")
            return body

    # -- transport ------------------------------------------------------

    async def _post_form(self, url: str, fields: dict[str, str]) -> dict[str, Any]:
        async with self._session.post(
            url, data=fields, headers={"Content-Type": "application/x-www-form-urlencoded"}
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                raise OasisApiError(f"{resp.status} {url}: {body}")
            return body

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._session.post(url, json=payload) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                raise OasisApiError(f"{resp.status} {url}: {body}")
            return body

    async def _call(self, method: str, path: str, payload: Any = None) -> Any:
        await self.authenticate()
        order = [self._token_field] + [
            f for f in ("access_token", "id_token") if f != self._token_field
        ]
        last: Exception | None = None
        for attempt in range(2):
            for field in order:
                token = self._access_token if field == "access_token" else self._id_token
                if not token:
                    continue
                async with self._session.request(
                    method,
                    f"{API_BASE}{path}",
                    json=payload,
                    headers={"Authorization": token},
                ) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status in (401, 403):
                        last = OasisApiError(f"{resp.status}: {body}")
                        continue
                    if resp.status >= 400:
                        raise OasisApiError(f"{resp.status} {path}: {body}")
                    self._token_field = field
                    return body
            if attempt == 0:
                await self.authenticate(force=True)
        raise OasisAuthError(str(last) if last else "No usable Oasis token")

    # -- devices --------------------------------------------------------

    async def async_get_lights(self) -> list[dict[str, Any]]:
        """Return one record per controllable device across all nodes."""
        data = await self._call("GET", "/user/nodes?node_details=true")
        lights: list[dict[str, Any]] = []
        for node in data.get("node_details", []) or []:
            node_id = node.get("id") or node.get("node_id")
            config = node.get("config", {}) or {}
            params = node.get("params", {}) or {}
            connected = (
                (node.get("status", {}) or {}).get("connectivity", {}).get("connected", False)
            )
            for device in config.get("devices", []) or []:
                device_name = device.get("name")
                device_params = params.get(device_name, {}) or {}
                param_defs = device.get("params", []) or []
                names = [p.get("name") for p in param_defs] or list(device_params)
                lights.append(
                    {
                        "node_id": node_id,
                        "device": device_name,
                        "name": device_params.get("Name") or device_name,
                        "online": bool(connected),
                        "params": device_params,
                        "param_defs": param_defs,
                        "key_power": resolve_param(names, PARAM_POWER),
                        "key_brightness": resolve_param(names, PARAM_BRIGHTNESS),
                        "key_cct": resolve_param(names, PARAM_CCT),
                        "fw_version": device_params.get("FW Version"),
                        "serial": device_params.get("Serial Number"),
                    }
                )
        return lights

    async def async_set_params(
        self, node_id: str, device: str, payload: dict[str, Any]
    ) -> Any:
        return await self._call(
            "PUT", "/user/nodes/params", [{"node_id": node_id, "payload": {device: payload}}]
        )

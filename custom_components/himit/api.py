"""Async API client for Hisense Hi-Mit II heat pump cloud."""
from __future__ import annotations

import base64
import hashlib
import json
import random
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    APP_ID, APP_SECRET, AUTH_BASE, HMT_BASE, LANGUAGE_ID,
    RSA_SIGN_KEY_B64, RSA_PWD_KEY_B64, SIGN_SALT, SOURCE_ID,
    TIMEZONE, USER_AGENT,
)

_BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
}
_POST_HEADERS = {**_BASE_HEADERS, "Content-Type": "application/json; charset=utf-8"}


# ── Crypto helpers (sync — microsecond operations, safe in event loop) ────────

def _load_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    sign_key = serialization.load_der_public_key(
        base64.b64decode(RSA_SIGN_KEY_B64), backend=default_backend()
    )
    pwd_key = serialization.load_der_public_key(
        base64.b64decode(RSA_PWD_KEY_B64), backend=default_backend()
    )
    return sign_key, pwd_key


_SIGN_KEY, _PWD_KEY = _load_keys()


def compute_sign(params: dict) -> str:
    """Build the RSA-signed request signature.

    Algorithm (RsaSignUtil.obtainSign):
      sort params (skip empty/"[]") → k=v&k=v...+SALT → SHA-256 → RSA-PKCS1v15-Encrypt → Base64
    """
    from cryptography.hazmat.primitives.asymmetric import padding as _padding
    filtered = {k: v for k, v in params.items() if v and str(v) not in ("", "[]")}
    sign_str = "&".join(f"{k}={v}" for k, v in sorted(filtered.items())) + SIGN_SALT
    sha256 = hashlib.sha256(sign_str.encode("utf-8")).digest()
    encrypted = _SIGN_KEY.encrypt(sha256, _padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def encode_password(plaintext: str) -> str:
    """Encode login password (RsaPasswordUtils.enCodePwd).

    MD5(plaintext) → uppercase hex → RSA-PKCS1v15-Encrypt(pwd_key) → Base64
    """
    from cryptography.hazmat.primitives.asymmetric import padding as _padding
    md5_upper = hashlib.md5(plaintext.encode("utf-8")).hexdigest().upper()
    encrypted = _PWD_KEY.encrypt(md5_upper.encode("utf-8"), _padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def _ts() -> str:
    return str(int(time.time() * 1000))


def _rand() -> str:
    rand_input = str(uuid.uuid4()) + _ts()
    return hashlib.md5(rand_input.encode()).hexdigest()


def _base_params(access_token: str = "") -> dict:
    """Mirror CommonParameters.getHeadParameter()."""
    p: dict[str, Any] = {
        "languageId": LANGUAGE_ID,
        "randStr":    _rand(),
        "timeStamp":  _ts(),
        "timezone":   TIMEZONE,
        "version":    "2.1" if access_token else "5.0",
    }
    if access_token:
        p["accessToken"] = access_token
    return p


# ── API class ─────────────────────────────────────────────────────────────────

class HimitAPIError(Exception):
    """Raised when the server returns a non-zero result code."""


class HimitAuthError(HimitAPIError):
    """Raised for authentication failures (bad credentials, expired token)."""


class HimitAPI:
    """Async HTTP client for the Hi-Mit II cloud API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check(self, resp: dict, label: str) -> dict:
        """Raise HimitAPIError if the response indicates failure."""
        if "response" in resp and isinstance(resp["response"], dict):
            inner = resp["response"]
            code = str(inner.get("resultCode", inner.get("code", "?")))
            if code != "0":
                msg = inner.get("errorDesc", inner.get("msg", "no detail"))
                if code in ("401", "1001", "1002", "10001"):
                    raise HimitAuthError(f"[{label}] Auth error {code}: {msg}")
                raise HimitAPIError(f"[{label}] Server error {code}: {msg}")
            return inner
        code = str(resp.get("code", resp.get("result", "?")))
        if code not in ("0", "200", "success"):
            msg = resp.get("msg", resp.get("message", "no detail"))
            raise HimitAPIError(f"[{label}] Server error {code}: {msg}")
        return resp

    async def _get(self, url: str, params: dict) -> dict:
        params = dict(params)
        params["sign"] = compute_sign(params)
        async with self._session.get(url, params=params, headers=_BASE_HEADERS) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def _post(self, url: str, body: dict) -> dict:
        body = dict(body)
        body["sign"] = compute_sign(body)
        async with self._session.post(url, json=body, headers=_POST_HEADERS) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    # ── Public API ────────────────────────────────────────────────────────────

    async def login(self, username: str, password: str) -> dict:
        """Login with username/password.

        Returns dict with: accessToken, refreshToken, tokenExpireTime,
        refreshTokenExpiredTime, tokenCreateTime, customerId.
        """
        body = {
            "languageId": "1",
            "randStr":    _rand(),
            "timeStamp":  _ts(),
            "timezone":   TIMEZONE,
            "version":    "5.0",
            "loginName":  username,
            "password":   encode_password(password),
            "appId":      APP_ID,
            "appSecret":  APP_SECRET,
            "sourceId":   SOURCE_ID,
        }
        resp = await self._post(f"{AUTH_BASE}/account/acc/login_pwd", body)
        inner = self._check(resp, "login_pwd")
        token = inner.get("accessToken") or inner.get("access_token", "")
        if not token:
            raise HimitAPIError(f"No accessToken in login response: {resp}")
        return {
            "access_token":          token,
            "refresh_token":         inner.get("refreshToken", ""),
            "token_expire_secs":     inner.get("tokenExpireTime", 7200),
            "refresh_expire_secs":   inner.get("refreshTokenExpiredTime", 2592000),
            "token_created_ms":      int(inner.get("tokenCreateTime", time.time() * 1000)),
            "customer_id":           str(inner.get("customerId", "")),
        }

    async def refresh_token(self, refresh_token: str) -> dict:
        """Exchange a refresh token for a new access token.

        Returns same shape as login().
        """
        body = {
            "languageId":   LANGUAGE_ID,
            "randStr":      _rand(),
            "timeStamp":    _ts(),
            "timezone":     TIMEZONE,
            "version":      "5.0",
            "refreshToken": refresh_token,
            "appId":        APP_ID,
            "appSecret":    APP_SECRET,
            "sourceId":     SOURCE_ID,
        }
        resp = await self._post(f"{AUTH_BASE}/account/acc/refresh_token", body)
        inner = self._check(resp, "refresh_token")
        token = inner.get("accessToken") or inner.get("access_token", "")
        if not token:
            raise HimitAPIError("No accessToken in refresh response")
        return {
            "access_token":        token,
            "refresh_token":       inner.get("refreshToken", refresh_token),
            "token_expire_secs":   inner.get("tokenExpireTime", 7200),
            "refresh_expire_secs": inner.get("refreshTokenExpiredTime", 2592000),
            "token_created_ms":    int(inner.get("tokenCreateTime", time.time() * 1000)),
        }

    async def get_home_list(self, access_token: str) -> list[dict]:
        """Return list of homes [{homeId, homeName, ...}]."""
        params = _base_params(access_token)
        resp = await self._get(f"{HMT_BASE}/himit-lgs/get_home_list", params)
        inner = self._check(resp, "get_home_list")
        return inner.get("homeList") or inner.get("home_list") or []

    async def get_devices(self, access_token: str, home_id: str) -> dict:
        """Return the raw customerDeviceResponse dict."""
        params = _base_params(access_token)
        params["homeId"]     = home_id
        params["deviceType"] = "0"
        resp = await self._get(
            f"{HMT_BASE}/himit-dms/get_customer_device_list_info", params
        )
        return self._check(resp, "get_devices")

    async def get_device_property(
        self, access_token: str, devices: list[dict]
    ) -> list[dict]:
        """Fetch full state for a list of {wifiId, deviceId} dicts.

        Returns devicesProperties list — each item has functions/status/allStatus.
        """
        body = {
            "languageId":  LANGUAGE_ID,
            "randStr":     _rand(),
            "timeStamp":   _ts(),
            "timezone":    TIMEZONE,
            "version":     "5.0",
            "accessToken": access_token,
            "appId":       APP_ID,
            "appSecret":   APP_SECRET,
            "sourceId":    SOURCE_ID,
        }
        device_list_json = json.dumps(devices, separators=(",", ":"))
        sign_params = dict(body)
        sign_params["deviceList"] = device_list_json
        body["sign"] = compute_sign(sign_params)
        body["deviceList"] = devices

        async with self._session.post(
            f"{HMT_BASE}/himit-dshd/getDeviceProperty",
            json=body,
            headers=_POST_HEADERS,
        ) as r:
            r.raise_for_status()
            resp = await r.json(content_type=None)

        inner = self._check(resp, "getDeviceProperty")
        return inner.get("devicesProperties") or []

    async def set_device_property(
        self,
        access_token: str,
        wifi_id: str,
        device_id: str,
        properties: list[dict],
    ) -> dict:
        """Send control commands to a device.

        properties: [{cmdType: str, cmdValue: str}, ...]
        """
        body = {
            "languageId":    LANGUAGE_ID,
            "randStr":       _rand(),
            "timeStamp":     _ts(),
            "timezone":      TIMEZONE,
            "version":       "2.1",
            "accessToken":   access_token,
            "appId":         APP_ID,
            "appSecret":     APP_SECRET,
            "sourceId":      SOURCE_ID,
            "wifiId":        wifi_id,
            "deviceId":      device_id,
            "controlRecord": "1",
        }
        props_json = json.dumps(properties, separators=(",", ":"))
        sign_params = dict(body)
        sign_params["properties"] = props_json
        body["sign"] = compute_sign(sign_params)
        body["properties"] = properties

        async with self._session.post(
            f"{HMT_BASE}/himit-dshd/setDeviceProperty",
            json=body,
            headers=_POST_HEADERS,
        ) as r:
            r.raise_for_status()
            resp = await r.json(content_type=None)

        return self._check(resp, "setDeviceProperty")

    async def usr_control_record(
        self,
        access_token: str,
        wifi_id: str,
        device_id: str,
        properties: list[dict],
    ) -> dict:
        """Log a control action (called after setDeviceProperty).

        The mobile app calls this endpoint after every setDeviceProperty to
        confirm/commit the change.  Same body as setDeviceProperty minus
        the controlRecord flag.
        """
        body = {
            "languageId":  LANGUAGE_ID,
            "randStr":     _rand(),
            "timeStamp":   _ts(),
            "timezone":    TIMEZONE,
            "version":     "2.1",
            "accessToken": access_token,
            "appId":       APP_ID,
            "appSecret":   APP_SECRET,
            "sourceId":    SOURCE_ID,
            "wifiId":      wifi_id,
            "deviceId":    device_id,
        }
        props_json = json.dumps(properties, separators=(",", ":"))
        sign_params = dict(body)
        sign_params["properties"] = props_json
        body["sign"] = compute_sign(sign_params)
        body["properties"] = properties

        async with self._session.post(
            f"{HMT_BASE}/himit-dshd/usrControlRecord",
            json=body,
            headers=_POST_HEADERS,
        ) as r:
            r.raise_for_status()
            resp = await r.json(content_type=None)

        return self._check(resp, "usrControlRecord")

#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║          Hisense Hi-Mit II — Device Query (Fully Working)           ║
╚══════════════════════════════════════════════════════════════════════╝

Authenticate with username/password and print all devices + current state.

USAGE
─────
  Query (read-only — prints all device state):
    python3 himit_query.py <username> <password>
    python3 himit_query.py <username> <password> --json
    python3 himit_query.py --token <accessToken> --home <homeId>

  Control — Circuit 1 (Ciclo 1):
    python3 himit_query.py <username> <password> --c1-on
    python3 himit_query.py <username> <password> --c1-off
    python3 himit_query.py --token <tok> --home <hid> --c1-on
    python3 himit_query.py --token <tok> --home <hid> --c1-off

  Control — Circuit 2 (Ciclo 2):
    python3 himit_query.py <username> <password> --c2-on
    python3 himit_query.py <username> <password> --c2-off

  Control — Domestic Hot Water (DHW):
    python3 himit_query.py <username> <password> --dhw-on
    python3 himit_query.py <username> <password> --dhw-off

  Multiple controls in one call:
    python3 himit_query.py <username> <password> --c1-on --dhw-off

  Control with explicit device (needed if account has >1 ATW device):
    python3 himit_query.py --token <tok> --home <hid> \
        --wifi-id <wifiId> --device-id <deviceId> --c1-on

  Verbose / debug:
    python3 himit_query.py <username> <password> -v

TEMPERATURE FIELDS
──────────────────
  In the app you see two numbers per circuit, e.g. "15" and "20".
  They map to these JSON fields in getDeviceProperty → devicesProperties[0]:

    Ts_c1_water  (in status)     — Circuit 1 water SETPOINT  (the "15" you dial)
    Ts_c2_water  (in status)     — Circuit 2 water SETPOINT
    TDHWS        (in status)     — DHW setpoint (°C)
    Tswps        (in status)     — Swimming pool setpoint (°C)

    fixedDid18   (in functions)  — Circuit 1 ACTUAL water temp  ← "17" shown next to C1 setpoint
    fixedDid19   (in functions)  — Circuit 2 ACTUAL water temp
    fixedDid16   (in functions)  — DHW ACTUAL water temp         ← "20" shown on home card
    fixedDid17   (in functions)  — Swimming pool ACTUAL water temp
                                   (confirmed from doSetCycle1Item/doSetCycle2Item in APK:
                                    tvTag333←fixedDid18 C1, tvTag444←fixedDid19 C2,
                                    tvTag111←fixedDid16 DHW, tvTag222←fixedDid17 SWP)
                                   -127 = sensor not connected

    TsR1..TsR8   (in status)     — Room sensor temperatures (°C)
    Trc1R1..R4   (in functions)  — Circuit 1 room set-point temperatures
    swj_Ta       (in status)     — Outdoor ambient temperature (°C)

SWITCH FIELDS (setDeviceProperty cmdType)
─────────────────────────────────────────
    c1_SW_ON     "1"/"0"   Circuit 1 (Ciclo 1) master on/off
    c2_SW_ON     "1"/"0"   Circuit 2 (Ciclo 2) master on/off
    DHW_SW_ON    "1"/"0"   Domestic Hot Water on/off
    SWP_SW_ON    "1"/"0"   Swimming Pool on/off
    A2W_SW_ON    "1"/"0"   Air-to-Water heat pump on/off
    c1R1_SW..    "1"/"0"   Individual room switches (circuit 1, rooms 1-4)
    c2R1_SW..    "1"/"0"   Individual room switches (circuit 2, rooms 1-4)

API ENDPOINTS (all on hmt-eu-gateway.hijuconn.com)
───────────────────────────────────────────────────
    GET  /himit-lgs/get_home_list               — list homes
    GET  /himit-dms/get_customer_device_list_info  — list all devices
    GET  /himit-dms/get_hmt_attr_info           — firmware versions
    POST /himit-dms/get_atw_vales               — ATW parameter values
    POST /himit-dshd/getDeviceProperty          — full device state (3 sub-dicts)
    POST /himit-dshd/setDeviceProperty          — send control commands

REQUIREMENTS
    pip install cryptography requests

HOW THE SIGNING WORKS (reverse-engineered from APK classes.dex)
────────────────────────────────────────────────────────────────
Found in: com.hisense.juconnect.hismart.networks.parameters.RsaSignUtil

  1. Collect all request params into a dict (skip empty values and "[]")
  2. Sort keys alphabetically
  3. Build:  key1=val1&key2=val2&...
  4. Append SALT:  D9519A4B756946F081B7BB5B5E8D1197
  5. SHA-256 the whole string → 32 bytes
  6. RSA PKCS1v15 ENCRYPT the 32-byte hash with the 2048-bit PUBLIC KEY
     from assets/rsa_public_key.key  (raw DER binary in the APK)
  7. Base64-encode the 256-byte result → that's the `sign` parameter

  NOTE: The server holds the matching PRIVATE key and decrypts to verify.
  No private key is needed client-side — we only need to ENCRYPT.

PASSWORD ENCODING (from RsaPasswordUtils.kt)
─────────────────────────────────────────────
  1. MD5(plaintext_password) → uppercase hex string  e.g. "A1B2C3..."
  2. RSA PKCS1v15 ENCRYPT the UTF-8 bytes of that hex string
     with the 512-bit PUBLIC KEY from assets/rsa_account_public_key.key
     (base64-encoded DER in the APK)
  3. Base64 (no-wrap) encode → that's the `password` field in login body
"""

import argparse
import base64
import hashlib
import json
import random
import sys
import time
from pathlib import Path

# ── Third-party ──────────────────────────────────────────────────────────────
try:
    import requests
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("Missing dependencies. Run:  pip install cryptography requests")
    sys.exit(1)

# ═════════════════════════════════════════════════════════════════════════════
#  EMBEDDED PUBLIC KEYS  (extracted from assets/ in the APK)
# ═════════════════════════════════════════════════════════════════════════════

# rsa_public_key.key — 2048-bit, raw DER binary (for request signing)
RSA_SIGN_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyyWrNG6q475HIHu7sMVu"
    "vHof6vlgPeixmxa4EL/UsvVvHPz33NnWoQetQqit9TBNzUjMXw0KlY9PXM4iqHUU"
    "U+dSyNDq1jZWIiJ2C2FccppswJtIKL3NRMFvT9PFh6NlP/4FUcQKojgKFbF7Kacc"
    "JPKYHlwaO7qgoIjLxAHlSOXGpucJcOkPzT2EqsSVnW8sn8kenvNmghXDayhgxsh6"
    "AyxK4kehJplEnmX/iYCfNoFXknGcLqFWYccgBz3fybvx30C/0IgU1980L8QsUAv5"
    "esZmN8ugnbRgLRxKRlkQQLxQAiZMZdKTAx665YflT3YMHJvEFE8c2XFgoxHzSMc4"
    "BwIDAQAB"
)

# rsa_account_public_key.key — 512-bit, base64-DER (for password encryption)
RSA_PWD_KEY_B64 = (
    "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAL1pyw5RThDowxOMDeV/p5vY3f8o5hgt"
    "hurwD9Ybby5OVQl3gyHLPie4j6HVmDCMypWbGt94LvpYtVW3ZDVIAc0CAwEAAQ=="
)

# ═════════════════════════════════════════════════════════════════════════════
#  CONSTANTS  (extracted from captured traffic + decompiled code)
# ═════════════════════════════════════════════════════════════════════════════

SIGN_SALT    = "D9519A4B756946F081B7BB5B5E8D1197"  # from RsaSignUtil.SALT
APP_ID       = "5065090793492"
APP_SECRET   = "cW12jvV8DYFLNYS80XNCANGOHskZ1ze_C2NqNHt9UF9fKpJK23bqc6OMr20ExObd"
SOURCE_ID    = "td0010020000EC3A181482E84C7AB9091A47C2F77C5B"
APP_VERSION  = "5.0"
VERSION_CODE = "1.3.5"
TIMEZONE     = "CET"
LANGUAGE_ID  = "9"
PLATFORM_ID  = "103"
USER_AGENT   = "Hi-Mit II/1.3.5 (iPhone; iOS 26.3; Scale/3.00)"

AUTH_BASE    = "https://auth-gateway.hijuconn.com"
HMT_BASE     = "https://hmt-eu-gateway.hijuconn.com"

# ═════════════════════════════════════════════════════════════════════════════
#  KEY LOADING
# ═════════════════════════════════════════════════════════════════════════════

def _load_sign_key():
    der = base64.b64decode(RSA_SIGN_KEY_B64)
    return serialization.load_der_public_key(der, backend=default_backend())

def _load_pwd_key():
    der = base64.b64decode(RSA_PWD_KEY_B64)
    return serialization.load_der_public_key(der, backend=default_backend())

_SIGN_KEY = _load_sign_key()
_PWD_KEY  = _load_pwd_key()

# ═════════════════════════════════════════════════════════════════════════════
#  CRYPTO HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def compute_sign(params: dict) -> str:
    """
    Build the `sign` parameter for any API request.

    Algorithm (from RsaSignUtil.obtainSign):
      sorted(params, skip empty/"[]") → k=v&k=v... + SALT → SHA256 → RSA-PKCS1v15-Encrypt → Base64
    """
    filtered = {k: v for k, v in params.items() if v and str(v) not in ("", "[]")}
    sign_str = "&".join(f"{k}={v}" for k, v in sorted(filtered.items())) + SIGN_SALT
    sha256   = hashlib.sha256(sign_str.encode("utf-8")).digest()
    encrypted = _SIGN_KEY.encrypt(sha256, padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def encode_password(plaintext: str) -> str:
    """
    Encode the password for the login request.

    Algorithm (from RsaPasswordUtils.enCodePwd):
      MD5(plaintext) → UPPERCASE hex → RSA-PKCS1v15-Encrypt(pwd_key) → Base64-no-wrap
    """
    md5_upper = hashlib.md5(plaintext.encode("utf-8")).hexdigest().upper()
    encrypted  = _PWD_KEY.encrypt(md5_upper.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()

# ═════════════════════════════════════════════════════════════════════════════
#  REQUEST HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _ts() -> str:
    return str(int(time.time() * 1000))

def _rand() -> str:
    return f"{random.randint(0, 999999):06d}"

def _base_params(access_token: str = "", language: str = LANGUAGE_ID) -> dict:
    """
    Mirrors CommonParameters.getHeadParameter() from hi-http module.
    - No-token variant: version=5.0, accessToken from stored session
    - Token variant:    version=2.1, accessToken passed explicitly
    timeStamp is milliseconds (System.currentTimeMillis()).
    randStr is MD5(UUID+timestamp) — we use a UUID hex for simplicity.
    """
    import uuid, hashlib
    rand_input = str(uuid.uuid4()) + str(int(time.time() * 1000))
    rand_str = hashlib.md5(rand_input.encode()).hexdigest()
    p = {
        "languageId": language,
        "randStr":    rand_str,
        "timeStamp":  _ts(),           # milliseconds
        "timezone":   TIMEZONE,
        "version":    "2.1" if access_token else "5.0",
    }
    if access_token:
        p["accessToken"] = access_token
    return p

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      USER_AGENT,
        "Accept":          "*/*",
        "Accept-Encoding": "gzip, deflate, br",
    })
    return s

SESSION = _session()

def _get(url: str, params: dict) -> dict:
    params = dict(params)
    params["sign"] = compute_sign(params)
    r = SESSION.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def _post(url: str, body: dict) -> dict:
    body = dict(body)
    body["sign"] = compute_sign(body)
    r = SESSION.post(url, json=body,
                     headers={"Content-Type": "application/json; charset=utf-8"},
                     timeout=15)
    r.raise_for_status()
    return r.json()

def _check(resp: dict, label: str) -> None:
    """Check a response for errors — handles both auth-gateway and hmt-gateway shapes."""
    # Auth-gateway shape:  {"response": {"resultCode": 0, ...}, "signatureServer": "..."}
    if "response" in resp and isinstance(resp["response"], dict):
        inner = resp["response"]
        code = inner.get("resultCode", inner.get("code", "?"))
        if str(code) != "0":
            msg = inner.get("errorDesc", inner.get("msg", "no message"))
            raise RuntimeError(f"[{label}] Server error {code}: {msg}\nFull response: {json.dumps(resp, indent=2)}")
        return
    # HMT-gateway shape:  {"code": "0", "msg": "...", "data": {...}}
    code = str(resp.get("code", resp.get("result", "?")))
    if code not in ("0", "200", "success"):
        msg = resp.get("msg", resp.get("message", "no message"))
        raise RuntimeError(f"[{label}] Server error {code}: {msg}\nFull response: {json.dumps(resp, indent=2)}")

# ═════════════════════════════════════════════════════════════════════════════
#  API CALLS
# ═════════════════════════════════════════════════════════════════════════════

def login(username: str, password: str) -> tuple[str, str]:
    """Returns (accessToken, customerId)"""
    print("  \u2192 Encoding password \u2026")
    enc_pwd = encode_password(password)

    # Login uses common params (version, timeStamp, languageId, timezone, randStr)
    # plus login-specific params: loginName, password, appId, appSecret, sourceId
    # (no accessToken, platformId, or versionCode)
    body = _base_params(language="1")
    body.update({
        "loginName": username,   # Params.LOGINNAME = "loginName"
        "password":  enc_pwd,
        "appId":     APP_ID,
        "appSecret": APP_SECRET,
        "sourceId":  SOURCE_ID,
    })

    resp = _post(f"{AUTH_BASE}/account/acc/login_pwd", body)
    _check(resp, "login_pwd")

    # Response shape: {"response": {"resultCode": 0, "accessToken": "...", "customerId": "..."}, ...}
    inner = resp.get("response", resp)
    token = inner.get("accessToken") or inner.get("access_token", "")
    cid   = str(inner.get("customerId") or inner.get("customer_id", ""))
    if not token:
        raise RuntimeError(f"No accessToken in response: {json.dumps(resp, indent=2)}")
    return token, cid



def get_home_list(access_token: str) -> list:
    params = _base_params(access_token)
    resp = _get(f"{HMT_BASE}/himit-lgs/get_home_list", params)
    _check(resp, "get_home_list")
    # HiResult envelope: {"response": {"resultCode": 0, "homeList": [...], ...}, "signatureServer": "..."}
    inner = resp.get("response", resp)
    homes = inner.get("homeList") or inner.get("home_list") or []
    if not homes and not isinstance(homes, list):
        homes = []
    return homes


def get_devices(access_token: str, home_id: str) -> dict:
    params = _base_params(access_token)
    params["homeId"]     = home_id
    params["deviceType"] = "0"
    resp = _get(f"{HMT_BASE}/himit-dms/get_customer_device_list_info", params)
    _check(resp, "get_customer_device_list_info")
    # Return the inner response object so callers can inspect it
    return resp.get("response", resp) if "response" in resp else resp

def get_hmt_attr_info(access_token: str, wifi_id: str, home_id: str) -> dict:
    """GET /himit-dms/get_hmt_attr_info  — returns DeviceControlResponse.
    Fields: wifiVersion, mcuVersion, inUnitVersion, outUnitVersion,
            attrDeviceInfoList (list of ControlDeviceInfo dicts).
    """
    params = _base_params(access_token)
    params["wifiId"]  = wifi_id
    params["homeId"]  = home_id
    resp = _get(f"{HMT_BASE}/himit-dms/get_hmt_attr_info", params)
    _check(resp, "get_hmt_attr_info")
    return resp.get("response", resp)


def get_atw_vales(access_token: str, wifi_id: str, device_id: str) -> dict:
    """POST /himit-dms/get_atw_vales  — returns DeviceValeInfoResponse.
    Params sent as JSON body: wifiId, deviceId (plus common params).
    """
    body = _base_params(access_token)
    body["wifiId"]   = wifi_id
    body["deviceId"] = device_id
    resp = _post(f"{HMT_BASE}/himit-dms/get_atw_vales", body)
    _check(resp, "get_atw_vales")
    return resp.get("response", resp)


def get_device_property(access_token: str, devices: list) -> dict:
    """POST /himit-dshd/getDeviceProperty — returns room-level temperatures and on/off states.

    From Telerik capture: uses version=5.0 and includes appId/appSecret/sourceId in body.
    `devices` is a list of dicts with keys: wifiId, deviceId.

    The sign covers all scalar fields + the JSON-serialised deviceList string.
    """
    import json as _json
    body = {
        "languageId": LANGUAGE_ID,
        "randStr":    _rand(),
        "timeStamp":  _ts(),
        "timezone":   TIMEZONE,
        "version":    "5.0",
        "accessToken": access_token,
        "appId":      APP_ID,
        "appSecret":  APP_SECRET,
        "sourceId":   SOURCE_ID,
    }
    # Serialise the deviceList as a JSON string for signing (mirrors Java JSONArray.toString())
    device_list_json = _json.dumps(devices, separators=(",", ":"))
    # Sign over all scalar fields + the serialised list
    sign_params = dict(body)
    sign_params["deviceList"] = device_list_json
    body["sign"] = compute_sign(sign_params)
    # Send the actual list object (not a string) in the POST body
    body["deviceList"] = devices
    r = SESSION.post(
        f"{HMT_BASE}/himit-dshd/getDeviceProperty",
        json=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    r.raise_for_status()
    resp = r.json()
    _check(resp, "getDeviceProperty")
    # Response: {"response": {"resultCode": 0, "devicesProperties": [...]}, ...}
    inner = resp.get("response", resp)
    return inner.get("devicesProperties", inner)


def set_device_property(access_token: str, wifi_id: str, device_id: str,
                        properties: list) -> dict:
    """POST /himit-dshd/setDeviceProperty  — sends one or more control commands.

    Reverse-engineered from DeviceServiceImpl.sendCommand() and ParameterUtils.createParamBodySpec().

    Body structure (from APK):
      scalar params: wifiId, deviceId, controlRecord="1"  (+ common auth params)
      array param:   properties = [{cmdType: str, cmdValue: str}, ...]
    Sign covers ALL params including the JSON-stringified properties array.

    Common field → cmdType / cmdValue pairs:
      c1_SW_ON   "1"/"0"   — Circuit 1 (Ciclo 1) master on/off
      c2_SW_ON   "1"/"0"   — Circuit 2 master on/off
      DHW_SW_ON  "1"/"0"   — Domestic Hot Water on/off
      SWP_SW_ON  "1"/"0"   — Swimming Pool on/off
      A2W_SW_ON  "1"/"0"   — Air-to-Water heat pump on/off
      Ts_c1_water  "<int>" — Circuit 1 water temperature SETPOINT (°C)
      Ts_c2_water  "<int>" — Circuit 2 water temperature SETPOINT (°C)
      TDHWS        "<int>" — DHW temperature setpoint (°C)
      Tswps        "<int>" — Pool temperature setpoint (°C)
    """
    import json as _json

    # ── Build body (mirrors createParamBodySpec in ParameterUtils.kt) ─────────
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
        # Scalar params for this endpoint
        "wifiId":         wifi_id,
        "deviceId":       device_id,
        "controlRecord":  "1",
    }
    # Sign covers scalars + the JSONArray serialised as a string
    # (matches: linkedHashMap2.put(key, StringsKt.replace(jsonArray.toString(), "\\/", "/", ...)))
    props_json = _json.dumps(properties, separators=(",", ":"))
    sign_params = dict(body)
    sign_params["properties"] = props_json
    body["sign"] = compute_sign(sign_params)
    # Send actual array in the body (not a string)
    body["properties"] = properties

    r = SESSION.post(
        f"{HMT_BASE}/himit-dshd/setDeviceProperty",
        json=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    r.raise_for_status()
    resp = r.json()
    _check(resp, "setDeviceProperty")
    return resp.get("response", resp)


def set_switch(access_token: str, wifi_id: str, device_id: str,
               field: str, on: bool) -> dict:
    """Toggle a single on/off switch field via setDeviceProperty.

    field must be one of: c1_SW_ON, c2_SW_ON, DHW_SW_ON, SWP_SW_ON, A2W_SW_ON
    """
    val = "1" if on else "0"
    return set_device_property(access_token, wifi_id, device_id,
                                [{"cmdType": field, "cmdValue": val}])


# ─────────────────────────────────────────────────────────────────────────────
#  PRETTY PRINTER
# ─────────────────────────────────────────────────────────────────────────────

MODE_MAP   = {0:"Auto", 1:"Cool", 2:"Dry", 3:"Fan", 4:"Heat"}
FAN_MAP    = {0:"Auto", 1:"Low",  2:"Med", 3:"High", 4:"Turbo"}
ONLINE_MAP = {0:"Offline", 1:"Online"}

ANSI = {
    "reset": "\033[0m", "bold": "\033[1m",
    "green": "\033[92m", "red": "\033[91m",
    "cyan":  "\033[96m", "yellow": "\033[93m",
    "blue":  "\033[94m", "dim":  "\033[2m",
}
def c(color, text):   return f"{ANSI[color]}{text}{ANSI['reset']}"
def bold(text):        return c("bold", text)


def _decode(val, lookup):
    try:
        return lookup.get(int(val), str(val))
    except (TypeError, ValueError):
        return str(val) if val is not None else "—"


def print_device(idx: int, dev: dict) -> None:
    did    = dev.get("deviceId", dev.get("device_id", "—"))
    dname  = dev.get("deviceName", dev.get("device_name", f"Device {idx}"))
    dtype  = dev.get("deviceType", dev.get("device_type", "—"))
    online = dev.get("onlineStatus", dev.get("online_status", -1))

    props_raw = dev.get("properties") or dev.get("property") or {}
    if isinstance(props_raw, list):
        props = {p.get("name", "?"): p.get("value") for p in props_raw}
    else:
        props = props_raw

    def p(k, *aliases):
        for key in (k, *aliases):
            if key in props:
                return props[key]
        return None

    power    = p("power", "onOff")
    mode     = p("mode")
    set_temp = p("setTemp", "targetTemperature")
    in_temp  = p("indoorTemp", "currentTemperature")
    out_temp = p("outdoorTemp")
    fan      = p("fanSpeed", "windSpeed")
    swing    = p("swing", "updownWind")
    economy  = p("economy")
    sleep_m  = p("sleep")
    health   = p("health")

    power_s  = (c("green", "● ON ") if str(power) == "1" else c("red", "○ OFF")) if power is not None else "—"
    mode_s   = _decode(mode, MODE_MAP)
    fan_s    = _decode(fan, FAN_MAP)
    online_s = (c("green", "Online") if str(online) == "1" else c("red", "Offline")) if online != -1 else "—"

    W = 58
    print(f"\n  {bold(c('cyan', f'╔══ Device {idx}'))} {c('dim', '═'*(W-12))}")
    print(f"  {bold('║')}  {bold('Name'):<12}  {dname}")
    print(f"  {bold('║')}  {c('dim','Device ID'):<20}  {c('dim', did)}")
    print(f"  {bold('║')}  {'Type':<12}  {dtype}   {'Status':<8} {online_s}")
    print(f"  {bold('║')}  {'─'*(W-2)}")
    print(f"  {bold('║')}  {'Power':<12}  {power_s}")
    if mode     is not None: print(f"  {bold('║')}  {'Mode':<12}  {mode_s}")
    if set_temp is not None: print(f"  {bold('║')}  {'Set Temp':<12}  {set_temp} °C")
    if in_temp  is not None: print(f"  {bold('║')}  {'Indoor Temp':<12}  {in_temp} °C")
    if out_temp is not None: print(f"  {bold('║')}  {'Outdoor Temp':<12}  {out_temp} °C")
    if fan      is not None: print(f"  {bold('║')}  {'Fan Speed':<12}  {fan_s}")
    if swing    is not None: print(f"  {bold('║')}  {'Swing':<12}  {swing}")
    if economy  is not None: print(f"  {bold('║')}  {'Economy':<12}  {economy}")
    if sleep_m  is not None: print(f"  {bold('║')}  {'Sleep':<12}  {sleep_m}")
    if health   is not None: print(f"  {bold('║')}  {'Health':<12}  {health}")

    # Extra properties not in the standard list
    standard = {"power","onOff","mode","setTemp","targetTemperature","indoorTemp",
                "currentTemperature","outdoorTemp","fanSpeed","windSpeed","swing",
                "updownWind","economy","sleep","health"}
    extras = {k: v for k, v in props.items() if k not in standard}
    if extras:
        print(f"  {bold('║')}  {c('dim', '── additional ──')}")
        for k, v in sorted(extras.items()):
            print(f"  {bold('║')}  {c('dim', k):<30}  {v}")

    print(f"  {bold(c('cyan', '╚'))}{'═'*(W-1)}")



def print_atw_device(idx, dev, attr_info=None, vales=None):
    """Pretty-print an ATW heat-pump device with its queried parameters."""
    wifi_id  = dev.get("wifiId", "—")
    did      = dev.get("deviceId", "—")
    dname    = dev.get("deviceNickName") or dev.get("deviceName") or f"ATW {idx}"
    online   = dev.get("onLineStatus", dev.get("onlineStatus", -1))
    model    = dev.get("modelCode", "—")

    online_s = (c("green", "Online") if str(online) == "1" else c("red", "Offline")) if online != -1 else "—"

    W = 58
    print(f"\n  {bold(c('cyan', f'╔══ ATW Device {idx}'))} {c('dim', '═'*(W-15))}")
    print(f"  {bold('║')}  {bold('Name'):<16}  {dname}")
    print(f"  {bold('║')}  {c('dim','WiFi ID'):<24}  {c('dim', wifi_id)}")
    print(f"  {bold('║')}  {c('dim','Device ID'):<24}  {c('dim', did)}")
    print(f"  {bold('║')}  {'Model':<16}  {model}   {online_s}")

    if attr_info:
        print(f"  {bold('║')}  {'─'*(W-2)}")
        print(f"  {bold('║')}  {c('yellow', 'Firmware / Versions')}")
        for label, key in [
            ("WiFi FW",     "wifiVersion"),
            ("MCU FW",      "mcuVersion"),
            ("Indoor Unit", "inUnitVersion"),
            ("Outer Unit",  "outUnitVersion"),
        ]:
            val = attr_info.get(key)
            if val:
                print(f"  {bold('║')}    {label:<14}  {val}")
        attr_devices = attr_info.get("attrDeviceInfoList") or []
        if attr_devices:
            print(f"  {bold('║')}  {c('dim', '  sub-devices:')}")
            for sd in attr_devices:
                sd_name  = sd.get("name", "?")
                sd_did   = sd.get("deviceId", "?")
                sd_cat   = sd.get("deviceCategory", "?")
                sd_sys   = sd.get("systemNum", "?")
                print(f"  {bold('║')}    • {sd_name:<20}  id={sd_did}  cat={sd_cat}  sys={sd_sys}")

    if vales:
        print(f"  {bold('║')}  {'─'*(W-2)}")
        print(f"  {bold('║')}  {c('yellow', 'Current Parameters (get_atw_vales)')}")
        # Print every key/value in the vales response
        skip = {"resultCode", "errorCode", "errorDesc"}
        for k, v in sorted(vales.items()):
            if k not in skip and v is not None:
                print(f"  {bold('║')}    {c('dim', k):<30}  {v}")

    print(f"  {bold(c('cyan', '╚'))}{'═'*(W-1)}")


def extract_devices(resp: dict) -> list:
    """Extract ALL device lists from a CustomerDeviceResponse inner object.

    CustomerDeviceResponse JSON fields (from decompiled Kotlin):
        himitInfoList, airconInfoList, airPumpInfoList, valeInfoList,
        atwInfoList, hicubeAtwList, hicubeInfoList
    Returns a flat list of HimitDeviceInfo dicts (each has wifiId, deviceId, …).
    """
    atw_lists = (
        resp.get("atwInfoList") or [],
        resp.get("hicubeAtwList") or [],
    )
    other_lists = (
        resp.get("airconInfoList") or [],
        resp.get("airPumpInfoList") or [],
        resp.get("valeInfoList") or [],
        resp.get("himitInfoList") or [],
        resp.get("hicubeInfoList") or [],
    )
    flat = []
    for lst in (*atw_lists, *other_lists):
        if isinstance(lst, list):
            flat.extend(lst)
    # Fallback for older server shapes that used a generic deviceInfoList / data wrapper
    if not flat:
        data = resp.get("data") or resp
        for key in ("deviceInfoList", "deviceList", "list"):
            if isinstance(data, dict) and isinstance(data.get(key), list):
                flat = data[key]
                break
        if not flat and isinstance(data, list):
            flat = data
    return [d for d in flat if isinstance(d, dict)]


def get_atw_devices(resp: dict) -> list:
    """Return only the ATW heat-pump devices from a CustomerDeviceResponse."""
    devices = (resp.get("atwInfoList") or []) + (resp.get("hicubeAtwList") or [])
    return [d for d in devices if isinstance(d, dict)]

# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

def print_device_property(prop):
    """Pretty-print the getDeviceProperty response.

    Each device entry has nested sub-dicts:
      functions  - static/capability fields (Trc1R1..Trc2R4 room set-points, fixedDid*, etc.)
      status     - current state (TDHWS, Tswps, Ts_c1_water, TsR1-8, SW fields, etc.)
      allStatus  - merged superset (used as fallback)

    We build a flat merged view: allStatus < functions < status (status wins).
    """
    items = prop if isinstance(prop, list) else [prop]
    for item in items:
        wid = item.get("wifiId") or item.get("wifiid", "")
        did = item.get("deviceId") or item.get("deviceid", "")

        # Build flat merged view - status values take priority
        flat = {}
        flat.update(item.get("allStatus") or {})
        flat.update(item.get("functions") or {})
        flat.update(item.get("status")    or {})

        print(c("cyan", f"  ┌─ Device Property  wifiId={wid}  deviceId={did}"))

        # ── On/off switches ──────────────────────────────────────────────────
        def sw(val):
            if val is None: return c("dim", "—")
            return c("green", "ON ") if str(val) == "1" else c("red", "OFF")

        print(c("bold", "  │  Switches"))
        sw_fields = [
            ("A2W (heat pump)", flat.get("A2W_SW_ON")),
            ("DHW (hot water)",  flat.get("DHW_SW_ON")),
            ("SWP (swim pool)",  flat.get("SWP_SW_ON")),
            ("Circuit 1",        flat.get("c1_SW_ON")),
            ("Circuit 2",        flat.get("c2_SW_ON")),
        ]
        for label, val in sw_fields:
            print(f"  │    {label:<22} {sw(val)}")

        # ── Room switches ────────────────────────────────────────────────────
        room_sw = [
            ("C1R1", flat.get("c1R1_SW")), ("C1R2", flat.get("c1R2_SW")),
            ("C1R3", flat.get("c1R3_SW")), ("C1R4", flat.get("c1R4_SW")),
            ("C2R1", flat.get("c2R1_SW")), ("C2R2", flat.get("c2R2_SW")),
            ("C2R3", flat.get("c2R3_SW")), ("C2R4", flat.get("c2R4_SW")),
        ]
        active_rooms = [(n, v) for n, v in room_sw if v is not None]
        if active_rooms:
            print(c("bold", "  │  Room Switches"))
            row = "  │    " + "  ".join(f"{n}:{sw(v)}" for n, v in active_rooms)
            print(row)

        # ── Temperatures ─────────────────────────────────────────────────────
        def temp(val, unit="°C"):
            if val is None: return c("dim", "—")
            try:
                v = int(float(str(val)))
                if v == -127: return c("dim", "N/A")
                return c("yellow", f"{v}{unit}")
            except (TypeError, ValueError):
                return str(val)

        print(c("bold", "  │  Temperatures"))
        # fixedDid16 = actual current water temperature (confirmed from
        #   PumpListAdapter.java which reads fixedDid16 for tv_fwater_cur_temp)
        # fixedDid17/18/19 = additional sensors (-127 means not connected)
        def _t(v):
            """Return temperature value, or None if sensor N/A or zero."""
            if v in (None, "", "0", 0):
                return None
            try:
                if float(v) <= -100:   # -127 = sensor not connected
                    return None
                return v
            except (ValueError, TypeError):
                return None

        # Setpoint / actual pairs confirmed from HeatPumpControllActivity.doSetCycle1/2Item:
        #   tvTag3   ← Ts_c1_water  setpoint  tvTag333 ← fixedDid18  C1 actual
        #   tvTag4   ← Ts_c2_water  setpoint  tvTag444 ← fixedDid19  C2 actual
        #   tvTag1   ← TDHWS        setpoint  tvTag111 ← fixedDid16  DHW actual
        #   tvTag2   ← Tswps        setpoint  tvTag222 ← fixedDid17  SWP actual
        temp_fields = [
            # ── Circuit 1 (Ciclo 1) ───────────────────────────────────────────
            ("C1 water SETPOINT  (Ts_c1_water)", flat.get("Ts_c1_water")),
            ("C1 water ACTUAL    (fixedDid18)",  flat.get("fixedDid18")),
            # ── Circuit 2 (Ciclo 2) ───────────────────────────────────────────
            ("C2 water SETPOINT  (Ts_c2_water)", flat.get("Ts_c2_water")),
            ("C2 water ACTUAL    (fixedDid19)",  flat.get("fixedDid19")),
            # ── DHW (hot water) ───────────────────────────────────────────────
            ("DHW setpoint       (TDHWS)",        flat.get("TDHWS")),
            ("DHW water ACTUAL   (fixedDid16)",   flat.get("fixedDid16")),
            # ── Swimming pool ─────────────────────────────────────────────────
            ("SWP setpoint       (Tswps)",        flat.get("Tswps")),
            ("SWP water ACTUAL   (fixedDid17)",   flat.get("fixedDid17")),
            # ── Ambient ───────────────────────────────────────────────────────
            ("Outdoor ambient    (swj_Ta)",        flat.get("swj_Ta")),
        ]
        for label, val in temp_fields:
            v = _t(val)
            if v is not None:
                print(f"  │    {label:<38} {temp(v)}")

        # Room set-point temps (Trc1R1 … Trc2R4) - from functions sub-dict
        fn = item.get("functions") or flat
        room_temps = [
            ("C1R1", fn.get("Trc1R1")), ("C1R2", fn.get("Trc1R2")),
            ("C1R3", fn.get("Trc1R3")), ("C1R4", fn.get("Trc1R4")),
            ("C2R1", fn.get("Trc2R1")), ("C2R2", fn.get("Trc2R2")),
            ("C2R3", fn.get("Trc2R3")), ("C2R4", fn.get("Trc2R4")),
        ]
        active_rt = [(n, v) for n, v in room_temps if v not in (None, "0", 0)]
        if active_rt:
            print(c("bold", "  │  Room Set-point Temps (Trc)"))
            row = "  │    " + "  ".join(f"{n}:{temp(v)}" for n, v in active_rt)
            print(row)

        # Room sensor temps (TsR1 … TsR8) - from status sub-dict
        st = item.get("status") or flat
        room_sensor = [
            ("R1", st.get("TsR1")), ("R2", st.get("TsR2")),
            ("R3", st.get("TsR3")), ("R4", st.get("TsR4")),
            ("R5", st.get("TsR5")), ("R6", st.get("TsR6")),
            ("R7", st.get("TsR7")), ("R8", st.get("TsR8")),
        ]
        active_rs = [(n, v) for n, v in room_sensor if v not in (None, "0", 0)]
        if active_rs:
            print(c("bold", "  │  Room Sensor Temps (TsR)"))
            row = "  │    " + "  ".join(f"{n}:{temp(v)}" for n, v in active_rs)
            print(row)

        # ── Alarm / mode ─────────────────────────────────────────────────────
        alarm = flat.get("alarmCode")
        mode  = flat.get("mode") or flat.get("realRunMode")
        if alarm and alarm != "0":
            print(f"  │  {c('red', 'Alarm code: ' + str(alarm))}")
        if mode and mode != "0":
            print(f"  │  Mode: {mode}")

        print(c("cyan", "  └" + "─" * 50))


def main():
    parser = argparse.ArgumentParser(
        description="Hisense Hi-Mit II — query devices and control ATW heat pump",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES
  Query all devices (prints state, temperatures, switches):
    python3 himit_query.py user@email.com password
    python3 himit_query.py --token TOKEN --home HOMEID

  Control Circuit 1 (Ciclo 1):
    python3 himit_query.py user@email.com password --c1-on
    python3 himit_query.py user@email.com password --c1-off

  Control Circuit 2 (Ciclo 2):
    python3 himit_query.py user@email.com password --c2-on
    python3 himit_query.py user@email.com password --c2-off

  Control Domestic Hot Water (DHW):
    python3 himit_query.py user@email.com password --dhw-on
    python3 himit_query.py user@email.com password --dhw-off

  Combine multiple controls in one call:
    python3 himit_query.py user@email.com password --c1-on --dhw-off

  With pre-captured token (wifiId/deviceId auto-detected if 1 ATW device):
    python3 himit_query.py --token TOKEN --home HOMEID --c1-on
    python3 himit_query.py --token TOKEN --home HOMEID --wifi-id WIFID --device-id 3-3-0-0 --dhw-on

  Raw JSON output:
    python3 himit_query.py user@email.com password --json
    python3 himit_query.py user@email.com password -v
        """,
    )
    parser.add_argument("username", nargs="?", help="Account email/username")
    parser.add_argument("password", nargs="?", help="Account password")
    parser.add_argument("--token",  help="Use a pre-captured accessToken (skip login)")
    parser.add_argument("--home",   help="homeId (required with --token)")
    parser.add_argument("--json",   action="store_true", help="Print raw JSON response")
    parser.add_argument("--verbose","-v", action="store_true", help="Show HTTP details")
    # ── Control switches (require --token --home or credentials + --wifi-id --device-id) ──
    parser.add_argument("--wifi-id",    help="wifiId of the device to control (auto-detected if 1 ATW device)")
    parser.add_argument("--device-id",  help="deviceId of the device to control (auto-detected if 1 ATW device)")
    parser.add_argument("--c1-on",   action="store_true", help="Enable  Circuit 1 (Ciclo 1)")
    parser.add_argument("--c1-off",  action="store_true", help="Disable Circuit 1 (Ciclo 1)")
    parser.add_argument("--dhw-on",  action="store_true", help="Enable  Domestic Hot Water (DHW)")
    parser.add_argument("--dhw-off", action="store_true", help="Disable Domestic Hot Water (DHW)")
    parser.add_argument("--c2-on",   action="store_true", help="Enable  Circuit 2 (Ciclo 2)")
    parser.add_argument("--c2-off",  action="store_true", help="Disable Circuit 2 (Ciclo 2)")
    args = parser.parse_args()

    print()
    print(bold(c("cyan", "╔══════════════════════════════════════════════════╗")))
    print(bold(c("cyan", "║      Hisense Hi-Mit II — Device Query Tool       ║")))
    print(bold(c("cyan", "╚══════════════════════════════════════════════════╝")))
    print()

    access_token = ""
    home_id      = ""

    # ── Authentication ───────────────────────────────────────────────────────
    if args.token:
        if not args.home:
            parser.error("--home <homeId> is required when using --token")
        access_token = args.token
        home_id      = args.home
        print(c("yellow", "  ⚡ Using pre-captured token, skipping login"))
    else:
        if not args.username or not args.password:
            parser.error("Provide <username> and <password>, or use --token + --home")

        print(c("blue", "  ┌─ Step 1 — Authenticate"))
        access_token, customer_id = login(args.username, args.password)
        print(c("green", f"  ✓ Login OK    customerI d: {customer_id}"))
        print(c("dim",   f"    accessToken: {access_token[:50]}…"))

        # ── Home list ────────────────────────────────────────────────────────
        print()
        print(c("blue", "  ┌─ Step 2 — Get Home List"))
        homes = get_home_list(access_token)
        if not homes:
            print(c("red", "  ✗ No homes found in account"))
            sys.exit(1)

        for i, h in enumerate(homes):
            # Home model fields: id (int), defaultHomeName, homeImageUrl, homeDesc
            hid  = h.get("id") or h.get("homeId") or h.get("home_id", "?")
            name = h.get("defaultHomeName") or h.get("homeName") or h.get("name", "—")
            marker = c("green", "✓") if i == 0 else " "
            print(f"    {marker}  homeId={c('bold', str(hid))}  name={name}")

        first = homes[0]
        home_id = str(first.get("id") or first.get("homeId") or first.get("home_id", ""))
        print(c("green", f"  ✓ Using homeId: {home_id}"))

    # ── Device list & current state ──────────────────────────────────────────
    print()
    print(c("blue", "  ┌─ Step 3 — Get Device List & Current State"))
    resp = get_devices(access_token, home_id)
    devices   = extract_devices(resp)
    atw_devs  = get_atw_devices(resp)

    if not devices and not atw_devs:
        print(c("yellow", "  ⚠  No devices found. Raw response:"))
        print(json.dumps(resp, indent=2))
        sys.exit(0)

    print(c("green", f"  ✓ Found {len(devices)} total device(s), {len(atw_devs)} ATW heat-pump(s)"))

    if args.json:
        print()
        print(json.dumps(resp, indent=2))
    else:
        # Print non-ATW devices (aircon, etc.)
        non_atw = [d for d in devices if d.get("wifiId") not in {a.get("wifiId") for a in atw_devs}]
        for i, dev in enumerate(non_atw, 1):
            print_device(i, dev)

        # Print ATW devices with queried parameters
        if atw_devs:
            print()
            print(c("blue", f"  ┌─ Step 4 — Query ATW Parameters ({len(atw_devs)} device(s))"))
            for i, dev in enumerate(atw_devs, 1):
                wifi_id   = dev.get("wifiId", "")
                device_id = dev.get("deviceId", "")
                dname     = dev.get("deviceNickName") or device_id

                attr_info = None
                vales     = None

                if wifi_id:
                    try:
                        print(c("dim", f"    → get_hmt_attr_info  wifiId={wifi_id}"))
                        attr_info = get_hmt_attr_info(access_token, wifi_id, home_id)
                    except Exception as e:
                        print(c("yellow", f"    ⚠  get_hmt_attr_info failed: {e}"))
                    try:
                        print(c("dim", f"    → get_atw_vales      wifiId={wifi_id}  deviceId={device_id}"))
                        vales = get_atw_vales(access_token, wifi_id, device_id)
                    except Exception as e:
                        print(c("yellow", f"    ⚠  get_atw_vales failed: {e}"))

                dev_prop = None
                try:
                    print(c("dim", f"    → getDeviceProperty  wifiId={wifi_id}  deviceId={device_id}"))
                    dev_prop = get_device_property(access_token, [{"wifiId": wifi_id, "deviceId": device_id}])
                except Exception as e:
                    print(c("yellow", f"    ⚠  getDeviceProperty failed: {e}"))

                print_atw_device(i, dev, attr_info, vales)
                if dev_prop:
                    print_device_property(dev_prop)

    # ── Step 5 — Execute control commands if requested ──────────────────────
    control_map = [
        (args.c1_on,   "c1_SW_ON",  True,  "Circuit 1 (Ciclo 1)"),
        (args.c1_off,  "c1_SW_ON",  False, "Circuit 1 (Ciclo 1)"),
        (args.c2_on,   "c2_SW_ON",  True,  "Circuit 2 (Ciclo 2)"),
        (args.c2_off,  "c2_SW_ON",  False, "Circuit 2 (Ciclo 2)"),
        (args.dhw_on,  "DHW_SW_ON", True,  "DHW (hot water)"),
        (args.dhw_off, "DHW_SW_ON", False, "DHW (hot water)"),
    ]
    pending = [(field, on, label) for (flag, field, on, label) in control_map if flag]

    if pending:
        # Resolve target device: explicit args, or auto-select if exactly 1 ATW device
        ctrl_wifi   = getattr(args, "wifi_id",   None)
        ctrl_device = getattr(args, "device_id", None)
        if (not ctrl_wifi or not ctrl_device) and len(atw_devs) == 1:
            ctrl_wifi   = atw_devs[0].get("wifiId", "")
            ctrl_device = atw_devs[0].get("deviceId", "")
        if not ctrl_wifi or not ctrl_device:
            print(c("red", "  ✗ Cannot resolve target device — use --wifi-id and --device-id"))
            sys.exit(1)

        print()
        print(c("blue", "  ┌─ Step 5 — Apply Control Commands"))
        for field, on, label in pending:
            action = "ON " if on else "OFF"
            print(c("dim", f"    → setDeviceProperty  {label} → {action}"))
            try:
                result = set_switch(access_token, ctrl_wifi, ctrl_device, field, on)
                rc = result.get("resultCode", result.get("resultcode", "?"))
                if str(rc) == "0":
                    status_str = c("green", f"✓ {label} turned {action.strip()}")
                else:
                    status_str = c("yellow", f"⚠  resultCode={rc}  {label}")
                print(f"  │  {status_str}")
            except Exception as e:
                print(c("red", f"  ✗ setDeviceProperty failed: {e}"))

    # Save full JSON for scripting
    out_path = Path(f"/tmp/himit_devices_{int(time.time())}.json")
    payload  = {"customerDeviceResponse": resp}
    if atw_devs:
        payload["atwCount"] = len(atw_devs)
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\n  {c('dim', f'Full JSON saved to: {out_path}')}")
    print()


if __name__ == "__main__":
    main()

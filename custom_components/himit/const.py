"""Constants for the Hisense Hi-Mit II integration."""

DOMAIN = "himit"

# ── Config entry keys ─────────────────────────────────────────────────────────
CONF_HOME_ID            = "home_id"
CONF_ACCESS_TOKEN       = "access_token"
CONF_REFRESH_TOKEN      = "refresh_token"
CONF_TOKEN_CREATED_MS   = "token_created_ms"   # millis when token was issued
CONF_TOKEN_EXPIRE_SECS  = "token_expire_secs"  # lifetime in seconds
CONF_REFRESH_EXPIRE_SECS = "refresh_expire_secs"

DEFAULT_SCAN_INTERVAL = 30  # seconds

# ── API crypto (reverse-engineered from APK) ──────────────────────────────────
# rsa_public_key.key — 2048-bit DER base64 (for request signing)
RSA_SIGN_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyyWrNG6q475HIHu7sMVu"
    "vHof6vlgPeixmxa4EL/UsvVvHPz33NnWoQetQqit9TBNzUjMXw0KlY9PXM4iqHUU"
    "U+dSyNDq1jZWIiJ2C2FccppswJtIKL3NRMFvT9PFh6NlP/4FUcQKojgKFbF7Kacc"
    "JPKYHlwaO7qgoIjLxAHlSOXGpucJcOkPzT2EqsSVnW8sn8kenvNmghXDayhgxsh6"
    "AyxK4kehJplEnmX/iYCfNoFXknGcLqFWYccgBz3fybvx30C/0IgU1980L8QsUAv5"
    "esZmN8ugnbRgLRxKRlkQQLxQAiZMZdKTAx665YflT3YMHJvEFE8c2XFgoxHzSMc4"
    "BwIDAQAB"
)

# rsa_account_public_key.key — 512-bit DER base64 (for password encryption)
RSA_PWD_KEY_B64 = (
    "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAL1pyw5RThDowxOMDeV/p5vY3f8o5hgt"
    "hurwD9Ybby5OVQl3gyHLPie4j6HVmDCMypWbGt94LvpYtVW3ZDVIAc0CAwEAAQ=="
)

SIGN_SALT   = "D9519A4B756946F081B7BB5B5E8D1197"
APP_ID      = "5065090793492"
APP_SECRET  = "cW12jvV8DYFLNYS80XNCANGOHskZ1ze_C2NqNHt9UF9fKpJK23bqc6OMr20ExObd"
SOURCE_ID   = "td0010020000EC3A181482E84C7AB9091A47C2F77C5B"
TIMEZONE    = "CET"
LANGUAGE_ID = "9"
USER_AGENT  = "Hi-Mit II/1.3.5 (iPhone; iOS 26.3; Scale/3.00)"

AUTH_BASE   = "https://auth-gateway.hijuconn.com"
HMT_BASE    = "https://hmt-eu-gateway.hijuconn.com"

# ── Device property field names ───────────────────────────────────────────────
# Switches (status sub-dict) — value "1"=ON / "0"=OFF
FIELD_A2W_SW    = "A2W_SW_ON"
FIELD_C1_SW     = "c1_SW_ON"
FIELD_C2_SW     = "c2_SW_ON"
FIELD_DHW_SW    = "DHW_SW_ON"
FIELD_SWP_SW    = "SWP_SW_ON"

# Setpoints (status sub-dict) — integer strings in °C
FIELD_C1_SETPOINT  = "Ts_c1_water"
FIELD_C2_SETPOINT  = "Ts_c2_water"
FIELD_DHW_SETPOINT = "TDHWS"
FIELD_SWP_SETPOINT = "Tswps"

# Actual temperatures (functions sub-dict) — from doSetCycle1/2Item in APK
#   tvTag333 ← fixedDid18  Circuit 1 actual water temp
#   tvTag444 ← fixedDid19  Circuit 2 actual water temp
#   tvTag111 ← fixedDid16  DHW actual water temp
#   tvTag222 ← fixedDid17  SWP actual water temp
FIELD_C1_ACTUAL  = "fixedDid18"
FIELD_C2_ACTUAL  = "fixedDid19"
FIELD_DHW_ACTUAL = "fixedDid16"
FIELD_SWP_ACTUAL = "fixedDid17"
FIELD_OUTDOOR    = "swj_Ta"

# Setpoint range limits (functions sub-dict) — from APK doSetCycle1/2Item
FIELD_C1_MIN_HEAT  = "fixedDid25"   # 12
FIELD_C1_MAX_HEAT  = "fixedDid26"   # 22
FIELD_C2_MIN_HEAT  = "fixedDid27"   # 27
FIELD_C2_MAX_HEAT  = "fixedDid28"   # 55
FIELD_DHW_MIN      = "fixedDid29"   # 40
FIELD_DHW_MAX      = "fixedDid30"   # 55
FIELD_SWP_MIN      = "fixedDid31"   # 24
FIELD_SWP_MAX      = "fixedDid32"   # 33

# Room temperatures (status) — TsR1..TsR8
ROOM_TEMP_FIELDS = [f"TsR{i}" for i in range(1, 9)]

# Room setpoints (functions) — Trc1R1..Trc1R4
ROOM_SP_FIELDS_C1 = [f"Trc1R{i}" for i in range(1, 5)]
ROOM_SP_FIELDS_C2 = [f"Trc2R{i}" for i in range(1, 5)]

# Sensor disconnected sentinel
SENSOR_DISCONNECTED = -127

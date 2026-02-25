# Hi-Mit II — Home Assistant Integration

A custom Home Assistant integration for the **Hisense Hi-Mit II Air-to-Water heat pump** (ATW), reverse-engineered from the official mobile app APK.

---

## Features

| Platform | Entity | Description |
|---|---|---|
| `binary_sensor` | Heat Pump Running | Reports whether the compressor / A2W unit is active |
| `sensor` | Circuit 1 Water Temp | Live actual water temperature — Circuit 1 (fixedDid18) |
| `sensor` | Circuit 2 Water Temp | Live actual water temperature — Circuit 2 (fixedDid19) |
| `sensor` | DHW Water Temp | Live actual domestic hot water temperature (fixedDid16) |
| `sensor` | Pool Water Temp | Live actual swimming pool temperature (fixedDid17) |
| `sensor` | Outdoor Ambient Temp | External sensor reading (swj_Ta) |
| `sensor` | Room 1–8 Temp | Individual room sensor readings (TsR1–TsR8) |
| `switch` | Circuit 1 (Heating) | Enable / disable Circuit 1 |
| `switch` | Circuit 2 (Heating) | Enable / disable Circuit 2 |
| `switch` | Domestic Hot Water | Enable / disable DHW heating |
| `switch` | Swimming Pool | Enable / disable pool heating |
| `number` | Circuit 1 Setpoint | Water temperature target for Circuit 1 (°C) |
| `number` | Circuit 2 Setpoint | Water temperature target for Circuit 2 (°C) |
| `number` | DHW Setpoint | Domestic hot water target temperature (°C) |
| `number` | Pool Setpoint | Pool water target temperature (°C) |

**Setpoint min/max limits are read live from the device** (the pump reports its own allowed ranges per heating/cooling mode).

---

## Installation

### HACS (recommended)

1. In HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add this repository URL, category **Integration**
3. Install **Hi-Mit II**
4. Restart Home Assistant

### Manual

```bash
# From your HA config directory
git clone https://github.com/YOUR_USERNAME/HiMitII_HomeAssistant.git /tmp/himit
cp -r /tmp/himit/custom_components/himit config/custom_components/himit
```

Restart Home Assistant.

---

## Configuration

1. **Settings → Integrations → Add Integration**
2. Search for **Hi-Mit II**
3. Enter your Hisense / Hi-Mit II account email and password
4. If your account has multiple homes, select the one with your heat pump
5. Done — entities appear immediately and update every 30 seconds

### Token handling

The integration handles authentication automatically:

- The access token is **refreshed silently** before it expires using the stored refresh token
- If the refresh token also expires, a **Re-authenticate** prompt appears in the Integrations page — no need to delete and re-add the integration
- All tokens are stored securely in the Home Assistant config entry (`.storage/`)

---

## Forcing a Data Refresh

By default the integration polls every 30 seconds. If you need an immediate update there are two options:

### 1. Built-in service call (no code changes needed)

Call the standard Home Assistant service on any of the integration's entities:

```yaml
service: homeassistant.update_entity
target:
  entity_id: sensor.hi_mit_ii_circuit_1_water_temp
```

This triggers `coordinator.async_request_refresh()` immediately.

### 2. Dedicated Refresh button entity

A `button` platform can be added to expose a single **Refresh** button in the UI / dashboard:

```python
class HimitRefreshButton(HimitEntity, ButtonEntity):
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
```

Press it from a dashboard card or use it in an automation and data updates instantly.

---

## How it works

This integration was built by reverse-engineering the official **Hi-Mit II Android APK**:

- **RSA request signing** — every API request is signed using RSA-PKCS1v15 with a 2048-bit public key embedded in the APK (`assets/rsa_public_key.key`). The server holds the private key and decrypts to verify.
- **Password encoding** — the login password is MD5-hashed (uppercase), then RSA-encrypted with a separate 512-bit key (`assets/rsa_account_public_key.key`).
- **Temperature field mapping** — actual live temperatures come from `fixedDid16–19` fields (not obvious names), confirmed by tracing `doSetCycle1Item` / `doSetCycle2Item` in `HeatPumpControllActivity.java`:

  | Field | Description |
  |---|---|
  | `fixedDid18` | Circuit 1 actual water temp (tvTag333 in app UI) |
  | `fixedDid19` | Circuit 2 actual water temp (tvTag444 in app UI) |
  | `fixedDid16` | DHW actual water temp (tvTag111 in app UI) |
  | `fixedDid17` | Pool actual water temp (tvTag222 in app UI) |

- **Control** — `POST /himit-dshd/setDeviceProperty` with a `properties` array of `{cmdType, cmdValue}` pairs. The sign covers all scalar fields plus the JSON-stringified properties array.

### API endpoints

All on `https://hmt-eu-gateway.hijuconn.com`:

| Method | Path | Purpose |
|---|---|---|
| POST | `/account/acc/login_pwd` | Login (auth-gateway) |
| POST | `/account/acc/refresh_token` | Refresh access token |
| GET | `/himit-lgs/get_home_list` | List homes |
| GET | `/himit-dms/get_customer_device_list_info` | List devices |
| POST | `/himit-dshd/getDeviceProperty` | Full device state |
| POST | `/himit-dshd/setDeviceProperty` | Send control commands |

---

## File structure

```
custom_components/himit/
├── __init__.py          # Integration setup / teardown
├── api.py               # Async HTTP client (all crypto + API calls)
├── binary_sensor.py     # Read-only status sensors (A2W running)
├── config_flow.py       # UI login flow + home selection
├── const.py             # All constants (keys, field names, endpoints)
├── coordinator.py       # DataUpdateCoordinator — polling + token refresh
├── entity.py            # Shared base entity class
├── manifest.json        # HA integration manifest
├── number.py            # Temperature setpoint controls
├── sensor.py            # Temperature sensors
├── switch.py            # On/off switches
└── translations/
    └── en.json          # Config flow UI strings
```

---

## Requirements

- Home Assistant 2024.1 or newer
- Python packages (installed automatically): `cryptography>=41.0.0`, `aiohttp>=3.9.0`
- A valid Hisense / Hi-Mit II cloud account

---

## Disclaimer

This integration is not affiliated with or endorsed by Hisense. It was built by analysing the official mobile app for personal use. Use at your own risk.

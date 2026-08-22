# RLTech FTTR Home Assistant integration

Custom integration for RLTech OLT/FTTR Web UI inventory data.

Requires Home Assistant `2026.3.0` or newer.

The integration reads two RLTech Web UI planes:

- Port `8080` for FTTR AP and Wi-Fi station inventory.
- Port `80` for OLT hardware, LAN/LAN-PON, and ONU optical status.
- Optional local MQTT on port `8883` for faster station and AP health updates
  between HTTP polls.

The integration logs out immediately after each poll so Web UI sessions are not
kept open.

## HACS install

This repository can be installed with HACS as a custom integration.

1. Open HACS in Home Assistant.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add this repository URL:

   ```text
   https://github.com/hmsta/ha-rltech-fttr
   ```

4. Select **Integration** as the category.
5. Install **RLTech FTTR** from HACS.
6. Restart Home Assistant.
7. Add the integration from **Settings > Devices & services**.

HACS installs the integration files, including the bundled table card
JavaScript. For the normal Home Assistant storage-mode dashboard setup, the
integration registers the bundled card resources automatically when it starts.

If your Home Assistant Lovelace resources are configured in YAML mode, add
these dashboard resources manually after the integration is installed:

```text
/rltech_fttr/rltech-fttr-station-table-card.js
/rltech_fttr/rltech-fttr-ap-table-card.js
```

Resource type: JavaScript module.

## Manual install

Copy `custom_components/rltech_fttr` into Home Assistant's
`custom_components` directory and restart Home Assistant.

## Configure

Add the integration from the Home Assistant UI. Required fields:

- OLT IP address or hostname, for example `192.168.1.1`. The integration
  automatically uses `http://`, port `80`, port `8080`, and MQTT port `8883`.
- Port `80` username, default `admin`
- Port `80` password, default `admin`
- Additional port `80` OLT hosts, optional. Use this for downstream/slave OLTs
  whose ONU optical rows should enrich the APs discovered from the master.
  Separate multiple hosts with commas, spaces, or new lines.
- Username for the port `8080` FTTR Web UI
- Password for the port `8080` FTTR Web UI
- Scan interval, default `60` seconds
- Station retention, default `3600` seconds
- AP inventory polling, enabled by default
- Station inventory polling, enabled by default
- Hardware and ONU status polling, enabled by default
- MQTT live overlay, disabled by default. When enabled, the integration uses
  the same OLT host on fixed port `8883`. Configure MQTT username, password,
  PSK identity, and PSK. The PSK may be pasted as hex, hex with separators, or
  plain text; the integration stores it internally as hex. The MQTT connection
  is owned by this integration and does not require Home Assistant's MQTT
  integration.
- AP username for direct AP actions, default `useradmin`
- AP password for direct AP actions, default `1234`
- Area for AP devices, optional. When set, newly created AP devices are assigned
  to this area if they do not already have an area.

The OLT serves plain HTTP in the observed deployment. Use this only on a trusted
management network or VPN.

The AP reboot button logs into the AP directly at `http://<ap-ip>` with the
configured AP credentials and posts the RLTech reboot form. It does not log out
after a successful reboot request because the AP Web UI is expected to restart.

## Entities

- One device for the OLT/controller with aggregate and optional health sensors.
- One additional OLT hardware device for each configured additional port `80`
  host, with its own CPU, memory, LAN, and LAN-PON sensors.
- One Home Assistant device per managed AP with an `SN`, with AP status,
  associated-client-count, profile, alias, and optional AP optical/status
  sensors, plus a config button to reboot the AP through its direct Web UI.
- Aggregate station sensors, including reported station count.
- Optional LAN and LAN-PON diagnostic port sensors.

Wi-Fi stations are not created as Home Assistant devices or trackers. They are
kept as inventory rows for the bundled Lovelace card, avoiding entity-registry
spam and recorder churn from volatile client details.

When FTTR station hostnames are missing or junk values such as `N/A`, the
coordinator can enrich the in-memory station rows from Home Assistant's DHCP
discovery cache. This is a once-per-poll map lookup by normalized MAC address
and IP address; it does not create station entities or persist station data.

When MQTT live overlay is enabled, MQTT station updates also reuse this backend
hostname enrichment. If a hostname is not known when a station first appears,
the integration retries enrichment later so DHCP data that arrives after the
station update can still fill the table row.

Station rows also include a best-effort MAC vendor column. This uses the local
`aiooui` OUI database installed with the integration; it is a local file lookup,
not an online lookup, and does not create station entities or persist station
data.

## MQTT live overlay

MQTT is optional and complements HTTP polling; it does not replace it.

- HTTP remains the authority for AP inventory, station baseline, OLT status,
  LAN/LAN-PON status, and ONU optical TX/RX.
- MQTT subscribes only to the local AP notification and AP lifecycle topics,
  then parses station updates, known-AP health heartbeats, and known-AP
  online/offline events.
- MQTT station updates refresh the in-memory station table data between HTTP
  polls, without creating station entities.
- MQTT AP updates are applied only to APs already discovered by HTTP. Unknown
  AP heartbeats and lifecycle events are ignored.
- MQTT can update AP associated-client count, CPU usage, CPU temperature,
  memory usage, flash usage, AP last boot, and AP online state.
- The Lovelace cards remain pull-based. MQTT updates do not force the cards to
  refetch or redraw on every message.

If MQTT is unavailable or misconfigured, the integration continues to work with
HTTP polling only. MQTT passwords, PSKs, and raw payloads are not exposed in
diagnostics.

## Station table card

Add a station card:

```yaml
type: custom:rltech-fttr-station-table-card
```

The card reads the latest coordinator data through the integration websocket
API and supports search, sort, and filters for SSID, AP, VLAN, band, and active
state. A station is `Active` when it appears in the latest successful station
poll, and `Inactive` while it is retained from an earlier poll. Inactive rows
expire after the configured station retention window.

The visible columns, mobile columns, page size, sort order, and filters can be
changed in the card's table options menu. By default those UI preferences are
remembered in the current browser's local storage. Search text is intentionally
not remembered. On phone-sized screens the card switches from a wide table to a
compact row layout using `mobile_columns`.

When MQTT is enabled, the station card can subscribe to lightweight station
change notifications. The backend sends only a dirty event, not station rows.
The card auto-refetches only when the current view is narrowed by search text
or filters, with debounce/throttling to avoid full-table churn.

## AP table card

Add an AP inventory card:

```yaml
type: custom:rltech-fttr-ap-table-card
```

The AP card uses the same websocket pattern and supports search, sort, and
filters for online state, profile, model, and uplink. It shows AP inventory
fields such as alias, MAC, IP, firmware, channels, association count, uplink,
serial number, and ONU optical/status details when hardware status polling is
enabled.

Source ownership is intentionally strict:

- Port `8080` provides AP inventory and station inventory.
- Port `80` provides OLT runtime/CPU/memory, LAN/LAN-PON status, and ONU/AP
  optical/status rows.
- The first port `80` source is the master OLT hardware device. Additional
  port `80` hosts are represented as separate OLT hardware devices.
- AP optical/status rows from port `80` are joined to AP inventory by AP serial
  number, not alias, MAC, or IP.
- `Reg/Off Time` is parsed as a timestamp using Home Assistant's local time
  zone. For online ONUs it appears to be registration time; for offline ONUs it
  appears to be off time.

AP devices and AP sensor unique IDs use the AP hardware serial, for example
`RLGM3BB8E3D0`. AP rows without an `SN` remain visible as table inventory but
do not create AP HA devices/entities, avoiding accidental duplicate devices
from fallback identifiers. New AP sensor entity IDs are suggested from the
serial, while the friendly device name can still use the AP alias. Each AP
device uses its AP IP as the Home Assistant configuration URL when available.

The AP table receives the current HA entity IDs from Home Assistant's entity
registry; clicking AP-backed cells such as alias, state, profile, or associated
station count opens the normal HA more-info/history dialog. Other AP fields,
including channels, uplink details, ONU interface, and source OLT host, remain
inventory-only table data.

Both table cards accept:

```yaml
entry_id: optional_config_entry_id
page_size: 25
mobile_page_size: 10
page_size_options:
  - 25
  - 50
  - 100
remember_preferences: true
storage_key: optional_unique_key
columns: []
mobile_columns: []
```

When exactly one RLTech FTTR integration is configured, `entry_id` can be
omitted and the card will select it automatically. Set `entry_id` only when
multiple RLTech FTTR integrations are configured. The visible columns, mobile
columns, and page size have built-in defaults and can be changed from the
card's table options menu.

Use `storage_key` if you place multiple cards for the same config entry on
different dashboards and want separate remembered browser layouts.

The AP table also accepts `default_sort_key` and `default_sort_dir`. By default
APs are sorted by `online` ascending, so offline APs appear first.

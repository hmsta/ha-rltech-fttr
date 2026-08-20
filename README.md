# RLTech FTTR Home Assistant integration

Read-only custom integration for RLTech OLT/FTTR Web UI inventory data.

The integration logs in to the OLT Web UI for each poll, reads the managed AP
inventory, Wi-Fi station inventory, optional OLT/controller status, and optional
LAN/LAN-PON status. Optional AP optical details are polled on a slower interval.
The integration logs out immediately after each poll so the single Web UI
session is not kept open.

## Install

Copy `custom_components/rltech_fttr` into Home Assistant's
`custom_components` directory and restart Home Assistant.

## Configure

Add the integration from the Home Assistant UI. Required fields:

- Base URL, for example `http://192.168.1.1`
- Username
- Password
- Scan interval, default `60` seconds
- Station retention, default `3600` seconds
- AP inventory polling, enabled by default
- Station inventory polling, enabled by default
- OLT status polling, enabled by default
- LAN port status polling, enabled by default
- AP optical detail polling, enabled by default
- AP optical detail interval, default `600` seconds

The OLT serves plain HTTP in the observed deployment. Use this only on a trusted
management network or VPN.

## Entities

- One device for the OLT/controller with aggregate and optional health sensors.
- One Home Assistant device per managed AP with an `SN`, with AP status,
  associated-client-count, profile, alias, and optional optical diagnostic
  sensors.
- Aggregate station sensors, including reported station count.
- Optional LAN and LAN-PON diagnostic port sensors.

Wi-Fi stations are not created as Home Assistant devices or trackers. They are
kept as inventory rows for the bundled Lovelace card, avoiding entity-registry
spam and recorder churn from volatile client details.

When FTTR station hostnames are missing or junk values such as `N/A`, the
coordinator can enrich the in-memory station rows from Home Assistant's DHCP
discovery cache. This is a once-per-poll map lookup by normalized MAC address
and IP address; it does not create station entities or persist station data.

## Station table card

Add these JavaScript resources to Lovelace:

```text
/rltech_fttr/rltech-fttr-station-table-card.js
/rltech_fttr/rltech-fttr-ap-table-card.js
```

Then add a station card:

```yaml
type: custom:rltech-fttr-station-table-card
entry_id: your_config_entry_id
page_size: 25
columns:
  - mac
  - ip
  - hostname
  - ssid
  - ap_alias
  - reported_online
  - rssi
  - band
  - channel
  - vlan
  - uptime
  - last_seen
  - details
mobile_columns:
  - hostname
  - ip
  - ssid
  - reported_online
  - rssi
  - details
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

## AP table card

Add an AP inventory card:

```yaml
type: custom:rltech-fttr-ap-table-card
entry_id: your_config_entry_id
page_size: 25
columns:
  - alias
  - mac
  - ip
  - online
  - model
  - version
  - profile
  - assoc_count
  - channel_24
  - channel_5
  - uplink_label
  - sn
  - details
mobile_columns:
  - alias
  - ip
  - online
  - assoc_count
  - channel_24
  - channel_5
  - details
```

The AP card uses the same websocket pattern and supports search, sort, and
filters for online state, profile, model, and uplink. It shows AP inventory
fields such as alias, MAC, IP, firmware, channels, association count, uplink,
serial number, and slow-polled AP optical details when enabled.

AP devices and AP sensor unique IDs use the AP hardware serial, for example
`RLGM3BB8E3D0`. AP rows without an `SN` remain visible as table inventory but
do not create AP HA devices/entities, avoiding accidental duplicate devices
from fallback identifiers. New AP sensor entity IDs are suggested from the
serial, while the friendly device name can still use the AP alias. Each AP
device uses its AP IP as the Home Assistant configuration URL when available.

The AP table receives the current HA entity IDs from Home Assistant's entity
registry; clicking AP-backed cells such as alias, state, profile, or associated
station count opens the normal HA more-info/history dialog. Other AP fields,
including channels, uplink details, ONT distance, last PON down/up times, and
resource details, remain inventory-only table data.

Both table cards accept:

```yaml
page_size_options:
  - 25
  - 50
  - 100
remember_preferences: true
storage_key: optional_unique_key
```

Use `storage_key` if you place multiple cards for the same config entry on
different dashboards and want separate remembered browser layouts.

"""RLTech OLT Web UI client and parsers."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import html
import json
import logging
import re
import time
from typing import Any
import zlib

try:
    import aiohttp
except ModuleNotFoundError:
    aiohttp = None  # type: ignore[assignment]

from .models import (
    RltechAp,
    RltechApDetail,
    RltechData,
    RltechLanPonPort,
    RltechLanPort,
    RltechOltStatus,
    RltechStation,
)

_LOGGER = logging.getLogger(__name__)

STA_RE = re.compile(r"var\s+STA_manage\s*=\s*'((?:\\'|[^'])*)'", re.S)
AP_RE = re.compile(r"var\s+AP_manage\s*=\s*'((?:\\'|[^'])*)'", re.S)
JS_SINGLE_QUOTED_RE = r"((?:\\'|[^'])*)"

BANDWIDTH_MAP = {
    1: "20 MHz",
    2: "40 MHz",
    3: "20/40 MHz",
    4: "20/40/80 MHz",
    5: "20/40/80/160 MHz",
}
_BOOT_TIME_DRIFT_GRACE = timedelta(minutes=2)


def _client_timeout(seconds: int) -> Any:
    if aiohttp is None:
        return None
    return aiohttp.ClientTimeout(total=seconds)


class RltechError(Exception):
    """Base integration API error."""


class AuthenticationError(RltechError):
    """The device rejected credentials or locked login."""


class AccountBusyError(RltechError):
    """The single Web UI account/session is already in use."""


class SessionExpired(RltechError):
    """Authenticated page access failed."""


class UnexpectedResponse(RltechError):
    """The device returned an unexpected response."""


def eboo_value(fields: Sequence[tuple[str, str]]) -> str:
    """Return the RLTech EBOOVALUE CRC for decoded ordered form fields."""
    cleartext = "".join(name + value for name, value in fields)
    return format(zlib.crc32(cleartext.encode("utf-8")) & 0xFFFFFFFF, "x")


def extract_embedded_json(page: str, variable: str) -> dict[str, Any]:
    """Extract and decode a Web UI JSON object embedded in a JS string."""
    regex = AP_RE if variable == "AP_manage" else STA_RE if variable == "STA_manage" else None
    if regex is None:
        regex = re.compile(rf"var\s+{re.escape(variable)}\s*=\s*'((?:\\'|[^'])*)'", re.S)
    match = regex.search(page)
    if match is None:
        raise SessionExpired(f"{variable} missing from response")
    payload = html.unescape(match.group(1)).replace("\\'", "'")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UnexpectedResponse(f"{variable} contains invalid JSON") from exc


def _extract_js_string(page: str, variable: str) -> str:
    """Extract a JavaScript single-quoted string assigned by var/let/const."""
    match = re.search(
        rf"(?:var|let|const)\s+{re.escape(variable)}\s*=\s*'{JS_SINGLE_QUOTED_RE}'",
        page,
        re.S,
    )
    if match is None:
        raise SessionExpired(f"{variable} missing from response")
    return html.unescape(match.group(1)).replace("\\'", "'")


def _extract_json_from_js_string(page: str, variable: str) -> dict[str, Any]:
    """Extract JSON from a JavaScript single-quoted string assignment."""
    payload = _extract_js_string(page, variable)
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UnexpectedResponse(f"{variable} contains invalid JSON") from exc


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _none_if_na(value: Any) -> str | None:
    text = _text(value)
    if text is None or text.upper() == "N/A":
        return None
    return text


def _int(value: Any) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _bool_status(value: Any) -> bool | None:
    text = _text(value)
    if text is None:
        return None
    if text == "1":
        return True
    if text == "0":
        return False
    return None


def normalize_mac(value: Any) -> str | None:
    """Normalize a MAC address to colon-separated uppercase text."""
    text = _text(value)
    if text is None:
        return None
    clean = re.sub(r"[^0-9A-Fa-f]", "", text)
    if len(clean) != 12:
        return None
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2)).upper()


def _channel_band(channel: int | None) -> str | None:
    if channel is None or channel <= 0:
        return None
    return "2.4 GHz" if channel <= 14 else "5 GHz"


def _bandwidth(value: Any) -> str | None:
    return BANDWIDTH_MAP.get(_int(value))


def _payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    code = str(payload.get("respCode", "0"))
    if code == "3":
        return []
    if code != "0":
        raise UnexpectedResponse(f"unexpected respCode {code}")
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    rows = data.get("list")
    return rows if isinstance(rows, list) else []


def _payload_total(payload: dict[str, Any]) -> int:
    return _int(payload.get("total")) or 0


def _normalize_ap_payloads(ap_payloads: Iterable[dict[str, Any]]) -> dict[str, RltechAp]:
    """Normalize AP payload pages into an AP map."""
    aps: dict[str, RltechAp] = {}
    for payload in ap_payloads:
        for row in _payload_rows(payload):
            ap = normalize_ap(row)
            if ap is not None:
                aps[ap.mac] = ap
    return aps


def normalize_ap(row: dict[str, Any]) -> RltechAp | None:
    """Normalize one managed AP row."""
    mac = normalize_mac(row.get("Mac"))
    if mac is None:
        return None
    return RltechAp(
        mac=mac,
        ip=_text(row.get("IP")),
        model=_text(row.get("Model")),
        version=_text(row.get("Version")),
        online=_bool_status(row.get("Status")),
        profile=_text(row.get("Profile")),
        profile_idx=_text(row.get("ProfileIdx")),
        channel_24=_int(row.get("ChannelG24")),
        channel_5=_int(row.get("ChannelG5")),
        bssid_24=normalize_mac(row.get("BssidG24")),
        bssid_5=normalize_mac(row.get("BssidG5")),
        assoc_count=_int(row.get("Assoc")),
        alias=_text(row.get("Alias")),
        uplink=_int(row.get("Uplink")),
        uplink_port=_int(row.get("UplinkPort")),
        sn=_text(row.get("SN")),
        dev_sn=_text(row.get("DevSN")),
        upgrade_flag=_text(row.get("UpgradeFlag")),
    )


def parse_ap_detail(text: str) -> RltechApDetail:
    """Parse ap_online_detail.asp embedded AP and PON detail JSON."""
    ap_payload = _extract_json_from_js_string(text, "list_ap")
    ap_data = ap_payload.get("data")
    if not isinstance(ap_data, dict):
        raise UnexpectedResponse("list_ap missing data object")

    pon_payload = _extract_json_from_js_string(text, "list_pon")
    pon_data_raw = pon_payload.get("data")
    pon_data: dict[str, Any] = {}
    if isinstance(pon_data_raw, str) and pon_data_raw.strip():
        try:
            decoded = json.loads(pon_data_raw)
        except json.JSONDecodeError as exc:
            raise UnexpectedResponse("list_pon data contains invalid JSON") from exc
        if isinstance(decoded, dict):
            pon_data = decoded
    elif isinstance(pon_data_raw, dict):
        pon_data = pon_data_raw

    return RltechApDetail(
        mac=normalize_mac(ap_data.get("Mac")),
        ip=_text(ap_data.get("IP")),
        model=_text(ap_data.get("Model")),
        version=_text(ap_data.get("Version")),
        online=_bool_status(ap_data.get("Status")),
        profile=_text(ap_data.get("Profile")),
        alias=_text(ap_data.get("Alias")),
        sn=_text(ap_data.get("SN")),
        dev_sn=_text(ap_data.get("DevSN")),
        uplink=_int(ap_data.get("Uplink")),
        uplink_port=_int(ap_data.get("UplinkPort")),
        assoc_count=_int(ap_data.get("Assoc")),
        channel_24=_int(ap_data.get("ChannelG24")),
        channel_5=_int(ap_data.get("ChannelG5")),
        bssid_24=normalize_mac(ap_data.get("BssidG24")),
        bssid_5=normalize_mac(ap_data.get("BssidG5")),
        hostname=_text(ap_data.get("DevName")),
        sys_duration=_int(ap_data.get("SysDuration")),
        ram_size=_int(ap_data.get("RamSize")),
        flash_size=_int(ap_data.get("FlashSize")),
        cpu_usage=_float(ap_data.get("CPUUsage")),
        cpu_temperature=_float(ap_data.get("CPUTemp")),
        memory_usage=_float(ap_data.get("MEMUsage")),
        flash_usage=_float(ap_data.get("FlashUsage")),
        pon_id=_int(pon_data.get("pon_id")),
        onu_id=_int(pon_data.get("onu_id")),
        pon_sn=_text(pon_data.get("pon_sn")),
        onu_status=_text(pon_data.get("onu_status")),
        ont_distance=_int(pon_data.get("ont_distance")),
        optical_temperature=_float(pon_data.get("opt_temperature")),
        optical_current=_float(pon_data.get("opt_current")),
        optical_voltage=_float(pon_data.get("opt_voltage")),
        optical_tx_power=_float(pon_data.get("opt_tx_power")),
        optical_rx_power=_float(pon_data.get("opt_rx_power")),
        downstream_optical_rx_power=_float(pon_data.get("dnopt_rx_power")),
        optical_error_status=_int(pon_data.get("opt_err_status")),
        active=_bool_status(pon_data.get("active")),
        last_up_time=_text(pon_data.get("last_up_time")),
        last_down_time=_text(pon_data.get("last_down_time")),
        last_dying_gasp_time=_text(pon_data.get("last_dying_gasptime")),
        last_down_cause=_text(pon_data.get("last_down_cause")),
        identify_vendor=_text(pon_data.get("identify_vendor")),
        equipment_id=_text(pon_data.get("equipment_id")),
        sn_address=_text(pon_data.get("sn_address")),
        hardware_version=_none_if_na(pon_data.get("hardware_version")),
        software_version=_none_if_na(pon_data.get("software_version")),
        firmware_version=_none_if_na(pon_data.get("fireware_version")),
    )


def normalize_station(
    row: dict[str, Any],
    *,
    now: datetime,
    aps: dict[str, RltechAp],
) -> RltechStation | None:
    """Normalize one station row."""
    mac = normalize_mac(row.get("Mac"))
    if mac is None:
        return None
    channel = _int(row.get("Channel"))
    ap_mac = normalize_mac(row.get("APMac"))
    ap = aps.get(ap_mac or "")
    reported_online = _bool_status(row.get("Status")) is not False
    return RltechStation(
        mac=mac,
        id=_text(row.get("ID")),
        reported_online=reported_online,
        home=reported_online,
        last_seen=now if reported_online else None,
        ip=_text(row.get("IP")),
        hostname=_text(row.get("HostName")),
        ssid=_text(row.get("SSID")),
        ap_mac=ap_mac,
        ap_alias=ap.alias if ap else None,
        rssi=_int(row.get("RSSI")),
        rx_rate=_float(row.get("RxRate")),
        tx_rate=_float(row.get("TxRate")),
        rx_nego_rate=_float(row.get("RxNegoRate")),
        tx_nego_rate=_float(row.get("TxNegoRate")),
        uptime=_int(row.get("UpTime")),
        channel=channel,
        band=_channel_band(channel),
        bandwidth=_bandwidth(row.get("Bandwidth")),
        vlan=_int(row.get("Vlan")),
        alias=_text(row.get("Alias")),
        total_count=_text(row.get("ToTalcnt")),
        update_time=_int(row.get("UpDateTime")),
    )


def _js_string(text: str, name: str) -> str | None:
    patterns = [
        rf"var\s+{re.escape(name)}\s*=\s*['\"]([^'\"]*)['\"]",
        rf"this\.{re.escape(name)}\s*=\s*['\"]([^'\"]*)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.S)
        if match:
            return html.unescape(match.group(1).strip())
    return None


def _hidden_value(text: str, element_id: str) -> str | None:
    match = re.search(
        rf"id=['\"]{re.escape(element_id)}['\"][^>]*value=['\"]([^'\"]*)['\"]",
        text,
        re.I | re.S,
    )
    return html.unescape(match.group(1).strip()) if match else None


def _field_literal(text: str, name: str) -> str | None:
    patterns = [
        rf"{re.escape(name)}\s*[:=]\s*['\"]([^'\"]*)['\"]",
        rf"{re.escape(name)}['\"]?\s*,\s*['\"]([^'\"]*)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return html.unescape(match.group(1).strip())
    return None


def _field_number(text: str, name: str) -> float | None:
    literal = _field_literal(text, name)
    if literal is not None:
        return _float(literal)
    match = re.search(rf"{re.escape(name)}\D+(-?\d+(?:\.\d+)?)", text, re.I | re.S)
    return _float(match.group(1)) if match else None


def _table_value(text: str, label: str) -> str | None:
    match = re.search(
        rf"<td[^>]*>\s*{re.escape(label)}:\s*</td>\s*<td[^>]*>(.*?)</td>",
        text,
        re.I | re.S,
    )
    if not match:
        return None
    value = match.group(1)
    script_literal = re.search(
        r"document\.write\(\s*['\"]([^'\"]*)['\"]\s*\)", value, re.I | re.S
    )
    if script_literal:
        return _none_if_na(html.unescape(script_literal.group(1).strip()))
    value = re.sub(r"<script\b.*?</script>", "", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value).replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _table_number(text: str, label: str) -> float | None:
    value = _table_value(text, label)
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return _float(match.group(0)) if match else None


def _duration(value: str | None) -> timedelta | None:
    """Parse vendor duration text such as '18 Days 20 Hour 37 Min 46 Sec'."""
    if value is None:
        return None
    total = 0
    for number, unit in re.findall(
        r"(\d+)\s*(days?|d|hours?|h|mins?|minutes?|m|secs?|seconds?|s)\b",
        value,
        re.I,
    ):
        amount = int(number)
        unit = unit.lower()
        if unit.startswith("d"):
            total += amount * 86400
        elif unit.startswith("h"):
            total += amount * 3600
        elif unit.startswith("m"):
            total += amount * 60
        elif unit.startswith("s"):
            total += amount
    return timedelta(seconds=total) if total else None


def _duration_text(duration: timedelta) -> str:
    """Format a duration in the same unit names used by the vendor UI."""
    total = max(0, int(duration.total_seconds()))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} Days")
    if hours or parts:
        parts.append(f"{hours} Hour")
    if minutes or parts:
        parts.append(f"{minutes} Min")
    parts.append(f"{seconds} Sec")
    return " ".join(parts)


def _function_var_literal(text: str, function_name: str, var_name: str) -> str | None:
    """Return a JavaScript var literal from a named function body."""
    match = re.search(rf"function\s+{re.escape(function_name)}\s*\(", text)
    if not match:
        return None
    body = text[match.end() : match.end() + 4000]
    var_match = re.search(
        rf"\bvar\s+{re.escape(var_name)}\s*=\s*['\"]([^'\"]*)['\"]",
        body,
    )
    return html.unescape(var_match.group(1).strip()) if var_match else None


def _script_wan_link_uptime(text: str) -> str | None:
    """Parse WAN link uptime rendered by sta-device.asp JavaScript."""
    is_wan_up = _function_var_literal(text, "wanUpTime", "IsWanUp")
    if is_wan_up in {"0", "N/A"}:
        return None
    cur_time = _int(_function_var_literal(text, "wanUpTime", "curTime"))
    wan_up_time = _int(_function_var_literal(text, "wanUpTime", "WanUpTime"))
    if cur_time is None or wan_up_time is None or cur_time < wan_up_time:
        return None
    return _duration_text(timedelta(seconds=cur_time - wan_up_time))


def parse_olt_status(text: str, *, now: datetime | None = None) -> RltechOltStatus:
    """Parse optional OLT/controller status values from sta-device.asp."""
    now = now or datetime.now(UTC)
    link_state = _int(_js_string(text, "LinkSta"))
    system_uptime = _table_value(text, "Run Time") or _field_literal(text, "sysUpTime")
    wan_table_value = _table_value(text, "WAN Link Up Time")
    wan_literal_value = _field_literal(text, "WanUpTime")
    wan_link_uptime = (
        wan_table_value
        if _duration(wan_table_value) is not None
        else _script_wan_link_uptime(text)
        or (
            wan_literal_value
            if wan_literal_value is not None and _duration(wan_literal_value) is not None
            else None
        )
    )
    system_duration = _duration(system_uptime)
    wan_duration = _duration(wan_link_uptime)
    return RltechOltStatus(
        pon_link_state=link_state,
        fec_state=(
            _int(_js_string(text, "fecState")) == 1
            if _js_string(text, "fecState") is not None
            else None
        ),
        pon_tx_frames=_int(_js_string(text, "PonSendPkt")),
        pon_rx_frames=_int(_js_string(text, "PonRecvPkt")),
        pon_up_since=_js_string(text, "ponuptime") or _hidden_value(text, "Uptime"),
        current_time=_none_if_na(_js_string(text, "curtime")),
        system_uptime=system_uptime,
        wan_link_uptime=wan_link_uptime,
        last_boot=now - system_duration if system_duration is not None else None,
        wan_link_up_since=now - wan_duration if wan_duration is not None else None,
        device_type=_table_value(text, "Device Type") or _field_literal(text, "DeviceType"),
        gateway_type=_table_value(text, "Gateway Type") or _field_literal(text, "ModelName"),
        cpu_temperature=_table_number(text, "CPU Temperature") or _field_number(text, "CpuTemp"),
        cpu_usage=_field_number(text, "CpuUsage"),
        memory_usage=_field_number(text, "MemoryUsage"),
        flash_usage=_field_number(text, "FlashUsage"),
        manufacturer=_table_value(text, "Manufacturer") or _field_literal(text, "Manufacturer"),
        serial_number=_table_value(text, "Serial Number") or _field_literal(text, "SerialNum"),
        hardware_version=_table_value(text, "Hardware Version") or _field_literal(text, "CustomerHWVersion"),
        software_version=_table_value(text, "Software Version") or _field_literal(text, "CustomerSWVersion"),
    )


def _stable_datetime(
    new_value: datetime | None,
    old_value: datetime | None,
    *,
    grace: timedelta = _BOOT_TIME_DRIFT_GRACE,
) -> datetime | None:
    """Keep derived timestamps stable across small uptime/poll timing drift."""
    if new_value is None or old_value is None:
        return new_value
    if abs(new_value - old_value) <= grace:
        return old_value
    return new_value


def _stabilize_olt_status(
    status: RltechOltStatus | None, previous: RltechData | None
) -> RltechOltStatus | None:
    """Preserve prior OLT boot/link timestamps when only parser drift changed."""
    if status is None or previous is None or previous.olt_status is None:
        return status
    return replace(
        status,
        last_boot=_stable_datetime(status.last_boot, previous.olt_status.last_boot),
        wan_link_up_since=_stable_datetime(
            status.wan_link_up_since, previous.olt_status.wan_link_up_since
        ),
    )


def parse_lan_ports(text: str) -> dict[int, RltechLanPort]:
    """Parse LAN Ethernet port rows from sta-user.asp."""
    try:
        payload = _extract_json_from_js_string(text, "lancntvalue")
    except SessionExpired:
        payload = None
    if payload is not None:
        rows = payload.get("data")
        ports: dict[int, RltechLanPort] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                port = _int(row.get("Port"))
                if port is None:
                    continue
                connected = _bool_status(row.get("LanState"))
                label = f"LANPON{port - 4}" if port > 4 else f"LAN-{port}"
                mode = _none_if_na(row.get("Mode"))
                if mode == "Full":
                    mode = "Full-Duplex"
                elif mode == "Half":
                    mode = "Half-Duplex"
                ports[port] = RltechLanPort(
                    port=port,
                    label=label,
                    status="connected"
                    if connected
                    else "disconnected"
                    if connected is False
                    else None,
                    connected=connected,
                    rate=_none_if_na(row.get("Negoration")),
                    mode=mode,
                )
        return ports

    match = re.search(r"Ethernet\s*=\s*(\[.*?\])\s*(?:;|\n)", text, re.S)
    if not match:
        return {}
    raw = re.sub(r",\s*null\s*(?=\])", "", match.group(1))
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnexpectedResponse("Ethernet array contains invalid JSON") from exc

    ports: dict[int, RltechLanPort] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, list) or len(row) < 10:
            continue
        path = _text(row[0])
        port = _int(path.rsplit(".", 1)[-1]) if path and "." in path else index
        ports[port or index] = RltechLanPort(
            port=port or index,
            label=f"LAN-{port or index}",
            path=path,
            status=_none_if_na(row[1]),
            connected=(_none_if_na(row[1]) or "").lower() == "up",
            tx_bytes=_int(row[2]),
            tx_packets=_int(row[3]),
            tx_errors=_int(row[4]),
            tx_drops=_int(row[5]),
            rx_bytes=_int(row[6]),
            rx_packets=_int(row[7]),
            rx_errors=_int(row[8]),
            rx_drops=_int(row[9]),
        )
    return ports


def parse_lanpon_ports(text: str) -> dict[int, RltechLanPonPort]:
    """Parse LAN-PON port rows from sta-user.asp."""
    try:
        payload = extract_embedded_json(text, "ponport_info")
    except SessionExpired:
        return {}
    rows = payload.get("list")
    if not isinstance(rows, list):
        return {}

    ports: dict[int, RltechLanPonPort] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ponid = _int(row.get("ponid"))
        if ponid is None:
            continue
        ports[ponid] = RltechLanPonPort(
            ponid=ponid,
            status=_none_if_na(row.get("status")),
            active=_none_if_na(row.get("active")),
            fec=_none_if_na(row.get("fec")),
            autoregister=_none_if_na(row.get("autoregister")),
            tx_power=_float(row.get("tx_power")),
            rx_power=_float(row.get("rx_power")),
            temperature=_float(row.get("temp")),
            voltage=_float(row.get("voltage")),
            current=_float(row.get("current")),
        )
    return ports


def normalize_snapshot(
    ap_payloads: Iterable[dict[str, Any]],
    station_payloads: Iterable[dict[str, Any]],
    *,
    olt_html: str | None,
    user_html: str | None = None,
    previous: RltechData | None = None,
    now: datetime | None = None,
    station_retention: int = 3600,
    poll_duration_ms: int | None = None,
    ap_details: dict[str, RltechApDetail] | None = None,
) -> RltechData:
    """Normalize AP, station, and optional OLT responses into HA-friendly data."""
    now = now or datetime.now(UTC)

    aps = _normalize_ap_payloads(ap_payloads)

    stations: dict[str, RltechStation] = {}
    for payload in station_payloads:
        for row in _payload_rows(payload):
            station = normalize_station(row, now=now, aps=aps)
            if station is not None:
                stations[station.mac] = station

    if previous is not None:
        for mac, old in previous.stations.items():
            if mac in stations:
                continue
            if old.last_seen is not None:
                age = (now - old.last_seen).total_seconds()
                if age >= station_retention:
                    continue
                stations[mac] = RltechStation(
                    **{
                        **asdict(old),
                        "reported_online": False,
                        "home": False,
                    }
                )

    olt_status = parse_olt_status(olt_html, now=now) if olt_html is not None else None

    return RltechData(
        aps=aps,
        ap_details=ap_details or {},
        stations=stations,
        olt_status=_stabilize_olt_status(olt_status, previous),
        lan_ports=parse_lan_ports(user_html) if user_html is not None else {},
        lanpon_ports=parse_lanpon_ports(user_html) if user_html is not None else {},
        last_success=now,
        poll_duration_ms=poll_duration_ms,
    )


class RltechClient:
    """Minimal async client for the RLTech OLT Web UI."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.token: str | None = None
        self._lock = asyncio.Lock()
        self._ap_detail_cursor = 0

    async def login(self, session: Any) -> None:
        """Authenticate and retain the returned token."""
        fields = [
            ("username", self.username),
            ("password", self.password),
            ("Language_Flag", "0"),
            ("selectLanguage", "English"),
        ]
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": "EBOOVALUE=ecntBaorga; loginTimes=0",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/cgi-bin/login.asp",
            "X-Requested-With": "XMLHttpRequest",
        }
        async with session.post(
            f"{self.base_url}/cgi-bin/check_auth.json",
            data=fields,
            headers=headers,
            allow_redirects=False,
            timeout=_client_timeout(self.timeout),
        ) as response:
            text = await response.text()
            if response.status != 200:
                raise AuthenticationError(f"login HTTP status {response.status}")
        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AuthenticationError("login did not return JSON") from exc

        if str(result.get("Locked", "0")) == "1":
            raise AuthenticationError("Web login is locked")
        if str(result.get("Logged", "0")) != "0":
            raise AccountBusyError("account is already logged into the Web UI")
        if str(result.get("Privilege", "0")) == "0":
            raise AuthenticationError("invalid username/password or no privilege")
        if str(result.get("Active", "0")) != "1":
            raise AuthenticationError("account is not active")

        token = str(result.get("ecntToken", ""))
        if not token or set(token) == {"0"}:
            raise AuthenticationError("login returned no usable token")
        self.token = token

    async def logout(self, session: Any) -> None:
        """Log out the retained Web UI token."""
        if self.token is None:
            return
        token = self.token
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Cookie": f"ecntToken={token}",
            "Referer": f"{self.base_url}/cgi-bin/sta-device.asp",
        }
        async with session.get(
            f"{self.base_url}/cgi-bin/logout.cgi",
            headers=headers,
            allow_redirects=False,
            timeout=_client_timeout(self.timeout),
        ) as response:
            await response.read()
            if response.status != 200:
                raise UnexpectedResponse(f"logout HTTP status {response.status}")
        self.token = None

    def _require_token(self) -> str:
        if self.token is None:
            raise SessionExpired("not authenticated")
        return self.token

    async def fetch_device_html(self, session: Any) -> str:
        """Fetch the optional OLT/controller status page."""
        token = self._require_token()
        url = f"{self.base_url}/cgi-bin/sta-device.asp"
        async with session.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Cookie": f"ecntToken={token}",
                "Referer": url,
            },
            allow_redirects=False,
            timeout=_client_timeout(self.timeout),
        ) as response:
            text = await response.text(errors="replace")
            if 300 <= response.status < 400:
                raise SessionExpired("device-status request redirected")
            if response.status != 200:
                raise UnexpectedResponse(f"device-status HTTP status {response.status}")
        if "check_auth.json" in text and "username" in text:
            raise SessionExpired("device-status request returned login page")
        return text

    async def fetch_user_html(self, session: Any) -> str:
        """Fetch LAN and LAN-PON status from sta-user.asp."""
        token = self._require_token()
        url = f"{self.base_url}/cgi-bin/sta-user.asp"
        async with session.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Cookie": f"ecntToken={token}",
                "Referer": url,
            },
            allow_redirects=False,
            timeout=_client_timeout(self.timeout),
        ) as response:
            text = await response.text(errors="replace")
            if 300 <= response.status < 400:
                raise SessionExpired("user-status request redirected")
            if response.status != 200:
                raise UnexpectedResponse(f"user-status HTTP status {response.status}")
        if "check_auth.json" in text and "username" in text:
            raise SessionExpired("user-status request returned login page")
        return text

    async def fetch_station_page(
        self,
        session: Any,
        *,
        page: int = 1,
        page_size: int = 10000,
    ) -> dict[str, Any]:
        """Fetch one station-list page."""
        token = self._require_token()
        fields = [
            ("pageidx_rows", f"{page},{page_size}"),
            ("filterkey_value", "Mac,"),
            ("search_item", "0"),
            ("search_condition", ""),
            ("auto_refresh", "0"),
            ("txtMaxRows", str(page_size)),
            ("txtCurPageIndex", str(page)),
            ("rebootToChangeMode", "Yes"),
        ]
        url = f"{self.base_url}/cgi-bin/ap_wlan_ac_client_list.asp"
        async with session.post(
            url,
            data=fields,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": f"ecntToken={token}; EBOOVALUE={eboo_value(fields)}",
                "Origin": self.base_url,
                "Referer": url,
            },
            allow_redirects=False,
            timeout=_client_timeout(self.timeout),
        ) as response:
            text = await response.text(errors="replace")
            if 300 <= response.status < 400:
                raise SessionExpired("station request redirected")
            if response.status != 200:
                raise UnexpectedResponse(f"station HTTP status {response.status}")
        return extract_embedded_json(text, "STA_manage")

    async def fetch_ap_page(
        self,
        session: Any,
        *,
        page: int = 1,
        page_size: int = 10000,
    ) -> dict[str, Any]:
        """Fetch one managed-AP inventory page."""
        token = self._require_token()
        fields = [
            ("pageidx_rows", f"{page},{page_size}"),
            ("filtervalue", ""),
            ("filterkey_value", ""),
            ("upgrade_mac", "0"),
            ("upgrade_action", ""),
            ("delete", "0"),
            ("search_item", "0"),
            ("search_condition", ""),
            ("auto_refresh", "0"),
            ("txtMaxRows", str(page_size)),
            ("txtCurPageIndex", str(page)),
            ("get_value", "0"),
            ("save_value", "0"),
            ("click_num", "0"),
            ("rebootToChangeMode", "Yes"),
        ]
        url = f"{self.base_url}/cgi-bin/ap_online_list.asp"
        async with session.post(
            url,
            data=fields,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": f"ecntToken={token}; EBOOVALUE={eboo_value(fields)}",
                "Origin": self.base_url,
                "Referer": url,
            },
            allow_redirects=False,
            timeout=_client_timeout(self.timeout),
        ) as response:
            text = await response.text(errors="replace")
            if 300 <= response.status < 400:
                raise SessionExpired("AP inventory request redirected")
            if response.status != 200:
                raise UnexpectedResponse(f"AP inventory HTTP status {response.status}")
        return extract_embedded_json(text, "AP_manage")

    async def fetch_ap_detail_html(self, session: Any, ap: RltechAp) -> str:
        """Fetch one managed-AP detail page."""
        token = self._require_token()
        if not ap.sn:
            raise UnexpectedResponse("AP detail request needs AP SN")
        mac_key = re.sub(r"[^0-9A-Fa-f]", "", ap.mac).upper()
        param1 = f"{mac_key}_{ap.sn}"
        url = f"{self.base_url}/cgi-bin/ap_online_detail.asp"
        async with session.get(
            f"{url}?param1={param1}&param2={ap.sn}",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Cookie": f"ecntToken={token}",
                "Referer": f"{self.base_url}/cgi-bin/ap_online_list.asp",
            },
            allow_redirects=False,
            timeout=_client_timeout(self.timeout),
        ) as response:
            text = await response.text(errors="replace")
            if 300 <= response.status < 400:
                raise SessionExpired("AP detail request redirected")
            if response.status != 200:
                raise UnexpectedResponse(f"AP detail HTTP status {response.status}")
        if "check_auth.json" in text and "username" in text:
            raise SessionExpired("AP detail request returned login page")
        return text

    async def _fetch_all(
        self,
        fetch_page: Any,
        session: Any,
        *,
        page_size: int = 10000,
    ) -> list[dict[str, Any]]:
        pages = []
        page = 1
        seen = 0
        while True:
            payload = await fetch_page(session, page=page, page_size=page_size)
            pages.append(payload)
            rows = _payload_rows(payload)
            seen += len(rows)
            total = _payload_total(payload)
            if not rows or seen >= total:
                return pages
            page += 1

    def _ap_detail_due(
        self,
        aps: dict[str, RltechAp],
        previous: RltechData | None,
        *,
        now: datetime,
        scan_interval: int,
        detail_interval: int,
    ) -> list[RltechAp]:
        """Return APs due for slow detail polling with a stable jitter."""
        if detail_interval <= 0:
            return []
        previous_details = previous.ap_details if previous is not None else {}
        polls_per_detail_interval = max(1, detail_interval // max(1, scan_interval))
        max_per_poll = max(
            1, (len(aps) + polls_per_detail_interval - 1) // polls_per_detail_interval
        )
        ordered_aps = sorted(
            (ap for ap in aps.values() if ap.sn),
            key=lambda ap: (
                zlib.crc32((ap.sn or ap.mac).encode("utf-8")),
                ap.sn or ap.mac,
            ),
        )
        missing = [
            ap
            for ap in ordered_aps
            if previous_details.get(ap.mac) is None
            or previous_details[ap.mac].last_update is None
        ]
        if missing:
            return self._ap_detail_batch(missing, max_per_poll)

        due: list[tuple[float, str, RltechAp]] = []
        for ap in ordered_aps:
            detail = previous_details.get(ap.mac)
            if detail is not None and detail.last_update is not None:
                age = (now - detail.last_update).total_seconds()
                if age < detail_interval:
                    continue
                priority = age
            else:
                priority = float(detail_interval)
            due.append((priority, ap.sn, ap))

        due.sort(key=lambda item: (-item[0], item[1]))
        return [ap for _, _, ap in due[:max_per_poll]]

    def _ap_detail_batch(self, aps: list[RltechAp], limit: int) -> list[RltechAp]:
        """Return a rotating AP detail batch."""
        if not aps or limit <= 0:
            return []
        start = self._ap_detail_cursor % len(aps)
        count = min(limit, len(aps))
        batch = [aps[(start + offset) % len(aps)] for offset in range(count)]
        self._ap_detail_cursor = (start + count) % len(aps)
        return batch

    async def _fetch_due_ap_details(
        self,
        session: Any,
        aps: dict[str, RltechAp],
        previous: RltechData | None,
        *,
        now: datetime,
        scan_interval: int,
        detail_interval: int,
    ) -> dict[str, RltechApDetail]:
        """Fetch due AP detail pages and preserve last good detail values."""
        details = {
            mac: detail
            for mac, detail in (previous.ap_details if previous is not None else {}).items()
            if mac in aps
        }
        for ap in self._ap_detail_due(
            aps,
            previous,
            now=now,
            scan_interval=scan_interval,
            detail_interval=detail_interval,
        ):
            try:
                detail = parse_ap_detail(await self.fetch_ap_detail_html(session, ap))
            except Exception as err:  # noqa: BLE001 - keep polling other APs
                _LOGGER.debug("Unable to fetch AP detail for %s: %s", ap.mac, err)
                continue
            details[ap.mac] = replace(detail, last_update=now)
        return details

    async def fetch_snapshot(
        self,
        session: Any,
        *,
        previous: RltechData | None = None,
        station_retention: int = 3600,
        include_ap_inventory: bool = True,
        include_station_inventory: bool = True,
        include_olt_status: bool = True,
        include_lan_port_status: bool = True,
        include_ap_details: bool = True,
        ap_detail_interval: int = 600,
        scan_interval: int = 60,
    ) -> RltechData:
        """Run one serialized login/fetch/logout transaction."""
        async with self._lock:
            started = time.monotonic()
            if self.token is not None:
                await self.logout(session)

            await self.login(session)
            primary_error: Exception | None = None
            try:
                ap_pages = (
                    await self._fetch_all(self.fetch_ap_page, session)
                    if include_ap_inventory
                    else []
                )
                aps = _normalize_ap_payloads(ap_pages)
                station_pages = (
                    await self._fetch_all(self.fetch_station_page, session)
                    if include_station_inventory
                    else []
                )
                now = datetime.now(UTC)
                ap_details = (
                    await self._fetch_due_ap_details(
                        session,
                        aps,
                        previous,
                        now=now,
                        scan_interval=scan_interval,
                        detail_interval=ap_detail_interval,
                    )
                    if include_ap_details and include_ap_inventory
                    else {
                        mac: detail
                        for mac, detail in (
                            previous.ap_details if previous is not None else {}
                        ).items()
                        if mac in aps
                    }
                )
                olt_html = None
                user_html = None
                if include_olt_status:
                    olt_html = await self.fetch_device_html(session)
                if include_lan_port_status:
                    user_html = await self.fetch_user_html(session)
                return normalize_snapshot(
                    ap_pages,
                    station_pages,
                    olt_html=olt_html,
                    user_html=user_html,
                    previous=previous,
                    now=now,
                    station_retention=station_retention if include_station_inventory else 0,
                    poll_duration_ms=int((time.monotonic() - started) * 1000),
                    ap_details=ap_details,
                )
            except Exception as exc:
                primary_error = exc
                raise
            finally:
                try:
                    await asyncio.shield(self.logout(session))
                except Exception as exc:
                    _LOGGER.warning("RLTech logout cleanup failed: %s", exc)
                    if primary_error is None:
                        raise

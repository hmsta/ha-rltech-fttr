"""Data models for RLTech FTTR."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RltechAp:
    """Managed AP inventory row."""

    mac: str
    ip: str | None = None
    model: str | None = None
    version: str | None = None
    online: bool | None = None
    profile: str | None = None
    profile_idx: str | None = None
    channel_24: int | None = None
    channel_5: int | None = None
    bssid_24: str | None = None
    bssid_5: str | None = None
    assoc_count: int | None = None
    alias: str | None = None
    uplink: int | None = None
    uplink_port: int | None = None
    sn: str | None = None
    dev_sn: str | None = None
    upgrade_flag: str | None = None


@dataclass(frozen=True)
class RltechApDetail:
    """Detailed managed AP status from ap_online_detail.asp."""

    mac: str | None = None
    last_update: datetime | None = None
    ip: str | None = None
    model: str | None = None
    version: str | None = None
    online: bool | None = None
    profile: str | None = None
    alias: str | None = None
    sn: str | None = None
    dev_sn: str | None = None
    uplink: int | None = None
    uplink_port: int | None = None
    assoc_count: int | None = None
    channel_24: int | None = None
    channel_5: int | None = None
    bssid_24: str | None = None
    bssid_5: str | None = None
    hostname: str | None = None
    sys_duration: int | None = None
    ram_size: int | None = None
    flash_size: int | None = None
    cpu_usage: float | None = None
    cpu_temperature: float | None = None
    memory_usage: float | None = None
    flash_usage: float | None = None
    pon_id: int | None = None
    onu_id: int | None = None
    pon_sn: str | None = None
    onu_status: str | None = None
    ont_distance: int | None = None
    optical_temperature: float | None = None
    optical_current: float | None = None
    optical_voltage: float | None = None
    optical_tx_power: float | None = None
    optical_rx_power: float | None = None
    downstream_optical_rx_power: float | None = None
    optical_error_status: int | None = None
    active: bool | None = None
    last_up_time: str | None = None
    last_down_time: str | None = None
    last_dying_gasp_time: str | None = None
    last_down_cause: str | None = None
    reg_off_time: str | None = None
    interface: str | None = None
    source_host: str | None = None
    register_status: str | None = None
    identify_vendor: str | None = None
    equipment_id: str | None = None
    sn_address: str | None = None
    hardware_version: str | None = None
    software_version: str | None = None
    firmware_version: str | None = None


@dataclass(frozen=True)
class RltechStation:
    """Wi-Fi station row."""

    mac: str
    reported_online: bool
    home: bool
    last_seen: datetime | None
    id: str | None = None
    ip: str | None = None
    hostname: str | None = None
    ssid: str | None = None
    ap_mac: str | None = None
    ap_alias: str | None = None
    rssi: int | None = None
    rx_rate: float | None = None
    tx_rate: float | None = None
    rx_nego_rate: float | None = None
    tx_nego_rate: float | None = None
    uptime: int | None = None
    channel: int | None = None
    band: str | None = None
    bandwidth: str | None = None
    vlan: int | None = None
    alias: str | None = None
    total_count: str | None = None
    update_time: int | None = None


@dataclass(frozen=True)
class RltechOltStatus:
    """Optional OLT/controller status parsed from sta-device.asp."""

    pon_link_state: int | None = None
    fec_state: bool | None = None
    pon_tx_frames: int | None = None
    pon_rx_frames: int | None = None
    pon_up_since: str | None = None
    current_time: str | None = None
    system_uptime: str | None = None
    wan_link_uptime: str | None = None
    last_boot: datetime | None = None
    wan_link_up_since: datetime | None = None
    device_type: str | None = None
    gateway_type: str | None = None
    cpu_temperature: float | None = None
    cpu_usage: float | None = None
    memory_usage: float | None = None
    flash_usage: float | None = None
    manufacturer: str | None = None
    serial_number: str | None = None
    hardware_version: str | None = None
    software_version: str | None = None


@dataclass(frozen=True)
class RltechLanPort:
    """LAN Ethernet port status parsed from sta-user.asp."""

    port: int
    label: str | None = None
    path: str | None = None
    status: str | None = None
    connected: bool | None = None
    rate: str | None = None
    mode: str | None = None
    tx_bytes: int | None = None
    tx_packets: int | None = None
    tx_errors: int | None = None
    tx_drops: int | None = None
    rx_bytes: int | None = None
    rx_packets: int | None = None
    rx_errors: int | None = None
    rx_drops: int | None = None


@dataclass(frozen=True)
class RltechLanPonPort:
    """LAN-PON port status parsed from sta-user.asp."""

    ponid: int
    status: str | None = None
    active: str | None = None
    fec: str | None = None
    autoregister: str | None = None
    tx_power: float | None = None
    rx_power: float | None = None
    temperature: float | None = None
    voltage: float | None = None
    current: float | None = None


@dataclass(frozen=True)
class RltechLegacyOltSource:
    """One legacy port-80 OLT hardware/status source."""

    host: str
    base_url: str
    olt_status: RltechOltStatus | None = None
    lan_ports: dict[int, RltechLanPort] = field(default_factory=dict)
    lanpon_ports: dict[int, RltechLanPonPort] = field(default_factory=dict)


@dataclass(frozen=True)
class RltechData:
    """Complete normalized coordinator snapshot."""

    aps: dict[str, RltechAp] = field(default_factory=dict)
    ap_details: dict[str, RltechApDetail] = field(default_factory=dict)
    stations: dict[str, RltechStation] = field(default_factory=dict)
    olt_status: RltechOltStatus | None = None
    lan_ports: dict[int, RltechLanPort] = field(default_factory=dict)
    lanpon_ports: dict[int, RltechLanPonPort] = field(default_factory=dict)
    legacy_sources: dict[str, RltechLegacyOltSource] = field(default_factory=dict)
    last_success: datetime | None = None
    poll_duration_ms: int | None = None

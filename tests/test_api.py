"""Tests for RLTech FTTR API parsing and transaction behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from importlib import util
import json
from pathlib import Path
import sys

PKG_ROOT = Path(__file__).parents[1] / "custom_components" / "rltech_fttr"


def load_module(name: str):
    spec = util.spec_from_file_location(
        f"custom_components.rltech_fttr.{name}", PKG_ROOT / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


models = load_module("models")
api = load_module("api")
identifiers = load_module("identifiers")
ap_inventory = load_module("ap_inventory")
dhcp_enrichment = load_module("dhcp_enrichment")
hostname_enrichment = load_module("hostname_enrichment")
station_inventory = load_module("station_inventory")


def payload(rows, total=None, code=0):
    return {
        "respCode": code,
        "total": len(rows) if total is None else total,
        "data": {"list": rows},
    }


def test_station_trackers_are_not_a_default_platform() -> None:
    const_text = (PKG_ROOT / "const.py").read_text(encoding="utf-8")
    assert "Platform.DEVICE_TRACKER" not in const_text


def test_eboo_value_vector() -> None:
    fields = [
        ("pageidx_rows", "1,100"),
        ("filterkey_value", "Mac,"),
        ("search_item", "0"),
        ("search_condition", ""),
        ("auto_refresh", "0"),
        ("txtMaxRows", "100"),
        ("txtCurPageIndex", "1"),
        ("rebootToChangeMode", "Yes"),
    ]
    assert api.eboo_value(fields) == "6cbf7420"


def test_extract_embedded_json_html_unescapes() -> None:
    embedded = html_payload("STA_manage", {"respCode": 0, "data": {"list": [{"HostName": "a&b"}]}})
    result = api.extract_embedded_json(embedded, "STA_manage")
    assert result["data"]["list"][0]["HostName"] == "a&b"


def test_parse_ap_online_detail_embedded_json() -> None:
    detail = api.parse_ap_detail(
        """
        <SCRIPT>
        var list_ap ='{ "respCode":0, "data":{ "Model":"RH802GW-AX3", "IP":"172.20.11.27", "Version":"V0.0.49", "Mac":"44953BB8DCE0", "Status":"1", "Profile":"Default", "ChannelG24":"1", "ChannelG5":"40", "Assoc":"1", "Alias":"House11_Office", "SN":"RLGM3BB8DCE0", "Uplink":"2", "UplinkPort":"5", "BssidG24":"44953BB8DCE4", "BssidG5":"44953BB8DCE5", "SysDuration":"77425", "RamSize":"536870912", "FlashSize":"268435456", "DevName":"FTTRSub_B8DCE0", "CPUUsage":"5", "CPUTemp":"66", "MEMUsage":"30", "FlashUsage":"86", "DevSN":"RL2024090300054", "UpgradeFlag":"1", "ProfileIdx":"1" } } '
        let list_pon = '{ "result": 0, "data": "{ \\"pon_id\\": 1, \\"onu_id\\": 2, \\"pon_sn\\": \\"RLGM3BB8DCE0\\", \\"opt_temperature\\": \\" 51.45\\", \\"opt_current\\": \\" 12.23\\", \\"opt_voltage\\": \\"  3.26\\", \\"opt_tx_power\\": \\" -1.79\\", \\"opt_rx_power\\": \\"-15.34\\", \\"active\\": 1, \\"onu_status\\": \\"online\\", \\"ont_distance\\": 443, \\"opt_err_status\\": 0, \\"last_up_time\\": \\"2026-08-19 17:43:11\\", \\"last_down_time\\": \\"2026-08-19 17:42:35\\", \\"last_dying_gasptime\\": \\"2026-08-17 15:26:17\\", \\"last_down_cause\\": \\"FiberBroken\\", \\"dnopt_rx_power\\": \\"-19.86\\", \\"identify_vendor\\": \\"RLGM\\", \\"equipment_id\\": \\"RH802GW-AX3\\", \\"sn_address\\": \\"RLGM-3BB8DCE0\\", \\"hardware_version\\": \\"N/A\\", \\"software_version\\": \\"V0.0.49\\", \\"fireware_version\\": \\"N/A\\" }" } ';
        </SCRIPT>
        """
    )

    assert detail.mac == "44:95:3B:B8:DC:E0"
    assert detail.ip == "172.20.11.27"
    assert detail.online is True
    assert detail.alias == "House11_Office"
    assert detail.sn == "RLGM3BB8DCE0"
    assert detail.hostname == "FTTRSub_B8DCE0"
    assert detail.sys_duration == 77425
    assert detail.ram_size == 536870912
    assert detail.flash_size == 268435456
    assert detail.cpu_usage == 5
    assert detail.cpu_temperature == 66
    assert detail.memory_usage == 30
    assert detail.flash_usage == 86
    assert detail.pon_id == 1
    assert detail.onu_id == 2
    assert detail.pon_sn == "RLGM3BB8DCE0"
    assert detail.onu_status == "online"
    assert detail.ont_distance == 443
    assert detail.optical_temperature == 51.45
    assert detail.optical_current == 12.23
    assert detail.optical_voltage == 3.26
    assert detail.optical_tx_power == -1.79
    assert detail.optical_rx_power == -15.34
    assert detail.downstream_optical_rx_power == -19.86
    assert detail.active is True
    assert detail.last_down_cause == "FiberBroken"
    assert detail.last_up_time == "2026-08-19 17:43:11"
    assert detail.last_down_time == "2026-08-19 17:42:35"
    assert detail.last_dying_gasp_time == "2026-08-17 15:26:17"
    assert detail.hardware_version is None
    assert detail.software_version == "V0.0.49"


def test_respcode_3_normalizes_to_empty() -> None:
    data = api.normalize_snapshot([payload([], code=3)], [payload([], code=3)], olt_html=None)
    assert data.aps == {}
    assert data.stations == {}


def test_normalization_join_and_channel_rules() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    data = api.normalize_snapshot(
        [
            payload(
                [
                    {
                        "Mac": "44953BB8DCD0",
                        "Alias": "Hall AP",
                        "Status": "1",
                        "BssidG24": "44:95:3b:b8:dc:d1",
                        "ChannelG24": "6",
                        "ChannelG5": "36",
                        "Assoc": "2",
                    }
                ]
            )
        ],
        [
            payload(
                [
                    {
                        "Mac": "7C45D04C1759",
                        "APMac": "44:95:3B:B8:DC:D0",
                        "Status": "1",
                        "Channel": "0",
                        "Bandwidth": "4",
                        "RSSI": "-61",
                    }
                ]
            )
        ],
        olt_html=None,
        now=now,
    )
    station = data.stations["7C:45:D0:4C:17:59"]
    assert station.ap_alias == "Hall AP"
    assert station.band is None
    assert station.bandwidth == "20/40/80 MHz"
    assert station.last_seen == now


def test_station_retention_keeps_then_expires_station() -> None:
    first = api.normalize_snapshot(
        [payload([])],
        [payload([{"Mac": "7C45D04C1759", "Status": "1"}])],
        olt_html=None,
        now=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
    )
    kept = api.normalize_snapshot(
        [payload([])],
        [payload([])],
        olt_html=None,
        previous=first,
        now=datetime(2026, 8, 20, 1, 1, tzinfo=UTC),
        station_retention=180,
    )
    expired = api.normalize_snapshot(
        [payload([])],
        [payload([])],
        olt_html=None,
        previous=first,
        now=datetime(2026, 8, 20, 1, 5, tzinfo=UTC),
        station_retention=180,
    )
    assert kept.stations["7C:45:D0:4C:17:59"].reported_online is False
    assert "7C:45:D0:4C:17:59" not in expired.stations


def test_station_inventory_rows_are_serialized_without_entities() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    data = api.normalize_snapshot(
        [payload([])],
        [
            payload(
                [
                    {
                        "Mac": "7C45D04C1759",
                        "IP": "192.168.1.10",
                        "HostName": "phone",
                        "SSID": "main",
                        "APMac": "44953BB8DCD0",
                        "Status": "1",
                        "RSSI": "-55",
                        "Channel": "36",
                        "Vlan": "40",
                        "UpTime": "123",
                    }
                ]
            )
        ],
        olt_html=None,
        now=now,
    )

    rows = station_inventory.station_rows(data)

    assert rows == [
        {
            "mac": "7C:45:D0:4C:17:59",
            "ip": "192.168.1.10",
            "hostname": "phone",
            "ssid": "main",
            "ap_mac": "44:95:3B:B8:DC:D0",
            "ap_alias": None,
            "rssi": -55,
            "band": "5 GHz",
            "channel": 36,
            "vlan": 40,
            "uptime": 123,
            "reported_online": True,
            "last_seen": now.isoformat(),
            "alias": None,
            "home": True,
            "rx_rate": None,
            "tx_rate": None,
            "rx_nego_rate": None,
            "tx_nego_rate": None,
            "bandwidth": None,
            "total_count": None,
        }
    ]


def test_dhcp_enrichment_fills_missing_or_junk_station_hostnames() -> None:
    data = api.normalize_snapshot(
        [payload([])],
        [
            payload(
                [
                    {
                        "Mac": "7C45D04C1759",
                        "IP": "192.168.1.10",
                        "HostName": "N/A",
                        "Status": "1",
                    },
                    {
                        "Mac": "7C45D04C1760",
                        "IP": "192.168.1.11",
                        "HostName": "",
                        "Status": "1",
                    },
                ]
            )
        ],
        olt_html=None,
    )

    enriched = dhcp_enrichment.enrich_station_hostnames(
        data,
        {"7c45d04c1759": "phone-from-mac"},
        {"192.168.1.11": "tablet-from-ip"},
    )

    assert enriched.stations["7C:45:D0:4C:17:59"].hostname == "phone-from-mac"
    assert enriched.stations["7C:45:D0:4C:17:60"].hostname == "tablet-from-ip"


def test_dhcp_enrichment_does_not_replace_useful_fttr_hostname() -> None:
    data = api.normalize_snapshot(
        [payload([])],
        [
            payload(
                [
                    {
                        "Mac": "7C45D04C1759",
                        "IP": "192.168.1.10",
                        "HostName": "fttr-phone",
                        "Status": "1",
                    }
                ]
            )
        ],
        olt_html=None,
    )

    enriched = dhcp_enrichment.enrich_station_hostnames(
        data,
        {"7c45d04c1759": "dhcp-phone"},
        {"192.168.1.10": "dhcp-phone-ip"},
    )

    assert enriched.stations["7C:45:D0:4C:17:59"].hostname == "fttr-phone"


def test_dhcp_match_summary_counts_fillable_missing_hostnames() -> None:
    data = api.normalize_snapshot(
        [payload([])],
        [
            payload(
                [
                    {
                        "Mac": "0EF0A5FA19C9",
                        "IP": "192.168.43.207",
                        "HostName": "",
                        "Status": "1",
                    },
                    {
                        "Mac": "7C45D04C1760",
                        "IP": "192.168.1.11",
                        "HostName": "",
                        "Status": "1",
                    },
                ]
            )
        ],
        olt_html=None,
    )

    summary = hostname_enrichment.dhcp_match_summary(
        object(),
        data.stations.values(),
        lookup_fn=lambda _hass: (
            {"0ef0a5fa19c9": "Yaron-s-Tab-S7-FE"},
            {"192.168.43.207": "Yaron-s-Tab-S7-FE"},
        ),
    )

    assert summary["dhcp_mac_count"] == 1
    assert summary["dhcp_ip_count"] == 1
    assert summary["station_mac_match_count"] == 1
    assert summary["station_ip_match_count"] == 1
    assert summary["station_missing_hostname_fillable_count"] == 1


def test_ap_inventory_rows_are_serialized_for_table() -> None:
    data = api.normalize_snapshot(
        [
            payload(
                [
                    {
                        "Mac": "44953BB8DCD0",
                        "Alias": "Hall AP",
                        "IP": "192.168.1.20",
                        "Model": "RH802GW-AX3",
                        "Version": "V0.0.49",
                        "Status": "1",
                        "Profile": "Default",
                        "ProfileIdx": "1",
                        "BssidG24": "44953BB8DCD4",
                        "BssidG5": "44953BB8DCD5",
                        "ChannelG24": "6",
                        "ChannelG5": "40",
                        "Assoc": "3",
                        "Uplink": "2",
                        "UplinkPort": "6",
                        "SN": "RLGM3BB8DCD0",
                        "DevSN": "RL2024090300001",
                        "UpgradeFlag": "1",
                    }
                ]
            )
        ],
        [payload([])],
        olt_html=None,
    )

    rows = ap_inventory.ap_rows(data)

    assert rows == [
        {
            "device_id": None,
            "hardware_id": "RLGM3BB8DCD0",
            "mac": "44:95:3B:B8:DC:D0",
            "alias": "Hall AP",
            "ip": "192.168.1.20",
            "online": True,
            "model": "RH802GW-AX3",
            "version": "V0.0.49",
            "profile": "Default",
            "profile_idx": "1",
            "channel_24": 6,
            "channel_5": 40,
            "bssid_24": "44:95:3B:B8:DC:D4",
            "bssid_5": "44:95:3B:B8:DC:D5",
            "assoc_count": 3,
            "uplink": 2,
            "uplink_port": 6,
            "sn": "RLGM3BB8DCD0",
            "dev_sn": "RL2024090300001",
            "upgrade_flag": "1",
            "entities": {},
        }
    ]


def test_ap_sensor_unique_id_prefers_serial() -> None:
    ap = models.RltechAp(
        mac="44:95:3B:B8:DC:D0",
        sn="RLGM3BB8DCD0",
        dev_sn="RL2024090300001",
    )

    assert (
        identifiers.ap_sensor_unique_id("entry", ap, "assoc_count")
        == "entry_ap_RLGM3BB8DCD0_assoc_count"
    )
    assert identifiers.AP_SENSOR_KEYS[:4] == ("online", "assoc_count", "profile", "alias")
    assert "optical_rx_power" in identifiers.AP_SENSOR_KEYS


def test_ap_hardware_id_does_not_use_dev_sn() -> None:
    ap = models.RltechAp(
        mac="44:95:3B:B8:DC:D0",
        dev_sn="RL2024090300001",
    )

    assert identifiers.ap_hardware_id(ap) is None
    assert identifiers.ap_sensor_unique_id("entry", ap, "assoc_count") is None


def test_normalize_snapshot_preserves_ap_details() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    detail = models.RltechApDetail(
        mac="44:95:3B:B8:DC:E0",
        optical_rx_power=-15.34,
        last_update=now,
    )

    data = api.normalize_snapshot(
        [
            payload(
                [
                    {
                        "Mac": "44953BB8DCE0",
                        "SN": "RLGM3BB8DCE0",
                    }
                ]
            )
        ],
        [payload([])],
        olt_html=None,
        now=now,
        ap_details={"44:95:3B:B8:DC:E0": detail},
    )

    assert data.ap_details["44:95:3B:B8:DC:E0"].optical_rx_power == -15.34


def test_ap_detail_due_respects_interval() -> None:
    client = api.RltechClient("http://example.invalid", "u", "p")
    now = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
    ap = models.RltechAp(
        mac="44:95:3B:B8:DC:E0",
        sn="RLGM3BB8DCE0",
    )
    fresh = models.RltechData(
        aps={ap.mac: ap},
        ap_details={
            ap.mac: models.RltechApDetail(
                mac=ap.mac,
                last_update=now - timedelta(seconds=599),
            )
        },
    )
    stale = models.RltechData(
        aps={ap.mac: ap},
        ap_details={
            ap.mac: models.RltechApDetail(
                mac=ap.mac,
                last_update=now - timedelta(seconds=600),
            )
        },
    )

    assert client._ap_detail_due(
        {ap.mac: ap},
        fresh,
        now=now,
        scan_interval=60,
        detail_interval=600,
    ) == []
    assert client._ap_detail_due(
        {ap.mac: ap},
        stale,
        now=now,
        scan_interval=60,
        detail_interval=600,
    ) == [ap]


def test_ap_detail_due_covers_missing_details_without_starvation() -> None:
    client = api.RltechClient("http://example.invalid", "u", "p")
    start = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
    aps = {
        f"44:95:3B:B8:E0:{index:02X}": models.RltechAp(
            mac=f"44:95:3B:B8:E0:{index:02X}",
            sn=f"RLGM3BB8E0{index:02X}",
        )
        for index in range(29)
    }
    seen: set[str] = set()

    for offset in range(0, 600, 60):
        due = client._ap_detail_due(
            aps,
            None,
            now=start + timedelta(seconds=offset),
            scan_interval=60,
            detail_interval=600,
        )
        assert len(due) <= 3
        seen.update(ap.sn for ap in due if ap.sn)

    assert seen == {ap.sn for ap in aps.values()}


def test_parse_olt_status_optional_fields() -> None:
    status = api.parse_olt_status(
        """
        var phy_status = 'gpon_phy_up';
        var pon_mode = '1';
        this.LinkSta = '1';
        this.trafficstate = 'up';
        this.fecState = '1';
        this.PonSendPkt = '12';
        this.PonRecvPkt = '34';
        var ponuptime = "2026-08-20 01:00:00";
        var curtime = '2026-08-20 01:05:00';
        CpuUsage = '13';
        MemoryUsage = '44';
        FlashUsage = '55';
        CpuTemp = '48.5';
        CustomerSWVersion = 'V0.0.29';
        """
    )
    assert status.fec_state is True
    assert status.pon_tx_frames == 12
    assert status.pon_rx_frames == 34
    assert status.cpu_usage == 13
    assert status.software_version == "V0.0.29"


def test_parse_olt_status_table_rendered_browser_values() -> None:
    now = datetime(2026, 8, 20, 15, 0, 0, tzinfo=UTC)
    status = api.parse_olt_status(
        """
        var phy_status = 'down';
        var pon_mode = '3';
        this.LinkSta = 'N/A';
        this.trafficstate = 'down';
        this.fecState = 'N/A';
        this.PonSendPkt = '1063260816';
        this.PonRecvPkt = '1753625037';
        <TR><TD class="table_title">Manufacturer:</TD><TD>
        <SCRIPT>document.write('RLTech');</SCRIPT>&nbsp;</TD></TR>
        <TR><TD class="table_title">Device Type:</TD><TD>10GE&nbsp;</TD></TR>
        <TR><TD class="table_title">Gateway Type:</TD><TD>RH8002GR&nbsp;</TD></TR>
        <TR><TD class="table_title">Serial Number:</TD><TD>
        44953B-RL2024092600019&nbsp;</TD></TR>
        <TR><TD class="table_title">Hardware Version:</TD><TD>V0.1.0&nbsp;</TD></TR>
        <TR><TD class="table_title">Software Version:</TD><TD>V0.0.29&nbsp;</TD></TR>
        <TR><TD class="table_title">Run Time:</TD><TD>
        18 Days 20 Hour 37 Min 46 Sec&nbsp;</TD></TR>
        <TR><TD class="table_title">CPU Temperature:</TD><TD>63 ℃&nbsp;</TD></TR>
        <TR><TD class="table_title">WAN Link Up Time:</TD><TD>
        18 Days 20 Hour 37 Min 14 Sec&nbsp;</TD></TR>
        """,
        now=now,
    )
    assert status.manufacturer == "RLTech"
    assert status.device_type == "10GE"
    assert status.gateway_type == "RH8002GR"
    assert status.serial_number == "44953B-RL2024092600019"
    assert status.hardware_version == "V0.1.0"
    assert status.software_version == "V0.0.29"
    assert status.system_uptime == "18 Days 20 Hour 37 Min 46 Sec"
    assert status.wan_link_uptime == "18 Days 20 Hour 37 Min 14 Sec"
    assert status.last_boot == datetime(2026, 8, 1, 18, 22, 14, tzinfo=UTC)
    assert status.wan_link_up_since == datetime(2026, 8, 1, 18, 22, 46, tzinfo=UTC)
    assert status.cpu_temperature == 63
    assert status.current_time is None


def test_parse_lan_and_lanpon_ports() -> None:
    html = """
    var lancntvalue = '{"data":[{"Port":"1", "LanState":"1", "TxBytes":"9643532541", "RxBytes":"9726199278", "Negoration":"1000M", "Mode":"Full"},{"Port":"2", "LanState":"0", "TxBytes":"0", "RxBytes":"0", "Negoration":"Down", "Mode":""},{"Port":"5", "LanState":"1", "TxBytes":"2095094151", "RxBytes":"18446744073115276764", "Negoration":"2500M", "Mode":"Full"}]}';
    Ethernet = [["0","Disabled","560097","4123","0","0","3096680","5897","0","0"],
    ["InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig.2","Up","560097","4123","0","0","3096680","5897","0","0"],
    ["InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig.3","Disabled","560362","4124","0","0","3096680","5897","0","0"],
    ["InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig.4","Disabled","560362","4124","0","0","3096680","5897","0","0"],null]
    var ponport_info = '{ "list": [ { "ponid": 1, "fec": "disable", "active": "enable", "autoregister": "enable", "status": "up", "tx_power": "2.73", "rx_power": "-20.56", "temp": "53.59", "voltage": "3.08", "current": "44.39" }, { "ponid": 2, "fec": "disable", "active": "enable", "autoregister": "enable", "status": "up", "tx_power": "3.00", "rx_power": "-21.69", "temp": "52.26", "voltage": "3.08", "current": "40.92" } ] }';
    """

    lan_ports = api.parse_lan_ports(html)
    lanpon_ports = api.parse_lanpon_ports(html)

    assert lan_ports[1].status == "connected"
    assert lan_ports[1].connected is True
    assert lan_ports[1].rate == "1000M"
    assert lan_ports[1].mode == "Full-Duplex"
    assert lan_ports[2].status == "disconnected"
    assert lan_ports[5].label == "LANPON1"
    assert lan_ports[5].rate == "2500M"
    assert lanpon_ports[1].status == "up"
    assert lanpon_ports[1].rx_power == -20.56
    assert lanpon_ports[2].temperature == 52.26


def test_parse_lan_ports_falls_back_to_ethernet_array() -> None:
    lan_ports = api.parse_lan_ports(
        """
        Ethernet = [["InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig.2","Up","1","2","3","4","5","6","7","8"],null]
        """
    )

    assert lan_ports[2].label == "LAN-2"
    assert lan_ports[2].status == "Up"
    assert lan_ports[2].connected is True
    assert lan_ports[2].tx_bytes == 1
    assert lan_ports[2].rx_packets == 6


def test_normalize_snapshot_includes_optional_lan_ports() -> None:
    data = api.normalize_snapshot(
        [payload([])],
        [payload([])],
        olt_html=None,
        user_html="""
        var lancntvalue = '{"data":[{"Port":"5", "LanState":"1", "TxBytes":"1", "RxBytes":"2", "Negoration":"2500M", "Mode":"Full"}]}';
        var ponport_info = '{ "list": [ { "ponid": 1, "status": "up" } ] }';
        """,
    )

    assert data.lan_ports[5].status == "connected"
    assert data.lan_ports[5].label == "LANPON1"
    assert data.lanpon_ports[1].status == "up"


def test_diagnostics_redaction_helper() -> None:
    diagnostics = load_module("diagnostics")
    result = diagnostics._redact(
        {
            "password": "secret",
            "username": "admin",
            "base_url": "http://192.168.1.1",
            "nested": {"token": "abc", "ok": True, "mac": "aa:bb"},
        }
    )
    assert result["password"] == diagnostics.REDACTED
    assert result["username"] == diagnostics.REDACTED
    assert result["base_url"] == diagnostics.REDACTED
    assert result["nested"]["token"] == diagnostics.REDACTED
    assert result["nested"]["mac"] == diagnostics.REDACTED
    assert result["nested"]["ok"] is True


def test_diagnostics_missing_optical_only_counts_online_pon_aps() -> None:
    diagnostics = load_module("diagnostics")
    online_pon = models.RltechAp(mac="44:95:3B:B8:DC:D0", online=True, uplink=2)
    online_lan = models.RltechAp(mac="44:95:3B:B8:DC:E0", online=True, uplink=0)
    offline_pon = models.RltechAp(mac="44:95:3B:B8:DC:F0", online=False, uplink=2)
    complete_pon = models.RltechAp(mac="44:95:3B:B8:DD:00", online=True, uplink=2)

    assert diagnostics._ap_detail_missing_expected_optical(
        online_pon,
        models.RltechApDetail(mac=online_pon.mac, uplink=2),
    )
    assert not diagnostics._ap_detail_missing_expected_optical(
        online_lan,
        models.RltechApDetail(mac=online_lan.mac, uplink=0),
    )
    assert not diagnostics._ap_detail_missing_expected_optical(
        offline_pon,
        models.RltechApDetail(mac=offline_pon.mac, uplink=2),
    )
    assert not diagnostics._ap_detail_missing_expected_optical(
        complete_pon,
        models.RltechApDetail(
            mac=complete_pon.mac,
            uplink=2,
            optical_rx_power=-15.34,
            optical_tx_power=-1.79,
        ),
    )


def test_authentication_error_mapping() -> None:
    async def run() -> None:
        client = api.RltechClient("http://olt", "u", "p")
        session = FakeSession([FakeResponse(200, json.dumps({"Privilege": "0"}))])
        try:
            await client.login(session)
        except api.AuthenticationError:
            return
        raise AssertionError("expected AuthenticationError")

    asyncio.run(run())


def test_account_busy_mapping() -> None:
    async def run() -> None:
        client = api.RltechClient("http://olt", "u", "p")
        session = FakeSession([FakeResponse(200, json.dumps({"Logged": "1"}))])
        try:
            await client.login(session)
        except api.AccountBusyError:
            return
        raise AssertionError("expected AccountBusyError")

    asyncio.run(run())


def test_logout_after_success_and_failure_retains_token() -> None:
    async def run_success() -> None:
        client = api.RltechClient("http://olt", "u", "p")
        session = FakeSession(
            [
                FakeResponse(200, json.dumps({"Logged": "0", "Privilege": "1", "Active": "1", "ecntToken": "tok"})),
                FakeResponse(200, html_payload("AP_manage", payload([]))),
                FakeResponse(200, html_payload("STA_manage", payload([]))),
                FakeResponse(200, "var phy_status = 'down';"),
                FakeResponse(200, ""),
                FakeResponse(200, ""),
            ]
        )
        await client.fetch_snapshot(session)
        assert client.token is None
        assert session.calls[-1][0] == "GET"
        assert session.calls[-1][1].endswith("/logout.cgi")

    async def run_failed_logout() -> None:
        client = api.RltechClient("http://olt", "u", "p")
        session = FakeSession(
            [
                FakeResponse(200, json.dumps({"Logged": "0", "Privilege": "1", "Active": "1", "ecntToken": "tok"})),
                FakeResponse(500, ""),
            ]
        )
        await client.login(session)
        try:
            await client.logout(session)
        except api.UnexpectedResponse:
            assert client.token == "tok"
            return
        raise AssertionError("expected logout failure")

    asyncio.run(run_success())
    asyncio.run(run_failed_logout())


def test_fetch_snapshot_can_skip_ap_and_station_pages() -> None:
    async def run() -> None:
        client = api.RltechClient("http://olt", "u", "p")
        session = FakeSession(
            [
                FakeResponse(200, json.dumps({"Logged": "0", "Privilege": "1", "Active": "1", "ecntToken": "tok"})),
                FakeResponse(200, "CpuTemp = '40';"),
                FakeResponse(200, ""),
            ]
        )
        data = await client.fetch_snapshot(
            session,
            include_ap_inventory=False,
            include_station_inventory=False,
            include_olt_status=True,
            include_lan_port_status=False,
        )

        assert data.aps == {}
        assert data.stations == {}
        assert all("ap_online_list" not in call[1] for call in session.calls)
        assert all("ap_wlan_ac_client_list" not in call[1] for call in session.calls)

    asyncio.run(run())


def html_payload(name: str, body: dict) -> str:
    return f"var {name} = '{json.dumps(body).replace('&', '&amp;')}';"


class FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def text(self, **kwargs):
        return self.body

    async def read(self):
        return self.body.encode()


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

"""Constants for RLTech FTTR."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "rltech_fttr"
PLATFORMS = [Platform.SENSOR]

STATION_CARD_URL = "/rltech_fttr/rltech-fttr-station-table-card.js"
STATION_CARD_FILENAME = "rltech-fttr-station-table-card.js"
AP_CARD_URL = "/rltech_fttr/rltech-fttr-ap-table-card.js"
AP_CARD_FILENAME = "rltech-fttr-ap-table-card.js"

CONF_BASE_URL = "base_url"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STATION_RETENTION = "station_retention"
CONF_ENABLE_AP_POLLING = "enable_ap_polling"
CONF_ENABLE_STATION_POLLING = "enable_station_polling"
CONF_ENABLE_OLT_STATUS = "enable_olt_status"
CONF_ENABLE_LAN_PORT_STATUS = "enable_lan_port_status"
CONF_ENABLE_AP_DETAIL_POLLING = "enable_ap_detail_polling"
CONF_AP_DETAIL_INTERVAL = "ap_detail_interval"

DEFAULT_BASE_URL = "http://192.168.1.1"
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_STATION_RETENTION = 3600
DEFAULT_ENABLE_AP_POLLING = True
DEFAULT_ENABLE_STATION_POLLING = True
DEFAULT_ENABLE_OLT_STATUS = True
DEFAULT_ENABLE_LAN_PORT_STATUS = True
DEFAULT_ENABLE_AP_DETAIL_POLLING = True
DEFAULT_AP_DETAIL_INTERVAL = 600

MIN_SCAN_INTERVAL = 30
MIN_AP_DETAIL_INTERVAL = 300
DEFAULT_TIMEOUT = 10

"""Constants for RLTech FTTR."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "rltech_fttr"
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

STATION_CARD_URL = "/rltech_fttr/rltech-fttr-station-table-card.js"
STATION_CARD_FILENAME = "rltech-fttr-station-table-card.js"
AP_CARD_URL = "/rltech_fttr/rltech-fttr-ap-table-card.js"
AP_CARD_FILENAME = "rltech-fttr-ap-table-card.js"

CONF_BASE_URL = "base_url"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STATION_RETENTION = "station_retention"
CONF_ENABLE_AP_POLLING = "enable_ap_polling"
CONF_ENABLE_STATION_POLLING = "enable_station_polling"
CONF_AP_AREA_ID = "ap_area_id"
CONF_ENABLE_HARDWARE_STATUS = "enable_hardware_status"
CONF_LEGACY_USERNAME = "legacy_username"
CONF_LEGACY_PASSWORD = "legacy_password"
CONF_LEGACY_HOSTS = "legacy_hosts"
CONF_AP_USERNAME = "ap_username"
CONF_AP_PASSWORD = "ap_password"
CONF_ENABLE_MQTT = "enable_mqtt"
CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_MQTT_PSK_IDENTITY = "mqtt_psk_identity"
CONF_MQTT_PSK = "mqtt_psk"

DEFAULT_BASE_URL = "http://192.168.1.1:8080"
DEFAULT_USERNAME = "useradmin"
DEFAULT_AP_USERNAME = "useradmin"
DEFAULT_AP_PASSWORD = "1234"
DEFAULT_LEGACY_USERNAME = "admin"
DEFAULT_LEGACY_PASSWORD = "admin"
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_STATION_RETENTION = 3600
DEFAULT_ENABLE_AP_POLLING = True
DEFAULT_ENABLE_STATION_POLLING = True
DEFAULT_ENABLE_HARDWARE_STATUS = True
DEFAULT_ENABLE_MQTT = False
DEFAULT_MQTT_PORT = 8883
DEFAULT_MQTT_USERNAME = "admin"
DEFAULT_MQTT_PASSWORD = "123456"
DEFAULT_MQTT_PSK_IDENTITY = "admin"
DEFAULT_DHCP_HOSTNAME_REFRESH_INTERVAL = 300

MIN_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT = 10

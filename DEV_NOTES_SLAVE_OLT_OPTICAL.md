# Slave OLT Optical Enrichment Notes

This is a development note, not end-user README content.

## Problem

The master FTTR Web UI on port 8080 is the authoritative source for AP inventory
and station inventory, but AP optical detail is incomplete for APs that are
physically behind downstream/slave OLTs.

Polling each AP directly would avoid the slave topology assumption, but it would
turn one controller poll into one poll per AP. For larger installs that is a bad
default shape.

## Proposed Shape

Keep the master FTTR config entry as the only Home Assistant device owner:

- Master OLT creates AP devices and AP sensors.
- Master OLT creates no station entities; stations remain table inventory data.
- Optional slave OLT sources only enrich existing AP optical values.
- Slave OLT sources do not create AP devices, station data, or controller devices
  by default.

The clean matching key is:

```text
slave ONU row PONSN == master AP SN
```

Example:

```text
master AP SN:     RLGM3BB8E0D0
slave ONU PONSN:  RLGM3BB8E0D0
```

## Preferred Source

Use the legacy slave OLT HTTP interface on port 80:

```text
http://<slave-olt>/onu_mgmt.asp
```

The local test tool for this path is:

```text
local_tools/probe_olt80_onu.py
```

That script logs into the old port-80 UI, fetches `onu_mgmt.asp`, parses the
rendered JavaScript ONU rows, and logs out.

Older exploratory LAN-PON probe:

```text
local_tools/probe_lanpon_info.py
```

That script probes `sta-LanPonInfo.asp` / `LanPonInfo.cgi` style pages from the
newer FTTR UI path. It was useful for discovering field names, but it was not
the reliable source for the slave OLT plan. Prefer `probe_olt80_onu.py` for
actual port-80 slave OLT validation.

## Useful Fields

From the slave OLT ONU/legacy data, the useful AP enrichment fields are:

```text
PONSN
OnuStatus
OptTxPower
OptRxPower
LastDownCause
```

These should fill existing AP optical sensors owned by the master entry:

```text
sensor.rltech_ap_<sn>_optical_tx_power
sensor.rltech_ap_<sn>_optical_rx_power
```

## Resolution Order

For AP optical sensors:

```text
1. Master :8080 AP detail/registerinfo optical data
2. Slave OLT :80 ONU optical data matched by PONSN/SN
3. Unknown
```

## Config Idea

Expose this as an optional advanced section on the master OLT entry:

```text
Slave OLT optical sources
```

Suggested helper text:

```text
Optional legacy OLT web interfaces used only to fill missing AP optical values
for APs connected behind downstream/slave OLTs.
```

Default should remain master-only. This keeps the public integration clean for
normal users and keeps the slave OLT behavior explicitly opt-in.

## Notes From Telnet Research

Telnet confirmed that the same optical data exists locally under tcapi nodes:

```sh
/userfs/bin/tcapi get SlaveMgr_Common maxPonClientNum
/userfs/bin/tcapi get LanPon_Subdevice_Entry0 PONSN
/userfs/bin/tcapi get LanPon_Subdevice_Entry0 OnuStatus
/userfs/bin/tcapi get LanPon_Subdevice_Entry0 OptTxPower
/userfs/bin/tcapi get LanPon_Subdevice_Entry0 OptRxPower
/userfs/bin/tcapi get LanPon_Subdevice_Entry0 LastDownCause
```

That is useful evidence for parser/source validation, but the cleaner Home
Assistant path should still prefer HTTP where possible. Telnet can stay a
research fallback unless HTTP proves unreliable.

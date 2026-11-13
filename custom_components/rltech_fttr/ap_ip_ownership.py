"""Track current AP management IP ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from ipaddress import ip_address
from typing import Mapping

from .models import RltechAp, RltechData


def normalize_ap_ip(value: str | None) -> str | None:
    """Return a stable AP IP value."""
    if not value or not (text := value.strip()):
        return None
    try:
        return str(ip_address(text))
    except ValueError:
        return text.lower()


@dataclass(frozen=True)
class ApIpClaim:
    """Latest accepted IP and online state for one AP."""

    mac: str
    ip: str | None
    online: bool | None
    observed_at: datetime
    source: str


@dataclass(frozen=True)
class ApIpConflict:
    """Multiple online APs claiming one management IP."""

    ip: str
    owner_mac: str
    claimant_macs: tuple[str, ...]


class ApIpOwnershipTracker:
    """Reconcile AP IP claims from HTTP inventory and MQTT lifecycle events."""

    def __init__(self) -> None:
        self._claims: dict[str, ApIpClaim] = {}
        self._owners: dict[str, str] = {}
        self._conflicts: dict[str, ApIpConflict] = {}
        self.revision = 0

    @property
    def conflicts(self) -> Mapping[str, ApIpConflict]:
        """Return current online IP conflicts."""
        return self._conflicts

    def claim_for(self, mac: str) -> ApIpClaim | None:
        """Return the latest accepted claim for one AP."""
        return self._claims.get(mac)

    def is_conflicted(self, mac: str) -> bool:
        """Return whether an AP participates in an active IP conflict."""
        return any(
            mac in conflict.claimant_macs
            for conflict in self._conflicts.values()
        )

    def observe_http_inventory(
        self,
        aps: Mapping[str, RltechAp],
        *,
        now: datetime,
        protected_fields: Mapping[str, set[str]] | None = None,
    ) -> None:
        """Accept online AP IP claims from one successful HTTP inventory poll."""
        before = self._state()
        protected_fields = protected_fields or {}
        for mac, ap in aps.items():
            old = self._claims.get(mac)
            protected = protected_fields.get(mac, set())

            if "online" in protected and old is not None:
                online = old.online
            else:
                online = ap.online

            accepted_ip = False
            current_ip = old.ip if old is not None else None
            if (
                "ip" not in protected
                and ap.online is True
                and (reported_ip := normalize_ap_ip(ap.ip)) is not None
            ):
                current_ip = reported_ip
                accepted_ip = True

            changed = (
                old is None
                or old.ip != current_ip
                or old.online != online
            )
            source = old.source if old is not None else "http"
            if accepted_ip and changed:
                source = "http"
            self._claims[mac] = ApIpClaim(
                mac=mac,
                ip=current_ip,
                online=online,
                observed_at=now if changed else old.observed_at,
                source=source,
            )

        self._recompute(aps)
        self._finish_update(before)

    def observe_mqtt_status(
        self,
        aps: Mapping[str, RltechAp],
        *,
        mac: str,
        online: bool,
        reported_ip: str | None,
        now: datetime,
    ) -> None:
        """Accept one known AP MQTT lifecycle report."""
        before = self._state()
        old = self._claims.get(mac)
        current_ip = old.ip if old is not None else None
        preferred_owner: tuple[str, str] | None = None
        if online and (mqtt_ip := normalize_ap_ip(reported_ip)) is not None:
            current_ip = mqtt_ip
            preferred_owner = (mqtt_ip, mac)
        self._claims[mac] = ApIpClaim(
            mac=mac,
            ip=current_ip,
            online=online,
            observed_at=now,
            source="mqtt",
        )
        self._recompute(aps, preferred_owner=preferred_owner)
        self._finish_update(before)

    def apply(self, data: RltechData) -> RltechData:
        """Apply unique current ownership to AP inventory rows."""
        assigned = {mac: ip for ip, mac in self._owners.items()}
        aps = data.aps
        for mac, ap in data.aps.items():
            current_ip = assigned.get(mac)
            if ap.ip == current_ip:
                continue
            if aps is data.aps:
                aps = dict(data.aps)
            aps[mac] = replace(ap, ip=current_ip)
        return data if aps is data.aps else replace(data, aps=aps)

    def _recompute(
        self,
        aps: Mapping[str, RltechAp],
        *,
        preferred_owner: tuple[str, str] | None = None,
    ) -> None:
        """Rebuild unique owners and active conflicts."""
        groups: dict[str, list[ApIpClaim]] = {}
        for claim in self._claims.values():
            if claim.ip is not None:
                groups.setdefault(claim.ip, []).append(claim)

        old_owners = self._owners
        owners: dict[str, str] = {}
        conflicts: dict[str, ApIpConflict] = {}
        claims_to_clear: set[str] = set()

        for ip, claims in groups.items():
            online = [claim for claim in claims if claim.online is True]
            if len(online) == 1:
                owner = online[0]
                owners[ip] = owner.mac
                claims_to_clear.update(
                    claim.mac for claim in claims if claim.mac != owner.mac
                )
                continue

            if len(online) > 1:
                preferred_mac = (
                    preferred_owner[1]
                    if preferred_owner is not None and preferred_owner[0] == ip
                    else None
                )
                if preferred_mac is not None and any(
                    claim.mac == preferred_mac for claim in online
                ):
                    owner_mac = preferred_mac
                elif (old_owner := old_owners.get(ip)) is not None and any(
                    claim.mac == old_owner for claim in online
                ):
                    owner_mac = old_owner
                else:
                    newest = max(claim.observed_at for claim in online)
                    tied = [
                        claim.mac for claim in online if claim.observed_at == newest
                    ]
                    owner_mac = min(
                        tied,
                        key=lambda mac: (
                            (aps.get(mac).sn if aps.get(mac) else "") or "",
                            mac,
                        ),
                    )
                owners[ip] = owner_mac
                conflicts[ip] = ApIpConflict(
                    ip=ip,
                    owner_mac=owner_mac,
                    claimant_macs=tuple(sorted(claim.mac for claim in online)),
                )
                continue

            if len(claims) == 1:
                owners[ip] = claims[0].mac
            else:
                claims_to_clear.update(claim.mac for claim in claims)

        for mac in claims_to_clear:
            claim = self._claims[mac]
            self._claims[mac] = replace(claim, ip=None)

        self._owners = owners
        self._conflicts = conflicts

    def _state(
        self,
    ) -> tuple[
        dict[str, ApIpClaim],
        dict[str, str],
        dict[str, ApIpConflict],
    ]:
        """Return a comparable copy of mutable tracker state."""
        return (dict(self._claims), dict(self._owners), dict(self._conflicts))

    def _finish_update(
        self,
        before: tuple[dict[str, ApIpClaim], dict[str, str], dict[str, ApIpConflict]],
    ) -> None:
        """Advance the revision only when ownership state changed."""
        if before != self._state():
            self.revision += 1

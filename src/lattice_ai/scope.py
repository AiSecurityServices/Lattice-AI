import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ScopePolicy:
    allow_domains: list[str] = field(default_factory=list)
    allow_ips: list[str] = field(default_factory=list)
    allow_cidrs: list[str] = field(default_factory=list)
    allow_ports: list[int] = field(default_factory=list)
    allow_url_prefixes: list[str] = field(default_factory=list)


def scope_policy_from_dict(data: dict | None) -> ScopePolicy:
    data = data or {}
    return ScopePolicy(
        allow_domains=[str(v) for v in data.get("allow_domains", [])],
        allow_ips=[str(v) for v in data.get("allow_ips", [])],
        allow_cidrs=[str(v) for v in data.get("allow_cidrs", [])],
        allow_ports=[int(v) for v in data.get("allow_ports", [])],
        allow_url_prefixes=[str(v) for v in data.get("allow_url_prefixes", [])],
    )


def _is_configured(policy: ScopePolicy) -> bool:
    return any(
        (
            policy.allow_domains,
            policy.allow_ips,
            policy.allow_cidrs,
            policy.allow_ports,
            policy.allow_url_prefixes,
        )
    )


def scope_configured(policy: ScopePolicy) -> bool:
    return _is_configured(policy)


def _domain_of_target(target: str) -> str:
    target = target.strip()
    if "://" in target:
        return (urlparse(target).hostname or "").lower()
    if "/" in target:
        return target.split("/", 1)[0].split(":")[0].lower()
    return target.split(":")[0].lower()


def _port_of_target(target: str) -> int | None:
    target = target.strip()
    parsed = urlparse(target) if "://" in target else urlparse("//" + target)
    try:
        return parsed.port
    except ValueError:
        return None


def _host_matches(policy: ScopePolicy, host: str) -> bool:
    host = (host or "").lower()
    if any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in policy.allow_domains):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if any(str(ip) == value for value in policy.allow_ips):
        return True
    return any(ip in ipaddress.ip_network(value, strict=False) for value in policy.allow_cidrs)


def evaluate_scope(policy: ScopePolicy, target: str) -> tuple[bool, str]:
    if not _is_configured(policy):
        return True, "scope not configured"

    target = (target or "").strip()
    host = _domain_of_target(target)
    if not host:
        return False, "target host could not be parsed"

    if not _host_matches(policy, host):
        return False, "target host is not in allowed scope"

    # Ports and URL prefixes are NOT authorization gates. They are operational
    # filters that narrow what a scanner should probe (see registry.run). A
    # host is authorized by domain suffix / IP / CIDR alone, so discovery of
    # subdomains, ports and paths is allowed inside the authorized boundary.
    return True, "target is in allowed scope"


# Restricted / reserved targets that should never be probed even if they fall
# inside an authorized domain or CIDR. Kept conservative: do NOT flag private
# or loopback ranges, which are legitimate in an authorized internal engagement.
_RESTRICTED_SUFFIXES = (".gov", ".mil", ".gouv.fr", ".mod.uk", ".int")

_RESTRICTED_NETWORKS = [
    "0.0.0.0/8",           # "this" network
    "100.64.0.0/10",       # carrier-grade NAT
    "192.0.0.0/24",        # IETF protocol assignments
    "192.0.2.0/24",        # documentation
    "198.51.100.0/24",     # documentation
    "203.0.113.0/24",      # documentation
    "224.0.0.0/4",         # multicast
    "240.0.0.0/4",         # reserved
    "255.255.255.255/32",  # broadcast
]


def is_restricted_target(target: str) -> bool:
    """Return True when the target is restricted public infrastructure or a
    reserved range that should not be used as a test target."""
    host = _domain_of_target(target)
    if not host:
        return False
    lowered = host.lower()
    if any(lowered.endswith(suffix) for suffix in _RESTRICTED_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(net, strict=False) for net in _RESTRICTED_NETWORKS)

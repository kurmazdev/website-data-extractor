"""SSRF protection lives at both URL and actual DNS connection boundaries."""

import ipaddress
import socket

from aiohttp.resolver import DefaultResolver
from yarl import URL

from .models import validate_url

DEMO_HOST = "demo.website-extractor.test"


class AccessError(Exception):
    pass


def public_ip(value):
    ip = ipaddress.ip_address(value.split("%")[0])
    # IPv6 transition mechanisms can embed private IPv4 destinations.
    if (
        not ip.is_global
        or ip.is_multicast
        or ip.is_reserved
        or (ip.version == 6 and ip.is_site_local)
        or (ip.version == 4 and ip in ipaddress.ip_network("192.0.0.0/24"))
        or str(ip) == "168.63.129.16"
        or (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo))
    ):
        raise AccessError(
            "Private, internal, reserved, and transition-network addresses are blocked."
        )


def check_url(url):
    try:
        validate_url(url)
        # Match the exact IDNA normalization used by aiohttp, before checking
        # literals: Unicode spellings can normalize directly to an IP address.
        host = URL(url).raw_host.rstrip(".")
    except ValueError as e:
        raise AccessError(str(e))
    if host == DEMO_HOST:
        return
    if (
        host.lower().rstrip(".") in ("localhost", "metadata.google.internal")
        or "%" in host
    ):
        raise AccessError("Internal hostnames are blocked.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # Some socket stacks accept short, octal, hexadecimal, or integer IPv4
        # literals even though ipaddress rejects those spellings.
        try:
            host = socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            return
    public_ip(host)


def origin(url):
    p = URL(url)
    return p.scheme, p.raw_host.rstrip("."), p.port


class PublicResolver(DefaultResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        addresses = await super().resolve(host, port, family)
        if not addresses:
            raise AccessError("The hostname did not resolve.")
        for address in addresses:
            public_ip(address["host"])
        return addresses

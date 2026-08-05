"""Tests for the shared SSRF perimeter.

Every case here is a real technique someone will point at a public endpoint.
These are the tests that matter most in the whole hub: they are what keeps a
new tool from re-opening egress.
"""

from __future__ import annotations

import socket

import pytest

from hirara_core.ssrf import BlockedURL, check_ip, resolve_target


def fake_resolver(*addresses: str):
    """Build a getaddrinfo stand-in that returns fixed addresses."""

    def _resolve(host, port, *args, **kwargs):
        out = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            out.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
        return out

    return _resolve


PUBLIC = fake_resolver("93.184.216.34")


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/win.ini",
        "gopher://example.com:70/_test",
        "ftp://example.com/secret.txt",
        "data:text/html,<h1>hi",
        "javascript:alert(1)",
    ],
)
def test_rejects_non_http_schemes(url):
    with pytest.raises(BlockedURL, match="scheme"):
        resolve_target(url, resolver=PUBLIC)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",          # loopback
        "0.0.0.0",            # unspecified
        "10.1.2.3",           # RFC1918
        "172.16.0.5",         # RFC1918
        "192.168.1.1",        # RFC1918
        "169.254.169.254",    # cloud metadata, the classic
        "100.64.0.1",         # CGNAT
        "198.18.0.1",         # benchmarking
        "::1",                # v6 loopback
        "fd00::1",            # v6 unique-local
        "fe80::1",            # v6 link-local
    ],
)
def test_rejects_internal_addresses(address):
    with pytest.raises(BlockedURL):
        resolve_target("https://internal.example/", resolver=fake_resolver(address))


@pytest.mark.parametrize(
    "address",
    [
        "::ffff:169.254.169.254",  # v4-mapped metadata address
        "::ffff:127.0.0.1",        # v4-mapped loopback
        "2002:a00:1::",            # 6to4 wrapping 10.0.0.1
    ],
)
def test_rejects_v6_wrapped_internal_addresses(address):
    with pytest.raises(BlockedURL):
        resolve_target("https://sneaky.example/", resolver=fake_resolver(address))


def test_rejects_when_any_resolved_address_is_internal():
    """One public answer must not launder a private one alongside it."""
    resolver = fake_resolver("93.184.216.34", "169.254.169.254")
    with pytest.raises(BlockedURL, match="169.254.169.254"):
        resolve_target("https://split.example/", resolver=resolver)


def test_rejects_credentials_in_url():
    with pytest.raises(BlockedURL, match="credentials"):
        resolve_target("https://user:pass@example.com/", resolver=PUBLIC)


@pytest.mark.parametrize("port", [22, 25, 3306, 6379, 9200, 11211])
def test_rejects_non_web_ports(port):
    with pytest.raises(BlockedURL, match="port"):
        resolve_target(f"https://example.com:{port}/", resolver=PUBLIC)


def test_allows_public_address_and_pins_the_ip():
    target = resolve_target("https://example.com/a?b=c", resolver=PUBLIC)
    assert target.ip == "93.184.216.34"
    assert target.host == "example.com"
    assert target.host_header == "example.com"


def test_escape_hatch_allows_private_addresses():
    target = resolve_target(
        "http://localhost:8080/",
        allow_private_ips=True,
        resolver=fake_resolver("127.0.0.1"),
    )
    assert target.ip == "127.0.0.1"


def test_check_ip_accepts_public_and_rejects_private():
    assert check_ip("93.184.216.34") is None
    assert check_ip("10.0.0.1") is not None
    assert check_ip("not-an-ip") is not None

"""Invalid proxy headers must not break authentication or rate limiting."""

import unittest
from types import SimpleNamespace

from starlette.requests import Request

from frigate.api.auth import get_remote_addr


class TestRemoteAddr(unittest.TestCase):
    def request(self, forwarded_for=None, trusted_proxies=None):
        return Request(
            {
                "type": "http",
                "client": ("192.0.2.10", 1234),
                "headers": (
                    [(b"x-forwarded-for", forwarded_for.encode())]
                    if forwarded_for is not None
                    else []
                ),
                "app": SimpleNamespace(
                    frigate_config=SimpleNamespace(
                        auth=SimpleNamespace(trusted_proxies=trusted_proxies or [])
                    )
                ),
            }
        )

    def test_missing_header_uses_direct_address(self):
        self.assertEqual(get_remote_addr(self.request()), "192.0.2.10")

    def test_invalid_network_is_skipped(self):
        self.assertEqual(
            get_remote_addr(self.request("198.51.100.20, 10.0.0.1", ["bad", "10.0.0.0/8"])),
            "198.51.100.20",
        )

    def test_invalid_hop_uses_direct_address(self):
        self.assertEqual(
            get_remote_addr(self.request("bad, 10.0.0.1", ["10.0.0.0/8"])),
            "192.0.2.10",
        )

    def test_empty_header_uses_direct_address(self):
        self.assertEqual(get_remote_addr(self.request("")), "192.0.2.10")

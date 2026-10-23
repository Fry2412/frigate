import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from portal_runner.http import PortalClient, PortalError


def test_json_request_never_follows_redirect_with_runner_credentials():
    forwarded = []

    class Destination(BaseHTTPRequestHandler):
        def do_GET(self):
            forwarded.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args):
            pass

    destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header(
                "Location", f"http://127.0.0.1:{destination.server_port}/capture"
            )
            self.end_headers()

        def log_message(self, *_args):
            pass

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    servers = (destination, redirect)
    threads = [threading.Thread(target=server.serve_forever) for server in servers]
    for thread in threads:
        thread.start()
    try:
        client = PortalClient(
            f"http://127.0.0.1:{redirect.server_port}", "private-runner-token"
        )
        with pytest.raises(PortalError, match="HTTP 302"):
            client.json("GET", "/claim")
        assert forwarded == []
    finally:
        for server, thread in zip(servers, threads, strict=True):
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

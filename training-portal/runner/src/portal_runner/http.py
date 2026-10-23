from __future__ import annotations

import http.client
import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class PortalError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward runner credentials to a redirect destination.
        return None


@dataclass
class PortalClient:
    base_url: str
    token: str
    timeout: float = 30

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, bytes, dict[str, str]]:
        request_headers = {"Authorization": f"Bearer {self.token}"}
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=request_headers, method=method
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=self.timeout) as response:
                status, payload, response_headers = (
                    response.status,
                    response.read(),
                    dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            payload = exc.read(4096)
            detail = payload.decode("utf-8", "replace")
            raise PortalError(
                f"portal returned HTTP {exc.code}: {detail[:500]}", exc.code
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PortalError(f"portal request failed: {exc}") from exc
        if status not in expected:
            raise PortalError(f"unexpected portal status {status}", status)
        return status, payload, response_headers

    def json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        _, payload, _ = self.request(
            method, path, json_body=json_body, headers=headers, expected=expected
        )
        return json.loads(payload) if payload else None

    def download_file(
        self,
        path: str,
        destination: Path,
        *,
        max_bytes: int,
        headers: dict[str, str] | None = None,
    ) -> int:
        connection, response = self._stream_request("GET", path, headers=headers)
        temp = destination.with_suffix(destination.suffix + ".part")
        try:
            if response.status != 200:
                raise PortalError(
                    f"portal returned HTTP {response.status}: {response.read(4096).decode('utf-8', 'replace')[:500]}",
                    response.status,
                )
            length = response.getheader("Content-Length")
            if length and int(length) > max_bytes:
                raise PortalError("dataset exceeds configured download limit")
            count = 0
            destination.parent.mkdir(parents=True, exist_ok=True)
            with temp.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > max_bytes:
                        raise PortalError("dataset exceeds configured download limit")
                    output.write(chunk)
            os.replace(temp, destination)
            return count
        finally:
            temp.unlink(missing_ok=True)
            connection.close()

    def upload_file(
        self,
        path: str,
        source: Path,
        *,
        max_bytes: int,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> None:
        size = source.stat().st_size
        if size > max_bytes:
            raise PortalError("artifact exceeds configured upload limit")
        request_headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Length": str(size),
        }
        if headers:
            request_headers.update(headers)
        connection, _ = self._stream_request(
            "PUT", path, headers=request_headers, send_body=source
        )
        try:
            response = connection.getresponse()
            if response.status not in expected:
                detail = response.read(4096).decode("utf-8", "replace")[:500]
                raise PortalError(
                    f"portal returned HTTP {response.status}: {detail}", response.status
                )
            response.read()
        finally:
            connection.close()

    def _stream_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        send_body: Path | None = None,
    ) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise PortalError("invalid portal URL")
        connection_type = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        options = {"timeout": self.timeout}
        if parsed.scheme == "https":
            options["context"] = ssl.create_default_context()
        connection = connection_type(parsed.hostname, parsed.port, **options)
        full_path = (parsed.path.rstrip("/") + path) or "/"
        try:
            connection.putrequest(method, full_path)
            base_headers = {"Authorization": f"Bearer {self.token}"}
            base_headers.update(headers or {})
            for key, value in base_headers.items():
                connection.putheader(key, value)
            connection.endheaders()
            if send_body is not None:
                with send_body.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        connection.send(chunk)
            return connection, connection.getresponse() if send_body is None else None
        except Exception:
            connection.close()
            raise

"""Camera names must not exempt unrelated API namespaces from admin checks."""

import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from starlette.requests import Request

from frigate.api.auth import require_admin_by_default


class TestAdminCameraNamespace(unittest.IsolatedAsyncioTestCase):
    def request(self, route_path, camera_name=None, role="viewer"):
        return Request(
            {
                "type": "http",
                "scheme": "http",
                "server": ("localhost", 5000),
                "path": "/faces/train",
                "headers": [(b"remote-role", role.encode())],
                "route": SimpleNamespace(path=route_path),
                "path_params": {"camera_name": camera_name} if camera_name else {},
                "app": SimpleNamespace(
                    frigate_config=SimpleNamespace(cameras={"faces": {}})
                ),
            }
        )

    async def test_unrelated_namespace_still_requires_admin(self):
        with self.assertRaises(HTTPException) as error:
            await require_admin_by_default()(self.request("/faces/train"))
        self.assertEqual(error.exception.status_code, 403)

    async def test_real_camera_route_remains_accessible(self):
        await require_admin_by_default()(
            self.request("/{camera_name}/latest.jpg", "faces")
        )

    async def test_admin_can_access_namespace(self):
        await require_admin_by_default()(self.request("/faces/train", role="admin"))

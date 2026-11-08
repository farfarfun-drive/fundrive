import os
import stat
from types import SimpleNamespace

import pytest

pytest.importorskip("aligo")
pytest.importorskip("fundrives.aliopen")

from fundrive.drives.alipan import drive_open  # noqa: E402


class FakeManage:
    instances = []
    token = "scanned-token"
    fail = False

    def __init__(self):
        self.auth = SimpleNamespace(
            get_access_token=lambda: {"refresh_token": self.token}
        )
        self.instances.append(self)

    def login(self, **kwargs):
        self.login_kwargs = kwargs
        if self.fail:
            raise RuntimeError("login failed")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    cache_file = tmp_path / ".farfarfun/fundrive/drives/aliopen/refresh_token"
    monkeypatch.setattr(drive_open, "CACHE_FILE", cache_file)
    monkeypatch.setattr(drive_open, "_AliOpenManage", FakeManage)
    monkeypatch.setattr(
        drive_open,
        "read_secret",
        lambda *path: None if path[-1] == "refresh_token" else path[-1],
    )
    FakeManage.instances.clear()
    FakeManage.token = "scanned-token"
    FakeManage.fail = False
    return cache_file


def test_login_caches_and_reuses_refresh_token(cache):
    assert drive_open.AliopenDrive().login()
    assert FakeManage.instances[-1].login_kwargs["refresh_token"] is None
    assert cache.read_text() == "scanned-token"
    assert stat.S_IMODE(os.stat(cache.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(cache).st_mode) == 0o600

    FakeManage.token = "rotated-token"
    second_drive = drive_open.AliopenDrive()
    assert second_drive.login()
    assert FakeManage.instances[-1].login_kwargs["refresh_token"] == "scanned-token"
    assert cache.read_text() == "rotated-token"

    FakeManage.token = "later-token"
    second_drive.drive.auth.get_access_token()
    assert cache.read_text() == "later-token"
    assert second_drive.drive.auth._refresh_token == "later-token"

    assert drive_open.AliopenDrive().login(
        refresh_token="explicit-token", is_resource=True
    )
    assert FakeManage.instances[-1].login_kwargs["refresh_token"] == "explicit-token"
    assert FakeManage.instances[-1].login_kwargs["use_resource"] is True


def test_failed_login_does_not_replace_cache(cache):
    cache.parent.mkdir(parents=True)
    cache.write_text("old-token")
    FakeManage.fail = True
    with pytest.raises(RuntimeError, match="login failed"):
        drive_open.AliopenDrive().login()
    assert cache.read_text() == "old-token"


def test_cache_write_failure_preserves_previous_token(cache, monkeypatch):
    cache.parent.mkdir(parents=True)
    cache.write_text("old-token")

    def fail_replace(*args):
        raise OSError("disk full")

    monkeypatch.setattr(drive_open.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        drive_open.AliopenDrive().login()
    assert cache.read_text() == "old-token"
    assert list(cache.parent.iterdir()) == [cache]


def test_upstream_relative_urls_have_one_separator(monkeypatch):
    calls = []

    def request(self, method, uri, *args, **kwargs):
        calls.append((method, uri))

    monkeypatch.setattr(drive_open.AliOpenManage, "_request", request)
    manage = drive_open._AliOpenManage()
    manage._request("post", "/adrive/v1.0/user/getDriveInfo")
    manage._request("get", "https://openapi.alipan.com/oauth/users/info")
    assert calls == [
        ("post", "adrive/v1.0/user/getDriveInfo"),
        ("get", "https://openapi.alipan.com/oauth/users/info"),
    ]

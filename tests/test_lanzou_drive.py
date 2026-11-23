"""LanZouDrive 单元测试（裸环境通过 monkeypatch 注入桩模块，零外部依赖）。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

LANZOU_DRIVE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "fundrive"
    / "drives"
    / "lanzou"
    / "drive.py"
)


@pytest.fixture
def lanzou_mod(monkeypatch):
    """直接加载 lanzou/drive.py，避免触发 snapshot 引入可选依赖 funfile。"""
    if "fundrives" not in sys.modules:
        ns = types.ModuleType("fundrives")
        ns.__path__ = []
        monkeypatch.setitem(sys.modules, "fundrives", ns)

    if "fundrives.lanzou" not in sys.modules:
        stub = types.ModuleType("fundrives.lanzou")

        class _StubLanZouCloud:
            MKDIR_ERROR = -1

        stub.LanZouCloud = _StubLanZouCloud
        utils = types.ModuleType("fundrives.lanzou.utils")
        utils.convert_file_size_to_int = lambda s: (
            int(s) if isinstance(s, int) else 1024
        )
        monkeypatch.setitem(sys.modules, "fundrives.lanzou", stub)
        monkeypatch.setitem(sys.modules, "fundrives.lanzou.utils", utils)

    spec = importlib.util.spec_from_file_location(
        "_test_lanzou_drive", LANZOU_DRIVE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drive(lanzou_mod):
    drive = lanzou_mod.LanZouDrive()
    sdk = Mock()
    drive.drive = sdk
    return drive, sdk


def test_parse_fid_url_pwd_and_login(lanzou_mod):
    drive, sdk = _drive(lanzou_mod)
    assert drive.parse_fid_url_pwd(123) == (123, None, None)
    assert drive.parse_fid_url_pwd("456") == ("456", None, None)
    assert drive.parse_fid_url_pwd("https://lz.test/s,abcd") == (
        None,
        "https://lz.test/s",
        "abcd",
    )

    sdk.login_by_cookie.return_value = 0
    assert drive.login(cookie={"ylogin": "u", "phpdisk_info": "p"}) is True
    sdk.login_by_cookie.return_value = -1
    assert drive.login(cookie={"ylogin": "u", "phpdisk_info": "p"}) is False


def test_mkdir_delete_move_and_lists(lanzou_mod):
    drive, sdk = _drive(lanzou_mod)

    sdk.mkdir.return_value = 999
    assert drive.mkdir(-1, "docs") == "999"

    sdk.mkdir.return_value = lanzou_mod.LanZouCloud.MKDIR_ERROR
    assert drive.mkdir(-1, "bad") == ""

    sdk.delete.return_value = 0
    assert drive.delete("999") is True
    sdk.move_file.return_value = 0
    assert drive.move("f1", "999") is True

    sdk.get_dir_list.return_value = (
        [SimpleNamespace(id="10", name="sub", desc="d")],
        0,
    )
    assert [(d["fid"], d["name"]) for d in drive.get_dir_list(-1)] == [("10", "sub")]

    sdk.get_file_list.return_value = [
        SimpleNamespace(id="20", name="a.txt", time="2026-01-01")
    ]
    sdk.get_folder_info_by_url.return_value = SimpleNamespace(
        files=[
            SimpleNamespace(
                id="21",
                name="shared.zip",
                time="2026-01-02",
                size=2048,
                url="https://lz.test/f21",
                pwd="pw",
            )
        ]
    )
    files = drive.get_file_list(10, url="https://lz.test/dir", pwd="pw")
    assert [(f["fid"], f["name"]) for f in files] == [
        ("20", "a.txt"),
        ("21", "shared.zip"),
    ]


def test_get_file_and_dir_info_fallback_to_url(lanzou_mod):
    drive, sdk = _drive(lanzou_mod)
    sdk.get_file_info_by_id.return_value = None
    sdk.get_file_info_by_url.return_value = SimpleNamespace(
        durl="dl-1",
        name="a.bin",
        desc="",
        time="now",
        size=512,
        url="https://lz.test/a",
        pwd="",
    )
    info = drive.get_file_info(fid="1", url="https://lz.test/a")
    assert info is not None and info["fid"] == "dl-1" and info["size"] == 512

    sdk.get_folder_info_by_id.return_value = SimpleNamespace(
        folder=SimpleNamespace(
            id="10", name="docs", desc="", time="now", url="https://lz.test/d"
        )
    )
    dinfo = drive.get_dir_info(fid="10")
    assert dinfo is not None and dinfo["fid"] == "10" and dinfo["name"] == "docs"

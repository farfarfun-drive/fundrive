"""AliopenDrive 单元测试（裸环境通过 monkeypatch 注入桩模块，零外部依赖）。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from unittest.mock import Mock

import pytest

from fundrive.core.exceptions import FunDriveError

DRIVE_OPEN_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "fundrive"
    / "drives"
    / "alipan"
    / "drive_open.py"
)


@pytest.fixture
def aliopen_mod(monkeypatch):
    """直接加载 drive_open.py，避免触发 alipan/__init__.py 引入可选依赖 aligo。"""
    if "fundrives" not in sys.modules:
        ns = types.ModuleType("fundrives")
        ns.__path__ = []
        monkeypatch.setitem(sys.modules, "fundrives", ns)

    if "fundrives.aliopen" not in sys.modules:
        stub = types.ModuleType("fundrives.aliopen")

        class _StubAliOpenManage:
            def _request(self, method, uri, *args, **kwargs):
                return {"method": method, "uri": uri}

        stub.AliOpenManage = _StubAliOpenManage
        monkeypatch.setitem(sys.modules, "fundrives.aliopen", stub)

    spec = importlib.util.spec_from_file_location(
        "_test_aliopen_drive_open", DRIVE_OPEN_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drive(aliopen_mod):
    drive = aliopen_mod.AliopenDrive()
    sdk = Mock()
    drive.drive = sdk
    return drive, sdk


def test_get_file_list_paginates_all_markers(aliopen_mod):
    drive, sdk = _drive(aliopen_mod)
    sdk.get_file_list.side_effect = [
        {
            "items": [
                {"file_id": "f1", "name": "a.txt", "type": "file", "size": 10},
            ],
            "next_marker": "m2",
        },
        {
            "items": [
                {"file_id": "f2", "name": "b.txt", "type": "file", "size": 20},
            ],
            "next_marker": "",
        },
    ]

    files = drive.get_file_list("root")
    assert [(f["fid"], f["name"], f["size"], f["isfile"]) for f in files] == [
        ("f1", "a.txt", 10, True),
        ("f2", "b.txt", 20, True),
    ]
    assert sdk.get_file_list.call_count == 2
    assert "marker" not in sdk.get_file_list.call_args_list[0].kwargs
    assert sdk.get_file_list.call_args_list[1].kwargs["marker"] == "m2"


def test_get_dir_list_handles_missing_size_and_paginates(aliopen_mod):
    drive, sdk = _drive(aliopen_mod)
    sdk.get_file_list.side_effect = [
        {
            "items": [{"file_id": "d1", "name": "docs", "type": "folder"}],
            "next_marker": "m2",
        },
        {
            "items": [{"file_id": "d2", "name": "pics", "type": "folder"}],
            "next_marker": None,
        },
    ]

    dirs = drive.get_dir_list("root")
    assert [(d["fid"], d["name"], d["isdir"], d["size"]) for d in dirs] == [
        ("d1", "docs", True, None),
        ("d2", "pics", True, None),
    ]


def test_get_file_list_raises_on_stalled_marker_or_invalid_response(aliopen_mod):
    drive, sdk = _drive(aliopen_mod)
    sdk.get_file_list.side_effect = [
        {
            "items": [{"file_id": "f1", "name": "a.txt", "type": "file"}],
            "next_marker": "m1",
        },
        {
            "items": [{"file_id": "f1", "name": "a.txt", "type": "file"}],
            "next_marker": "m1",
        },
    ]
    with pytest.raises(FunDriveError, match="next_marker"):
        drive.get_file_list("root")

    sdk.get_file_list.side_effect = [{"unexpected": True}]
    with pytest.raises(FunDriveError, match="items"):
        drive.get_file_list("root")


def test_get_info_and_exist_and_mkdir(aliopen_mod):
    drive, sdk = _drive(aliopen_mod)

    sdk.get_file_details.return_value = {"code": "NotFound.File"}
    assert drive.exist("missing") is False
    assert drive.get_file_info("missing") is None
    assert drive.get_dir_info("missing") is None

    sdk.get_file_details.return_value = {
        "file_id": "d1",
        "name": "docs",
        "type": "folder",
    }
    assert drive.exist("d1") is True
    assert drive.get_file_info("d1") is None
    info = drive.get_dir_info("d1")
    assert info is not None and info["fid"] == "d1" and info["isdir"] is True

    sdk.get_file_details.return_value = {
        "file_id": "f1",
        "name": "a.txt",
        "type": "file",
        "size": 99,
    }
    assert drive.get_dir_info("f1") is None
    finfo = drive.get_file_info("f1")
    assert finfo is not None and finfo["size"] == 99 and finfo["isfile"] is True

    sdk.get_file_list.return_value = {"items": [], "next_marker": ""}
    sdk.create_file.return_value = {"file_id": "new-dir"}
    assert drive.mkdir("root", "sub") == "new-dir"

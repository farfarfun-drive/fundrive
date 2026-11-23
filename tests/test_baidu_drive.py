"""BaiDuDrive 单元测试（裸环境通过 monkeypatch 注入桩模块，零外部依赖）。"""

from __future__ import annotations

import importlib
import sys
import types
from dataclasses import asdict, dataclass
from unittest.mock import Mock

import pytest

from fundrive.core.exceptions import FunDriveError


@dataclass
class _FakePcsFile:
    path: str
    size: int = 0
    is_dir: bool = False
    is_file: bool = True

    def _asdict(self):
        return asdict(self)


@pytest.fixture
def baidu_mod(monkeypatch):
    """隔离加载 fundrive.drives.baidu.drive，不污染全局 sys.modules。"""
    monkeypatch.delitem(sys.modules, "fundrive.drives.baidu.drive", raising=False)
    if "fundrives" not in sys.modules:
        ns = types.ModuleType("fundrives")
        ns.__path__ = []
        monkeypatch.setitem(sys.modules, "fundrives", ns)

    if "fundrives.baidu" not in sys.modules:
        stub = types.ModuleType("fundrives.baidu")
        stub.BaiduPCSApi = Mock()
        stub.PcsFile = _FakePcsFile
        monkeypatch.setitem(sys.modules, "fundrives.baidu", stub)

    mod = importlib.import_module("fundrive.drives.baidu.drive")
    yield mod
    monkeypatch.delitem(sys.modules, "fundrive.drives.baidu.drive", raising=False)


def _drive(baidu_mod):
    drive = baidu_mod.BaiDuDrive()
    sdk = Mock()
    sdk.bduss = "b"
    sdk.ptoken = "p"
    drive.drive = sdk
    return drive, sdk


def test_mkdir_handles_root_slash_existing_and_failure(baidu_mod):
    drive, sdk = _drive(baidu_mod)
    sdk.list.return_value = []

    assert drive.mkdir("/", "docs") == "/docs"
    sdk.makedir.assert_called_once_with("/docs")

    sdk.list.return_value = [_FakePcsFile(path="/docs", is_dir=True, is_file=False)]
    assert drive.mkdir("/", "docs") == "/docs"
    assert sdk.makedir.call_count == 1

    sdk.list.return_value = []
    sdk.makedir.side_effect = RuntimeError("quota")
    with pytest.raises(FunDriveError, match="/work/sub"):
        drive.mkdir("/work", "sub")


def test_list_and_info_handle_empty_meta(baidu_mod):
    drive, sdk = _drive(baidu_mod)
    sdk.list.return_value = [
        _FakePcsFile(path="/work/sub", size=0, is_dir=True, is_file=False),
        _FakePcsFile(path="/work/a.txt", size=42, is_dir=False, is_file=True),
    ]

    files = drive.get_file_list("/work")
    dirs = drive.get_dir_list("/work")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("/work/a.txt", "a.txt", 42)
    ]
    assert [(d["fid"], d["name"]) for d in dirs] == [("/work/sub", "sub")]

    sdk.is_file.return_value = True
    sdk.meta.return_value = []
    assert drive.get_file_info("/work/missing.txt") is None

    sdk.is_dir.return_value = True
    sdk.meta.return_value = [_FakePcsFile(path="/work/sub", is_dir=True, is_file=False)]
    assert drive.get_dir_info("/work/sub")["name"] == "sub"


def test_download_file_resolves_path_without_save_dir_crash(
    baidu_mod, monkeypatch, tmp_path
):
    drive, sdk = _drive(baidu_mod)
    sdk.download_link.return_value = "https://pcs.test/file"
    captured = {}

    def fake_download(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)

    monkeypatch.setattr(baidu_mod, "download", fake_download)

    out_path = str(tmp_path / "out.bin")
    assert drive.download_file("/work/a.txt", filepath=out_path, overwrite=True) is True
    assert captured["filepath"] == out_path
    assert captured["overwrite"] is True

    assert drive.download_file("/work/a.txt", save_dir=str(tmp_path)) is True
    assert captured["filepath"] == str(tmp_path / "a.txt")

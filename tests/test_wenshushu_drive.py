"""WenshushuDrive 单元测试（裸环境通过 monkeypatch 注入桩模块，零外部依赖）。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from unittest.mock import Mock

import pytest

WENSHUSHU_DRIVE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "fundrive"
    / "drives"
    / "wenshushu"
    / "drive.py"
)


@pytest.fixture
def wenshushu_mod(monkeypatch):
    if "base58" not in sys.modules:
        b58 = types.ModuleType("base58")
        b58.b58encode = lambda data: data
        b58.b58decode = lambda data: data
        monkeypatch.setitem(sys.modules, "base58", b58)

    if "Cryptodome" not in sys.modules:
        crypto = types.ModuleType("Cryptodome")
        crypto.__path__ = []
        cipher = types.ModuleType("Cryptodome.Cipher")
        cipher.__path__ = []
        des = types.ModuleType("Cryptodome.Cipher.DES")
        des.MODE_CBC = 2
        des.new = Mock()
        util = types.ModuleType("Cryptodome.Util")
        util.__path__ = []
        padding = types.ModuleType("Cryptodome.Util.Padding")
        padding.pad = lambda data, bs: data
        padding.unpad = lambda data, bs: data
        monkeypatch.setitem(sys.modules, "Cryptodome", crypto)
        monkeypatch.setitem(sys.modules, "Cryptodome.Cipher", cipher)
        monkeypatch.setitem(sys.modules, "Cryptodome.Cipher.DES", des)
        monkeypatch.setitem(sys.modules, "Cryptodome.Util", util)
        monkeypatch.setitem(sys.modules, "Cryptodome.Util.Padding", padding)

    spec = importlib.util.spec_from_file_location(
        "_test_wenshushu_drive", WENSHUSHU_DRIVE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wenshushu_uploaded_files_exist_and_unsupported_dir_ops(wenshushu_mod):
    drive = wenshushu_mod.WenShuShuDrive()
    drive.session = Mock()
    drive.uploaded_files["f-1"] = {
        "name": "demo.zip",
        "size": 4096,
        "upload_time": "2026-01-01",
        "share_url": "https://www.wenshushu.cn/f/1234567890abcdef",
        "mgr_url": "",
    }

    assert drive.exist("f-1") is True
    assert drive.exist("missing") is False
    assert drive.mkdir("/", "sub") == ""
    assert drive.delete("f-1") is False
    assert drive.get_dir_list("/") == []

    files = drive.get_file_list("/")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("f-1", "demo.zip", 4096)
    ]
    info = drive.get_file_info("f-1")
    assert info is not None and info["name"] == "demo.zip"

    # 校验分享链接存在性检查（16 位 token）
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"code": 0}
    drive.session.post.return_value = resp
    assert drive.exist("https://www.wenshushu.cn/f/1234567890abcdef") is True

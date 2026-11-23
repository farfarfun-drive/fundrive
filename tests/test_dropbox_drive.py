"""DropboxDrive 单元测试（裸环境通过 monkeypatch 注入桩模块，零外部依赖）。"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

DROPBOX_DRIVE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "fundrive"
    / "drives"
    / "dropbox"
    / "drive.py"
)


@dataclass
class _FileMetadata:
    path_display: str
    name: str
    size: int = 0
    server_modified: datetime | None = None
    content_hash: str = ""


@dataclass
class _FolderMetadata:
    path_display: str
    name: str


class _ApiError(Exception):
    def __init__(self, error=None):
        super().__init__("api error")
        self.error = error


class _AuthError(Exception):
    pass


@pytest.fixture
def dropbox_mod(monkeypatch):
    if "dropbox" not in sys.modules:
        dbx = types.ModuleType("dropbox")
        dbx.__path__ = []
        dbx.Dropbox = Mock()
        files_mod = types.ModuleType("dropbox.files")
        files_mod.FileMetadata = _FileMetadata
        files_mod.FolderMetadata = _FolderMetadata
        files_mod.WriteMode = SimpleNamespace(overwrite="overwrite", add="add")
        exc_mod = types.ModuleType("dropbox.exceptions")
        exc_mod.ApiError = _ApiError
        exc_mod.AuthError = _AuthError
        dbx.files = files_mod
        dbx.exceptions = exc_mod
        monkeypatch.setitem(sys.modules, "dropbox", dbx)
        monkeypatch.setitem(sys.modules, "dropbox.files", files_mod)
        monkeypatch.setitem(sys.modules, "dropbox.exceptions", exc_mod)

    spec = importlib.util.spec_from_file_location(
        "_test_dropbox_drive", DROPBOX_DRIVE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drive(dropbox_mod):
    drive = dropbox_mod.DropboxDrive(access_token="tok")
    drive.client = Mock()
    return drive


def test_get_file_and_dir_list_paginate_and_guard_stalled_cursor(dropbox_mod):
    drive = _drive(dropbox_mod)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    f_cls = dropbox_mod.dropbox.files.FileMetadata
    d_cls = dropbox_mod.dropbox.files.FolderMetadata

    drive.client.files_list_folder.return_value = SimpleNamespace(
        entries=[
            f_cls(path_display="/a.txt", name="a.txt", size=10, server_modified=now),
            d_cls(path_display="/docs", name="docs"),
        ],
        has_more=True,
        cursor="c1",
    )
    drive.client.files_list_folder_continue.return_value = SimpleNamespace(
        entries=[
            f_cls(path_display="/b.txt", name="b.txt", size=20, server_modified=now),
            d_cls(path_display="/pics", name="pics"),
        ],
        has_more=False,
        cursor="c2",
    )

    files = drive.get_file_list("/")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("/a.txt", "a.txt", 10),
        ("/b.txt", "b.txt", 20),
    ]
    dirs = drive.get_dir_list("/")
    assert [(d["fid"], d["name"]) for d in dirs] == [
        ("/docs", "docs"),
        ("/pics", "pics"),
    ]

    # 游标停滞时不死循环且不返回截断列表
    drive.client.files_list_folder_continue.return_value = SimpleNamespace(
        entries=[], has_more=True, cursor="c1"
    )
    assert drive.get_file_list("/") == []


def test_get_info_checks_metadata_type(dropbox_mod):
    drive = _drive(dropbox_mod)
    f_cls = dropbox_mod.dropbox.files.FileMetadata
    d_cls = dropbox_mod.dropbox.files.FolderMetadata

    drive.client.files_get_metadata.return_value = f_cls(
        path_display="/a.txt", name="a.txt", size=5
    )
    assert drive.get_file_info("/a.txt")["size"] == 5
    assert drive.get_dir_info("/a.txt") is None

    drive.client.files_get_metadata.return_value = d_cls(
        path_display="/docs", name="docs"
    )
    assert drive.get_dir_info("/docs")["name"] == "docs"
    assert drive.get_file_info("/docs") is None

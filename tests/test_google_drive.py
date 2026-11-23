"""GoogleDrive 单元测试（裸环境通过 monkeypatch 注入桩模块，零外部依赖）。"""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


class _FakeHttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.resp = SimpleNamespace(status=status)


@pytest.fixture
def google_mod(monkeypatch):
    """隔离加载 fundrive.drives.google.drive，不污染全局 sys.modules。"""
    monkeypatch.delitem(sys.modules, "fundrive.drives.google.drive", raising=False)
    stub_names = [
        "google",
        "google.auth",
        "google.auth.transport",
        "google.auth.transport.requests",
        "google.oauth2",
        "google.oauth2.credentials",
        "google_auth_oauthlib",
        "google_auth_oauthlib.flow",
        "googleapiclient",
        "googleapiclient.discovery",
        "googleapiclient.errors",
        "googleapiclient.http",
    ]
    if "googleapiclient" not in sys.modules:
        for mod_name in stub_names:
            if mod_name not in sys.modules:
                m = types.ModuleType(mod_name)
                if "." not in mod_name or mod_name in (
                    "google.auth",
                    "google.auth.transport",
                    "google.oauth2",
                ):
                    m.__path__ = []
                monkeypatch.setitem(sys.modules, mod_name, m)
        sys.modules["google.auth.transport.requests"].Request = Mock()
        sys.modules["google.oauth2.credentials"].Credentials = Mock()
        sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = Mock()
        sys.modules["googleapiclient.discovery"].build = Mock()
        sys.modules["googleapiclient.errors"].HttpError = _FakeHttpError
        sys.modules["googleapiclient.http"].MediaFileUpload = Mock()
        sys.modules["googleapiclient.http"].MediaIoBaseDownload = Mock()

    mod = importlib.import_module("fundrive.drives.google.drive")
    yield mod
    monkeypatch.delitem(sys.modules, "fundrive.drives.google.drive", raising=False)


def _drive(google_mod):
    drive = google_mod.GoogleDrive(credentials_file="cred.json")
    service = Mock()
    drive.service = service
    return drive, service


def test_get_file_and_dir_list_paginate_all_next_page_tokens(google_mod):
    drive, service = _drive(google_mod)
    files_api = service.files.return_value

    page1 = Mock()
    page1.execute.return_value = {
        "files": [{"id": "f1", "name": "a.txt", "size": "12"}],
        "nextPageToken": "tok-2",
    }
    page2 = Mock()
    page2.execute.return_value = {
        "files": [{"id": "f2", "name": "b.txt", "size": "34"}],
    }
    files_api.list.side_effect = [page1, page2]

    files = drive.get_file_list("root")
    assert [(f["fid"], f["name"], f["size"], f["isfile"]) for f in files] == [
        ("f1", "a.txt", 12, True),
        ("f2", "b.txt", 34, True),
    ]
    assert files_api.list.call_count == 2
    assert "pageToken" not in files_api.list.call_args_list[0].kwargs
    assert files_api.list.call_args_list[1].kwargs["pageToken"] == "tok-2"

    d1 = Mock()
    d1.execute.return_value = {
        "files": [{"id": "d1", "name": "sub1"}],
        "nextPageToken": "dtok-2",
    }
    d2 = Mock()
    d2.execute.return_value = {
        "files": [{"id": "d2", "name": "sub2"}],
    }
    files_api.list.side_effect = [d1, d2]

    dirs = drive.get_dir_list("root")
    assert [(d["fid"], d["name"], d["isdir"]) for d in dirs] == [
        ("d1", "sub1", True),
        ("d2", "sub2", True),
    ]


def test_get_file_list_stops_safely_on_stalled_page_token(google_mod):
    drive, service = _drive(google_mod)
    files_api = service.files.return_value
    p = Mock()
    p.execute.return_value = {
        "files": [{"id": "f1", "name": "a.txt", "size": "1"}],
        "nextPageToken": "same-tok",
    }
    files_api.list.side_effect = [p, p]
    # 分页停滞时不得死循环，也不得返回截断结果
    assert drive.get_file_list("root") == []


def test_exist_mkdir_and_delete(google_mod):
    drive, service = _drive(google_mod)
    files_api = service.files.return_value

    files_api.get.return_value.execute.return_value = {"id": "f1"}
    assert drive.exist("f1") is True

    files_api.get.return_value.execute.side_effect = google_mod.HttpError(404)
    assert drive.exist("missing") is False

    files_api.list.return_value.execute.return_value = {"files": []}
    files_api.create.return_value.execute.return_value = {"id": "new-folder"}
    assert drive.mkdir("root", "docs") == "new-folder"

    files_api.delete.return_value.execute.return_value = None
    assert drive.delete("f1") is True

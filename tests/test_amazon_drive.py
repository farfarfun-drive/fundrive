"""Amazon S3Drive 单元测试（裸环境通过 monkeypatch 注入桩模块，零外部依赖）。"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest


class _FakeClientError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeNoCredentialsError(Exception):
    pass


@pytest.fixture
def s3_mod(monkeypatch):
    """隔离加载 fundrive.drives.amazon.drive，不污染全局 sys.modules。"""
    monkeypatch.delitem(sys.modules, "fundrive.drives.amazon.drive", raising=False)
    if "boto3" not in sys.modules:
        boto3_stub = types.ModuleType("boto3")
        boto3_stub.Session = Mock()
        botocore_stub = types.ModuleType("botocore")
        botocore_stub.__path__ = []
        exc_stub = types.ModuleType("botocore.exceptions")
        exc_stub.ClientError = _FakeClientError
        exc_stub.NoCredentialsError = _FakeNoCredentialsError
        monkeypatch.setitem(sys.modules, "boto3", boto3_stub)
        monkeypatch.setitem(sys.modules, "botocore", botocore_stub)
        monkeypatch.setitem(sys.modules, "botocore.exceptions", exc_stub)

    mod = importlib.import_module("fundrive.drives.amazon.drive")
    yield mod
    monkeypatch.delitem(sys.modules, "fundrive.drives.amazon.drive", raising=False)


def _drive(s3_mod):
    drive = s3_mod.S3Drive(
        access_key_id="ak",
        secret_access_key="sk",
        region_name="us-east-1",
        bucket_name="my-bucket",
    )
    drive.s3_client = Mock()
    return drive


def test_get_file_and_dir_list_paginate_all_pages(s3_mod):
    drive = _drive(s3_mod)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    paginator = Mock()
    paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "docs/", "Size": 0, "LastModified": now, "ETag": '"0"'},
                {"Key": "docs/a.txt", "Size": 10, "LastModified": now, "ETag": '"e1"'},
            ],
            "CommonPrefixes": [{"Prefix": "docs/sub1/"}],
        },
        {
            "Contents": [
                {"Key": "docs/b.txt", "Size": 20, "LastModified": now, "ETag": '"e2"'},
            ],
            "CommonPrefixes": [{"Prefix": "docs/sub2/"}],
        },
    ]
    drive.s3_client.get_paginator.return_value = paginator

    files = drive.get_file_list("docs")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("docs/a.txt", "a.txt", 10),
        ("docs/b.txt", "b.txt", 20),
    ]

    dirs = drive.get_dir_list("docs")
    assert [(d["fid"], d["name"]) for d in dirs] == [
        ("docs/sub1/", "sub1"),
        ("docs/sub2/", "sub2"),
    ]


def test_exist_mkdir_and_delete_prefix_without_trailing_slash(s3_mod):
    drive = _drive(s3_mod)

    drive.s3_client.head_object.return_value = {}
    assert drive.exist("docs/a.txt") is True

    drive.s3_client.head_object.side_effect = s3_mod.ClientError("404")
    assert drive.exist("docs/missing.txt") is False

    # mkdir 创建目录标记对象
    assert drive.mkdir("docs", "newdir") == "docs/newdir/"
    drive.s3_client.put_object.assert_called_once()

    # delete("docs/sub") 无尾斜杠但命中前缀，批量删除
    drive.s3_client.list_objects_v2.return_value = {"KeyCount": 1}
    paginator = Mock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "docs/sub/1.txt"}, {"Key": "docs/sub/2.txt"}]}
    ]
    drive.s3_client.get_paginator.return_value = paginator
    drive.s3_client.delete_objects.return_value = {
        "Deleted": [{"Key": "docs/sub/1.txt"}, {"Key": "docs/sub/2.txt"}]
    }
    assert drive.delete("docs/sub") is True

    # 删除不存在的目标返回 False
    drive.s3_client.list_objects_v2.return_value = {"KeyCount": 0}
    assert drive.delete("docs/nope") is False

"""GiteeDrive 单元测试（纯 requests mock，裸环境直接运行）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.gitee import GiteeDrive


def _resp(status: int, payload=None):
    r = Mock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    return r


def _drive():
    drive = GiteeDrive(access_token="tok", repo="owner/repo", branch="master")
    drive.session = Mock()
    return drive


def test_list_handles_files_dirs_and_single_file_dict():
    drive = _drive()
    drive.session.get.return_value = _resp(
        200,
        [
            {
                "type": "file",
                "path": "docs/a.txt",
                "name": "a.txt",
                "size": 12,
                "sha": "s1",
                "download_url": "https://raw/a.txt",
                "html_url": "https://html/a.txt",
            },
            {
                "type": "dir",
                "path": "docs/sub",
                "name": "sub",
                "sha": "s2",
                "html_url": "https://html/sub",
            },
        ],
    )
    assert [(f["fid"], f["name"], f["size"]) for f in drive.get_file_list("docs")] == [
        ("docs/a.txt", "a.txt", 12)
    ]
    assert [(d["fid"], d["name"]) for d in drive.get_dir_list("docs")] == [
        ("docs/sub", "sub")
    ]

    drive.session.get.return_value = _resp(200, {"type": "file", "path": "a.txt"})
    assert drive.get_file_list("a.txt") == []
    assert drive.get_dir_list("a.txt") == []


def test_exist_and_delete():
    drive = _drive()
    drive.session.get.return_value = _resp(200)
    assert drive.exist("docs/a.txt") is True
    drive.session.get.return_value = _resp(404)
    assert drive.exist("missing") is False

    drive.session.get.return_value = _resp(
        200,
        {
            "type": "file",
            "path": "docs/a.txt",
            "name": "a.txt",
            "size": 12,
            "sha": "sha-1",
            "download_url": "u",
            "html_url": "h",
        },
    )
    drive.session.delete.return_value = _resp(200)
    assert drive.delete("docs/a.txt") is True

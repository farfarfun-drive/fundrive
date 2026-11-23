"""TSingHuaDrive 单元测试（纯 requests mock，裸环境直接运行）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.tsinghua import TSingHuaDrive


def _resp(status: int, payload=None):
    r = Mock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    return r


def test_tsinghua_list_exist_info_and_readonly_ops():
    drive = TSingHuaDrive(share_key="share-abc")
    drive.session = Mock()

    drive.session.get.return_value = _resp(
        200,
        {
            "dirent_list": [
                {
                    "is_dir": False,
                    "file_path": "/docs/a.pdf",
                    "file_name": "a.pdf",
                    "size": 1024,
                },
                {
                    "is_dir": True,
                    "folder_path": "/docs/sub",
                    "folder_name": "sub",
                },
            ]
        },
    )

    assert drive.exist("/docs") is True
    assert drive.mkdir("/docs", "new") == ""
    assert drive.delete("/docs/a.pdf") is False

    files = drive.get_file_list("/docs")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("/docs/a.pdf", "a.pdf", 1024)
    ]
    dirs = drive.get_dir_list("/docs")
    assert [(d["fid"], d["name"]) for d in dirs] == [("/docs/sub", "sub")]

    info = drive.get_file_info("/docs/a.pdf")
    assert info is not None and info["name"] == "a.pdf"

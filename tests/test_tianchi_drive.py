"""TianChiDrive 单元测试（纯 requests mock，裸环境直接运行）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.tianchi import drive as tianchi_drive


def _resp(status: int, payload=None):
    r = Mock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    return r


def test_tianchi_list_exist_and_readonly_ops(monkeypatch):
    drive = tianchi_drive.TianChiDrive(
        tc_cookie="tc", csrf_cookie="csrf", csrf_token="tok"
    )
    payload = {
        "success": True,
        "data": {
            "datalabFile": [
                {"id": 1, "filePath": "data/train.csv", "size": 512},
                {"id": 2, "filePath": "data/test.csv", "size": 256},
            ]
        },
    }
    monkeypatch.setattr(
        tianchi_drive.requests, "post", lambda *a, **kw: _resp(200, payload)
    )

    assert drive.exist("100") is True
    assert drive.mkdir("100", "sub") == ""
    assert drive.delete("1") is False
    assert drive.get_file_list("root") == []

    files = drive.get_file_list("100")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("1", "train.csv", 512),
        ("2", "test.csv", 256),
    ]
    dirs = drive.get_dir_list("100")
    assert [(d["fid"], d["name"]) for d in dirs] == [("data", "data")]

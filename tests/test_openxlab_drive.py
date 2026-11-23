"""OpenXLabDrive 单元测试（纯 requests mock，裸环境直接运行）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.openxlab import drive as openxlab_drive


def _resp(status: int, payload=None):
    r = Mock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    return r


def test_openxlab_list_exist_and_readonly_ops(monkeypatch):
    drive = openxlab_drive.OpenXLabDrive(opendatalab_session="s", ssouid="u")

    monkeypatch.setattr(openxlab_drive.requests, "get", lambda *a, **kw: _resp(200))
    assert drive.exist("org/ds") is True
    assert drive.mkdir("org/ds", "sub") == ""
    assert drive.delete("org/ds/a.txt") is False

    payload = {
        "data": {
            "list": [
                {
                    "type": "file",
                    "path": "train/a.csv",
                    "size": 128,
                    "dataset_id": "ds-1",
                },
                {
                    "type": "file",
                    "path": "train/b.csv",
                    "size": 256,
                    "dataset_id": "ds-1",
                },
            ]
        }
    }
    monkeypatch.setattr(
        openxlab_drive.requests, "get", lambda *a, **kw: _resp(200, payload)
    )
    assert drive.get_file_list("root") == []
    files = drive.get_file_list("org/ds")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("train/a.csv", "a.csv", 128),
        ("train/b.csv", "b.csv", 256),
    ]
    dirs = drive.get_dir_list("org/ds")
    assert [(d["fid"], d["name"]) for d in dirs] == [("train", "train")]

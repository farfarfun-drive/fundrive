"""OneDrive 单元测试（仅依赖核心 requests，裸环境直接运行）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.onedrive import OneDrive


def _resp(status: int, payload=None, text: str = ""):
    r = Mock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload if payload is not None else {}
    return r


def _drive():
    drive = OneDrive(
        client_id="cid",
        client_secret="sec",
        access_token="tok",
        refresh_token="rtok",
    )
    drive.session = Mock()
    return drive


def test_get_file_and_dir_list_paginate_odata_next_link_and_forward_timeout():
    drive = _drive()
    next_link = "https://graph.microsoft.com/v1.0/me/drive/root/children?$skiptoken=2"
    drive.session.get.side_effect = [
        _resp(
            200,
            {
                "value": [
                    {"id": "f1", "name": "a.txt", "size": 10, "file": {}},
                    {"id": "d1", "name": "docs", "size": 0, "folder": {}},
                ],
                "@odata.nextLink": next_link,
            },
        ),
        _resp(
            200,
            {
                "value": [
                    {"id": "f2", "name": "b.txt", "size": 20, "file": {}},
                    {"id": "d2", "name": "pics", "size": 0, "folder": {}},
                ],
            },
        ),
    ]

    files = drive.get_file_list("root", timeout=7)
    assert [(f["fid"], f["name"], f["size"], f["isfile"]) for f in files] == [
        ("f1", "a.txt", 10, True),
        ("f2", "b.txt", 20, True),
    ]
    assert drive.session.get.call_count == 2
    assert drive.session.get.call_args_list[0].kwargs["timeout"] == 7
    assert drive.session.get.call_args_list[1].args[0] == next_link
    assert drive.session.get.call_args_list[1].kwargs["timeout"] == 7

    drive.session.get.reset_mock()
    drive.session.get.side_effect = [
        _resp(
            200,
            {
                "value": [{"id": "d1", "name": "docs", "folder": {}}],
                "@odata.nextLink": next_link,
            },
        ),
        _resp(200, {"value": [{"id": "d2", "name": "pics", "folder": {}}]}),
    ]
    dirs = drive.get_dir_list("root", timeout=5)
    assert [(d["fid"], d["name"], d["isdir"]) for d in dirs] == [
        ("d1", "docs", True),
        ("d2", "pics", True),
    ]


def test_get_file_list_does_not_return_partial_page_on_page2_error_or_stall():
    drive = _drive()
    next_link = "https://graph.microsoft.com/v1.0/me/drive/root/children?$skiptoken=2"
    drive.session.get.side_effect = [
        _resp(
            200,
            {
                "value": [{"id": "f1", "name": "a.txt", "size": 10, "file": {}}],
                "@odata.nextLink": next_link,
            },
        ),
        _resp(503, text="service unavailable"),
    ]
    assert drive.get_file_list("root") == []

    same_url = f"{drive.GRAPH_API_BASE}/me/drive/root/children"
    drive.session.get.side_effect = [
        _resp(
            200,
            {
                "value": [{"id": "f1", "name": "a.txt", "size": 10, "file": {}}],
                "@odata.nextLink": same_url,
            },
        ),
    ]
    assert drive.get_file_list("root") == []


def test_exist_mkdir_delete_and_info():
    drive = _drive()

    drive.session.get.return_value = _resp(200)
    assert drive.exist("item-1") is True
    drive.session.get.return_value = _resp(404)
    assert drive.exist("missing") is False

    drive.session.get.return_value = _resp(200, {"value": []})
    drive.session.post.return_value = _resp(201, {"id": "new-dir"})
    assert drive.mkdir("root", "work") == "new-dir"
    assert (
        drive.session.post.call_args.kwargs["json"]["@microsoft.graph.conflictBehavior"]
        == "fail"
    )

    drive.session.delete.return_value = _resp(204)
    assert drive.delete("item-1") is True

    drive.session.get.return_value = _resp(
        200, {"id": "f1", "name": "a.txt", "size": 5, "file": {}}
    )
    assert drive.get_file_info("f1")["name"] == "a.txt"
    assert drive.get_dir_info("f1") is None

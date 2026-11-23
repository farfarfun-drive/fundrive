"""MediaFireDrive 单元测试（纯 mock，覆盖多分片分页、停滞保护与 CRUD）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.mediafire import MediaFireDrive


def _drive():
    drive = MediaFireDrive(email="u@example.com", password="pw")
    drive._make_request = Mock()
    return drive


def test_get_file_and_dir_list_paginate_all_chunks():
    drive = _drive()
    drive._make_request.side_effect = [
        {
            "response": {
                "folder_content": {
                    "more_chunks": "yes",
                    "files": [
                        {"quickkey": "k1", "filename": "a.txt", "size": "10"},
                    ],
                }
            }
        },
        {
            "response": {
                "folder_content": {
                    "more_chunks": "no",
                    "files": [
                        {"quickkey": "k2", "filename": "b.txt", "size": "20"},
                    ],
                }
            }
        },
    ]

    files = drive.get_file_list("root")
    assert [(f["fid"], f["name"], f["size"], f["isfile"]) for f in files] == [
        ("k1", "a.txt", 10, True),
        ("k2", "b.txt", 20, True),
    ]
    assert drive._make_request.call_args_list[0].kwargs["params"]["chunk"] == 1
    assert drive._make_request.call_args_list[1].kwargs["params"]["chunk"] == 2

    drive._make_request.side_effect = [
        {
            "response": {
                "folder_content": {
                    "more_chunks": "yes",
                    "folders": [{"folderkey": "d1", "name": "sub1"}],
                }
            }
        },
        {
            "response": {
                "folder_content": {
                    "more_chunks": "no",
                    "folders": [{"folderkey": "d2", "name": "sub2"}],
                }
            }
        },
    ]
    dirs = drive.get_dir_list("root")
    assert [(d["fid"], d["name"], d["isdir"]) for d in dirs] == [
        ("d1", "sub1", True),
        ("d2", "sub2", True),
    ]


def test_get_file_list_guards_stalled_empty_chunk():
    drive = _drive()
    drive._make_request.return_value = {
        "response": {"folder_content": {"more_chunks": "yes", "files": []}}
    }
    assert drive.get_file_list("root") == []


def test_mkdir_exist_and_delete():
    drive = _drive()
    drive._make_request.side_effect = [
        {"response": {"folder_content": {"more_chunks": "no", "folders": []}}},
        {"response": {"folder_key": "new-key"}},
    ]
    assert drive.mkdir("root", "docs") == "new-key"

    drive._make_request.side_effect = [{"response": {"folder_info": {}}}]
    assert drive.exist("new-key") is True

    drive._make_request.side_effect = [{"response": {"result": "Success"}}]
    assert drive.delete("k1") is True

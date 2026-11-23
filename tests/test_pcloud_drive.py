"""PCloudDrive 单元测试（纯 mock，覆盖列表、建目录与根目录防误删保护）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.pcloud import PCloudDrive


def _drive():
    drive = PCloudDrive(access_token="tok")
    drive._make_request = Mock()
    return drive


def test_get_file_and_dir_list():
    drive = _drive()
    drive._make_request.return_value = {
        "result": 0,
        "metadata": {
            "contents": [
                {"isfolder": True, "folderid": 10, "name": "docs"},
                {"isfolder": False, "fileid": 20, "name": "a.txt", "size": 99},
            ]
        },
    }
    files = drive.get_file_list("0")
    dirs = drive.get_dir_list("0")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [("20", "a.txt", 99)]
    assert [(d["fid"], d["name"]) for d in dirs] == [("10", "docs")]


def test_mkdir_and_delete_root_guard():
    drive = _drive()
    drive._make_request.side_effect = [
        {"result": 0, "metadata": {"contents": []}},
        {"result": 0, "metadata": {"folderid": 88}},
    ]
    assert drive.mkdir("0", "work") == "88"

    # 删除根目录 0 必须被安全护栏拦截（返回 False，不调用 deletefolderrecursive）
    drive._make_request.reset_mock()
    drive._make_request.return_value = {"result": 2009}
    assert drive.delete("0") is False
    for call in drive._make_request.call_args_list:
        assert call.args[0] != "deletefolderrecursive"

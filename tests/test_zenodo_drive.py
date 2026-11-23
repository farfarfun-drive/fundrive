"""ZenodoDrive 单元测试（纯 mock，覆盖记录/存储库列表与文件详情）。"""

from __future__ import annotations

from unittest.mock import Mock

from fundrive.drives.zenodo import ZenodoDrive


def _drive():
    drive = ZenodoDrive(access_token="tok")
    drive.client = Mock()
    return drive


def test_get_dir_list_and_file_list_and_info():
    drive = _drive()
    drive.client.list_depositions.return_value = (
        True,
        [{"id": 1001, "title": "Dataset A", "state": "done"}],
    )
    dirs = drive.get_dir_list("root")
    assert [(d["fid"], d["name"]) for d in dirs] == [("1001", "Dataset A")]

    # 已发布记录文件列表
    drive.client.get_record.return_value = (
        True,
        {
            "files": [
                {
                    "id": "f1",
                    "key": "data.tar.gz",
                    "size": 2048,
                    "checksum": "md5:abc",
                    "links": {"self": "https://zenodo.test/f1"},
                }
            ]
        },
    )
    files = drive.get_file_list("1001")
    assert [(f["fid"], f["name"], f["size"]) for f in files] == [
        ("1001/data.tar.gz", "data.tar.gz", 2048)
    ]

    info = drive.get_file_info("1001/data.tar.gz")
    assert info is not None and info["name"] == "data.tar.gz" and info["size"] == 2048

    # 回退到未发布存储库文件列表
    drive.client.get_record.return_value = (False, {})
    drive.client.list_deposition_files.return_value = (
        True,
        [{"id": "f2", "filename": "draft.csv", "filesize": 512, "checksum": "md5:def"}],
    )
    draft_files = drive.get_file_list("2002")
    assert [(f["fid"], f["name"], f["size"]) for f in draft_files] == [
        ("2002/draft.csv", "draft.csv", 512)
    ]

    # 按 deposition_id 查询详情
    drive.client.get_deposition.return_value = (
        True,
        {"id": 2002, "title": "Draft B", "state": "unsubmitted"},
    )
    dinfo = drive.get_file_info("2002")
    assert dinfo is not None and dinfo["name"] == "Draft B"

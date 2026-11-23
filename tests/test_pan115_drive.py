"""115 网盘驱动：不得把任意异常当成"文件不存在"（SPEC §8.2）。

历史问题：``Pan115Drive.exist()`` 用 ``except Exception: return False`` 兜住
一切，而它调用的 ``get_file_info`` / ``get_dir_info`` 内部也各自
``except Exception`` 后返回 ``None``。于是网络中断、cookie 过期、SDK 内部
错误全部被翻译成"这个文件不存在"——上层据此判断可以安全覆盖/创建，是会丢
数据的那类误判。

``fundrive-pan115``（``fundrives.pan115``）只支持 Python >= 3.12 且是可选依赖，
CI 的裸环境里不装它，所以这里在 import 驱动之前把它和 ``funfile`` 替换成桩模块。
``fundrives.pan115`` 的 ``P115FileNotFoundError`` 继承内置 ``FileNotFoundError``，
桩里保持同样的继承关系，这正是"资源确实不存在"的唯一可靠信号。
"""

import sys
import types
from unittest.mock import Mock

import pytest


class _FakeP115Client:
    """桩客户端：``fs_file`` 的行为由测试逐例注入。"""

    def __init__(self, *args, **kwargs):
        self.fs_file_result = {"data": []}

    def fs_file(self, fid):
        if isinstance(self.fs_file_result, Exception):
            raise self.fs_file_result
        return self.fs_file_result


class _FakeP115FileNotFoundError(FileNotFoundError):
    """对应 ``fundrives.pan115.exception.P115FileNotFoundError``。"""


def _check_response(response):
    if not response.get("state", True):
        raise ValueError(response.get("error", "115 API error"))
    return response


def _install_stubs():
    """把 fundrives.pan115 / funfile 装成桩模块，让驱动能在裸环境 import。"""
    if "fundrives.pan115" not in sys.modules:
        try:
            import fundrives.pan115  # noqa: F401
        except ImportError:
            if "fundrives" not in sys.modules:
                ns = types.ModuleType("fundrives")
                ns.__path__ = []
                sys.modules["fundrives"] = ns
            mod = types.ModuleType("fundrives.pan115")
            mod.P115Client = _FakeP115Client
            sys.modules["fundrives.pan115"] = mod
            client_mod = types.ModuleType("fundrives.pan115.client")
            client_mod.check_response = _check_response
            sys.modules["fundrives.pan115.client"] = client_mod
            util_mod = types.ModuleType("fundrives.pan115.util")
            util_mod.share_extract_payload = lambda link: {"share_code": link}
            sys.modules["fundrives.pan115.util"] = util_mod
    if "funfile" not in sys.modules:
        try:
            import funfile  # noqa: F401
        except ImportError:
            mod = types.ModuleType("funfile")
            mod.file_size = lambda *a, **k: 0
            mod.file_sha1 = lambda *a, **k: ""
            sys.modules["funfile"] = mod


_install_stubs()

from fundrive.core.exceptions import AuthenticationError, FunDriveError  # noqa: E402
from fundrive.drives.pan115 import drive as pan115_drive  # noqa: E402

FILE_ENTRY = {
    "fid": "123",
    "n": "a.txt",
    "s": 5,
    "sha": "deadbeef",
    "t": "2026-01-01",
    "pc": "pc",
    "fc": 1,
}
DIR_ENTRY = {"cid": "456", "ns": "docs", "t": "2026-01-01", "pc": "pc", "fc": 0}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """驱动里每次查询都 ``time.sleep(1)``，测试里去掉。"""
    monkeypatch.setattr(pan115_drive.time, "sleep", lambda *_: None)


def _drive(fs_file_result):
    drive = pan115_drive.Pan115Drive()
    client = _FakeP115Client()
    client.fs_file_result = fs_file_result
    drive._client = client
    return drive


def test_exist_true_for_file():
    assert _drive({"data": [FILE_ENTRY]}).exist("123") is True


def test_exist_true_for_dir():
    assert _drive({"data": [DIR_ENTRY]}).exist("456") is True


def test_exist_false_when_sdk_says_not_found():
    """SDK 明确表示资源不存在 —— 这才是唯一允许返回 False 的情况。"""
    drive = _drive(_FakeP115FileNotFoundError("no such file"))
    assert drive.exist("123") is False


def test_exist_false_on_empty_result():
    assert _drive({"data": []}).exist("123") is False


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionError("network down"),
        TimeoutError("timed out"),
        PermissionError("cookie expired"),
        ValueError("SDK 解析失败"),
        KeyError("state"),
    ],
)
def test_exist_raises_on_other_errors(exc):
    """网络/认证/SDK 错误必须抛出，不能伪装成"文件不存在"。"""
    drive = _drive(exc)
    with pytest.raises(FunDriveError) as info:
        drive.exist("123")
    # 异常信息必须保留可定位的上下文：fid + 原始异常类型
    assert "fid=123" in str(info.value)
    assert type(exc).__name__ in str(info.value)
    assert info.value.__cause__ is exc


def test_get_file_info_raises_on_network_error():
    with pytest.raises(FunDriveError):
        _drive(ConnectionError("network down")).get_file_info("123")


def test_get_dir_info_raises_on_network_error():
    with pytest.raises(FunDriveError):
        _drive(ConnectionError("network down")).get_dir_info("456")


def test_get_file_info_returns_none_for_dir_entry():
    assert _drive({"data": [DIR_ENTRY]}).get_file_info("456") is None


def test_get_file_info_parses_file_entry():
    info = _drive({"data": [FILE_ENTRY]}).get_file_info("123")
    assert info["fid"] == "123"
    assert info["name"] == "a.txt"
    assert info["isfile"] is True


def test_get_dir_info_parses_dir_entry():
    info = _drive({"data": [DIR_ENTRY]}).get_dir_info("456")
    assert info["fid"] == "456"
    assert info["name"] == "docs"
    assert info["isdir"] is True


def test_operations_require_login():
    """未登录时必须抛认证异常，而不是 AttributeError 或"不存在"。"""
    drive = pan115_drive.Pan115Drive()
    with pytest.raises(AuthenticationError):
        drive.exist("123")


def test_save_shared_receives_all_root_entries_with_password_override(monkeypatch):
    drive = _drive({"data": []})
    client = drive._client
    client.share_snap = Mock(
        side_effect=[
            {"state": True, "data": {"count": 3, "list": [{"fid": "1"}, {"cid": "2"}]}},
            {"state": True, "data": {"count": 3, "list": [{"fid": "3"}]}},
        ]
    )
    client.share_receive = Mock(return_value={"state": True})
    monkeypatch.setattr(
        pan115_drive,
        "share_extract_payload",
        lambda _: {
            "share_code": "abc",
            "receive_code": "in-link",
        },
    )

    assert drive.save_shared("https://115.com/s/abc", "99", password="explicit") is True
    assert client.share_snap.call_args_list[0].args[0] == {
        "share_code": "abc",
        "receive_code": "explicit",
        "cid": 0,
        "limit": 1000,
        "offset": 0,
    }
    assert client.share_snap.call_args_list[1].args[0]["offset"] == 2
    client.share_receive.assert_called_once_with(
        {
            "share_code": "abc",
            "receive_code": "explicit",
            "file_id": "1,2,3",
            "cid": "99",
        }
    )


def test_save_shared_empty_share_does_not_submit(monkeypatch):
    drive = _drive({"data": []})
    drive._client.share_snap = Mock(
        return_value={
            "state": True,
            "data": {"count": 0, "list": []},
        }
    )
    drive._client.share_receive = Mock()
    monkeypatch.setattr(
        pan115_drive, "share_extract_payload", lambda _: {"share_code": "abc"}
    )

    assert drive.save_shared("abc", "99") is False
    assert drive._client.share_snap.call_args.args[0]["receive_code"] == ""
    drive._client.share_receive.assert_not_called()


@pytest.mark.parametrize("failed_step", ["share_snap", "share_receive"])
def test_save_shared_returns_false_on_api_failure(monkeypatch, failed_step):
    drive = _drive({"data": []})
    client = drive._client
    client.share_snap = Mock(
        return_value={
            "state": True,
            "data": {"count": 1, "list": [{"fid": "1"}]},
        }
    )
    client.share_receive = Mock(return_value={"state": True})
    getattr(client, failed_step).return_value = {"state": False, "error": "failed"}
    monkeypatch.setattr(
        pan115_drive, "share_extract_payload", lambda _: {"share_code": "abc"}
    )

    assert drive.save_shared("abc", "99") is False
    if failed_step == "share_snap":
        client.share_receive.assert_not_called()


def test_save_shared_requires_login():
    with pytest.raises(AuthenticationError):
        pan115_drive.Pan115Drive().save_shared("abc", "99")


# --------------------------------------------------------------------------
# get_all_list 分页、超时、字段归一化与失败语义（issue #16）
# --------------------------------------------------------------------------


def test_get_all_list_paginates_all_pages_and_forwards_timeout():
    """多页目录必须读完全部分页，并将 timeout 透传给每一页的 fs_files。"""

    def page(fid):
        entry = {"fc": 0, "cid": fid, "ns": f"dir-{fid}", "t": 0, "pc": "x"}
        return {
            "state": True,
            "path": [{"name": "root"}],
            "count": 2,
            "data": [entry],
        }

    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.side_effect = [page("101"), page("102")]

    entries = drive.get_all_list("0", timeout=3)

    assert [entry["fid"] for entry in entries] == ["101", "102"]
    assert [entry["name"] for entry in entries] == ["dir-101", "dir-102"]
    assert all(entry["isdir"] is True and entry["isfile"] is False for entry in entries)
    assert len(sdk.fs_files.call_args_list) == 2
    assert sdk.fs_files.call_args_list[0].args[0]["cid"] == "0"
    assert sdk.fs_files.call_args_list[0].args[0]["offset"] == 0
    assert sdk.fs_files.call_args_list[0].kwargs == {"timeout": 3}
    assert sdk.fs_files.call_args_list[1].args[0]["cid"] == "0"
    assert sdk.fs_files.call_args_list[1].args[0]["offset"] == 1
    assert sdk.fs_files.call_args_list[1].kwargs == {"timeout": 3}


def test_get_all_list_normalizes_fc_and_name_fields_for_dirs_and_files():
    """fc=0 / fc='0' 均识别为目录，目录兼容 ns/name/n，文件兼容 n/name/ns 并保留 sha/size。"""
    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.return_value = {
        "state": True,
        "path": [{"name": "根目录"}, {"name": "work"}],
        "count": 6,
        "data": [
            {"fc": 0, "cid": "10", "ns": "dir-ns", "t": 0, "pc": "p1"},
            {"fc": "0", "cid": "11", "name": "dir-name", "t": 1},
            {"fc": "0", "cid": 12, "n": "dir-n"},
            {
                "fc": 1,
                "fid": "20",
                "n": "file-n.txt",
                "s": 128,
                "sha": "A" * 40,
                "t": "1700000000",
                "pc": "p2",
            },
            {
                "fc": "1",
                "fid": "21",
                "name": "file-name.bin",
                "size": 0,
                "sha1": "B" * 40,
            },
            {"fc": "1", "fid": 22, "ns": "file-ns.log"},
        ],
    }

    entries = drive.get_all_list("0", timeout=5)
    assert len(entries) == 6

    dirs = [e for e in entries if e["isdir"]]
    files = [e for e in entries if e["isfile"]]
    assert [(d["fid"], d["name"], d["isdir"], d["isfile"]) for d in dirs] == [
        ("10", "dir-ns", True, False),
        ("11", "dir-name", True, False),
        ("12", "dir-n", True, False),
    ]
    assert all(e["dirname"] == "work" for e in entries)
    assert [
        (f["fid"], f["name"], f["isdir"], f["isfile"], f["size"], f["sha"])
        for f in files
    ] == [
        ("20", "file-n.txt", False, True, 128, "A" * 40),
        ("21", "file-name.bin", False, True, 0, "B" * 40),
        ("22", "file-ns.log", False, True, None, None),
    ]
    assert [d["fid"] for d in drive.get_dir_list("0", timeout=5)] == ["10", "11", "12"]
    assert [f["fid"] for f in drive.get_file_list("0", timeout=5)] == ["20", "21", "22"]


def test_get_dir_and_file_info_accept_string_fc():
    assert (
        _drive({"data": [{"fc": "0", "cid": "456", "n": "docs"}]}).get_dir_info("456")[
            "name"
        ]
        == "docs"
    )
    assert (
        _drive({"data": [{"fc": "1", "fid": "123", "name": "a.txt"}]}).get_file_info(
            "123"
        )["name"]
        == "a.txt"
    )


def test_get_all_list_empty_directory_returns_empty_list():
    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.return_value = {
        "state": True,
        "path": [{"name": "root"}],
        "count": 0,
        "data": [],
    }

    assert drive.get_all_list("0", timeout=3) == []
    sdk.fs_files.assert_called_once()


def test_get_all_list_raises_when_second_page_times_out():
    """第二页超时必须抛出异常，不能把第一页当成完整结果返回。"""
    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.side_effect = [
        {
            "state": True,
            "path": [{"name": "root"}],
            "count": 2,
            "data": [{"fc": 0, "cid": "101", "ns": "dir-101"}],
        },
        TimeoutError("page 2 timed out"),
    ]

    with pytest.raises(TimeoutError, match="page 2 timed out"):
        drive.get_all_list("0", timeout=3)


def test_get_all_list_raises_on_auth_failure():
    """未登录或服务端返回认证失败响应时必须抛出异常。"""
    with pytest.raises(AuthenticationError):
        pan115_drive.Pan115Drive().get_all_list("0", timeout=3)

    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.return_value = {
        "state": False,
        "errno": 99,
        "error": "请重新登录",
    }

    with pytest.raises(Exception, match="请重新登录"):
        drive.get_all_list("0", timeout=3)


@pytest.mark.parametrize(
    "bad_response",
    [
        None,
        {"state": True, "count": 0},
        {"state": True, "count": 1, "data": None},
        {"state": True, "count": 1, "data": {}},
    ],
)
def test_get_all_list_raises_when_response_missing_data_list(bad_response):
    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.return_value = bad_response

    with pytest.raises(FunDriveError):
        drive.get_all_list("0", timeout=3)


def test_get_all_list_raises_when_pagination_stalls_with_empty_page():
    """服务端声明 count=2，但第二页返回空列表（分页未前进）时必须抛异常。"""
    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.side_effect = [
        {
            "state": True,
            "path": [{"name": "root"}],
            "count": 2,
            "data": [{"fc": 0, "cid": "101", "ns": "dir-101"}],
        },
        {
            "state": True,
            "path": [{"name": "root"}],
            "count": 2,
            "data": [],
        },
    ]

    with pytest.raises(FunDriveError, match="分页未前进"):
        drive.get_all_list("0", timeout=3)


def test_get_all_list_raises_when_server_offset_does_not_advance():
    """服务端显式返回的 offset 与请求的 offset 不一致时必须抛异常。"""
    drive = pan115_drive.Pan115Drive()
    sdk = Mock()
    drive._client = sdk
    sdk.fs_files.side_effect = [
        {
            "state": True,
            "offset": 0,
            "count": 2,
            "data": [{"fc": 0, "cid": "101", "ns": "dir-101"}],
        },
        {
            "state": True,
            "offset": 0,
            "count": 2,
            "data": [{"fc": 0, "cid": "101", "ns": "dir-101"}],
        },
    ]

    with pytest.raises(FunDriveError, match="分页未前进"):
        drive.get_all_list("0", timeout=3)


def test_request_interval_configurable(monkeypatch):
    """request_interval=0 不调用 sleep，自定义正值按配置等待。"""
    sleeps: list[float] = []
    monkeypatch.setattr(pan115_drive.time, "sleep", sleeps.append)

    drive_fast = pan115_drive.Pan115Drive(request_interval=0)
    sdk = Mock()
    sdk.fs_files.return_value = {"state": True, "count": 0, "data": []}
    drive_fast._client = sdk
    assert drive_fast.get_all_list("0") == []
    assert sleeps == []

    drive_slow = pan115_drive.Pan115Drive(request_interval=0.25)
    drive_slow._client = sdk
    assert drive_slow.get_all_list("0") == []
    assert sleeps == [0.25]


def test_search_normalizes_entries_and_forwards_timeout():
    drive = pan115_drive.Pan115Drive(request_interval=0)
    sdk = Mock()
    drive._client = sdk
    sdk.fs_search.return_value = {
        "state": True,
        "data": [
            {"fc": "0", "cid": "10", "ns": "report-dir", "t": 0},
            {"fc": "1", "fid": "20", "n": "report.pdf", "s": 256, "sha": "C" * 40},
        ],
    }

    hits = drive.search("report", fid="0", timeout=4)
    assert [
        (h["fid"], h["name"], h["isdir"], h["isfile"], h["size"]) for h in hits
    ] == [
        ("10", "report-dir", True, False, None),
        ("20", "report.pdf", False, True, 256),
    ]
    sdk.fs_search.assert_called_once_with(
        {"search_value": "report", "cid": "0"}, timeout=4
    )

    sdk.fs_search.return_value = {"state": True, "data": None}
    with pytest.raises(FunDriveError):
        drive.search("report")

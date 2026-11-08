"""115 网盘驱动：不得把任意异常当成"文件不存在"（SPEC §8.2）。

历史问题：``Pan115Drive.exist()`` 用 ``except Exception: return False`` 兜住
一切，而它调用的 ``get_file_info`` / ``get_dir_info`` 内部也各自
``except Exception`` 后返回 ``None``。于是网络中断、cookie 过期、SDK 内部
错误全部被翻译成"这个文件不存在"——上层据此判断可以安全覆盖/创建，是会丢
数据的那类误判。

``p115client`` 只支持 Python >= 3.12 且是可选依赖，CI 的裸环境里不装它，
所以这里在 import 驱动之前把它和 ``funfile`` 替换成桩模块。``p115client``
的 ``P115FileNotFoundError`` 继承内置 ``FileNotFoundError``，桩里保持同样的
继承关系，这正是"资源确实不存在"的唯一可靠信号。
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
    """对应 ``p115client.exception.P115FileNotFoundError``。"""


def _check_response(response):
    if not response.get("state", True):
        raise ValueError(response.get("error", "115 API error"))
    return response


def _install_stubs():
    """把 p115client / funfile 装成桩模块，让驱动能在裸环境 import。"""
    if "p115client" not in sys.modules:
        mod = types.ModuleType("p115client")
        mod.P115Client = _FakeP115Client
        sys.modules["p115client"] = mod
        client_mod = types.ModuleType("p115client.client")
        client_mod.check_response = _check_response
        sys.modules["p115client.client"] = client_mod
        util_mod = types.ModuleType("p115client.util")
        util_mod.share_extract_payload = lambda link: {"share_code": link}
        sys.modules["p115client.util"] = util_mod
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

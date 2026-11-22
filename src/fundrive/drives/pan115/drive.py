"""
115网盘驱动，基于 fundrive-pan115（fundrives.pan115）实现。
"""

import os
import time
import traceback
from pathlib import Path
from typing import Any

from farlog import getLogger
from fundrives.pan115 import P115Client
from fundrives.pan115.client import check_response
from fundrives.pan115.util import share_extract_payload
from funfile import file_sha1, file_size
from funget import simple_download

from fundrive.core import BaseDrive, DriveFile
from fundrive.core.base import get_filepath
from fundrive.core.exceptions import AuthenticationError, FunDriveError

logger = getLogger("fundrive")

_DEFAULT_PAGE_LIMIT = 1150


def _first_present(it: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in it and it[key] is not None:
            return it[key]
    return None


def _first_nonempty_str(it: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = it.get(key)
        if val is not None:
            text = str(val)
            if text:
                return text
    return ""


def _is_dir_entry(it: dict[str, Any]) -> bool:
    fc = it.get("fc")
    if fc is not None and str(fc).strip() != "":
        return str(fc).strip() == "0"
    return not it.get("fid")


def _convert_info_to_file(
    it: dict[str, Any], dirname: str | None = None, *args: Any, **kwargs: Any
) -> DriveFile:
    fid = _first_nonempty_str(it, "fid", "id")
    name = _first_nonempty_str(it, "n", "name", "ns", "fn")
    raw_size = _first_present(it, "s", "size", "fs")
    size = int(raw_size) if raw_size is not None else None
    raw_sha = _first_present(it, "sha", "sha1")
    sha = str(raw_sha) if raw_sha is not None and str(raw_sha) != "" else None
    return DriveFile(
        fid=fid,
        name=name,
        size=size,
        sha=sha,
        time=_first_present(it, "t", "te", "tp"),
        pc=it.get("pc"),
        isfile=True,
        isdir=False,
        dirname=dirname,
    )


def _convert_info_to_dir(
    it: dict[str, Any], dirname: str | None = None, *args: Any, **kwargs: Any
) -> DriveFile:
    fid = _first_nonempty_str(it, "cid", "fid", "id")
    name = _first_nonempty_str(it, "ns", "name", "n")
    return DriveFile(
        fid=fid,
        name=name,
        time=_first_present(it, "t", "te", "tp"),
        pc=it.get("pc"),
        isfile=False,
        isdir=True,
        dirname=dirname,
    )


class Pan115Drive(BaseDrive):
    """
    115网盘驱动，基于 fundrive-pan115（fundrives.pan115）实现

    ``fid`` 用 115 自己的 ID 体系：目录用 ``cid``，文件用 ``fid``，根目录是
    ``"0"``。几乎所有接口都要求先 :meth:`login`。
    """

    def __init__(self, *args: Any, **kwargs: Any):
        """
        初始化115网盘驱动

        这里只准备字段，真正建立会话在 :meth:`login` 中完成。

        Args:
            *args: 透传给 ``BaseDrive`` 的可变位置参数
            **kwargs: 透传给 ``BaseDrive`` 的可变关键字参数
        """
        super().__init__(*args, **kwargs)
        self._client: P115Client | None = None

    def login(
        self,
        cookies: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """
        登录115网盘

        不传 ``cookies`` 时读取 ``~/115-cookies.txt``，并以 ``qandroid`` 客户端
        走一次扫码/续期登录。

        Args:
            cookies (str, optional): 115 的 cookie 字符串
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            bool: 登录成功返回 ``True``
        """
        if cookies is not None:
            self._client = P115Client(cookies=cookies)
        else:
            self._client = P115Client(
                Path("~/115-cookies.txt").expanduser(),
                app="qandroid",
            )
            self._client.login()
        return True

    def mkdir(
        self,
        fid: str,
        name: str,
        return_if_exist: bool = True,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """
        在指定目录下创建子目录

        Args:
            fid (str): 父目录的 cid
            name (str): 新目录名
            return_if_exist (bool): 保留参数；115 服务端对同名目录直接返回已有
                目录的 cid，本驱动不额外判重
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            str: 新目录的 cid；创建失败返回空字符串

        Note:
            按 ``BaseDrive`` 契约这里必须返回**目录ID**。历史实现 ``return True``，
            调用方（如 ``upload_dir`` / ``copy_data``）会把 ``True`` 当成 cid 继续
            往下传，导致后续上传全部落到错误位置。
        """
        client = self._require_client()
        response = client.fs_mkdir(name, fid) or {}
        cid = response.get("cid") or (response.get("data") or {}).get("cid")
        if not cid:
            logger.error(f"115创建目录失败 parent_fid={fid} name={name}: {response}")
            return ""
        return str(cid)

    def _require_client(self) -> P115Client:
        """返回已登录的客户端，未登录时抛出认证异常。"""
        if self._client is None:
            raise AuthenticationError("请先调用 Pan115Drive.login() 登录 115 网盘")
        return self._client

    def _query_entries(self, fid: str) -> list[dict]:
        """查询 fid 对应的原始条目列表。

        只有 115 明确回答"资源不存在"时才返回空列表；网络、认证、SDK 等其他
        错误会带着 fid 上下文抛出 :class:`FunDriveError`，不再被伪装成
        "文件不存在"（SPEC §8.2）。
        """
        client = self._require_client()
        time.sleep(1)
        try:
            response = client.fs_file(fid)
        except FileNotFoundError:
            # p115client 的 P115FileNotFoundError 继承内置 FileNotFoundError，
            # 这是 SDK 明确表示"资源不存在"的唯一信号。
            return []
        except Exception as e:
            raise FunDriveError(
                f"查询 115 条目失败 fid={fid}: {type(e).__name__}: {e}",
                error_code="PAN115_QUERY_FAILED",
                details={"fid": fid},
            ) from e
        return list(response.get("data") or [])

    def exist(self, fid: str, *args: Any, **kwargs: Any) -> bool:
        """
        判断文件或目录是否存在

        Args:
            fid (str): 文件或目录ID
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            bool: 存在返回 ``True``

        Raises:
            AuthenticationError: 尚未登录
            FunDriveError: 查询过程中出现网络/SDK 等非"资源不存在"的错误
        """
        return bool(self._query_entries(fid))

    def delete(self, fid: str, *args: Any, **kwargs: Any) -> bool:
        """
        删除文件或目录

        Args:
            fid (str): 待删除的文件或目录ID
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            bool: 删除成功返回 ``True``，失败记录日志并返回 ``False``
        """
        try:
            self._require_client().fs_delete(fid)
            return True
        except Exception as e:
            logger.error(f"删除文件失败 {fid}: {e}")
            return False

    def get_all_list(
        self,
        fid: str,
        *args: Any,
        timeout: float | None = None,
        limit: int = _DEFAULT_PAGE_LIMIT,
        **kwargs: Any,
    ) -> list[DriveFile]:
        """
        获取目录下的全部条目（文件 + 子目录），自动拉取完整分页。

        为避免触发 115 的频率限制，每页请求前固定 sleep 1 秒。

        Args:
            fid (str): 目录的 cid
            *args: 可变位置参数
            timeout (float, optional): 透传给底层 ``fs_files`` 的单页请求超时（秒）
            limit (int): 单页条数上限，默认 1150
            **kwargs: 其他透传给底层 ``fs_files`` 的关键字参数

        Returns:
            list[DriveFile]: 完整目录条目列表，用 ``isfile`` / ``isdir`` 区分类型

        Raises:
            AuthenticationError: 尚未登录
            ValueError: ``limit <= 0``
            FunDriveError: 响应格式异常、缺少条目列表或分页未前进
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        client = self._require_client()
        request_kwargs = dict(kwargs)
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        result: list[DriveFile] = []
        offset = 0
        while True:
            time.sleep(1)
            payload = {
                "cid": fid,
                "limit": limit,
                "offset": offset,
                "show_dir": 1,
            }
            response = client.fs_files(payload, **request_kwargs)
            if not isinstance(response, dict):
                raise FunDriveError(
                    f"读取 115 目录失败 fid={fid}: 响应格式无效",
                    error_code="PAN115_LIST_INVALID_RESPONSE",
                    details={"fid": fid, "offset": offset},
                )
            response = check_response(response)
            if not isinstance(response, dict) or response.get("state") is False:
                raise FunDriveError(
                    f"读取 115 目录失败 fid={fid}: 服务端返回失败响应",
                    error_code="PAN115_LIST_FAILED",
                    details={"fid": fid, "offset": offset},
                )
            entries = response.get("data")
            if not isinstance(entries, list):
                raise FunDriveError(
                    f"读取 115 目录失败 fid={fid}: 响应缺少条目列表",
                    error_code="PAN115_LIST_INVALID_RESPONSE",
                    details={"fid": fid, "offset": offset},
                )

            raw_offset = response.get("offset")
            if raw_offset is not None:
                try:
                    resp_offset = int(raw_offset)
                except (TypeError, ValueError) as e:
                    raise FunDriveError(
                        f"读取 115 目录失败 fid={fid}: offset 字段无效 ({raw_offset!r})",
                        error_code="PAN115_LIST_INVALID_RESPONSE",
                        details={
                            "fid": fid,
                            "offset": offset,
                            "response_offset": raw_offset,
                        },
                    ) from e
                if resp_offset != offset:
                    raise FunDriveError(
                        f"读取 115 目录失败 fid={fid}: 分页未前进 (expected offset={offset}, got {resp_offset})",
                        error_code="PAN115_LIST_STALLED",
                        details={
                            "fid": fid,
                            "offset": offset,
                            "response_offset": resp_offset,
                        },
                    )

            raw_count = response.get("count")
            total_count: int | None = None
            if raw_count is not None:
                try:
                    total_count = int(raw_count)
                except (TypeError, ValueError) as e:
                    raise FunDriveError(
                        f"读取 115 目录失败 fid={fid}: count 字段无效 ({raw_count!r})",
                        error_code="PAN115_LIST_INVALID_RESPONSE",
                        details={"fid": fid, "offset": offset, "count": raw_count},
                    ) from e
                if total_count < 0:
                    raise FunDriveError(
                        f"读取 115 目录失败 fid={fid}: count 为负数 ({total_count})",
                        error_code="PAN115_LIST_INVALID_RESPONSE",
                        details={"fid": fid, "offset": offset, "count": total_count},
                    )

            path_items = response.get("path")
            if isinstance(path_items, list) and len(path_items) > 1:
                dirname = "/".join(
                    str(p.get("name", ""))
                    for p in path_items[1:]
                    if isinstance(p, dict)
                )
            else:
                dirname = ""

            for it in entries:
                if not isinstance(it, dict):
                    raise FunDriveError(
                        f"读取 115 目录失败 fid={fid}: 条目格式无效",
                        error_code="PAN115_LIST_INVALID_RESPONSE",
                        details={"fid": fid, "offset": offset},
                    )
                if _is_dir_entry(it):
                    result.append(_convert_info_to_dir(it, dirname=dirname))
                else:
                    result.append(_convert_info_to_file(it, dirname=dirname))

            if total_count is not None:
                if offset + len(entries) >= total_count:
                    break
                if not entries:
                    raise FunDriveError(
                        f"读取 115 目录失败 fid={fid}: 分页未前进 (offset={offset}, count={total_count})",
                        error_code="PAN115_LIST_STALLED",
                        details={
                            "fid": fid,
                            "offset": offset,
                            "count": total_count,
                        },
                    )
                offset += len(entries)
            else:
                if not entries or len(entries) < limit:
                    break
                offset += len(entries)

        return result

    def get_file_list(self, fid: str, *args: Any, **kwargs: Any) -> list[DriveFile]:
        """
        获取目录下的文件列表

        Args:
            fid (str): 目录的 cid
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            list[DriveFile]: 文件列表
        """
        return [i for i in self.get_all_list(fid, *args, **kwargs) if i["isfile"]]

    def get_dir_list(self, fid: str, *args: Any, **kwargs: Any) -> list[DriveFile]:
        """
        获取目录下的子目录列表

        Args:
            fid (str): 目录的 cid
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            list[DriveFile]: 子目录列表
        """
        return [i for i in self.get_all_list(fid, *args, **kwargs) if i["isdir"]]

    def get_file_info(self, fid: str, *args: Any, **kwargs: Any) -> DriveFile | None:
        """
        获取文件详情

        Args:
            fid (str): 文件ID
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            DriveFile | None: 文件信息；不存在或该ID是目录时返回 ``None``
        """
        for it in self._query_entries(fid):
            if not _is_dir_entry(it):
                return _convert_info_to_file(it)
        return None

    def get_dir_info(self, fid: str, *args: Any, **kwargs: Any) -> DriveFile | None:
        """
        获取目录详情

        Args:
            fid (str): 目录的 cid
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            DriveFile | None: 目录信息；不存在或该ID是文件时返回 ``None``
        """
        for it in self._query_entries(fid):
            if _is_dir_entry(it):
                return _convert_info_to_dir(it)
        return None

    def download_file(
        self,
        fid: str,
        save_dir: str | None = None,
        filename: str | None = None,
        filepath: str | None = None,
        overwrite: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """
        下载单个文件

        Args:
            fid (str): 文件ID
            save_dir (str, optional): 保存目录
            filename (str, optional): 保存文件名，默认用网盘上的文件名
            filepath (str, optional): 完整保存路径，给了就忽略 save_dir/filename
            overwrite (bool): 目标已存在时是否覆盖
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            bool: 下载成功返回 ``True``，失败记录日志并返回 ``False``
        """
        try:
            # 注意不能写成 get_file_info(fid=fid, *args)：*args 会去填第一个位置
            # 形参（也是 fid），直接 TypeError: got multiple values for 'fid'。
            file_info = self.get_file_info(fid, **kwargs)
            if not file_info:
                logger.error(f"文件不存在或不是文件 {fid}")
                return False
            downer = self._require_client().download_url_app(file_info["pc"])
            url = downer["data"][fid]["url"]["url"]
            if not filepath:
                save_filename = filename or file_info["name"]
                filepath = get_filepath(save_dir, save_filename)
            simple_download(
                url, filepath=filepath, headers=downer["headers"], overwrite=overwrite
            )
            return True
        except Exception as e:
            logger.error(f"下载文件失败 {fid}: {e}:{traceback.format_exc()}")
            return False

    def upload_file(
        self,
        filepath: str,
        fid: str,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """
        上传单个文件

        Args:
            filepath (str): 本地文件路径
            fid (str): 目标目录的 cid
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            bool: 上传成功返回 ``True``，失败记录日志并返回 ``False``
        """
        try:
            self._require_client().upload_file(
                file=Path(filepath),
                pid=fid,
                partsize=1024,
                filename=os.path.basename(filepath),
                filesize=file_size(filepath),
                filesha1=file_sha1(filepath),
            )
            return True
        except Exception as e:
            logger.error(f"上传文件失败 {filepath}: {e}:{traceback.format_exc()}")
            return False

    def search(
        self,
        keyword: str,
        fid: str | None = None,
        file_type: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> list[DriveFile]:
        """
        按关键字搜索文件

        Args:
            keyword (str): 搜索关键字
            fid (str, optional): 保留参数，当前实现是全盘搜索，不限定目录
            file_type (str, optional): 保留参数，当前实现不按类型过滤
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            list[DriveFile]: 命中条目

        Note:
            这里返回的是 115 接口的原始条目字典，字段名与 ``DriveFile`` 并不一致，
            调用方暂时不能按 ``DriveFile`` 的字段去取值。
        """
        return list(self._require_client().fs_search(keyword)["data"])

    def move(
        self,
        source_fid: str,
        target_fid: str,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """
        移动文件或目录

        Args:
            source_fid (str): 源文件或目录ID
            target_fid (str): 目标目录的 cid
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            bool: 移动成功返回 ``True``，失败记录日志并返回 ``False``
        """
        try:
            self._require_client().fs_move(source_fid, target_fid)
            return True
        except Exception as e:
            logger.error(f"移动文件失败 {source_fid} -> {target_fid}: {e}")
            return False

    def rename(self, fid: str, new_name: str, *args: Any, **kwargs: Any) -> bool:
        """
        重命名文件或目录

        Args:
            fid (str): 文件或目录ID
            new_name (str): 新名称
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            bool: 重命名成功返回 ``True``，失败记录日志并返回 ``False``
        """
        try:
            self._require_client().fs_rename((fid, new_name))
            return True
        except Exception as e:
            logger.error(f"重命名失败 {fid} -> {new_name}: {e}")
            return False

    def get_quota(self, *args: Any, **kwargs: Any) -> dict:
        """
        获取网盘空间使用情况

        Args:
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            dict: 含 ``total`` / ``used`` / ``free`` 三个键，单位字节
        """
        data = self._require_client().user_space_info()["data"]
        total = int(data["all_total"]["size"])
        used = int(data["all_use"]["size"])
        return {"total": total, "used": used, "free": total - used}

    def save_shared(
        self, shared_url: str, fid: str, password: str | None = None
    ) -> bool:
        """将分享根目录中的文件和目录转存到目标目录 cid。"""
        client = self._require_client()
        try:
            share = share_extract_payload(shared_url)
            share["receive_code"] = (
                password if password is not None else share.get("receive_code", "")
            )
            ids: list[str] = []
            offset = 0
            while True:
                data = check_response(
                    client.share_snap(
                        {
                            **share,
                            "cid": 0,
                            "limit": 1000,
                            "offset": offset,
                        }
                    )
                )["data"]
                entries = data["list"]
                ids.extend(
                    str(item["fid"] if "fid" in item else item["cid"])
                    for item in entries
                )
                offset += len(entries)
                if offset >= int(data["count"]):
                    break
                if not entries:
                    raise ValueError("分享文件列表分页未前进")
            if not ids:
                return False
            check_response(
                client.share_receive(
                    {
                        **share,
                        "file_id": ",".join(ids),
                        "cid": fid,
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"115分享转存失败 fid={fid}: {e}")
            return False

    def get_download_url(self, fid: str, *args: Any, **kwargs: Any) -> str:
        """
        获取文件的下载直链

        Args:
            fid (str): 文件ID
            *args: 可变位置参数
            **kwargs: 可变关键字参数

        Returns:
            str: 下载链接（有时效，且通常需要配合 115 的请求头使用）

        Raises:
            FunDriveError: 文件不存在
        """
        # 同 download_file：不能写成 get_file_info(fid=fid, *args)
        file_info = self.get_file_info(fid, **kwargs)
        if not file_info:
            raise FunDriveError(
                f"文件不存在 fid={fid}",
                error_code="PAN115_FILE_NOT_FOUND",
                details={"fid": fid},
            )
        downer = self._require_client().download_url_app(file_info["pc"])
        return downer["data"][fid]["url"]["url"]

"""China Mobile Cloud personal SaaS driver (cm-cloud-manage file protocol)."""

import hashlib
import json
import os
import tempfile
import time
from email.utils import formatdate
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from fundrive.core import BaseDrive, DriveFile
from fundrive.core.exceptions import (
    AuthenticationError,
    FunDriveError,
    OperationNotSupportedError,
)

_BASE_URL = "https://openapi.yun.139.com/open-ai-space"
_FILE_API = "/richlifeApp/idaasV3/personalSaas/file/"
_REQUIRED_HEADERS = ("creditToken", "skillId", "clientId", "strategyId", "clawUid")
_BAD_NAME_CHARS = '\\/:*?"<>|;&$`{}'
_PART_SIZE = 5 * 1024 * 1024
_SEARCH_TYPES = {
    "image": "1",
    "audio": "2",
    "video": "3",
    "doc": "4",
    "docs": "4",
    "app": "5",
    "zip": "6",
    "folder": "100",
}


def _file(item: dict[str, Any]) -> DriveFile:
    fid, name = item.get("fileId"), item.get("name")
    if not isinstance(fid, str) or not fid or not isinstance(name, str) or not name:
        raise FunDriveError("移动云盘响应缺少文件标识或名称")
    size = item.get("size")
    if isinstance(size, str) and size.isdecimal():
        size = int(size)
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        size = None
    return DriveFile(
        fid=fid,
        name=name,
        size=size,
        ext={k: v for k, v in item.items() if k not in ("fid", "name", "size")},
    )


def _valid_name(name: str) -> bool:
    return (
        isinstance(name, str)
        and name not in ("", ".", "..")
        and len(name.encode("utf-8")) <= 255
        and not any(ch in _BAD_NAME_CHARS or ord(ch) < 32 for ch in name)
    )


def _signed_url(url: str) -> str:
    if not isinstance(url, str):
        raise FunDriveError("移动云盘返回的预签名地址无效")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise FunDriveError("移动云盘返回的预签名地址无效") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.query
        or parsed.username
        or parsed.password
        or parsed.fragment
        or any(ch.isspace() for ch in url)
    ):
        raise FunDriveError("移动云盘返回的预签名地址无效")
    return url


class CMCloudDrive(BaseDrive):
    """Use an already authorized IDaaS ticket; this class does not acquire or store one."""

    def __init__(
        self,
        headers: dict[str, str],
        hash_algorithm: str = "sha256",
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        if not isinstance(headers, dict) or any(
            not isinstance(headers.get(k), str) or not headers[k]
            for k in _REQUIRED_HEADERS
        ):
            raise ValueError(
                "headers must include creditToken, skillId, clientId, strategyId and clawUid"
            )
        if hash_algorithm not in ("sha1", "sha256"):
            raise ValueError("hash_algorithm must be sha1 or sha256")
        self._headers = {"version": "2.0.0", **headers}
        self._hash_algorithm = hash_algorithm
        self._session = requests.Session()
        self._root_fid = "/"
        self._dedicated_root_fid: str | None = None

    @property
    def dedicated_root_fid(self) -> str | None:
        return self._dedicated_root_fid

    def _request(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._session.request(
                "POST" if body is not None else "GET",
                _BASE_URL + path,
                headers=self._headers,
                json=body,
                timeout=15,
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise FunDriveError(
                    f"移动云盘 HTTP {response.status_code}",
                    details={"http_status": response.status_code},
                )
            payload = response.json()
        except requests.RequestException as exc:
            raise FunDriveError("移动云盘请求失败") from exc
        except ValueError as exc:
            raise FunDriveError("移动云盘返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise FunDriveError("移动云盘响应不是对象")
        code = payload.get("code")
        success = payload.get("success")
        if (
            (success is not None and str(success).lower() not in ("true", "1"))
            or (code is not None and str(code) not in ("0", "0000"))
            or (code is None and success is None)
        ):
            raise FunDriveError(f"移动云盘请求失败 (code={code})")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise FunDriveError("移动云盘响应缺少 data")
        return data

    def _file_request(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(_FILE_API + action, body)

    def login(self, *args: Any, **kwargs: Any) -> bool:
        self._is_logged_in = False
        self._dedicated_root_fid = None
        try:
            data = self._request("/richlifeApp/idaas/user/folder/query")
        except FunDriveError:
            return False
        root = data.get("folderId")
        if not isinstance(root, str) or not root:
            return False
        self._dedicated_root_fid = root
        self._is_logged_in = True
        return True

    def _node(self, fid: str) -> dict[str, Any]:
        if fid == "/":
            return {"fileId": "/", "parentFileId": "/", "name": "/", "type": "folder"}
        data = self._file_request("get", {"fileId": fid})
        if data.get("fileId") != fid or data.get("type") not in ("file", "folder"):
            raise FunDriveError("移动云盘文件详情与请求不一致")
        return data

    def _write_parent(self, fid: str) -> None:
        if not self._is_logged_in or not self._dedicated_root_fid:
            raise AuthenticationError("请先调用 login() 查询移动云盘专属目录")
        seen: set[str] = set()
        current = fid
        for _ in range(30):
            if current in seen or current == "/":
                break
            seen.add(current)
            node = self._node(current)
            if node["type"] != "folder" and current == fid:
                raise ValueError("目标不是目录")
            if current == self._dedicated_root_fid:
                return
            current = node.get("parentFileId")
            if not isinstance(current, str):
                break
        raise FunDriveError("写入目标不在智能体专属目录内")

    def exist(self, fid: str, *args: Any, **kwargs: Any) -> bool:
        if fid == "/":
            return True
        try:
            self._node(fid)
        except FunDriveError as exc:
            if exc.details.get("http_status") == 404:
                return False
            raise
        return True

    def get_file_info(self, fid: str, *args: Any, **kwargs: Any) -> DriveFile | None:
        node = self._node(fid)
        return _file(node) if node["type"] == "file" else None

    def get_dir_info(self, fid: str, *args: Any, **kwargs: Any) -> DriveFile | None:
        node = self._node(fid)
        return _file(node) if node["type"] == "folder" else None

    def _list(self, fid: str, kind: str) -> list[DriveFile]:
        files: list[DriveFile] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            page: dict[str, Any] = {"pageSize": 100}
            if cursor:
                page["pageCursor"] = cursor
            data = self._file_request(
                "list", {"parentFileId": fid, "type": kind, "pageInfo": page}
            )
            items = data.get("items")
            if not isinstance(items, list):
                raise FunDriveError("移动云盘列表响应缺少 items")
            if any(not isinstance(item, dict) for item in items):
                raise FunDriveError("移动云盘列表包含无效文件项")
            files.extend(_file(item) for item in items)
            cursor = data.get("nextPageCursor")
            if not cursor:
                return files
            if not isinstance(cursor, str) or cursor in seen:
                raise FunDriveError("移动云盘列表游标无效")
            seen.add(cursor)

    def get_file_list(self, fid: str, *args: Any, **kwargs: Any) -> list[DriveFile]:
        return self._list(fid, "file")

    def get_dir_list(self, fid: str, *args: Any, **kwargs: Any) -> list[DriveFile]:
        return self._list(fid, "folder")

    def search(
        self,
        keyword: str,
        fid: str | None = None,
        file_type: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> list[DriveFile]:
        if not isinstance(keyword, str) or not keyword:
            raise ValueError("搜索关键词不能为空")
        conditions: dict[str, Any] = {"keyword": keyword}
        if fid and fid != "/":
            if self._node(fid)["type"] != "folder":
                raise ValueError("搜索范围不是目录")
            conditions["includeFileIdList"] = [fid]
        if file_type:
            code = _SEARCH_TYPES.get(file_type, file_type)
            if code not in {"0", "1", "2", "3", "4", "5", "6", "100"}:
                raise ValueError("不支持的搜索文件类型")
            conditions["typeList"] = [code]
        files: list[DriveFile] = []
        cursor: list[Any] | None = None
        seen: set[str] = set()
        while True:
            show_info: dict[str, Any] = {"pageSize": 1000}
            if cursor:
                show_info["pageAfter"] = cursor
            data = self._request(
                "/richlifeApp/idaasV3/search/SearchSkillFile",
                {"conditions": conditions, "showInfo": show_info},
            )
            rows = data.get("rows", data.get("skillFileList"))
            if not isinstance(rows, list) or any(
                not isinstance(item, dict) for item in rows
            ):
                raise FunDriveError("移动云盘搜索响应缺少文件列表")
            for row in rows:
                if not isinstance(row.get("fileId"), str) or not row["fileId"]:
                    raise FunDriveError("移动云盘搜索响应缺少文件 ID")
                if row.get("type") not in ("file", "folder"):
                    row = {**row, "type": self._node(row.get("fileId"))["type"]}
                files.append(_file(row))
            cursor = data.get("pageAfter")
            if len(rows) < 1000 or not cursor:
                return files
            if not isinstance(cursor, list) or not all(
                isinstance(item, (str, dict)) for item in cursor
            ):
                raise FunDriveError("移动云盘搜索游标无效")
            marker = json.dumps(cursor, sort_keys=True)
            if marker in seen:
                raise FunDriveError("移动云盘搜索游标重复")
            seen.add(marker)

    def mkdir(
        self,
        fid: str,
        name: str,
        return_if_exist: bool = True,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        self._write_parent(fid)
        if not _valid_name(name):
            raise ValueError("无效的移动云盘目录名")
        existing = next(
            (item for item in self.get_dir_list(fid) if item.name == name), None
        )
        if existing:
            if return_if_exist:
                return existing.fid
            raise FunDriveError("目标目录已存在")
        data = self._file_request(
            "createFolder",
            {"parentFileId": fid, "name": name, "fileRenameMode": "refuse"},
        )
        if data.get("exist") is True and not return_if_exist:
            raise FunDriveError("目标目录已存在")
        if data.get("type") not in (None, "folder"):
            raise FunDriveError("移动云盘建目录响应类型不正确")
        folder_id = data.get("fileId")
        if not isinstance(folder_id, str) or not folder_id:
            raise FunDriveError("移动云盘未返回新目录 ID")
        return folder_id

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
        node = self._node(fid)
        if node["type"] != "file":
            raise ValueError("下载目标不是文件")
        name = filename or node["name"]
        if not filepath and (name in (".", "..") or "/" in name or "\\" in name):
            raise ValueError("无效的下载文件名")
        target = Path(filepath) if filepath else Path(save_dir or ".") / name
        if target.exists() and not overwrite:
            return False
        data = self._file_request("getDownloadUrl", {"fileId": fid})
        if data.get("fileId") != fid:
            raise FunDriveError("移动云盘下载地址与请求文件不一致")
        url = _signed_url(data.get("url", ""))
        expected = data.get("size")
        if isinstance(expected, str) and expected.isdecimal():
            expected = int(expected)
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise FunDriveError("移动云盘下载响应缺少文件大小")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
                temp_path = temp.name
                with self._session.get(
                    url, stream=True, timeout=600, allow_redirects=False
                ) as response:
                    if response.status_code != 200:
                        raise FunDriveError(f"移动云盘下载 HTTP {response.status_code}")
                    total = 0
                    for chunk in response.iter_content(1024 * 1024):
                        temp.write(chunk)
                        total += len(chunk)
            if total != expected:
                raise FunDriveError("移动云盘下载大小校验失败")
            if overwrite:
                os.replace(temp_path, target)
            else:
                os.link(temp_path, target)
            return True
        except FileExistsError:
            return False
        except requests.RequestException:
            raise FunDriveError("移动云盘下载失败") from None
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    def upload_file(self, filepath: str, fid: str, *args: Any, **kwargs: Any) -> bool:
        if kwargs.get("overwrite"):
            raise OperationNotSupportedError("移动云盘上传不支持覆盖原文件")
        self._write_parent(fid)
        path = Path(filepath)
        if not path.is_file() or not _valid_name(path.name):
            raise ValueError("无效的本地上传文件")
        size = path.stat().st_size
        if size == 0:
            raise ValueError("移动云盘分片上传不支持空文件")
        # shortcut: uploads over 5 GiB are unsupported, add a bounded streaming part reader when needed.
        if size > 5 * 1024**3:
            raise ValueError("单文件上传目前限 5 GiB")
        digest = hashlib.new(self._hash_algorithm)
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        part_size = max(_PART_SIZE, (size + 99) // 100)
        parts = [
            {"partNumber": n + 1, "partSize": min(part_size, size - n * part_size)}
            for n in range((size + part_size - 1) // part_size)
        ]
        data = self._file_request(
            "create",
            {
                "parentFileId": fid,
                "name": path.name,
                "type": "file",
                "size": size,
                "partInfos": parts,
                "fileRenameMode": "force_rename",
                "contentHash": digest.hexdigest(),
                "contentHashAlgorithm": self._hash_algorithm,
            },
        )
        file_id = data.get("fileId")
        if not isinstance(file_id, str) or not file_id:
            raise FunDriveError("移动云盘未返回上传文件 ID")
        if data.get("exist") is True and data.get("rapidUpload") is not True:
            raise FunDriveError("移动云盘返回已有文件，无法确认上传已完成")
        if data.get("rapidUpload") is not True:
            upload_id = data.get("uploadId")
            if not isinstance(upload_id, str) or not upload_id:
                raise FunDriveError("移动云盘未返回上传任务 ID")
            urls = {
                part.get("partNumber"): part.get("uploadUrl")
                for part in data.get("partInfos", [])
                if isinstance(part, dict)
            }
            with path.open("rb") as source:
                for part in parts:
                    number, length = part["partNumber"], part["partSize"]
                    url = urls.get(number)
                    if not url:
                        more = self._file_request(
                            "getUploadUrl",
                            {
                                "fileId": file_id,
                                "uploadId": upload_id,
                                "partInfos": [part],
                            },
                        )
                        url = next(
                            (
                                item.get("uploadUrl")
                                for item in more.get("partInfos", [])
                                if isinstance(item, dict)
                                and item.get("partNumber") == number
                            ),
                            None,
                        )
                    blob = source.read(length)
                    if len(blob) != length:
                        raise FunDriveError("本地文件在上传期间发生变化")
                    try:
                        response = self._session.put(
                            _signed_url(url),
                            data=blob,
                            headers={
                                "Content-Type": "application/octet-stream",
                                "Content-Length": str(length),
                                "Date": formatdate(usegmt=True),
                            },
                            timeout=600,
                            allow_redirects=False,
                        )
                    except requests.RequestException:
                        raise FunDriveError("移动云盘分片传输失败") from None
                    if response.status_code not in (200, 201, 204):
                        raise FunDriveError(
                            f"移动云盘分片传输 HTTP {response.status_code}"
                        )
            self._file_request(
                "complete",
                {
                    "fileId": file_id,
                    "uploadId": upload_id,
                    "contentHash": digest.hexdigest(),
                    "contentHashAlgorithm": self._hash_algorithm,
                },
            )
        verified = self._node(file_id)
        actual_size = verified.get("size")
        if isinstance(actual_size, str) and actual_size.isdecimal():
            actual_size = int(actual_size)
        if (
            verified["type"] != "file"
            or verified.get("parentFileId") != fid
            or actual_size != size
        ):
            raise FunDriveError("移动云盘上传结果核验失败")
        return True

    def copy(self, source_fid: str, target_fid: str, *args: Any, **kwargs: Any) -> bool:
        self._write_parent(target_fid)
        self._node(source_fid)
        data = self._file_request(
            "batchCopy", {"fileIds": [source_fid], "toParentFileId": target_fid}
        )
        task_id = data.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise FunDriveError("移动云盘复制请求未返回任务 ID，结果未知")
        for attempt in range(60):
            task = self._request(
                "/richlifeApp/idaasV3/personalSaas/task/get", {"taskId": task_id}
            ).get("taskInfo")
            if not isinstance(task, dict) or task.get("taskId") != task_id:
                raise FunDriveError(f"移动云盘复制任务 {task_id} 状态无效，结果未知")
            if task.get("status") == "Succeed":
                return True
            if task.get("status") in ("Failed", "PartialSucceed"):
                return False
            if task.get("status") != "Running":
                raise FunDriveError(f"移动云盘复制任务 {task_id} 状态无效，结果未知")
            if attempt < 59:
                time.sleep(5)
        raise FunDriveError(f"移动云盘复制任务 {task_id} 仍在运行，勿重复提交")

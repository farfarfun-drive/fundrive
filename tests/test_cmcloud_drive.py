"""Protocol and data-loss checks for the China Mobile Cloud driver."""

import hashlib

import pytest

from fundrive.core.exceptions import FunDriveError
from fundrive.drives import get_drive

HEADERS = {
    "creditToken": "ticket",
    "skillId": "skill",
    "clientId": "client",
    "strategyId": "strategy",
    "clawUid": "agent",
}


class Response:
    def __init__(self, data=None, status=200, code="0000", chunks=()):
        self.status_code = status
        self._payload = {"code": code, "data": data or {}}
        self._chunks = chunks

    def json(self):
        return self._payload

    def iter_content(self, size):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Session:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.download = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.download

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return Response()


@pytest.fixture
def cloud(monkeypatch):
    session = Session()
    monkeypatch.setattr(
        "fundrive.drives.cmcloud.drive.requests.Session", lambda: session
    )
    drive = get_drive("cmcloud", headers=HEADERS)
    return drive, session


def test_login_and_paginated_listing(cloud):
    drive, session = cloud
    session.responses = [
        Response({"folderId": "dedicated"}, code="0"),
        Response(
            {
                "items": [
                    {"fileId": "a", "name": "a.txt", "size": "3", "type": "file"}
                ],
                "nextPageCursor": "next",
            }
        ),
        Response(
            {"items": [{"fileId": "b", "name": "b.txt", "size": 4, "type": "file"}]}
        ),
    ]
    assert drive.login() is True
    assert drive.root_fid == "/"
    assert drive.dedicated_root_fid == "dedicated"
    files = drive.get_file_list("/")
    assert [(file.fid, file.size) for file in files] == [("a", 3), ("b", 4)]
    assert session.calls[2][2]["json"]["pageInfo"] == {
        "pageSize": 100,
        "pageCursor": "next",
    }
    assert session.calls[1][2]["headers"]["creditToken"] == "ticket"


def test_login_failure_and_write_scope(cloud):
    drive, session = cloud
    session.responses = [Response(status=401)]
    assert drive.login() is False
    with pytest.raises(FunDriveError):
        drive.mkdir("/", "bad")
    session.responses = [
        Response({"folderId": "dedicated"}, code="0"),
        Response(
            {
                "fileId": "outside",
                "name": "outside",
                "type": "folder",
                "parentFileId": "/",
            }
        ),
    ]
    assert drive.login() is True
    with pytest.raises(FunDriveError, match="专属目录"):
        drive.mkdir("outside", "bad")
    assert all(not url.endswith("createFolder") for _, url, _ in session.calls)


def test_mkdir_reuses_existing_directory(cloud):
    drive, session = cloud
    session.responses = [
        Response({"folderId": "dedicated"}, code="0"),
        Response(
            {"fileId": "dedicated", "name": "AI", "type": "folder", "parentFileId": "/"}
        ),
        Response({"items": [{"fileId": "old", "name": "docs", "type": "folder"}]}),
    ]
    assert drive.login()
    assert drive.mkdir("dedicated", "docs") == "old"
    assert all(not url.endswith("createFolder") for _, url, _ in session.calls)


def test_search_resolves_numeric_type(cloud):
    drive, session = cloud
    session.responses = [
        Response(
            {"rows": [{"fileId": "f", "name": "report.pdf", "type": 4, "size": 7}]}
        ),
        Response(
            {"fileId": "f", "name": "report.pdf", "type": "file", "parentFileId": "/"}
        ),
    ]
    files = drive.search("report", file_type="docs")
    assert [(file.fid, file.size, file.type) for file in files] == [("f", 7, "file")]
    assert session.calls[0][2]["json"] == {
        "conditions": {"keyword": "report", "typeList": ["4"]},
        "showInfo": {"pageSize": 1000},
    }


def test_upload_completes_and_verifies_result(cloud, tmp_path):
    drive, session = cloud
    source = tmp_path / "note.txt"
    source.write_bytes(b"hello")
    session.responses = [
        Response({"folderId": "dedicated"}, code="0"),
        Response(
            {"fileId": "dedicated", "name": "AI", "type": "folder", "parentFileId": "/"}
        ),
        Response(
            {
                "fileId": "new",
                "uploadId": "upload",
                "partInfos": [
                    {"partNumber": 1, "uploadUrl": "https://storage.example/part?sig=x"}
                ],
            }
        ),
        Response({}),
        Response(
            {
                "fileId": "new",
                "name": "note.txt",
                "type": "file",
                "parentFileId": "dedicated",
                "size": 5,
            }
        ),
    ]
    assert drive.login()
    assert drive.upload_file(str(source), "dedicated") is True
    create = next(
        kwargs["json"] for _, url, kwargs in session.calls if url.endswith("/create")
    )
    assert create["contentHash"] == hashlib.sha256(b"hello").hexdigest()
    assert create["partInfos"] == [{"partNumber": 1, "partSize": 5}]
    assert (
        next(kwargs["data"] for method, _, kwargs in session.calls if method == "PUT")
        == b"hello"
    )
    assert any(url.endswith("/complete") for _, url, _ in session.calls)


def test_download_keeps_existing_file_on_bad_size(cloud, tmp_path):
    drive, session = cloud
    destination = tmp_path / "note.txt"
    destination.write_bytes(b"old")
    session.responses = [
        Response(
            {
                "fileId": "f",
                "name": "note.txt",
                "type": "file",
                "parentFileId": "dedicated",
            }
        ),
        Response(
            {"fileId": "f", "url": "https://storage.example/file?sig=x", "size": 5}
        ),
    ]
    session.download = Response(chunks=[b"bad"])
    with pytest.raises(FunDriveError, match="大小校验"):
        drive.download_file("f", filepath=str(destination), overwrite=True)
    assert destination.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [destination]


def test_download_rejects_mismatched_file_id(cloud, tmp_path):
    drive, session = cloud
    session.responses = [
        Response(
            {"fileId": "f", "name": "note.txt", "type": "file", "parentFileId": "/"}
        ),
        Response(
            {"fileId": "other", "url": "https://storage.example/file?sig=x", "size": 3}
        ),
    ]
    with pytest.raises(FunDriveError, match="不一致"):
        drive.download_file("f", save_dir=str(tmp_path))
    assert not list(tmp_path.iterdir())
    assert len(session.calls) == 2


def test_copy_waits_for_terminal_success(cloud, monkeypatch):
    drive, session = cloud
    monkeypatch.setattr("fundrive.drives.cmcloud.drive.time.sleep", lambda _: None)
    session.responses = [
        Response({"folderId": "dedicated"}, code="0"),
        Response(
            {"fileId": "dedicated", "name": "AI", "type": "folder", "parentFileId": "/"}
        ),
        Response(
            {"fileId": "source", "name": "a.txt", "type": "file", "parentFileId": "/"}
        ),
        Response({"taskId": "task"}),
        Response({"taskInfo": {"taskId": "task", "status": "Running"}}),
        Response({"taskInfo": {"taskId": "task", "status": "Succeed"}}),
    ]
    assert drive.login()
    assert drive.copy("source", "dedicated") is True
    submit = next(
        kwargs["json"] for _, url, kwargs in session.calls if url.endswith("/batchCopy")
    )
    assert submit == {"fileIds": ["source"], "toParentFileId": "dedicated"}
    assert len([url for _, url, _ in session.calls if url.endswith("/task/get")]) == 2

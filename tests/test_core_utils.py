"""针对 `fundrive.core.utils` 与 `fundrive.core.snapshot` 的单元测试与回归守卫。"""

from __future__ import annotations

import hashlib
import re
from unittest.mock import MagicMock

import pytest

from fundrive.core.snapshot import DriveSnapshot
from fundrive.core.utils import (
    ConnectionPool,
    LRUCache,
    ProgressTracker,
    RateLimiter,
    cache_result,
    format_size,
    get_file_hash,
    handle_drive_errors,
    parse_size,
    sanitize_filename,
    validate_fid,
)


class TestLRUCacheAndDecorator:
    def test_evicts_least_recently_used(self):
        cache = LRUCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        assert cache.get("a") == 1  # 刷新 "a" 的最近使用顺序
        cache.put("c", 3)  # 应淘汰 "b"
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3

    def test_zero_max_size_is_safe_noop(self):
        cache = LRUCache(max_size=0)
        cache.put("a", 1)
        assert cache.get("a") is None
        assert cache.size() == 0

    def test_ttl_expiration(self, monkeypatch):
        now = [100.0]
        monkeypatch.setattr("fundrive.core.utils.time.time", lambda: now[0])
        cache = LRUCache(max_size=10, ttl=5)
        cache.put("k", "v")
        assert cache.get("k") == "v"
        now[0] = 106.0
        assert cache.get("k") is None

    def test_cache_result_decorator_reuses_and_clears(self):
        calls = 0

        @cache_result(max_size=4, ttl=60)
        def compute(x: int) -> int:
            nonlocal calls
            calls += 1
            return x * 2

        assert compute(3) == 6
        assert compute(3) == 6
        assert calls == 1
        compute.cache_clear()
        assert compute(3) == 6
        assert calls == 2


class TestConnectionPool:
    def test_reuse_limit_and_close_all_closes_in_use_too(self):
        conns = []

        def factory():
            c = MagicMock()
            conns.append(c)
            return c

        pool = ConnectionPool(factory=factory, max_size=2)
        c1 = pool.get_connection()
        c2 = pool.get_connection()
        with pytest.raises(RuntimeError, match="连接池已满"):
            pool.get_connection()

        pool.return_connection(c1)
        assert pool.stats()["pool_size"] == 1
        assert pool.stats()["in_use"] == 1

        # c1 在池中，c2 仍在借出状态；close_all 必须把两者都关闭
        pool.close_all()
        c1.close.assert_called_once()
        c2.close.assert_called_once()
        assert pool.stats()["total_created"] == 0


class TestRateLimiter:
    def test_acquire_and_timeout_when_exhausted(self, monkeypatch):
        now = [10.0]
        monkeypatch.setattr("fundrive.core.utils.time.time", lambda: now[0])
        monkeypatch.setattr("fundrive.core.utils.time.sleep", lambda _s: None)

        limiter = RateLimiter(max_calls=2, time_window=60.0)
        assert limiter.acquire(timeout=0.0) is True
        assert limiter.acquire(timeout=0.0) is True
        assert limiter.acquire(timeout=0.0) is False
        assert limiter.stats()["remaining"] == 0


class TestSizeHelpers:
    def test_format_size(self):
        assert format_size(None) == "未知"  # type: ignore[arg-type]
        assert format_size(0) == "0 B"
        assert format_size(512) == "512 B"
        assert format_size(1024) == "1.00 KB"
        assert format_size(1024**3) == "1.00 GB"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("512B", 512),
            ("1KB", 1024),
            ("2.5 MB", int(2.5 * 1024**2)),
            ("1.5GB", int(1.5 * 1024**3)),
            ("2TB", 2 * 1024**4),
            ("1PB", 1024**5),
            ("1024", 1024),
        ],
    )
    def test_parse_size_all_units(self, text: str, expected: int):
        """回归：此前 units 字典里 'B' 排在第一位，导致所有 KB/MB/GB/TB/PB 都报错。"""
        assert parse_size(text) == expected

    def test_parse_size_rejects_invalid_format(self):
        with pytest.raises(ValueError, match="无效的大小格式"):
            parse_size("not-a-size")


class TestFilenameHashAndProgress:
    def test_sanitize_filename(self):
        assert sanitize_filename("a<b>c:d/e\\f|g?h*i.txt") == "a_b_c_d_e_f_g_h_i.txt"
        assert sanitize_filename("   ...  ") == "unnamed_file"
        long_name = "a" * 300 + ".txt"
        sanitized = sanitize_filename(long_name)
        assert len(sanitized) <= 255
        assert sanitized.endswith(".txt")

    def test_get_file_hash(self, tmp_path):
        f = tmp_path / "demo.bin"
        payload = b"fundrive-hash-check"
        f.write_bytes(payload)
        assert get_file_hash(str(f), "sha256") == hashlib.sha256(payload).hexdigest()
        with pytest.raises(ValueError, match="不支持的哈希算法"):
            get_file_hash(str(f), "no-such-algo")
        with pytest.raises(FileNotFoundError):
            get_file_hash(str(tmp_path / "missing.bin"))

    def test_progress_tracker_zero_elapsed_does_not_divide_by_zero(self, monkeypatch):
        """回归：elapsed == 0 时估算剩余时间不能抛 ZeroDivisionError。"""
        now = [50.0]
        monkeypatch.setattr("fundrive.core.utils.time.time", lambda: now[0])
        tracker = ProgressTracker(total=100)
        assert tracker.estimated_remaining is None
        tracker.update(25)
        assert tracker.estimated_remaining is None  # elapsed == 0
        now[0] = 55.0
        assert tracker.estimated_remaining == pytest.approx(15.0)
        assert tracker.percentage == 25.0


class TestDecoratorsAndSnapshot:
    def test_handle_drive_errors_default_and_reraise(self):
        @handle_drive_errors(default_return=False, reraise_exceptions=(ValueError,))
        def fail(exc: Exception) -> bool:
            raise exc

        assert fail(RuntimeError("boom")) is False
        with pytest.raises(ValueError, match="bad"):
            fail(ValueError("bad"))

    def test_validate_fid_supports_pep585_list_return_annotation(self):
        """回归：Python 3.12 小写 `list[...]` 标注在空 fid 时也应返回 `[]`。"""

        class DummyDrive:
            @validate_fid()
            def list_items(self, fid: str) -> list[str]:
                return [fid]

            @validate_fid()
            def check(self, fid: str) -> bool:
                return True

        d = DummyDrive()
        assert d.list_items("") == []
        assert d.list_items("root") == ["root"]
        assert d.check("") is False

    def test_snapshot_tar_path_format(self):
        snap = DriveSnapshot()
        tar_path = snap._tar_path("/tmp/backup")
        assert re.fullmatch(r"/tmp/backup-\d{14}\.tar", tar_path)

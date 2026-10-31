"""网络访问基础设施：限速、磁盘缓存、带重试的 JSON 请求。

文献检索工具（第 5 步）统一走这里，避免每个工具各写一套重试和缓存。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import requests


class HttpError(Exception):
    """请求失败：网络异常、重试耗尽或非 2xx 响应。"""


class RateLimiter:
    """按最小间隔串行放行请求；多线程下同样生效。"""

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_at = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delay = self._last_at + self.min_interval - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._last_at = now


class DiskCache:
    """以 URL 为键的 JSON 磁盘缓存；ttl 为 0 表示不过期。"""

    def __init__(self, root, ttl=0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl

    def _path(self, key):
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / "{}.json".format(digest)

    def get(self, key):
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if self.ttl and time.time() - payload.get("created_at", 0) > self.ttl:
            return None
        return payload.get("value")

    def set(self, key, value):
        payload = {"created_at": time.time(), "value": value}
        self._path(key).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )


class HttpClient:
    def __init__(
        self,
        cache=None,
        limiter=None,
        timeout=30.0,
        retries=2,
        backoff=1.0,
        session=None,
    ):
        self.cache = cache
        self.limiter = limiter
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = session or requests.Session()

    def get_json(self, url, params=None, headers=None):
        key = "{}?{}".format(url, json.dumps(params or {}, sort_keys=True))
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        last_error = None
        for attempt in range(self.retries + 1):
            if self.limiter is not None:
                self.limiter.wait()
            try:
                response = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    try:
                        value = response.json()
                    except ValueError:
                        raise HttpError("响应不是合法 JSON: {}".format(url))
                    if self.cache is not None:
                        self.cache.set(key, value)
                    return value
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = HttpError("HTTP {}".format(response.status_code))
                else:
                    raise HttpError(
                        "HTTP {}: {}".format(response.status_code, response.text[:200])
                    )
            if attempt < self.retries:
                time.sleep(self.backoff * (2 ** attempt))

        raise HttpError("请求失败 {}: {}".format(url, last_error))

"""数据目录唯一的联网边界。导入本模块本身不会加载网络依赖。"""

from __future__ import annotations

import hashlib
from typing import Any
from pathlib import Path
from datetime import datetime, timezone


def fetch_url(
    url: str,
    destination: str | Path,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: int = 30,
    user_agent: str = "MaaGakumasu-data-catalog/2",
) -> dict[str, Any]:
    """下载来源快照并返回 manifest；只有此函数触发网络访问。"""

    # 延迟导入保证 validate/report/derive 等离线路径不加载网络栈。
    import urllib.error
    import urllib.request

    headers = {"User-Agent": user_agent}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    request = urllib.request.Request(url, headers=headers)
    target = Path(destination)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            response_headers = response.headers
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return {
                "url": url,
                "status": "not_modified",
                "fetched_at": _now_iso(),
                "content_hash": _existing_hash(target),
                "etag": etag,
                "last_modified": last_modified,
            }
        raise
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "url": url,
        "status": "ok" if status == 200 else f"http_{status}",
        "fetched_at": _now_iso(),
        "content_hash": f"sha256:{hashlib.sha256(payload).hexdigest()}",
        "bytes": len(payload),
        "etag": response_headers.get("ETag"),
        "last_modified": response_headers.get("Last-Modified"),
    }


def _existing_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

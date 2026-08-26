# -*- coding: utf-8 -*-
"""
记忆漩涡 MemoryVortex · 媒体存储层（uploads.py）
================================================
v0.8 引入：预签名上传（对齐阿里云 OSS「客户端直传」模型）。

当前实现：本地磁盘存储（data/uploads/），对外暴露与真实 OSS 相同的
「预签名直传」接口契约：
    POST /api/v1/uploads/presign   {filename, contentType}
        → {uploadUrl, fileKey, method: "PUT", headers, expiresAt}
    客户端把文件 PUT 到 uploadUrl（本地实现为本服务上传端点）→ 拿到 url
    → 关联到业务实体（memories.media）。

替换真实 OSS 时只需改本文件：
    - presign()      返回的 uploadUrl 指向 OSS 预签名 URL，headers 带签名；
    - save_file()    不再落盘（对象存储由客户端直传，服务端不再收字节）；
    - resolve_url()  返回 OSS 文件 URL。
路由层（main.py）与前端流程保持不变。

安全约束：
    - 文件标识（fileKey）由服务端生成（hex + 白名单扩展名），落盘前
      再次校验格式，杜绝路径穿越；
    - 大小上限 100MB（v0.9.3：原 5MB 无法容纳视频，放宽）；
      扩展名白名单覆盖图片/视频/音频（含 .webm，浏览器 MediaRecorder 回退格式）。
"""

import re
import secrets
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

MAX_SIZE_BYTES = 100 * 1024 * 1024        # 100MB
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp",
               ".mp4", ".mov", ".webm", ".m4a", ".mp3"}
DEFAULT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
}
EXPIRES_S = 3600                          # 预签名有效期 1 小时

# fileKey 格式：24 位 hex + 白名单扩展名（save_file 落盘前的路径穿越防线）
_KEY_RE = re.compile(r"[0-9a-f]{24}\.[a-z0-9]+")


def _safe_ext(filename: str) -> str:
    """取小写扩展名；无扩展名返回 ''（调用方抛 422）。"""
    m = re.search(r"\.([a-zA-Z0-9]+)$", str(filename or ""))
    return f".{m.group(1).lower()}" if m else ""


def presign(filename: str, content_type: str | None = None) -> dict:
    """生成预签名上传凭据（本地实现：uploadUrl 指向本服务上传端点）。

    返回契约（与真实 OSS 直传一致）：
        {fileKey, uploadUrl, method, headers, contentType, expiresAt}
    """
    ext = _safe_ext(filename)
    if ext not in ALLOWED_EXT:
        raise ValueError(f"不支持的文件类型: {ext or '(无扩展名)'}")
    file_key = f"{secrets.token_hex(12)}{ext}"
    ctype = content_type or DEFAULT_TYPES.get(ext, "application/octet-stream")
    return {
        "fileKey": file_key,
        "uploadUrl": f"/api/v1/uploads/{file_key}",
        "method": "PUT",
        "headers": {"Content-Type": ctype},
        "contentType": ctype,
        "expiresAt": int(time.time()) + EXPIRES_S,
    }


def save_file(file_key: str, data: bytes) -> None:
    """落盘；校验 key 格式（防路径穿越）+ 大小限制。"""
    if not _KEY_RE.fullmatch(file_key):
        raise ValueError("非法文件标识")
    if len(data) > MAX_SIZE_BYTES:
        raise ValueError(f"文件过大（上限 {MAX_SIZE_BYTES // 1024 // 1024}MB）")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / file_key).write_bytes(data)


def resolve_url(file_key: str) -> str:
    """文件对外访问地址（本地实现：本服务静态托管 /uploads/{key}）。"""
    return f"/uploads/{file_key}"


def upload_dir() -> Path:
    """上传目录（main.py 挂载静态托管用）。"""
    return UPLOAD_DIR

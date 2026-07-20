"""
附件下行：从飞书消息中下载文件/图片并落盘。
"""

import os
import time
from pathlib import Path

import lark_oapi as lark

# 下载目录
DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "downloads"


def ensure_downloads_dir():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def get_file_extension(file_name: str) -> str:
    """从文件名中提取扩展名"""
    if "." in file_name:
        return file_name.rsplit(".", 1)[1].lower()
    return "bin"


def download_message_resource(
    client: lark.Client,
    message_id: str,
    file_key: str,
    msg_type: str,  # "file" or "image"
    file_name: str = "unknown",
) -> tuple[bool, str, str]:
    """
    下载消息中的资源文件。

    Returns:
        (success, local_path_or_error_message, file_name)
    """
    ensure_downloads_dir()

    from lark_oapi.api.im.v1 import (
        GetMessageResourceRequest as Req,
    )

    # 构造请求
    request = (
        Req.builder()
        .message_id(message_id)
        .file_key(file_key)
        .type(msg_type)  # "file" or "image"
        .build()
    )

    # 发起下载
    response = client.im.v1.message_resource.get(request)

    if not response.success():
        return False, f"下载失败: code={response.code} msg={response.msg}", file_name

    # 生成本地文件名
    timestamp = int(time.time())
    ext = get_file_extension(file_name) if file_name != "unknown" else "bin"
    local_name = f"{timestamp}_{file_key[:12]}.{ext}"
    local_path = str(DOWNLOADS_DIR / local_name)

    # 写入文件
    with open(local_path, "wb") as f:
        f.write(response.file.read())

    file_size = os.path.getsize(local_path)
    return True, local_path, f"{file_name} ({file_size} bytes)"

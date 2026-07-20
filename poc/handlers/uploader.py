"""
附件上行：上传文件/图片到飞书，并以消息形式发送。
"""

import os
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateFileRequest,
    CreateFileRequestBody,
    CreateImageRequest,
    CreateImageRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)


def upload_file(client: lark.Client, file_path: str) -> tuple[bool, str]:
    """
    上传文件到飞书，获取 file_key。

    Returns:
        (success, file_key_or_error)
    """
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        return False, f"文件不存在: {file_path}"

    body = (
        CreateFileRequestBody.builder()
        .file_type("stream")
        .file_name(file_path_obj.name)
        .file(open(file_path, "rb"))
        .build()
    )

    request = (
        CreateFileRequest.builder()
        .request_body(body)
        .build()
    )

    response = client.im.v1.file.create(request)

    if not response.success():
        return False, f"上传失败: code={response.code} msg={response.msg}"

    return True, response.data.file_key


def upload_image(client: lark.Client, image_path: str) -> tuple[bool, str]:
    """
    上传图片到飞书，获取 image_key。

    Returns:
        (success, image_key_or_error)
    """
    image_path_obj = Path(image_path)
    if not image_path_obj.exists():
        return False, f"图片不存在: {image_path}"

    ext = image_path_obj.suffix.lower()
    image_type = "jpg"
    if ext in (".png",):
        image_type = "png"
    elif ext in (".gif",):
        image_type = "gif"
    elif ext in (".webp",):
        image_type = "webp"

    body = (
        CreateImageRequestBody.builder()
        .image_type(image_type)
        .image(open(image_path, "rb"))
        .build()
    )

    request = (
        CreateImageRequest.builder()
        .request_body(body)
        .build()
    )

    response = client.im.v1.image.create(request)

    if not response.success():
        return False, f"图片上传失败: code={response.code} msg={response.msg}"

    return True, response.data.image_key


def send_text(client: lark.Client, chat_id: str, text: str,
              reply_message_id: str = None) -> bool:
    """发送文字消息。如果有 reply_message_id 则回复消息，否则发送新消息。"""
    content = lark.JSON.marshal({"text": text})

    if reply_message_id:
        body = (
            ReplyMessageRequestBody.builder()
            .content(content)
            .msg_type("text")
            .build()
        )
        request = (
            ReplyMessageRequest.builder()
            .message_id(reply_message_id)
            .request_body(body)
            .build()
        )
        response = client.im.v1.message.reply(request)
    else:
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(content)
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        response = client.im.v1.message.create(request)

    if not response.success():
        print(f"  发送文字失败: code={response.code} msg={response.msg}")
        return False
    return True


def send_file(client: lark.Client, chat_id: str, file_key: str,
              reply_message_id: str = None) -> bool:
    """发送文件消息"""
    content = lark.JSON.marshal({"file_key": file_key})

    if reply_message_id:
        body = (
            ReplyMessageRequestBody.builder()
            .content(content)
            .msg_type("file")
            .build()
        )
        request = (
            ReplyMessageRequest.builder()
            .message_id(reply_message_id)
            .request_body(body)
            .build()
        )
        response = client.im.v1.message.reply(request)
    else:
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("file")
            .content(content)
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        response = client.im.v1.message.create(request)

    if not response.success():
        print(f"  发送文件失败: code={response.code} msg={response.msg}")
        return False
    return True


def send_image(client: lark.Client, chat_id: str, image_key: str,
               reply_message_id: str = None) -> bool:
    """发送图片消息"""
    content = lark.JSON.marshal({"image_key": image_key})

    if reply_message_id:
        body = (
            ReplyMessageRequestBody.builder()
            .content(content)
            .msg_type("image")
            .build()
        )
        request = (
            ReplyMessageRequest.builder()
            .message_id(reply_message_id)
            .request_body(body)
            .build()
        )
        response = client.im.v1.message.reply(request)
    else:
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("image")
            .content(content)
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        response = client.im.v1.message.create(request)

    if not response.success():
        print(f"  发送图片失败: code={response.code} msg={response.msg}")
        return False
    return True

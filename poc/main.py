"""
飞书 Bot POC — 主入口

长连接接收飞书消息，支持：
- M1: Echo 基线 — 收到文字消息原文回复
- M2: 附件下行 — 文件/图片下载到本地
- M3: 附件上行 — 回复文字 + 文件
- M4: 消息配对聚合 — SessionAggregator 聚合 text + file
- M5: 健壮性 — 幂等去重 + 3 秒时限 + 断线重连

用法：
    cp .env.example .env   # 填入 FEISHU_APP_ID / FEISHU_APP_SECRET
    python main.py
"""

import os
import sys
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

# ─── 加载 .env ──────────────────────────────────────────────
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

APP_ID = os.environ.get("FEISHU_APP_ID")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET")

if not APP_ID or not APP_SECRET:
    print("❌ 请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量或 .env 文件")
    sys.exit(1)

# ─── 全局组件 ───────────────────────────────────────────────
from aggregator import SessionAggregator

aggregator = SessionAggregator(window_seconds=15.0)
executor = ThreadPoolExecutor(max_workers=4)

# 全局 client 引用，在 main() 中初始化
_client: lark.Client = None
_processed_echo = 0


# ═══════════════════════════════════════════════════════════════
#  事件处理器（在主线程运行，必须在 3 秒内返回）
# ═══════════════════════════════════════════════════════════════

def handle_message(data: P2ImMessageReceiveV1) -> None:
    global _processed_echo

    try:
        event = data.event
        if not event or not event.message:
            return

        msg = event.message
        message_id = msg.message_id
        chat_id = msg.chat_id
        sender_id = event.sender.sender_id.open_id
        msg_type = msg.message_type
        content_str = msg.content or ""

        # ── M5: 幂等去重 ──
        if aggregator.is_duplicate(message_id):
            print(f"  ⏭️ 跳过重复消息: {message_id}")
            return
        aggregator.mark_processed(message_id)

        print(f"\n📩 [{msg_type}] chat={chat_id} sender={sender_id[:12]}...")

        try:
            content = json.loads(content_str)
        except json.JSONDecodeError:
            content = {}

        if msg_type == "text":
            text = content.get("text", "")
            # 清洗 HTML 标签（飞书 Thread 回复消息会带 <p> 等标签）
            import re
            text = re.sub(r'<[^>]+>', '', text).strip()
            # 清洗 @机器人 提及标记
            if hasattr(msg, 'mentions') and msg.mentions:
                for m in msg.mentions:
                    key = getattr(m, 'key', '') or ''
                    if key.startswith('@'):
                        text = text.replace(key, '').strip()
            print(f"  💬 {text[:80]}")
            flushed = aggregator.feed_text(chat_id, sender_id, message_id, text)
            if flushed:
                executor.submit(process_session, flushed)

        elif msg_type == "file":
            file_key = content.get("file_key", "")
            file_name = content.get("file_name", "unknown")
            print(f"  📎 {file_name}  key={file_key[:16]}...")
            aggregator.feed_file(chat_id, sender_id, message_id,
                                 file_key, file_name, "file")

        elif msg_type == "image":
            image_key = content.get("image_key", "")
            print(f"  🖼️ key={image_key[:16]}...")
            aggregator.feed_file(chat_id, sender_id, message_id,
                                 image_key, f"img_{message_id[:8]}.png", "image")

        else:
            print(f"  ⚠️ 未处理类型: {msg_type}")
    except Exception as e:
        print(f"  ❌ 处理消息异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════
#  聚合器 tick 定时器 + 会话处理
# ═══════════════════════════════════════════════════════════════

def aggregator_loop():
    """每 2 秒检查一次超时会话，提交到线程池处理"""
    while True:
        time.sleep(2.0)
        expired = aggregator.tick()
        for session in expired:
            print(f"\n⏰ 会话超时: chat={session.chat_id}")
            executor.submit(process_session, session)


def process_session(session):
    """处理聚合会话（在线程池运行，可超过 3 秒）"""
    try:
        from handlers.downloader import download_message_resource
        from handlers.uploader import send_text, send_file, upload_file

        client = _client
        chat_id = session.chat_id

        if session.has_text and session.has_files:
            # ── 文字 + 附件 ──
            print(f"  📋 文字+附件: {session.text[:60]}")

            downloaded_paths = []
            for f in session.files:
                success, result, name = download_message_resource(
                    client, f["message_id"], f["file_key"],
                    f["msg_type"], f["file_name"],
                )
                if success:
                    print(f"  ✅ 下载: {result}")
                    downloaded_paths.append(result)
                else:
                    print(f"  ⚠️ {result}")

            # 回复文字
            send_text(client, chat_id, f"收到: {session.text}",
                      reply_message_id=session.text_message_id)

            # M3: 上传并回传文件
            for file_path in downloaded_paths:
                success, file_key = upload_file(client, file_path)
                if success:
                    send_file(client, chat_id, file_key,
                              reply_message_id=session.text_message_id)
                    print(f"  ✅ 回传文件: {file_key[:16]}...")
                else:
                    print(f"  ⚠️ 上传失败: {file_key}")

        elif session.has_text and not session.has_files:
            # ── 纯文字：Echo ──
            global _processed_echo
            _processed_echo += 1
            print(f"  📋 纯文字 #{_processed_echo}: {session.text[:60]}")

            # #7 耗时任务模拟
            if session.text == "\u6d4b\u8bd5\u8017\u65f6":
                print("  \u23f3 \u6a21\u62df\u8017\u65f6 10s...")
                import time
                time.sleep(10)
                print("  \u2705 \u8017\u65f6\u4efb\u52a1\u5b8c\u6210\uff0c\u56de\u590d")

            send_text(client, chat_id, session.text,
                      reply_message_id=session.text_message_id)

        elif not session.has_text and session.has_files:
            # ── 仅附件 ──
            print(f"  📋 仅附件，无文字指令")
            for f in session.files:
                success, result, name = download_message_resource(
                    client, f["message_id"], f["file_key"],
                    f["msg_type"], f["file_name"],
                )
                if success:
                    print(f"  ✅ 下载: {result}")

            send_text(client, chat_id, "收到附件，但未附带文字指令，请发送文字说明。")
    except Exception as e:
        print(f"  ❌ process_session 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def main():
    global _client

    print(f"🚀 飞书 Bot POC")
    print(f"   App ID: {APP_ID[:12]}...")
    print(f"   聚合窗口: {aggregator.window_seconds}s")
    print()

    # 创建 API 客户端（全局单例）
    client = (
        lark.Client.builder()
        .app_id(APP_ID)
        .app_secret(APP_SECRET)
        .build()
    )
    _client = client

    # 注册事件处理器
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_message)
        .build()
    )

    # 长连接 WebSocket 客户端
    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )

    # 启动聚合器定时器（守护线程）
    tick_thread = threading.Thread(target=aggregator_loop, daemon=True)
    tick_thread.start()

    print("✅ 正在连接飞书长连接...")
    print("   控制台看到 connected to wss:// 即表示成功")
    print("   按 Ctrl+C 停止\n")

    try:
        ws_client.start()
    except KeyboardInterrupt:
        print("\n👋 已停止")


if __name__ == "__main__":
    main()

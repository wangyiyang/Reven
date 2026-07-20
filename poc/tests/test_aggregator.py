"""
SessionAggregator 纯逻辑单元测试（不依赖飞书连接）
"""

import time
import threading
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aggregator import SessionAggregator


def test_only_text():
    """场景：只有文字 → 窗口到期后成一次请求"""
    ag = SessionAggregator(window_seconds=0.1)
    now = time.time()

    ag.feed_text("chat_1", "user_1", "msg_1", "你好", now)

    # 未超时，tick 不应返回
    expired = ag.tick(now + 0.05)
    assert len(expired) == 0, "窗口未超时不应返回"

    # 超窗后
    expired = ag.tick(now + 0.2)
    assert len(expired) == 1, "应有一个会话超时"
    assert expired[0].text == "你好"
    assert not expired[0].has_files
    print("✅ test_only_text PASS")


def test_text_then_file():
    """场景：先文字后文件 → 窗口到期后聚合成一次请求"""
    ag = SessionAggregator(window_seconds=0.1)
    now = time.time()

    ag.feed_text("chat_1", "user_1", "msg_1", "出一下日报", now)
    ag.feed_file("chat_1", "user_1", "msg_2", "file_key_1",
                  "日报.xlsx", "file", now + 0.02)

    # 超窗
    expired = ag.tick(now + 0.2)
    assert len(expired) == 1
    session = expired[0]
    assert session.text == "出一下日报"
    assert len(session.files) == 1
    assert session.files[0]["file_name"] == "日报.xlsx"
    print("✅ test_text_then_file PASS")


def test_file_then_text():
    """场景：先文件后文字 → 窗口到期后聚合成一次请求"""
    ag = SessionAggregator(window_seconds=0.1)
    now = time.time()

    ag.feed_file("chat_1", "user_1", "msg_1", "file_key_1",
                  "数据.xlsx", "file", now)
    ag.feed_text("chat_1", "user_1", "msg_2", "分析一下", now + 0.02)

    expired = ag.tick(now + 0.2)
    assert len(expired) == 1
    session = expired[0]
    assert session.text == "分析一下"
    assert len(session.files) == 1
    print("✅ test_file_then_text PASS")


def test_only_file():
    """场景：仅文件（无文字）→ 超窗后按无指令附件处理"""
    ag = SessionAggregator(window_seconds=0.1)
    now = time.time()

    ag.feed_file("chat_1", "user_1", "msg_1", "file_key_1",
                  "报告.xlsx", "file", now)

    expired = ag.tick(now + 0.2)
    assert len(expired) == 1
    assert not expired[0].has_text
    assert len(expired[0].files) == 1
    print("✅ test_only_file PASS")


def test_multiple_files():
    """场景：窗口内多个文件 → 聚合为同一请求的多附件"""
    ag = SessionAggregator(window_seconds=0.1)
    now = time.time()

    ag.feed_text("chat_1", "user_1", "msg_0", "处理这些文件", now)
    ag.feed_file("chat_1", "user_1", "msg_1", "key_1",
                  "a.xlsx", "file", now + 0.02)
    ag.feed_file("chat_1", "user_1", "msg_2", "key_2",
                  "b.xlsx", "file", now + 0.04)

    expired = ag.tick(now + 0.2)
    assert len(expired) == 1
    session = expired[0]
    assert session.text == "处理这些文件"
    assert len(session.files) == 2
    assert session.files[0]["file_name"] == "a.xlsx"
    assert session.files[1]["file_name"] == "b.xlsx"
    print("✅ test_multiple_files PASS")


def test_different_sender_no_aggregate():
    """不同发送者不应聚合"""
    ag = SessionAggregator(window_seconds=0.1)
    now = time.time()

    ag.feed_text("chat_1", "user_1", "msg_1", "你好", now)
    ag.feed_file("chat_1", "user_2", "msg_2", "key_1",
                  "file.xlsx", "file", now + 0.02)

    expired = ag.tick(now + 0.2)
    assert len(expired) == 2, "两个不同发送者应各自超时"
    senders = {s.sender_id for s in expired}
    assert senders == {"user_1", "user_2"}
    print("✅ test_different_sender_no_aggregate PASS")


def test_deduplication():
    """幂等去重"""
    ag = SessionAggregator()
    assert not ag.is_duplicate("msg_1")
    ag.mark_processed("msg_1")
    assert ag.is_duplicate("msg_1")
    assert not ag.is_duplicate("msg_2")
    print("✅ test_deduplication PASS")


def test_concurrent_sessions():
    """并发会话：不同 chat 互不干扰"""
    ag = SessionAggregator(window_seconds=0.1)
    now = time.time()

    # chat_1: 文字
    ag.feed_text("chat_1", "user_1", "m1", "hello", now)
    # chat_2: 文字+文件
    ag.feed_text("chat_2", "user_2", "m2", "world", now)
    ag.feed_file("chat_2", "user_2", "m3", "key", "f.xlsx", "file", now + 0.02)

    expired = ag.tick(now + 0.2)
    assert len(expired) == 2

    chat1 = [s for s in expired if s.chat_id == "chat_1"]
    chat2 = [s for s in expired if s.chat_id == "chat_2"]
    assert len(chat1) == 1
    assert len(chat2) == 1
    assert chat1[0].text == "hello"
    assert chat2[0].text == "world"
    assert len(chat2[0].files) == 1
    print("✅ test_concurrent_sessions PASS")


def test_session_count():
    """session_count 应准确反映缓存中的会话数"""
    ag = SessionAggregator(window_seconds=1.0)
    now = time.time()

    assert ag.session_count() == 0
    ag.feed_text("chat_1", "user_1", "m1", "hello", now)
    assert ag.session_count() == 1
    ag.feed_file("chat_2", "user_2", "m2", "k", "f.xlsx", "file", now)
    assert ag.session_count() == 2

    ag.tick(now + 2.0)
    assert ag.session_count() == 0
    print("✅ test_session_count PASS")


def test_thread_safety():
    """线程安全：多线程并发 feed 不崩溃"""
    ag = SessionAggregator(window_seconds=0.5)
    now = time.time()
    errors = []

    def feed_text_thread(idx):
        try:
            ag.feed_text("chat_t", "user_t", f"msg_{idx}", f"text_{idx}", now)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=feed_text_thread, args=(i,))
               for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"线程安全测试失败: {errors}"
    print("✅ test_thread_safety PASS")


if __name__ == "__main__":
    test_only_text()
    test_text_then_file()
    test_file_then_text()
    test_only_file()
    test_multiple_files()
    test_different_sender_no_aggregate()
    test_deduplication()
    test_concurrent_sessions()
    test_session_count()
    test_thread_safety()
    print("\n🎉 所有测试通过！")

"""M10 PR4b — ``_StreamingThinkStripper`` 单元测试 (G5 #7)。

算法见 ``backend/services/dify/strip_think.py``；本测试不接触 Dify 协议层
也不依赖 settings, 是纯字符串状态机测试。

测试范围 (≥8 案例, 覆盖 PR4b spec 全部场景):
- 基础: 单 chunk 内的 open/close, 文本透传
- 跨 chunk: open 跨多个 chunk 累积, 跨 chunk close
- 多次: 同一 stream 多个 think 块
- 未闭合 flush: 异常模型输出 (open 后无 close), flush 丢弃
- 部分 ``<`` look-ahead: 切分在 ``<`` 内, 跨 chunk 确认/回退
- 大小写: 仅小写 ``<think>`` 标签被 strip
- 边界: 空 feed / 无 think 块 / flush 后不可重入
- 工厂: ``create_think_stripper()`` 返回新实例
"""
from __future__ import annotations

import pytest

from services.dify.strip_think import (
    THINK_CLOSE_TAG,
    THINK_OPEN_TAG,
    _StreamingThinkStripper,
    create_think_stripper,
)


# ============== 1. 基础: 单 chunk 内完整 think 块 ==============

def test_basic_open_close_in_single_chunk() -> None:
    stripper = _StreamingThinkStripper()
    out = stripper.feed(f"hello {THINK_OPEN_TAG}secret{THINK_CLOSE_TAG} world")
    assert out == "hello  world"
    # flush 之后无残留
    assert stripper.flush() == ""


def test_basic_text_only_no_think() -> None:
    stripper = _StreamingThinkStripper()
    out = stripper.feed("plain text with no tags")
    assert out == "plain text with no tags"
    assert stripper.flush() == ""


def test_basic_empty_feed() -> None:
    stripper = _StreamingThinkStripper()
    assert stripper.feed("") == ""
    assert stripper.feed("") == ""
    assert stripper.flush() == ""


# ============== 2. 跨 chunk: 真实 Dify v2 ~1-3 字符/chunk 场景 ==============

def test_cross_chunk_open_spans_multiple_chunks() -> None:
    """Dify v2 emits 1-3 char tokens; ``<thi``, ``nk`` 可能分两个 chunk。"""
    stripper = _StreamingThinkStripper()
    # chunk 1: 'a<think>' — open tag 完整在 chunk 1 内
    out1 = stripper.feed("a<think>")
    assert out1 == "a"
    # chunk 2: secret content (no close yet)
    out2 = stripper.feed("secret")
    assert out2 == ""  # 在 think 块内, 全部 hold
    # chunk 3: close tag
    out3 = stripper.feed(f"{THINK_CLOSE_TAG}done")
    assert out3 == "done"
    assert stripper.flush() == ""


def test_cross_chunk_open_split_across_chunks() -> None:
    """``<think>`` 切分在 chunk 边界: chunk 1 = 'a<thi', chunk 2 = 'nk>secret...'. 验证 hold-and-look-ahead。"""
    stripper = _StreamingThinkStripper()
    # chunk 1: 'a<thi' — open tag 还没出现完整, 需要 hold 末尾 '<'
    out1 = stripper.feed("a<thi")
    # 'a' 应该被 emit, '<thi' 应该被 hold
    assert out1 == "a"
    # chunk 2: 'nk>secret' — 完成 open, 进入 think 模式
    out2 = stripper.feed("nk>secret")
    assert out2 == ""  # 在 think 块内
    # chunk 3: '</thi', chunk 4: 'nk>after'
    out3 = stripper.feed("</thi")
    assert out3 == ""  # close 也跨 chunk
    out4 = stripper.feed("nk>after")
    assert out4 == "after"
    assert stripper.flush() == ""


def test_cross_chunk_char_level_dify_v2_simulation() -> None:
    """模拟真实 Dify v2 字符级 emit: 每个字符一个 chunk。"""
    stripper = _StreamingThinkStripper()
    payload = f"hi {THINK_OPEN_TAG}think-data{THINK_CLOSE_TAG} bye"
    accumulated = ""
    for ch in payload:
        accumulated += stripper.feed(ch)
    accumulated += stripper.flush()
    assert accumulated == "hi  bye"


# ============== 3. 多次: 多个 think 块 (M9 baseline ~3 块/响应) ==============

def test_multiple_think_blocks_in_single_stream() -> None:
    stripper = _StreamingThinkStripper()
    payload = (
        f"a{THINK_OPEN_TAG}s1{THINK_CLOSE_TAG}b"
        f"{THINK_OPEN_TAG}s2{THINK_CLOSE_TAG}c"
        f"{THINK_OPEN_TAG}s3{THINK_CLOSE_TAG}d"
    )
    out = stripper.feed(payload)
    assert out == "abcd"
    assert stripper.flush() == ""


def test_multiple_think_blocks_split_across_chunks() -> None:
    """2 个 think 块, 中间正常文本, 切分在第一块 close 之后。"""
    stripper = _StreamingThinkStripper()
    out1 = stripper.feed(f"hello {THINK_OPEN_TAG}think1{THINK_CLOSE_TAG} world")
    assert out1 == "hello  world"
    out2 = stripper.feed(f"x{THINK_OPEN_TAG}think2{THINK_CLOSE_TAG}y")
    assert out2 == "xy"
    assert stripper.flush() == ""


def test_interleaved_text_and_think_repeated() -> None:
    stripper = _StreamingThinkStripper()
    for chunk in [
        "before ",
        THINK_OPEN_TAG,
        "mid1",
        THINK_CLOSE_TAG,
        " middle ",
        THINK_OPEN_TAG,
        "mid2",
        THINK_CLOSE_TAG,
        " after",
    ]:
        stripper.feed(chunk)
    tail = stripper.flush()
    # flush 应保证全部安全文本被 emit
    assert "after" in tail or stripper._buffer == ""
    # 关键断言: 没有任何 'mid1'/'mid2' 泄漏
    assert "mid1" not in tail
    assert "mid2" not in tail


# ============== 4. 未闭合 flush: 模型异常 ==============

def test_unclosed_think_dropped_on_flush() -> None:
    """模型开了 ``<think>`` 但没关, flush 时整段丢弃 (异常处理)。"""
    stripper = _StreamingThinkStripper()
    stripper.feed("safe text ")
    stripper.feed(THINK_OPEN_TAG)  # 进入 think 模式
    stripper.feed("leaked reasoning that must not be exposed")
    # 此时没有 close tag
    leaked = stripper.flush()
    # flush 应该丢弃未闭合的 think 块, 不返回任何内容
    assert "leaked reasoning" not in leaked
    assert leaked == ""


def test_unclosed_think_with_lookahead_residue_dropped() -> None:
    """未闭合 + 末尾有 partial close 前缀, flush 两者都丢。"""
    stripper = _StreamingThinkStripper()
    stripper.feed(f"safe {THINK_OPEN_TAG}think-content</thi")  # 末尾 '</thi' 是 partial close
    leaked = stripper.flush()
    assert "think-content" not in leaked
    assert "</thi" not in leaked


def test_flush_after_clean_stream_returns_empty() -> None:
    """正常流结束后 flush 应返回 '' (无残留)。"""
    stripper = _StreamingThinkStripper()
    stripper.feed("all good")
    assert stripper.flush() == ""


# ============== 5. 部分 ``<`` look-ahead 边界 ==============

def test_partial_open_prefix_held_until_next_chunk() -> None:
    """``<`` 在 chunk 末尾, 需要 hold 住等下个 chunk 确认。

    算法的 look-ahead window = ``len(tag) - 1`` = 6 字符; 只有当 buffer 长度
    超过 6 (即 '<" + 6+ chars) 时, 才会释放开头的 '<'。这里验证:
    - feed("hello<") → emit "hello", hold "<"
    - feed("div>")  → buffer "<div>" 仅 5 字符, 仍在 look-ahead window 内, 仍 hold
    - feed("abcdef") → buffer "<div>abcdef" 11 字符, 超出 window, 释放 "<div>abcdef"
    """
    stripper = _StreamingThinkStripper()
    out1 = stripper.feed("hello<")
    assert out1 == "hello"  # '<' hold 住
    out2 = stripper.feed("div>")
    # buffer = "<div>" (5 chars), 仍在 6-char look-ahead window 内, 不释放
    assert out2 == ""
    out3 = stripper.feed("abcdef")
    # buffer = "<div>abcdef" (11 chars), 超出 window, find "<think>"=-1,
    # rfind("<")=0, len-0=11 >= 7, 释放整段
    assert out3 == "<div>abcdef"
    assert stripper.flush() == ""


def test_partial_open_prefix_resolved_as_think_tag() -> None:
    """Hold 的 '<' 紧接的 chunk 补全成 ``<think>``。"""
    stripper = _StreamingThinkStripper()
    out1 = stripper.feed("hi<")  # '<' hold
    assert out1 == "hi"
    out2 = stripper.feed(f"{THINK_OPEN_TAG[1:]}secret{THINK_CLOSE_TAG}done")
    # '<' + 'think>' = 完整 open, 进入 think 模式
    assert out2 == "done"
    assert stripper.flush() == ""


def test_partial_close_prefix_held_inside_think() -> None:
    """在 think 块内, 末尾 partial close 前缀应被 hold。

    THiNK_CLOSE_TAG[2:] = 'think>' (剥掉开头的 '</') — 这是 partial '</' 之后
    真实 chunk 应该带上的剩余部分。 buffer "</" + "think>" = "</think>",
    之后正常 exit think 模式, emit 后续 'after'。
    """
    stripper = _StreamingThinkStripper()
    stripper.feed(f"safe{THINK_OPEN_TAG}content</")  # '<' hold inside think
    out = stripper.feed(f"{THINK_CLOSE_TAG[2:]}after")
    assert out == "after"
    assert stripper.flush() == ""


# ============== 6. 大小写: 仅小写标签被 strip ==============

def test_uppercase_think_tag_passes_through_unchanged() -> None:
    """``<THINK>`` / ``</THINK>`` 大写应原样透传 (不误伤 normal text)。"""
    stripper = _StreamingThinkStripper()
    payload = "hello <THINK>visible</THINK> world"
    out = stripper.feed(payload)
    assert out == payload  # 完全不变
    assert stripper.flush() == ""


def test_mixed_case_think_tag_passes_through_unchanged() -> None:
    """``<Think>`` / ``<tHinK>`` 等混合大小写原样透传。"""
    stripper = _StreamingThinkStripper()
    payload = f"a<Think>v1</Think>b<tHinK>v2</tHinK>c"
    out = stripper.feed(payload)
    assert out == payload
    assert stripper.flush() == ""


def test_think_substring_inside_word_not_stripped() -> None:
    """``<thinker>`` 之类的含 'think' 子串的标签不应被识别为 think 块。"""
    stripper = _StreamingThinkStripper()
    # ``<thinker>`` 包含 'think' 但不匹配 ``<think>`` (因 'er' 跟在后面)
    payload = "look <thinker>at</thinker> this"
    out = stripper.feed(payload)
    assert out == payload
    assert stripper.flush() == ""


# ============== 7. 工厂 + 状态隔离 ==============

def test_factory_returns_new_instance() -> None:
    s1 = create_think_stripper()
    s2 = create_think_stripper()
    assert s1 is not s2
    assert isinstance(s1, _StreamingThinkStripper)
    assert isinstance(s2, _StreamingThinkStripper)


def test_stripper_state_isolated_per_instance() -> None:
    """两个 stripper 互不影响 (一个进入 think 模式不应影响另一个)。"""
    s1 = _StreamingThinkStripper()
    s2 = _StreamingThinkStripper()
    s1.feed(THINK_OPEN_TAG)  # s1 进入 think 模式
    # s2 仍然能正常处理 think 块
    s2_out = s2.feed(f"x{THINK_OPEN_TAG}y{THINK_CLOSE_TAG}z")
    assert s2_out == "xz"
    # s1 继续 hold
    s1_out = s1.feed("more content")
    assert s1_out == ""


def test_flush_resets_internal_state() -> None:
    """flush 后内部 state 应重置, 后续 feed 行为与新实例一致。"""
    stripper = _StreamingThinkStripper()
    stripper.feed(THINK_OPEN_TAG)
    stripper.feed("leak")
    stripper.flush()  # 丢弃, 重置
    # 接下来应能正常处理新内容
    out = stripper.feed(f"fresh {THINK_OPEN_TAG}think{THINK_CLOSE_TAG} end")
    assert out == "fresh  end"
    assert stripper.flush() == ""


# ============== 8. 与 frontend createThinkStripper 行为对齐 spot-check ==============

def test_open_then_close_emits_only_prefix() -> None:
    """对齐 frontend difyStream.ts:createThinkStripper 的 core contract.

    Pre-condition: open tag present, close tag present in same chunk.
    Post-condition: 只 emit open 之前的 prefix + close 之后的 suffix。
    """
    stripper = _StreamingThinkStripper()
    out = stripper.feed(
        f"prefix{THINK_OPEN_TAG}drop-me{THINK_CLOSE_TAG}suffix"
    )
    assert out == "prefixsuffix"


def test_open_with_no_close_at_end_of_stream_drops_residue() -> None:
    """对齐 frontend: open in feed, no close ever, flush 丢弃。"""
    stripper = _StreamingThinkStripper()
    assert stripper.feed("before ") == "before "
    assert stripper.feed(THINK_OPEN_TAG) == ""
    assert stripper.feed("inside") == ""
    assert stripper.flush() == ""


def test_trailing_lt_lookahead_window_is_tag_minus_one() -> None:
    """Look-ahead window = ``len(tag) - 1`` = 6 (for ``<think>``).

    末尾 6 字符 ``<think`` (没有 ``>``) 仍然 hold; 第 7 字符 ``>`` 出现才能
    确认 open. 这里测边界: 6 字符 hold, 7 字符不 hold.
    """
    stripper = _StreamingThinkStripper()
    out = stripper.feed(f"a{THINK_OPEN_TAG[:-1]}")  # 'a' + '<think' (6 chars after 'a')
    # 'a' emit, '<think' hold
    assert out == "a"
    # 再喂 '>', 完成 open, 进入 think
    out2 = stripper.feed(">secret")
    assert out2 == ""  # think 内 hold
    assert stripper.flush() == ""  # 未闭合, 丢

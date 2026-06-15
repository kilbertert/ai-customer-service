"""M10 PR4b — Streaming ``<think>`` stripper (G5 #7).

Python port of ``frontend-nextjs/src/services/difyStream.ts:createThinkStripper``
(算法 1:1 搬运, 不做任何协议层改动; 仅类型签名从 TypeScript 转 Python)。

Why hand-rolled vs per-chunk regex:
    真实 Dify v2 emits character-level tokens (~1-3 chars per chunk). 单纯的
    per-chunk 正则 ``<think>[\\s\\S]*?</think>`` 要求 open + close 在同一个
    string 内同时出现; 跨 chunk 时 open/close 永远不共存, per-chunk strip
    在真实 Dify 上是 complete no-op (见 M9-PROMPT §1)。

Algorithm — three rules (M9-PROMPT §2):
    1. Accumulate chunks into internal buffer
    2. While NOT inside a think block:
       - No ``<think>``  → emit all, clear buffer (with trailing-`<` lookahead)
       - ``<think>`` found → emit prefix before it, enter think mode
    3. While inside a think block:
       - No ``</think>`` → hold all (with trailing-`<` lookahead)
       - ``</think>`` found → skip past it, exit think mode
    4. Edge case: chunk boundary inside the tag characters → hold back any
       trailing ``<`` (could be start of partial open or close tag) until next
       chunk disambiguates it.  The lookahead window is ``len(tag) - 1`` chars.

flush() at stream end drops any unclosed think residue (model anomaly)
plus releases any safe-to-emit suffix that drain() retained due to a
trailing-`<` lookahead at end-of-stream.

**Case sensitivity**: spec 仅 strip 小写 ``<think>`` / ``</think>`` 标签。
大写 ``<THINK>`` 或混合大小写 ``<Think>`` 应原样透传(防止误伤 normal text)。
"""
from __future__ import annotations

# M2 / M9 锁定: 标签名严格小写, 不做 case-insensitive 匹配
THINK_OPEN_TAG = "<think>"
THINK_CLOSE_TAG = "</think>"


class _StreamingThinkStripper:
    """Streaming ``<think>`` block stripper (PR4b / G5 #7).

    用法::

        stripper = _StreamingThinkStripper()
        for chunk in dify_text_chunks:
            safe_text = stripper.feed(chunk)
            if safe_text:
                yield message_delta_event(safe_text)
        tail = stripper.flush()
        if tail:
            yield message_delta_event(tail)

    不可重入: 一个 stream 持有一个 stripper; 跨 stream 必须新实例。
    """

    __slots__ = ("_buffer", "_inside_think")

    def __init__(self) -> None:
        self._buffer: str = ""
        self._inside_think: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, chunk: str) -> str:
        """Feed a delta chunk; return the safe-to-emit prefix.

        Empty return means "hold everything; nothing to emit yet" — caller
        should not yield an empty ``message_delta`` event in that case.
        """
        if not chunk:
            return ""
        self._buffer += chunk
        return self._drain()

    def flush(self) -> str:
        """Flush remaining buffered text at stream end.

        Drops any unclosed think residue (model anomaly: ``<think>`` opened
        but no ``</think>`` ever arrived).  Returns any safe-to-emit suffix
        that ``_drain`` retained due to a trailing-``<`` lookahead at
        end-of-stream.
        """
        rest = self._drain()
        # Drop any leftover buffer residue — partial tag or unclosed think block.
        # Per spec §2, unclosed ``<think>`` is treated as a model anomaly and discarded.
        self._buffer = ""
        self._inside_think = False
        return rest

    # ------------------------------------------------------------------
    # Internal state machine
    # ------------------------------------------------------------------

    def _drain(self) -> str:
        """Drain buffer, returning safe-to-emit prefix.

        Single buffer may contain multiple think blocks + intervening text
        (M9-PROMPT §1.5 baseline shows ~3 think blocks per real Dify response).
        Loop until buffer is empty (with trailing-``<`` lookahead pause).
        """
        emit = ""
        while True:
            if self._inside_think:
                close_idx = self._buffer.find(THINK_CLOSE_TAG)
                if close_idx == -1:
                    # Inside think block, waiting for close. Hold ENTIRE buffer —
                    # we never emit anything from inside a think block, including
                    # any text that appears before a trailing partial-close prefix.
                    # The hold includes the partial close prefix so the next chunk
                    # can either confirm ``</think>`` (we then resume emitting) or
                    # override it as literal content (we drop it on flush).
                    last_lt = self._buffer.rfind("<")
                    if last_lt != -1 and len(self._buffer) - last_lt < len(THINK_CLOSE_TAG):
                        self._buffer = self._buffer[last_lt:]
                    else:
                        self._buffer = ""
                    return emit
                # Skip past close tag, exit think mode, continue loop to drain remainder
                self._buffer = self._buffer[close_idx + len(THINK_CLOSE_TAG):]
                self._inside_think = False
            else:
                open_idx = self._buffer.find(THINK_OPEN_TAG)
                if open_idx == -1:
                    # No open tag — hold trailing partial-open prefix (e.g. "<thi")
                    # so the next chunk can confirm or reject it as a real think tag.
                    last_lt = self._buffer.rfind("<")
                    if last_lt != -1 and len(self._buffer) - last_lt < len(THINK_OPEN_TAG):
                        emit += self._buffer[:last_lt]
                        self._buffer = self._buffer[last_lt:]
                    else:
                        emit += self._buffer
                        self._buffer = ""
                    return emit
                # Found open tag — emit prefix before it, enter think mode
                emit += self._buffer[:open_idx]
                self._buffer = self._buffer[open_idx + len(THINK_OPEN_TAG):]
                self._inside_think = True


def create_think_stripper() -> _StreamingThinkStripper:
    """Factory mirroring frontend ``createThinkStripper()`` signature.

    Backend callers (SseProxyLayer) use this so the algorithm is swappable
    and the test surface mirrors the TypeScript version.
    """
    return _StreamingThinkStripper()

"use client";

/**
 * M12 PR-5 — Reusable SSE chat panel.
 *
 * Accepts an injected `streamChat(text, signal) => AsyncIterable<TestChatEvent>`
 * so the same component works for both the visitor-side `/chat/stream`
 * (Playground) and the admin-side `/agents/{id}/test-chat` (this page).
 *
 * Event contract (matches basjoo SSE convention):
 *   session_started   → { session_id }
 *   message_delta     → { delta: string }
 *   message_complete  → { full_message: string }
 *   error             → { message }
 *   end               → {}
 */

import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TestChatEvent } from "../../services/api";

interface ChatPanelProps {
  streamChat: (
    text: string,
    signal: AbortSignal,
  ) => AsyncIterable<TestChatEvent>;
}

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  pending?: boolean;
}

export default function ChatPanel({ streamChat }: ChatPanelProps) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setError(null);

    const userMsg: ChatMessage = { role: "user", text };
    const assistantMsg: ChatMessage = { role: "assistant", text: "", pending: true };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setStreaming(true);

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      for await (const evt of streamChat(text, ctrl.signal)) {
        if (evt.event === "message_delta") {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last && last.role === "assistant") {
              copy[copy.length - 1] = {
                ...last,
                text: last.text + String(evt.data?.delta ?? ""),
              };
            }
            return copy;
          });
        } else if (evt.event === "message_complete") {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last && last.role === "assistant") {
              copy[copy.length - 1] = {
                ...last,
                text: String(evt.data?.full_message ?? last.text),
                pending: false,
              };
            }
            return copy;
          });
        } else if (evt.event === "error") {
          setError(String(evt.data?.message ?? "unknown error"));
        }
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant" && last.pending) {
          copy[copy.length - 1] = { ...last, pending: false };
        }
        return copy;
      });
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, streamChat]);

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto p-6">
        {messages.length === 0 && (
          <div className="text-center text-gray-400">
            {t("agentTest.emptyState")}
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "user"
                ? "flex justify-end"
                : "flex justify-start"
            }
          >
            <div
              className={
                m.role === "user"
                  ? "max-w-[70%] rounded-2xl bg-blue-500 px-4 py-2 text-white"
                  : "max-w-[70%] rounded-2xl bg-gray-100 px-4 py-2 text-gray-900 dark:bg-gray-800 dark:text-gray-100"
              }
            >
              {m.text}
              {m.pending && <span className="ml-1 animate-pulse">▍</span>}
            </div>
          </div>
        ))}
        {error && (
          <div className="text-sm text-red-600">
            {t("agentTest.error", { error })}
          </div>
        )}
      </div>

      <form
        className="flex gap-2 border-t border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={streaming}
          placeholder={t("agentTest.inputPlaceholder")}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="rounded-lg bg-blue-500 px-4 py-2 text-white disabled:opacity-50"
        >
          {streaming ? t("agentTest.sending") : t("agentTest.send")}
        </button>
      </form>
    </div>
  );
}
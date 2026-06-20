"use client";

/**
 * M12 PR-5 — Admin agent test page container.
 *
 * Loads the agent metadata, then renders <TestHeader /> + <ChatPanel />.
 * ChatPanel reuses the visitor-side SSE parsing logic but routes through the
 * admin `testChatAgent()` API method so the API key never leaves the server.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { api } from "../../services/api";
import type { Agent } from "../../services/api";
import TestHeader from "./TestHeader";
import ChatPanel from "./ChatPanel";

interface AgentTestPageProps {
  agentId: string;
}

export default function AgentTestPage({ agentId }: AgentTestPageProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const a = await api.getAgent(agentId);
        if (!cancelled) setAgent(a);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  if (error) {
    return (
      <div className="p-6 text-red-600">
        {t("agentTest.loadError", { error })}
        <button
          type="button"
          className="ml-3 underline"
          onClick={() => router.push("/agents")}
        >
          {t("agentTest.backToList")}
        </button>
      </div>
    );
  }

  if (!agent) {
    return <div className="p-6 text-gray-500">{t("agentTest.loading")}</div>;
  }

  return (
    <div className="flex h-full flex-col">
      <TestHeader agent={agent} />
      <ChatPanel
        streamChat={(text: string, signal: AbortSignal) =>
          api.testChatAgent(agentId, text, signal)
        }
      />
    </div>
  );
}
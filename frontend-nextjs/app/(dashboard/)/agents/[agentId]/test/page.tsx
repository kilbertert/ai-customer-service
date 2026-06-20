"use client";

/**
 * M12 PR-5 — Agent test page route.
 *
 * Renders the per-agent admin test page at `/agents/[agentId]/test`.
 * Mirrors the visitor-side Playground SSE chat experience but binds to the
 * admin-only `POST /api/v1/agents/{id}/test-chat` endpoint and uses the
 * agent's real `dify_workflow_id` (decrypted server-side).
 */

import { use } from "react";
import AgentTestPage from "@/src/components/AgentTestPage";

interface PageProps {
  params: Promise<{ agentId: string }>;
}

export default function TestAgentPage({ params }: PageProps) {
  const { agentId } = use(params);
  return <AgentTestPage agentId={agentId} />;
}
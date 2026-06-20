"use client";

/**
 * M12 PR-5 — Test page header showing agent identity + Dify publish status.
 *
 * NOTE: a standalone <DifyStatusBadge /> component does not yet exist in the
 * project (PR-6 scope), so we render the status inline here. Once PR-6 lands,
 * swap this for the shared badge component.
 */

import { useTranslation } from "react-i18next";

import type { Agent } from "../../services/api";

interface TestHeaderProps {
  agent: Agent;
}

function _statusLabel(status: string | undefined): { text: string; cls: string } {
  switch (status) {
    case "published":
      return { text: "✓ 已发布", cls: "bg-green-100 text-green-700" };
    case "publish_failed":
      return { text: "✗ 发布失败", cls: "bg-red-100 text-red-700" };
    default:
      return { text: "⋯ 草稿", cls: "bg-gray-100 text-gray-600" };
  }
}

export default function TestHeader({ agent }: TestHeaderProps) {
  const { t } = useTranslation();
  const status = _statusLabel(
    (agent as unknown as { dify_publish_status?: string }).dify_publish_status,
  );
  return (
    <header className="flex items-center gap-3 border-b border-gray-200 bg-white px-6 py-3 dark:border-gray-700 dark:bg-gray-900">
      <div className="text-2xl">🤖</div>
      <div className="flex-1">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          {agent.name}
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {agent.description || t("agentTest.noDescription")}
        </p>
      </div>
      <span className={`rounded-full px-3 py-1 text-xs ${status.cls}`}>
        {status.text}
      </span>
    </header>
  );
}
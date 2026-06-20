"use client";

/**
 * M12 PR-6 deferred → M13 — Dify status badge with "重新生成" button.
 *
 * Renders a status pill (草稿 / 已发布 / 发布失败) based on
 * `agent.dify_publish_status`. When the agent has a Dify app bound
 * (i.e. `agent.dify_app_id` is set), shows a "重新生成" button that
 * POSTs to `/api/v1/agents/{id}/regenerate-workflow` and reloads the
 * page on success so the parent re-fetches the agent metadata.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../services/api";
import type { Agent } from "../services/api";

interface DifyStatusBadgeProps {
	agent: Agent;
}

type Status = "draft" | "published" | "publish_failed" | "unknown";

function _resolveStatus(agent: Agent): Status {
	const raw = (agent as unknown as { dify_publish_status?: string })
		.dify_publish_status;
	if (raw === "draft" || raw === "published" || raw === "publish_failed") {
		return raw;
	}
	return "unknown";
}

export function DifyStatusBadge({ agent }: DifyStatusBadgeProps) {
	const { t } = useTranslation();
	const status = _resolveStatus(agent);
	const [isRegenerating, setIsRegenerating] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const canRegenerate = Boolean(
		(agent as unknown as { dify_app_id?: string }).dify_app_id,
	);

	const labelMap: Record<Status, { text: string; cls: string }> = {
		draft: { text: t("difyStatus.draft"), cls: "bg-gray-100 text-gray-600" },
		published: {
			text: t("difyStatus.published"),
			cls: "bg-green-100 text-green-700",
		},
		publish_failed: {
			text: t("difyStatus.publishFailed"),
			cls: "bg-red-100 text-red-700",
		},
		unknown: { text: t("difyStatus.unknown"), cls: "bg-gray-100 text-gray-500" },
	};
	const label = labelMap[status];

	const handleRegenerate = async () => {
		if (isRegenerating) return;
		setError(null);
		setIsRegenerating(true);
		try {
			await api.regenerateWorkflow(agent.id, {});
			if (typeof window !== "undefined") {
				window.location.reload();
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : String(e));
		} finally {
			setIsRegenerating(false);
		}
	};

	return (
		<span
			data-testid="dify-status-badge"
			className="inline-flex items-center gap-2"
		>
			<span
				className={`rounded-full px-3 py-1 text-xs font-medium ${label.cls}`}
			>
				{label.text}
			</span>
			{canRegenerate && (
				<button
					type="button"
					data-testid="dify-regenerate-btn"
					disabled={isRegenerating}
					onClick={handleRegenerate}
					className="rounded-md border border-blue-500 px-3 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50"
				>
					{isRegenerating ? t("difyStatus.regenerating") : t("difyStatus.regenerate")}
				</button>
			)}
			{error && (
				<span className="text-xs text-red-600" role="alert">
					{error}
				</span>
			)}
		</span>
	);
}

export default DifyStatusBadge;
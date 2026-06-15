"use client";

import { useTranslation } from "react-i18next";
import type { Agent, DifyPublishStatus } from "../services/api";

interface DifyStatusBadgeProps {
	agent: Pick<Agent, "dify_workflow_id" | "dify_publish_status" | "dify_publish_error">;
}

const COLOR_MAP: Record<
	DifyPublishStatus,
	{ bg: string; border: string; fg: string; testId: string }
> = {
	draft: {
		bg: "hsla(220deg, 10%, 50%, 0.12)",
		border: "hsla(220deg, 10%, 50%, 0.35)",
		fg: "var(--color-text-secondary)",
		testId: "dify-badge-draft",
	},
	published: {
		bg: "hsla(150deg, 80%, 45%, 0.12)",
		border: "hsla(150deg, 80%, 45%, 0.35)",
		fg: "var(--color-success)",
		testId: "dify-badge-published",
	},
	publish_failed: {
		bg: "hsla(45deg, 90%, 55%, 0.15)",
		border: "hsla(45deg, 90%, 55%, 0.45)",
		fg: "var(--color-warning, #b8860b)",
		testId: "dify-badge-failed",
	},
};

const LABEL_KEY: Record<DifyPublishStatus, string> = {
	draft: "agents.difyStatusDraft",
	published: "agents.difyStatusPublished",
	publish_failed: "agents.difyStatusFailed",
};

/**
 * M10+3 §7.C — Three-color Dify publish status badge.
 *
 * Hidden when the agent is not bound to a Dify workflow (legacy / Plan B
 * agent: dify_workflow_id is null). Renders a small pill with a title
 * tooltip that surfaces the error string for ``publish_failed`` so admins
 * can diagnose without leaving the page.
 */
export function DifyStatusBadge({ agent }: DifyStatusBadgeProps) {
	const { t } = useTranslation("common");

	// Gating: only Dify-bound agents get a badge. Legacy agents (no
	// dify_workflow_id) and Plan B workspaces show nothing.
	if (!agent.dify_workflow_id) return null;

	const status: DifyPublishStatus = agent.dify_publish_status ?? "draft";
	const colors = COLOR_MAP[status];
	const tooltip =
		status === "publish_failed" && agent.dify_publish_error
			? agent.dify_publish_error
			: t(`${LABEL_KEY[status]}Tooltip`);

	return (
		<span
			data-testid={colors.testId}
			title={tooltip}
			aria-label={t(LABEL_KEY[status])}
			style={{
				display: "inline-flex",
				alignItems: "center",
				gap: "var(--space-1)",
				padding: "2px var(--space-2)",
				borderRadius: "999px",
				background: colors.bg,
				border: `1px solid ${colors.border}`,
				color: colors.fg,
				fontSize: "var(--text-xs)",
				fontWeight: 600,
				lineHeight: 1.4,
				whiteSpace: "nowrap",
			}}
		>
			{t(LABEL_KEY[status])}
		</span>
	);
}

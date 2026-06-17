// @ts-nocheck
// @vitest-environment jsdom
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DifyStatusBadge } from "../../src/views/DifyStatusBadge";

vi.mock("react-i18next", () => ({
	useTranslation: () => ({
		t: (key: string) => key,
	}),
}));

function makeAgent(overrides: Record<string, unknown> = {}) {
	return {
		dify_workflow_id: "wf-uuid-1",
		dify_publish_status: "draft" as const,
		dify_publish_error: null,
		...overrides,
	};
}

describe("DifyStatusBadge", () => {
	it("renders nothing when agent has no dify_workflow_id", () => {
		const { container } = render(
			<DifyStatusBadge agent={makeAgent({ dify_workflow_id: null })} />,
		);
		expect(container.firstChild).toBeNull();
	});

	it("renders the draft badge (gray) for draft status", () => {
		render(
			<DifyStatusBadge
				agent={makeAgent({
					dify_publish_status: "draft",
				})}
			/>,
		);
		const badge = screen.getByTestId("dify-badge-draft");
		expect(badge).toBeInTheDocument();
		expect(badge).toHaveTextContent("agents.difyStatusDraft");
		expect(badge).toHaveAttribute("title", "agents.difyStatusDraftTooltip");
	});

	it("renders the published badge (green) for published status", () => {
		render(
			<DifyStatusBadge
				agent={makeAgent({
					dify_publish_status: "published",
				})}
			/>,
		);
		const badge = screen.getByTestId("dify-badge-published");
		expect(badge).toBeInTheDocument();
		expect(badge).toHaveTextContent("agents.difyStatusPublished");
		expect(badge).toHaveAttribute("title", "agents.difyStatusPublishedTooltip");
	});

	it("renders the failed badge (yellow) with error tooltip for publish_failed", () => {
		const errorMsg = "Dify workflow publish failed (likely empty graph validation)";
		render(
			<DifyStatusBadge
				agent={makeAgent({
					dify_publish_status: "publish_failed",
					dify_publish_error: errorMsg,
				})}
			/>,
		);
		const badge = screen.getByTestId("dify-badge-failed");
		expect(badge).toBeInTheDocument();
		expect(badge).toHaveTextContent("agents.difyStatusFailed");
		// Tooltip should surface the raw error string (not the i18n key) so
		// admins can diagnose without leaving the page.
		expect(badge).toHaveAttribute("title", errorMsg);
	});
});

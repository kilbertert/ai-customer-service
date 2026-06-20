/**
 * M13 — DifyStatusBadge tests.
 *
 * 4 tests:
 *   1. test_renders_published_status
 *   2. test_renders_publish_failed_status
 *   3. test_hides_regenerate_button_when_no_dify_app
 *   4. test_shows_regenerate_button_when_dify_app
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import DifyStatusBadge from "./DifyStatusBadge";
import type { Agent } from "../services/api";

vi.mock("react-i18next", () => ({
	useTranslation: () => ({
		t: (key: string) => key,
	}),
}));

vi.mock("../services/api", () => ({
	api: { regenerateWorkflow: vi.fn() },
}));

function makeAgent(overrides: Record<string, unknown> = {}): Agent {
	return {
		id: "agt_test",
		name: "test",
		agent_type: "custom",
		channel_mode: "web_widget",
		...overrides,
	} as unknown as Agent;
}

describe("DifyStatusBadge", () => {
	it("renders published status", () => {
		render(
			<DifyStatusBadge
				agent={makeAgent({
					dify_publish_status: "published",
					dify_app_id: "app-1",
				})}
			/>,
		);
		expect(screen.getByText("difyStatus.published")).toBeTruthy();
	});

	it("renders publish_failed status", () => {
		render(
			<DifyStatusBadge
				agent={makeAgent({
					dify_publish_status: "publish_failed",
					dify_app_id: "app-1",
				})}
			/>,
		);
		expect(screen.getByText("difyStatus.publishFailed")).toBeTruthy();
	});

	it("hides regenerate button when no dify_app_id", () => {
		render(
			<DifyStatusBadge
				agent={makeAgent({ dify_publish_status: "published" })}
			/>,
		);
		expect(screen.queryByTestId("dify-regenerate-btn")).toBeNull();
	});

	it("shows regenerate button when dify_app_id is set", () => {
		render(
			<DifyStatusBadge
				agent={makeAgent({
					dify_publish_status: "published",
					dify_app_id: "app-1",
				})}
			/>,
		);
		expect(screen.getByTestId("dify-regenerate-btn")).toBeTruthy();
	});
});
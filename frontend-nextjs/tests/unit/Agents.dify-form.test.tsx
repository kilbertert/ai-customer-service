// @ts-nocheck
// @vitest-environment jsdom
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Agents from "../../src/views/Agents";
import { api } from "../../src/services/api";

vi.mock("../../src/context/AuthContext", () => ({
	useAuth: () => ({
		admin: {
			id: 1,
			name: "Test Admin",
			email: "test@example.com",
			role: "super_admin",
		},
		token: "test-token",
		logout: vi.fn(),
	}),
}));

vi.mock("react-i18next", () => ({
	useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../src/services/api", () => ({
	api: {
		listAgents: vi.fn(),
		createAgent: vi.fn(),
		deleteAgent: vi.fn(),
		restoreAgent: vi.fn(),
		setSelectedAgentId: vi.fn(),
		clearSelectedAgentId: vi.fn(),
		getSelectedAgentId: vi.fn(),
		kbStatus: vi.fn(),
		kbSetup: vi.fn(),
		getWorkspaceConfig: vi.fn(),
	},
}));

const mockedApi = vi.mocked(api);

const emptyAgent = {
	id: "agt_empty",
	name: "",
	description: "",
	is_active: true,
	deleted_at: null,
};

function renderAgents(workspaceConfig: {
	dify_enabled: boolean;
	dify_api_base: string | null;
	dify_admin_configured: boolean;
}) {
	const router = createMemoryRouter(
		[{ path: "/agents", element: <Agents /> }],
		{ initialEntries: ["/agents"] },
	);
	render(<RouterProvider router={router} />);
	return router;
}

beforeEach(() => {
	vi.clearAllMocks();
	mockedApi.listAgents.mockResolvedValue({ agents: [], total: 0 });
	mockedApi.kbStatus.mockResolvedValue({ kb_setup_completed: false });
});

describe("Agents form — M10+3 Dify integration", () => {
	it("hides the workflow fields when workspace.dify_enabled is false", async () => {
		mockedApi.getWorkspaceConfig.mockResolvedValue({
			dify_enabled: false,
			dify_api_base: null,
			dify_admin_configured: false,
		});
		renderAgents({ dify_enabled: false, dify_api_base: null, dify_admin_configured: false });

		await waitFor(() => {
			expect(mockedApi.getWorkspaceConfig).toHaveBeenCalled();
		});

		expect(screen.queryByTestId("dify-form-section")).toBeNull();
		expect(screen.queryByTestId("dify-workflow-mode")).toBeNull();
		expect(screen.queryByTestId("dify-icon-emoji")).toBeNull();
	});

	it("shows the workflow fields when workspace.dify_enabled is true", async () => {
		mockedApi.getWorkspaceConfig.mockResolvedValue({
			dify_enabled: true,
			dify_api_base: "https://dify.test",
			dify_admin_configured: true,
		});
		renderAgents({ dify_enabled: true, dify_api_base: "https://dify.test", dify_admin_configured: true });

		await waitFor(() => {
			expect(screen.getByTestId("dify-form-section")).toBeInTheDocument();
		});
		expect(screen.getByTestId("dify-workflow-mode")).toBeInTheDocument();
		expect(screen.getByTestId("dify-icon-emoji")).toBeInTheDocument();
	});

	it("clamps the icon emoji input to 4 characters", async () => {
		mockedApi.getWorkspaceConfig.mockResolvedValue({
			dify_enabled: true,
			dify_api_base: "https://dify.test",
			dify_admin_configured: true,
		});
		renderAgents({ dify_enabled: true, dify_api_base: "https://dify.test", dify_admin_configured: true });

		const emojiInput = (await waitFor(() =>
			screen.getByTestId("dify-icon-emoji"),
		)) as HTMLInputElement;
		expect(emojiInput.maxLength).toBe(4);

		const user = userEvent.setup();
		await user.clear(emojiInput);
		await user.type(emojiInput, "🤖🤖🤖🤖EXTRA");
		// The input value is clamped to 4 chars; the "EXTRA" tail is rejected.
		expect(emojiInput.value.length).toBeLessThanOrEqual(4);
	});

	it("redirects to dashboard with a Dify hint when dify_enabled and dify_app_id present", async () => {
		mockedApi.getWorkspaceConfig.mockResolvedValue({
			dify_enabled: true,
			dify_api_base: "https://dify.test",
			dify_admin_configured: true,
		});
		mockedApi.createAgent.mockResolvedValue({
			...emptyAgent,
			id: "agt_with_dify",
			name: "Dify Bot",
			dify_app_id: "app-uuid-1",
			dify_workflow_id: "wf-uuid-1",
			dify_publish_status: "published",
			dify_publish_error: null,
		});
		renderAgents({
			dify_enabled: true,
			dify_api_base: "https://dify.test",
			dify_admin_configured: true,
		});

		const nameInput = (await waitFor(() =>
			screen.getByPlaceholderText("agents.namePlaceholder"),
		)) as HTMLInputElement;

		// Fill in name via fireEvent.change (input has a display-width-aware
		// trim/limit helper, so we feed in a known-good short string).
		fireEvent.change(nameInput, { target: { value: "DifyBot" } });

		const submitBtn = screen.getByRole("button", { name: "agents.create" });
		fireEvent.click(submitBtn);

		await waitFor(() => {
			expect(mockedApi.createAgent).toHaveBeenCalled();
		});

		// The Dify hint modal should be visible (NOT the KB wizard).
		await waitFor(() => {
			expect(screen.getByTestId("dify-hint-modal")).toBeInTheDocument();
		});
		expect(screen.queryByTestId("kb-onboarding-modal")).toBeNull();

		// The "Open in Dify Studio" link should be present with the correct
		// href composed from dify_api_base + dify_app_id.
		const link = screen.getByTestId("dify-open-studio-link");
		expect(link).toHaveAttribute(
			"href",
			"https://dify.test/app/app-uuid-1/workflow",
		);
		expect(link).toHaveAttribute("target", "_blank");
		expect(link).toHaveAttribute("rel", "noopener noreferrer");
	});

	it("keeps the KB wizard when dify_enabled is false (Plan B compat)", async () => {
		mockedApi.getWorkspaceConfig.mockResolvedValue({
			dify_enabled: false,
			dify_api_base: null,
			dify_admin_configured: false,
		});
		mockedApi.createAgent.mockResolvedValue({
			...emptyAgent,
			id: "agt_planb",
			name: "Plan B Bot",
		});
		renderAgents({ dify_enabled: false, dify_api_base: null, dify_admin_configured: false });

		const nameInput = (await waitFor(() =>
			screen.getByPlaceholderText("agents.namePlaceholder"),
		)) as HTMLInputElement;
		fireEvent.change(nameInput, { target: { value: "PlanB" } });

		const submitBtn = screen.getByRole("button", { name: "agents.create" });
		fireEvent.click(submitBtn);

		await waitFor(() => {
			expect(mockedApi.createAgent).toHaveBeenCalled();
		});

		// KB wizard should appear, Dify hint should NOT.
		await waitFor(() => {
			expect(screen.getByTestId("kb-onboarding-modal")).toBeInTheDocument();
		});
		expect(screen.queryByTestId("dify-hint-modal")).toBeNull();
		expect(screen.queryByTestId("dify-form-section")).toBeNull();
	});
});

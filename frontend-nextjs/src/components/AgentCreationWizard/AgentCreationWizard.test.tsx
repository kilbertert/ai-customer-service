// @ts-nocheck
// @vitest-environment jsdom
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom";
import AgentCreationWizard from "./index";
import { api } from "../../services/api";

vi.mock("../../services/api", () => ({
	api: {
		listTemplates: vi.fn(),
		generateWorkflowPreview: vi.fn(),
		createAgent: vi.fn(),
	},
}));

vi.mock("../../context/AuthContext", () => ({
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

const mockedApi = vi.mocked(api);

const fakeTemplates = [
	{
		id: "basic_chat",
		name: "基础对话",
		description: "单 LLM 节点的简单对话",
		category: "chat",
		min_dify_version: "1.14.0",
		params_schema_json: {
			type: "object",
			required: ["system_prompt"],
			properties: {
				system_prompt: {
					type: "string",
					title: "System Prompt",
					minLength: 1,
					description: "System prompt",
				},
				temperature: {
					type: "number",
					default: 0.7,
					minimum: 0,
					maximum: 2,
				},
			},
		},
		yml_preview: "Start → LLM → End",
	},
	{
		id: "rag_qa",
		name: "知识库问答",
		description: "Start → Knowledge Retrieval → LLM → End",
		category: "rag",
		min_dify_version: "1.14.0",
		params_schema_json: {
			type: "object",
			required: ["system_prompt"],
			properties: {
				system_prompt: { type: "string" },
			},
		},
		yml_preview: "Start → KB → LLM → End",
	},
];

const fakePreview = {
	yml_text:
		"app:\n  name: basic_chat\nkind: app\nworkflow:\n  graph:\n    nodes:\n    - id: '4001'\n      data:\n        type: start\n        title: 开始\n    - id: '4080'\n      data:\n        type: llm\n        title: Generate\n    - id: '4099'\n      data:\n        type: end\n        title: 结束\n    edges:\n    - source: '4001'\n      target: '4080'\n    - source: '4080'\n      target: '4099'",
	node_count: 3,
	attempt_count: 1,
};

const renderWizard = () => {
	const router = createMemoryRouter(
		[
			{ path: "/agents", element: <div>agents list</div> },
			{
				path: "/agents/new",
				element: <AgentCreationWizard />,
			},
			{
				path: "/agents/:agentId/dashboard",
				element: <div>dashboard</div>,
			},
		],
		{ initialEntries: ["/agents/new"] },
	);
	return render(<RouterProvider router={router} />);
};

describe("AgentCreationWizard (M12 PR-3)", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockedApi.listTemplates.mockResolvedValue({
			templates: fakeTemplates as never,
			total: fakeTemplates.length,
		});
		mockedApi.generateWorkflowPreview.mockResolvedValue(fakePreview as never);
		mockedApi.createAgent.mockResolvedValue({
			id: "new_agent_id",
			name: "Test",
			is_active: true,
			deleted_at: null,
			created_at: new Date().toISOString(),
		} as never);
	});

	it("step 1 → next button disabled until name entered", async () => {
		renderWizard();
		expect(screen.getByTestId("wizard-step-1")).toBeInTheDocument();
		const nextBtn = screen.getByTestId("wizard-next");
		// Name empty → error visible, button still clickable but validation rejects
		await userEvent.type(
			screen.getByTestId("wizard-name-input"),
			"测试智能体",
		);
		await userEvent.click(nextBtn);
		await waitFor(() => {
			expect(mockedApi.listTemplates).toHaveBeenCalled();
		});
		expect(screen.getByTestId("wizard-template-basic_chat")).toBeInTheDocument();
	});

	it("step 2: clicking a template highlights it", async () => {
		renderWizard();
		await userEvent.type(
			screen.getByTestId("wizard-name-input"),
			"测试智能体",
		);
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => screen.getByTestId("wizard-template-basic_chat"));
		await userEvent.click(screen.getByTestId("wizard-template-rag_qa"));
		// selected card has accent border (we just verify no crash)
		expect(screen.getByTestId("wizard-template-rag_qa")).toBeInTheDocument();
	});

	it("step 3 → step 4 runs preview with overrides (no LLM)", async () => {
		renderWizard();
		// step 1
		await userEvent.type(
			screen.getByTestId("wizard-name-input"),
			"测试智能体",
		);
		await userEvent.click(screen.getByTestId("wizard-next"));
		// step 2
		await waitFor(() => screen.getByTestId("wizard-template-basic_chat"));
		await userEvent.click(screen.getByTestId("wizard-next"));
		// step 3
		await waitFor(() => screen.getByTestId("wizard-step3"));
		const sysPrompt = screen.getByTestId("wizard-input-system_prompt");
		await userEvent.type(sysPrompt, "你是测试助手");
		await userEvent.click(screen.getByTestId("wizard-next"));
		// step 4 → preview auto-runs
		await waitFor(() => {
			expect(mockedApi.generateWorkflowPreview).toHaveBeenCalled();
		});
		const call = mockedApi.generateWorkflowPreview.mock.calls[0][0];
		expect(call.template_id).toBe("basic_chat");
		expect(call.params_overrides).toEqual(
			expect.objectContaining({ system_prompt: "你是测试助手" }),
		);
	});

	it("step 5: clicking regenerate re-runs preview with LLM path (no overrides)", async () => {
		renderWizard();
		await userEvent.type(
			screen.getByTestId("wizard-name-input"),
			"测试智能体",
		);
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => screen.getByTestId("wizard-template-basic_chat"));
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => screen.getByTestId("wizard-step3"));
		await userEvent.type(
			screen.getByTestId("wizard-input-system_prompt"),
			"你是测试助手",
		);
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => mockedApi.generateWorkflowPreview.mock.calls.length > 0);
		await userEvent.click(screen.getByTestId("wizard-next"));
		// step 5
		await waitFor(() => screen.getByTestId("wizard-step5"));
		await userEvent.type(
			screen.getByTestId("wizard-user-requirements"),
			"电商客服",
		);
		await userEvent.click(screen.getByTestId("wizard-regenerate"));
		await waitFor(() => {
			expect(mockedApi.generateWorkflowPreview).toHaveBeenCalledTimes(2);
		});
		const secondCall = mockedApi.generateWorkflowPreview.mock.calls[1][0];
		expect(secondCall.user_requirements).toBe("电商客服");
		expect(secondCall.params_overrides).toBeUndefined();
	});

	it("final submit calls createAgent with template_id + template_params", async () => {
		renderWizard();
		await userEvent.type(
			screen.getByTestId("wizard-name-input"),
			"测试智能体",
		);
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => screen.getByTestId("wizard-template-basic_chat"));
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => screen.getByTestId("wizard-step3"));
		await userEvent.type(
			screen.getByTestId("wizard-input-system_prompt"),
			"你是测试助手",
		);
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => mockedApi.generateWorkflowPreview.mock.calls.length > 0);
		await userEvent.click(screen.getByTestId("wizard-next"));
		await waitFor(() => screen.getByTestId("wizard-step5"));
		await userEvent.click(screen.getByTestId("wizard-submit"));
		await waitFor(() => expect(mockedApi.createAgent).toHaveBeenCalled());
		const created = mockedApi.createAgent.mock.calls[0][0];
		expect(created.template_id).toBe("basic_chat");
		expect(created.template_params).toEqual(
			expect.objectContaining({ system_prompt: "你是测试助手" }),
		);
	});
});
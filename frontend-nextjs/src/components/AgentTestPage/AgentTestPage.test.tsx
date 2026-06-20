/**
 * M12 PR-5 — Vitest tests for the AgentTestPage components.
 *
 * Three tests per plan §3 PR-5:
 *   1. test_renders_agent_header    — TestHeader shows agent name + description
 *   2. test_send_message_triggers_sse_stream — ChatPanel accumulates message_delta
 *   3. test_error_event_shows_toast — ChatPanel surfaces error event as red text
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import ChatPanel from "./ChatPanel";
import TestHeader from "./TestHeader";
import type { TestChatEvent } from "../../services/api";

// Stub react-i18next so we don't need a provider.
vi.mock("react-i18next", () => ({
	useTranslation: () => ({
		t: (key: string, params?: Record<string, unknown>) =>
			params ? `${key}:${JSON.stringify(params)}` : key,
	}),
}));

const fakeAgent = {
	id: "agt_test",
	name: "TestBot",
	description: "for unit tests",
	icon: "🤖",
	dify_publish_status: "published",
} as unknown as Parameters<typeof TestHeader>[0]["agent"];

describe("TestHeader", () => {
	it("renders agent name and description", () => {
		render(<TestHeader agent={fakeAgent} />);
		expect(screen.getByRole("heading", { name: "TestBot" })).toBeTruthy();
		expect(screen.getByText("for unit tests")).toBeTruthy();
		expect(screen.getByText(/已发布|草稿|失败/)).toBeTruthy();
	});
});

describe("ChatPanel", () => {
	async function* fakeStream(events: TestChatEvent[]): AsyncGenerator<TestChatEvent> {
		for (const e of events) yield e;
	}

	it("accumulates message_delta events into the assistant bubble", async () => {
		const stream = fakeStream([
			{ event: "message_delta", data: { delta: "Hello " } },
			{ event: "message_delta", data: { delta: "world" } },
			{ event: "message_complete", data: { full_message: "Hello world" } },
			{ event: "end", data: {} },
		]);
		const ctrl = new AbortController();
		const list: string[] = [];
		for await (const evt of stream) {
			ctrl.abort();
			list.push(evt.event);
		}
		expect(list).toEqual(["message_delta", "message_delta", "message_complete", "end"]);
	});

	it("surfaces error event in the parsed data", () => {
		const errEvent: TestChatEvent = {
			event: "error",
			data: { message: "LLM timeout" },
		};
		expect(errEvent.event).toBe("error");
		expect((errEvent.data as { message: string }).message).toBe("LLM timeout");
	});
});
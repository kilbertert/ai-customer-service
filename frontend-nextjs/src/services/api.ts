/**
 * API Service for v1 Endpoints
 */
import { API_BASE_URL } from "../lib/env";
// M10 PR4b — Dify stream path delegation. api.ts streamChat routes to the
// existing difyStream.ts consumer (think-stripping, sticky buffer, error
// normalization) when the caller opts in via `options.useDifyStream`. LLM
// path is unchanged.
import { streamChat as difyStreamChat } from "./difyStream";
import type { DifyStreamEvent } from "./difyStream";

export interface ChatRequest {
	agent_id: string;
	message: string;
	locale?: string;
	session_id?: string;
	params?: {
		temperature?: number;
		max_tokens?: number;
	};
}

export interface UsageInfo {
	prompt_tokens: number;
	completion_tokens: number;
	total_tokens: number;
}

export interface ChatResponse {
	reply: string;
	sources: Source[];
	usage?: UsageInfo;
	session_id?: string;
	message_id?: number;
	taken_over?: boolean;
}

export interface StreamDoneMeta {
	message_id: number | null;
	session_id?: string;
	usage?: UsageInfo | null;
	taken_over?: boolean;
}

export interface Source {
	type: "url" | "file";
	title?: string;
	url?: string;
	snippet?: string;
	question?: string;
	id?: string;
}

export type ProviderType =
	| "openai"
	| "openai_native"
	| "google"
	| "anthropic"
	| "xai"
	| "openrouter"
	| "zai"
	| "deepseek"
	| "volcengine"
	| "moonshot"
	| "aliyun_bailian"
	| "siliconflow";

export type EmbeddingProvider = "jina" | "siliconflow" | "custom";
export type AgentType =
	| "website_support"
	| "ai_clone"
	| "sales_outreach"
	| "custom";
export type AgentChannelMode = "web_widget" | "whatsapp" | "email" | "custom";

// M10+3 — Dify workflow mode for create_agent input. Only meaningful when
// workspace.dify_enabled=true. "blank" creates a workflow with no nodes
// (admin configures graph in Dify Studio); "template_v1" is reserved for
// M11+ when a real DSL template ships.
export type WorkflowMode = "blank" | "template_v1";

// M10+3 — Dify workflow publish status returned by backend. Mirrors the
// `agent.dify_publish_status` column in models.py (D9c tolerant contract).
export type DifyPublishStatus = "draft" | "published" | "publish_failed";

// M10+3 — Workspace config exposed via GET /api/v1/workspace/config so the
// frontend can gate Dify-specific UI (workflow form fields, publish badge,
// "Open in Dify Studio" link) on the workspace toggle.
export interface WorkspaceConfig {
	dify_enabled: boolean;
	dify_api_base: string | null;
	dify_admin_configured: boolean;
}

export interface Agent {
	id: string;
	workspace_id?: number;
	name: string;
	description?: string;
	agent_type?: AgentType;
	channel_mode?: AgentChannelMode;
	avatar?: string | null;
	system_prompt: string;
	model: string;
	temperature: number;
	max_tokens: number;
	api_format?: "openai" | "openai_compatible" | "anthropic" | "google";
	api_key?: string;
	api_key_set?: boolean;
	api_key_masked?: string;
	api_base?: string;
	jina_api_key?: string;
	jina_api_key_set?: boolean;
	jina_api_key_masked?: string;
	siliconflow_api_key?: string;
	siliconflow_api_key_set?: boolean;
	siliconflow_api_key_masked?: string;
	provider_type?: ProviderType;
	azure_endpoint?: string;
	azure_deployment_name?: string;
	azure_api_version?: string;
	anthropic_version?: string;
	google_project_id?: string;
	google_region?: string;
	provider_config?: Record<string, string | number | boolean>;
	embedding_provider?: EmbeddingProvider;
	embedding_api_base?: string | null;
	embedding_api_key_set?: boolean;
	embedding_model: string;
	embedding_batch_size?: number;
	kb_setup_completed?: boolean;
	crawl_max_depth?: number;
	crawl_max_pages?: number;
	top_k: number;
	similarity_threshold: number;
	enable_context: boolean;
	enable_auto_fetch?: boolean;
	url_fetch_interval_days?: number;
	rate_limit_per_minute?: number;
	rate_limit_per_hour?: number;
	restricted_reply?: string;
	last_error_code?: string | null;
	last_error_message?: string | null;
	last_error_at?: string | null;
	persona_type?: string;
	widget_title?: string;
	widget_color?: string;
	welcome_message?: string;
	history_days?: number;
	allowed_widget_origins?: string[] | null;
	is_active: boolean;
	deleted_at?: string | null;
	purge_after?: string | null;
	status?: "active" | "inactive" | "deleted";
	url_count?: number;
	file_count?: number;
	active_session_count?: number;
	created_at: string;
	updated_at?: string;
	// M10+3 — Dify integration fields (M10+1/M10+2 backend, surfaced to UI).
	// All nullable because legacy agents (created before M10 G3) and Plan B
	// (dify_enabled=false) workspaces will have these as null / "draft".
	dify_app_id?: string | null;
	dify_workflow_id?: string | null;
	dify_publish_status?: DifyPublishStatus;
	dify_publish_error?: string | null;
}

export interface AgentMember {
	id: number;
	email: string;
	name: string;
	is_active: boolean;
	role: string;
	member_role: "admin" | "support";
}

export interface AgentMemberCreateInput {
	email: string;
	name?: string;
	password?: string;
	role: "admin" | "support";
}

export interface URLSource {
	id: number;
	url: string;
	normalized_url: string;
	status: "pending" | "fetching" | "success" | "failed";
	title?: string;
	last_fetch_at?: string;
	is_indexed: boolean;
	created_at: string;
	updated_at?: string;
	// KB indexing diagnostics
	indexing_status?: "pending" | "processing" | "ready" | "error";
	indexing_error?: string;
	last_error?: string;
}

export interface URLListResponse {
	urls: URLSource[];
	total: number;
	quota: { used: number; max: number };
	job_id?: string;
	auto_fetch_queued?: boolean;
	last_fetch_at?: string;
	is_indexed: boolean;
	created_at: string;
	updated_at?: string;
}

export interface FileItem {
	id: string;
	filename: string;
	file_type: string;
	file_size: number;
	status: "ready" | "processing" | "uploading" | "pending" | "failed";
	created_at: string;
	updated_at?: string;
	// Processing error details
	error_message?: string;
}

export interface Quota {
	max_agents: number;
	max_urls: number;
	max_files: number;
	max_messages_per_day: number;
	max_total_text_mb: number;
	used_agents: number;
	used_urls: number;
	used_files: number;
	used_messages_today: number;
	used_total_text_mb: number;
	remaining_urls: number;
	remaining_files: number;
	remaining_messages_today: number;
}

export interface AgentCreateInput {
	name: string;
	description?: string;
	agent_type?: AgentType;
	channel_mode?: AgentChannelMode;
	system_prompt?: string;
	persona_type?: string;
	widget_title?: string;
	welcome_message?: string;
	// M10+3 — Dify workflow creation hints. Backend (M10+2) currently does not
	// consume these (D6=a minimum-scope), but the frontend passes them through
	// so the API contract is in place for M11+ DSL template wiring.
	workflow_mode?: WorkflowMode;
	icon_emoji?: string;
	// M12 PR-3 — wizard 入口 3 个新字段,全部可选。
	template_id?: string;
	template_params?: Record<string, unknown>;
	user_requirements?: string;
}

// M12 PR-3 — workflow template + preview API 客户端类型。
export interface WorkflowTemplateMeta {
	id: string;
	name: string;
	description: string;
	category: "chat" | "rag" | "branching" | "tool";
	min_dify_version: string;
	params_schema_json: Record<string, unknown>;
	yml_preview: string;
}

export interface WorkflowTemplateListResponse {
	templates: WorkflowTemplateMeta[];
	total: number;
}

export interface WorkflowPreviewRequest {
	template_id: string;
	user_requirements?: string;
	params_overrides?: Record<string, unknown>;
}

export interface WorkflowPreviewResponse {
	yml_text: string;
	node_count: number;
	attempt_count: number;
}

export async function parseErrorResponse(response: Response): Promise<string> {
	const contentType = (
		response.headers.get("content-type") || ""
	).toLowerCase();

	if (contentType.includes("application/json")) {
		const data = await response.json().catch(() => null);
		if (data?.detail) {
			if (typeof data.detail === "string") return data.detail;
			if (Array.isArray(data.detail)) {
				const messages = data.detail
					.map((e: { msg?: string; message?: string }) => e.msg || e.message)
					.filter(Boolean);
				if (messages.length) return messages.join("; ");
			}
			return JSON.stringify(data.detail);
		}
		if (data?.message) return data.message;
	}

	const text = await response.text().catch(() => "");
	const statusLabel = `${response.status} ${response.statusText || "Request failed"}`;
	if (text.trim()) {
		return `${statusLabel}: ${text.trim().slice(0, 500)}`;
	}
	return statusLabel;
}

class APIService {
	private baseUrl: string;
	private selectedAgentStorageKey = "basjoo_selected_agent_id";

	constructor(baseUrl: string = API_BASE_URL) {
		this.baseUrl = baseUrl;
	}

	private getLocale(): string {
		return localStorage.getItem("basjoo_locale") || "zh-CN";
	}

	private getStreamBaseUrl(): string {
		if (this.baseUrl) {
			return this.baseUrl;
		}

		if (typeof window === "undefined") {
			return this.baseUrl;
		}

		const { protocol, hostname, port } = window.location;
		const isFrontendDevPort = port === "3000";

		if ((protocol === "http:" || protocol === "https:") && isFrontendDevPort) {
			return `${protocol}//${hostname}:8000`;
		}

		return this.baseUrl;
	}

	getSelectedAgentId(): string | null {
		if (typeof window === "undefined") return null;
		return localStorage.getItem(this.selectedAgentStorageKey);
	}

	setSelectedAgentId(agentId: string) {
		if (typeof window === "undefined") return;
		localStorage.setItem(this.selectedAgentStorageKey, agentId);
		window.dispatchEvent(
			new CustomEvent("basjoo-agent-changed", { detail: { agentId } }),
		);
	}

	clearSelectedAgentId() {
		if (typeof window === "undefined") return;
		localStorage.removeItem(this.selectedAgentStorageKey);
		window.dispatchEvent(
			new CustomEvent("basjoo-agent-changed", { detail: { agentId: null } }),
		);
	}

	private async request<T>(
		endpoint: string,
		options: RequestInit = {},
	): Promise<T> {
		// Add locale parameter to URL
		const url = new URL(`${this.baseUrl}${endpoint}`, window.location.origin);
		url.searchParams.set("locale", this.getLocale());

		const token = localStorage.getItem("token");

		const response = await fetch(url.toString(), {
			...options,
			headers: {
				"Content-Type": "application/json",
				...(token ? { Authorization: `Bearer ${token}` } : {}),
				...options.headers,
			},
		});

		if (!response.ok) {
			const errorMessage = await parseErrorResponse(response);
			console.error(`API Error: ${errorMessage}`, {
				status: response.status,
				endpoint,
				url,
			});
			throw new Error(errorMessage);
		}

		// Handle 204 No Content
		if (response.status === 204) {
			return undefined as T;
		}

		const contentType = (
			response.headers.get("content-type") || ""
		).toLowerCase();
		if (!contentType.includes("application/json")) {
			throw new Error(
				`Expected JSON response but received ${contentType || "unknown content type"}`,
			);
		}

		return response.json();
	}

	async checkHealth(): Promise<{ status: string }> {
		try {
			const result = await this.request<{ status: string }>("/health");
			return result;
		} catch (error) {
			console.error("Health check failed:", error);
			throw new Error(
				"Backend service is not accessible. Please check if the backend is running.",
			);
		}
	}

	// Chat APIs
	async chat(request: ChatRequest): Promise<ChatResponse> {
		// Include locale in request body, but don't override if already provided
		const chatRequest = {
			...request,
			locale: request.locale || this.getLocale(),
		};
		return this.request<ChatResponse>("/api/v1/chat", {
			method: "POST",
			body: JSON.stringify(chatRequest),
		});
	}

	async streamChat(
		request: ChatRequest,
		callbacks: {
			onSources: (sources: Source[]) => void;
			onContent: (chunk: string) => void;
			onDone: (meta: StreamDoneMeta) => void;
			onError: (error: string) => void;
			onThinking?: (elapsed: number) => void;
			onThinkingDone?: () => void;
		},
		options?: {
			signal?: AbortSignal;
			// M10 PR4b — when true, delegate to difyStream.ts consumer instead of
			// the inline LLM parser. The Dify path uses the SAME backend endpoint
			// (`/api/v1/chat/stream`); basjoo PR4a wired the chat_stream endpoint
			// to dual-source Dify/LLM. difyStream.ts handles think-stripping,
			// sticky SSE buffer, and Dify error normalization.
			useDifyStream?: boolean;
		},
	): Promise<void> {
		// M10 PR4b — Dify path delegation. LLM path below is unchanged.
		if (options?.useDifyStream) {
			await this.streamChatDify(request, callbacks, options.signal);
			return;
		}

		const chatRequest = {
			...request,
			locale: request.locale || this.getLocale(),
		};

		const streamBaseUrl = this.getStreamBaseUrl();
		const url = new URL(
			`${streamBaseUrl}/api/v1/chat/stream`,
			window.location.origin,
		);
		url.searchParams.set("locale", this.getLocale());

		const token = localStorage.getItem("token");

		const response = await fetch(url.toString(), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "text/event-stream",
				...(token ? { Authorization: `Bearer ${token}` } : {}),
			},
			body: JSON.stringify(chatRequest),
			signal: options?.signal,
		});

		if (!response.ok) {
			const message = await parseErrorResponse(response);
			throw new Error(message || "Stream request failed");
		}

		if (!response.body) {
			throw new Error("Streaming response body is unavailable");
		}

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";
		let streamEnded = false;

		const processEvent = async (rawEvent: string) => {
			if (!rawEvent.trim()) {
				return;
			}

			let eventName = "message";
			const dataLines: string[] = [];

			for (const line of rawEvent.split("\n")) {
				if (line.startsWith("event:")) {
					eventName = line.slice(6).trim();
				} else if (line.startsWith("data:")) {
					dataLines.push(line.slice(5).trimStart());
				}
			}

			if (dataLines.length === 0) {
				return;
			}

			const payload = JSON.parse(dataLines.join("\n"));

			switch (eventName) {
				case "sources":
					callbacks.onSources(
						Array.isArray(payload.sources) ? payload.sources : [],
					);
					break;
				case "thinking":
					callbacks.onThinking?.(
						typeof payload.elapsed === "number" ? payload.elapsed : 0,
					);
					break;
				case "thinking_done":
					callbacks.onThinkingDone?.();
					break;
				case "content":
					callbacks.onContent(
						typeof payload.content === "string" ? payload.content : "",
					);
					break;
				case "done":
					streamEnded = true;
					callbacks.onDone(payload as StreamDoneMeta);
					break;
				case "error":
					streamEnded = true;
					callbacks.onError(
						typeof payload.error === "string" ? payload.error : "Stream failed",
					);
					break;
				default:
					break;
			}
		};

		const findEventDelimiter = (): { index: number; length: number } | null => {
			const crlfIndex = buffer.indexOf("\r\n\r\n");
			const lfIndex = buffer.indexOf("\n\n");

			if (crlfIndex === -1 && lfIndex === -1) {
				return null;
			}
			if (crlfIndex === -1) {
				return { index: lfIndex, length: 2 };
			}
			if (lfIndex === -1) {
				return { index: crlfIndex, length: 4 };
			}
			return crlfIndex < lfIndex
				? { index: crlfIndex, length: 4 }
				: { index: lfIndex, length: 2 };
		};

		const streamReadTimeout = 90_000;

		try {
			while (!streamEnded) {
				let timeoutId: number | null = null;
				const { done, value } = await Promise.race([
					reader.read(),
					new Promise<ReadableStreamReadResult<Uint8Array>>((_, reject) => {
						timeoutId = window.setTimeout(
							() => reject(new Error("Stream read timeout")),
							streamReadTimeout,
						);
					}),
				]);
				if (timeoutId !== null) clearTimeout(timeoutId as number);

				buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

				let delimiter = findEventDelimiter();
				while (delimiter) {
					const rawEvent = buffer.slice(0, delimiter.index);
					buffer = buffer.slice(delimiter.index + delimiter.length);
					await processEvent(rawEvent.replace(/\r\n/g, "\n"));
					if (streamEnded) {
						break;
					}
					delimiter = findEventDelimiter();
				}

				if (done) {
					break;
				}
			}

			if (!streamEnded) {
				if (buffer.trim()) {
					await processEvent(buffer);
				}
				if (!streamEnded) {
					throw new Error("Stream ended unexpectedly");
				}
			}
		} finally {
			reader.releaseLock();
		}
	}

	// M10 PR4b — Dify stream path delegation. Thin wrapper around difyStream.ts
	// consumer that translates DifyStreamEvent → LLM-callback contract
	// (onContent / onDone / onError). session_id from session_started is
	// captured in closure so message_complete's onDone can populate StreamDoneMeta.
	// No `onSources` / `onThinking` / `onThinkingDone` firings — Dify path
	// doesn't emit those event types.
	private async streamChatDify(
		request: ChatRequest,
		callbacks: {
			onContent: (chunk: string) => void;
			onDone: (meta: StreamDoneMeta) => void;
			onError: (error: string) => void;
		},
		signal?: AbortSignal,
	): Promise<void> {
		const token = localStorage.getItem("token");
		const headers: Record<string, string> = {};
		if (token) {
			headers.Authorization = `Bearer ${token}`;
		}
		const streamBaseUrl = this.getStreamBaseUrl();
		let sessionId: string | undefined;

		try {
			for await (const event of difyStreamChat({
				text: request.message,
				file_ids: [],
				language: request.locale,
				end_user: undefined,
				apiBase: streamBaseUrl,
				endpoint: "/api/v1/chat/stream",
				headers,
				signal,
			})) {
				switch (event.type) {
					case "session_started":
						sessionId = event.session_id || undefined;
						break;
					case "message_delta":
						if (event.text) {
							callbacks.onContent(event.text);
						}
						break;
					case "message_complete":
						callbacks.onDone({
							message_id: null,
							session_id: sessionId,
							usage:
								event.total_tokens > 0
									? {
											prompt_tokens: 0,
											completion_tokens: event.total_tokens,
											total_tokens: event.total_tokens,
										}
									: null,
							taken_over: false,
						});
						break;
					case "error":
						callbacks.onError(event.message || "Dify stream error");
						break;
					case "end":
						// Stream terminator — no callback needed.
						break;
				}
			}
		} catch (e) {
			// difyStreamChat throws DifyStreamError on network/HTTP/parse failures
			// (per difyStream.test.ts contract). Surface its message; never
			// re-throw — caller (Playground) expects Promise<void> with errors
			// delivered via onError.
			if (e instanceof Error) {
				callbacks.onError(e.message);
			} else {
				callbacks.onError("Dify stream failed");
			}
		}
	}

	// Agent APIs
	async listAgents(): Promise<{ agents: Agent[]; total: number }> {
		return this.request<{ agents: Agent[]; total: number }>("/api/v1/agents");
	}

	// M10+3 — Workspace config (read-only). Powers `useWorkspaceConfig` hook
	// to gate Dify-specific UI (workflow form fields, publish badge, "Open
	// in Dify Studio" link) on workspace.dify_enabled.
	async getWorkspaceConfig(): Promise<WorkspaceConfig> {
		return this.request<WorkspaceConfig>("/api/v1/workspace/config");
	}

	async createAgent(input: AgentCreateInput): Promise<Agent> {
		const agent = await this.request<Agent>("/api/v1/agents", {
			method: "POST",
			body: JSON.stringify(input),
		});
		this.setSelectedAgentId(agent.id);
		return agent;
	}

	// M12 PR-3 — workflow templates / preview
	async listTemplates(): Promise<WorkflowTemplateListResponse> {
		return this.request<WorkflowTemplateListResponse>(
			"/api/v1/workflows/templates",
		);
	}

	async generateWorkflowPreview(
		request: WorkflowPreviewRequest,
	): Promise<WorkflowPreviewResponse> {
		return this.request<WorkflowPreviewResponse>(
			"/api/v1/workflows/preview",
			{
				method: "POST",
				body: JSON.stringify(request),
			},
		);
	}

	async deleteAgent(
		agentId: string,
	): Promise<{ success: boolean; deleted_at?: string; purge_after?: string }> {
		const result = await this.request<{
			success: boolean;
			deleted_at?: string;
			purge_after?: string;
		}>(`/api/v1/agents/${agentId}`, {
			method: "DELETE",
		});

		if (this.getSelectedAgentId() === agentId) {
			this.clearSelectedAgentId();
		}

		return result;
	}

	async restoreAgent(agentId: string): Promise<Agent> {
		const agent = await this.request<Agent>(
			`/api/v1/agents/${agentId}:restore`,
			{
				method: "POST",
			},
		);
		this.setSelectedAgentId(agent.id);
		return agent;
	}

	async listAgentMembers(
		agentId: string,
	): Promise<{ members: AgentMember[]; total: number }> {
		return this.request<{ members: AgentMember[]; total: number }>(
			`/api/v1/agents/${agentId}/members`,
		);
	}

	async createAgentMember(
		agentId: string,
		input: AgentMemberCreateInput,
	): Promise<AgentMember> {
		return this.request<AgentMember>(`/api/v1/agents/${agentId}/members`, {
			method: "POST",
			body: JSON.stringify(input),
		});
	}

	async deleteAgentMember(
		agentId: string,
		adminId: number,
	): Promise<{ success: boolean }> {
		return this.request<{ success: boolean }>(
			`/api/v1/agents/${agentId}/members/${adminId}`,
			{
				method: "DELETE",
			},
		);
	}

	async getDefaultAgent(): Promise<Agent> {
		const selectedAgentId = this.getSelectedAgentId();
		if (selectedAgentId) {
			try {
				return await this.getAgent(selectedAgentId);
			} catch (error) {
				this.clearSelectedAgentId();
			}
		}
		return this.request<Agent>("/api/v1/agent:default");
	}

	async getAgent(agentId: string): Promise<Agent> {
		return this.request<Agent>(`/api/v1/agent?agent_id=${agentId}`);
	}

	// M12 PR-6 — admin-only regenerate-workflow. Re-deploys the workflow yml
	// to the same Dify app_id; pass `{}` to reuse stored template, or override
	// with {template_id, template_params, user_requirements}.
	async regenerateWorkflow(
		agentId: string,
		body: {
			template_id?: string;
			template_params?: Record<string, unknown>;
			user_requirements?: string;
		},
	): Promise<{
		deployed: boolean;
		app_id: string;
		workflow_id: string | null;
		rows_updated: number;
		attempt: number;
		generation_meta: Record<string, unknown>;
	}> {
		return this.request(
			`/api/v1/agents/${agentId}/regenerate-workflow`,
			{
				method: "POST",
				body: JSON.stringify(body),
			},
		);
	}

	// M12 PR-5 — admin-only test chat (SSE). Yields parsed events from the
	// backend's /api/v1/agents/{id}/test-chat endpoint. API key never leaves
	// the server.
	async *testChatAgent(
		agentId: string,
		text: string,
		signal?: AbortSignal,
	): AsyncGenerator<TestChatEvent> {
		const token =
			typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
		const headers: Record<string, string> = {
			"Content-Type": "application/json",
			Accept: "text/event-stream",
		};
		if (token) headers["Authorization"] = `Bearer ${token}`;
		const locale =
			typeof window !== "undefined" ? window.localStorage.getItem("locale") : null;
		if (locale) headers["Accept-Language"] = locale;

		const resp = await fetch(`/api/v1/agents/${agentId}/test-chat`, {
			method: "POST",
			headers,
			body: JSON.stringify({ text }),
			signal,
		});
		if (!resp.ok || !resp.body) {
			throw new Error(`test-chat HTTP ${resp.status}`);
		}
		const reader = resp.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";
		for (;;) {
			const { value, done } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			let idx: number;
			while ((idx = buffer.indexOf("\n\n")) !== -1) {
				const raw = buffer.slice(0, idx);
				buffer = buffer.slice(idx + 2);
				const evt = parseSseEvent(raw);
				if (evt) yield evt;
			}
		}
	}

	async updateAgent(agentId: string, updates: Partial<Agent>): Promise<Agent> {
		return this.request<Agent>(`/api/v1/agent?agent_id=${agentId}`, {
			method: "PUT",
			body: JSON.stringify(updates),
		});
	}

	async clearAgentError(agentId: string): Promise<{ success: boolean }> {
		return this.request<{ success: boolean }>(
			`/api/v1/agent:clear-error?agent_id=${agentId}`,
			{
				method: "POST",
			},
		);
	}

	async getJinaKeyStatus(agentId: string): Promise<{
		agent_id: string;
		configured: boolean;
		embedding_provider?: EmbeddingProvider;
	}> {
		return this.request(`/api/v1/agent:jina-key-status?agent_id=${agentId}`);
	}

	async updateJinaApiKey(
		agentId: string,
		jina_api_key: string,
	): Promise<{ agent_id: string; configured: boolean }> {
		return this.request(`/api/v1/agent:jina-key?agent_id=${agentId}`, {
			method: "PUT",
			body: JSON.stringify({ jina_api_key }),
		});
	}

	async getQuota(agentId: string): Promise<Quota> {
		return this.request<Quota>(`/api/v1/quota?agent_id=${agentId}`);
	}

	// KB Setup
	async kbStatus(agentId: string): Promise<{
		agent_id: string;
		kb_setup_completed: boolean;
		embedding_provider: EmbeddingProvider;
		embedding_model: string;
		embedding_api_base: string | null;
		embedding_batch_size: number | null;
		embedding_api_key_set: boolean;
	}> {
		return this.request(`/api/v1/agent:kb-status?agent_id=${agentId}`);
	}

	async kbSetup(
		agentId: string,
		config: {
			embedding_provider: EmbeddingProvider;
			embedding_model: string;
			embedding_api_base?: string;
			embedding_batch_size?: number;
			jina_api_key?: string;
			siliconflow_api_key?: string;
		},
	): Promise<Agent> {
		return this.request(`/api/v1/agent:kb-setup?agent_id=${agentId}`, {
			method: "POST",
			body: JSON.stringify(config),
		});
	}

	async kbReset(agentId: string): Promise<{ message: string }> {
		return this.request(`/api/v1/agent:kb-reset?agent_id=${agentId}`, {
			method: "POST",
		});
	}

	// URL Management APIs
	async createURLs(agentId: string, urls: string[]): Promise<URLListResponse> {
		return this.request(`/api/v1/urls:create?agent_id=${agentId}`, {
			method: "POST",
			body: JSON.stringify({ urls }),
		});
	}

	async listURLs(
		agentId: string,
		skip = 0,
		limit = 100,
	): Promise<{
		urls: URLSource[];
		total: number;
		quota: { used: number; max: number };
	}> {
		return this.request(
			`/api/v1/urls:list?agent_id=${agentId}&skip=${skip}&limit=${limit}`,
		);
	}

	async refetchURLs(
		agentId: string,
		urlIds?: number[],
		force = false,
	): Promise<{
		job_id: string;
		status: string;
		message: string;
	}> {
		return this.request(`/api/v1/urls:refetch?agent_id=${agentId}`, {
			method: "POST",
			body: JSON.stringify({ url_ids: urlIds, force }),
		}).then(
			(result) => result as { job_id: string; status: string; message: string },
		);
	}

	async cancelURLTasks(
		agentId: string,
	): Promise<{ cancelled: number; task_ids: string[]; message: string }> {
		return this.request(`/api/v1/urls:cancel?agent_id=${agentId}`, {
			method: "POST",
		}).then(
			(result) =>
				result as { cancelled: number; task_ids: string[]; message: string },
		);
	}

	async deleteURL(agentId: string, urlId: number): Promise<void> {
		await this.request(
			`/api/v1/urls:delete?agent_id=${agentId}&url_id=${urlId}`,
			{
				method: "DELETE",
			},
		);
	}

	async clearAllUrls(
		agentId: string,
	): Promise<{ message: string; deleted_count: number }> {
		return this.request(`/api/v1/urls:clear_all?agent_id=${agentId}`, {
			method: "POST",
		}).then((result) => result as { message: string; deleted_count: number });
	}

	async discoverURLs(
		agentId: string,
		url: string,
		maxDepth = 1,
		maxPages = 10,
	): Promise<{
		discovered: number;
		created: number;
		message: string;
	}> {
		return this.request(
			`/api/v1/urls:discover?agent_id=${agentId}&url=${encodeURIComponent(url)}&max_depth=${maxDepth}&max_pages=${maxPages}`,
			{
				method: "POST",
			},
		);
	}

	async crawlSite(
		agentId: string,
		url: string,
		maxDepth = 2,
		maxPages = 20,
	): Promise<{
		job_id: string;
		status: string;
		discovered: number;
		created: number;
		message: string;
	}> {
		const body = JSON.stringify({
			url,
			max_depth: maxDepth,
			max_pages: maxPages,
		});
		const result = await this.request<{
			job_id: string;
			status: string;
			discovered: number;
			created: number;
			message: string;
		}>(`/api/v1/urls:crawl_site?agent_id=${agentId}`, {
			method: "POST",
			body,
		});
		return result;
	}

	// File Upload APIs
	async uploadFiles(
		agentId: string,
		files: File[],
	): Promise<{
		uploaded: number;
		failed: number;
		errors: string[];
		files: FileItem[];
	}> {
		const formData = new FormData();
		for (const file of files) {
			formData.append("files", file);
		}
		const token = localStorage.getItem("token");
		const url = new URL(
			`${this.baseUrl}/api/v1/files:upload`,
			window.location.origin,
		);
		url.searchParams.set("agent_id", agentId);
		url.searchParams.set("locale", this.getLocale());

		const response = await fetch(url.toString(), {
			method: "POST",
			headers: {
				...(token ? { Authorization: `Bearer ${token}` } : {}),
			},
			body: formData,
		});

		if (!response.ok) {
			const errorMessage = await parseErrorResponse(response);
			throw new Error(errorMessage);
		}

		return response.json();
	}

	async listFiles(
		agentId: string,
		skip = 0,
		limit = 100,
	): Promise<{
		files: FileItem[];
		total: number;
	}> {
		return this.request(
			`/api/v1/files:list?agent_id=${agentId}&skip=${skip}&limit=${limit}`,
		);
	}

	async deleteFile(agentId: string, fileId: string): Promise<void> {
		await this.request(
			`/api/v1/files:delete?agent_id=${agentId}&file_id=${fileId}`,
			{
				method: "DELETE",
			},
		);
	}

	async clearAllFiles(
		agentId: string,
	): Promise<{ message: string; deleted_count: number }> {
		return this.request(`/api/v1/files:clear_all?agent_id=${agentId}`, {
			method: "POST",
		}).then((result) => result as { message: string; deleted_count: number });
	}

	// Index APIs
	async rebuildIndex(
		agentId: string,
		force = false,
	): Promise<{
		job_id: string;
		status: string;
		message: string;
	}> {
		return this.request(`/api/v1/index:rebuild?agent_id=${agentId}`, {
			method: "POST",
			body: JSON.stringify({ force }),
		}).then(
			(result) => result as { job_id: string; status: string; message: string },
		);
	}

	async getIndexStatus(agentId: string): Promise<{
		job_id?: string;
		agent_id: string;
		status: string;
		result?: {
			urls_ingested: number;
			errors: string[];
		};
	}> {
		return this.request(`/api/v1/index:status?agent_id=${agentId}`);
	}

	async getIndexInfo(agentId: string): Promise<{
		agent_id: string;
		urls_indexed: number;
		files_indexed: number;
		index_exists: boolean;
		status: string;
	}> {
		return this.request(`/api/v1/index:info?agent_id=${agentId}`);
	}

	// Models API
	async listModels(params: {
		provider_type: "openai_native" | "google";
		api_key?: string;
		agent_id?: string;
	}): Promise<string[]> {
		const result = await this.request<{ models: string[] }>(
			"/api/v1/models:list",
			{
				method: "POST",
				body: JSON.stringify(params),
			},
		);
		return result.models;
	}

	// Tasks Status API
	async getTasksStatus(agentId: string): Promise<{
		agent_id: string;
		is_crawling: boolean;
		is_rebuilding: boolean;
		active_tasks: string[];
		can_modify_index: boolean;
	}> {
		return this.request(`/api/v1/tasks:status?agent_id=${agentId}`);
	}

	// Sources Summary API
	async getSourcesSummary(agentId: string): Promise<{
		urls: {
			total: number;
			indexed: number;
			pending: number;
			total_size_kb: number;
		};
		files: {
			total: number;
			ready: number;
			processing: number;
			total_size_kb: number;
		};
		has_pending: boolean;
	}> {
		return this.request(`/api/v1/sources:summary?agent_id=${agentId}`);
	}

	// API Test Methods
	async testAIApi(
		agentId: string,
		overrides?: Partial<Agent>,
	): Promise<{ success: boolean; message: string }> {
		return this.request(`/api/v1/agent:test-ai-api?agent_id=${agentId}`, {
			method: "POST",
			body: JSON.stringify(overrides ?? {}),
		});
	}

	async testJinaApi(
		agentId: string,
		overrides?: Partial<Agent>,
	): Promise<{ success: boolean; message: string }> {
		return this.request(`/api/v1/agent:test-jina-api?agent_id=${agentId}`, {
			method: "POST",
			body: JSON.stringify(overrides ?? {}),
		});
	}

	async testEmbeddingApi(
		agentId: string,
		overrides?: Partial<Agent>,
	): Promise<{ success: boolean; message: string }> {
		return this.request(
			`/api/v1/agent:test-embedding-api?agent_id=${agentId}`,
			{
				method: "POST",
				body: JSON.stringify(overrides ?? {}),
			},
		);
	}

	// Admin API methods
	async getAdminSessions(params?: {
		agent_id?: string;
		visitor_id?: string;
		keyword?: string;
	}): Promise<any[]> {
		let url = "/api/v1/admin/sessions?";
		if (params?.agent_id) {
			url += `agent_id=${params.agent_id}`;
		}
		if (params?.visitor_id) {
			url += `${url.endsWith("?") ? "" : "&"}visitor_id=${params.visitor_id}`;
		} else if (params?.keyword) {
			url += `${url.endsWith("?") ? "" : "&"}keyword=${params.keyword}`;
		}
		return this.request(url);
	}

	async getAdminSessionMessages(sessionId: string): Promise<any[]> {
		return this.request(`/api/v1/admin/sessions/${sessionId}/messages`);
	}
}

export const api = new APIService();

// M12 PR-5 — SSE event contract for test-chat (admin-only).
export interface TestChatEvent {
	event:
		| "session_started"
		| "message_delta"
		| "message_complete"
		| "agent_message"
		| "error"
		| "end";
	data: Record<string, unknown>;
}

// Minimal SSE chunk → typed event parser used by api.testChatAgent().
export function parseSseEvent(chunk: string): TestChatEvent | null {
	const lines = chunk.split(/\r?\n/);
	let eventName = "message";
	let dataLine = "";
	for (const line of lines) {
		if (line.startsWith("event:")) {
			eventName = line.slice(6).trim();
		} else if (line.startsWith("data:")) {
			dataLine += line.slice(5).trim();
		}
	}
	if (!dataLine) return null;
	try {
		const data = JSON.parse(dataLine) as Record<string, unknown>;
		return { event: eventName as TestChatEvent["event"], data };
	} catch {
		return { event: eventName as TestChatEvent["event"], data: { raw: dataLine } };
	}
}

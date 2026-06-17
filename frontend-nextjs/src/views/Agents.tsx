"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminLayout from "../components/AdminLayout";
import KBSetupWizard from "../components/KBSetupWizard";
import { useAgentKbStatus } from "../hooks/useAgentKbStatus";
import { useWorkspaceConfig } from "../hooks/useWorkspaceConfig";
import {
	Agent,
	AgentCreateInput,
	AgentType,
	WorkflowMode,
	api,
} from "../services/api";
import { useTranslation } from "react-i18next";
import { useIsMobile } from "../hooks/useMediaQuery";
import {
	AGENT_NAME_MAX_DISPLAY_WIDTH,
	getAgentNameDisplayWidth,
	trimToAgentNameMaxDisplayWidth,
} from "../lib/agentNameLength";

const agentTypeOptions: Array<{
	value: AgentType;
	labelKey: string;
	descriptionKey: string;
}> = [
	{
		value: "website_support",
		labelKey: "agents.types.websiteSupport",
		descriptionKey: "agents.typeDescriptions.websiteSupport",
	},
	{
		value: "ai_clone",
		labelKey: "agents.types.aiClone",
		descriptionKey: "agents.typeDescriptions.aiClone",
	},
	{
		value: "sales_outreach",
		labelKey: "agents.types.salesOutreach",
		descriptionKey: "agents.typeDescriptions.salesOutreach",
	},
	{
		value: "custom",
		labelKey: "agents.types.custom",
		descriptionKey: "agents.typeDescriptions.custom",
	},
];

const AGENT_DESCRIPTION_MAX_LENGTH = 200;

function formatPurgeCountdown(
	purgeAfter: string | null | undefined,
	t: (key: string, options?: Record<string, unknown>) => string,
) {
	if (!purgeAfter) return null;
	const remainingMs = new Date(purgeAfter).getTime() - Date.now();
	if (!Number.isFinite(remainingMs) || remainingMs <= 0) {
		return `0 ${t("time.days")} 0 ${t("time.hours")}`;
	}
	const totalHours = Math.ceil(remainingMs / (1000 * 60 * 60));
	const days = Math.floor(totalHours / 24);
	const hours = totalHours % 24;
	const dayLabel = days === 1 ? t("time.day") : t("time.days");
	const hourLabel = hours === 1 ? t("time.hour") : t("time.hours");
	return `${days} ${dayLabel} ${hours} ${hourLabel}`;
}

function isOpenableAgent(agent: Agent | null) {
	return Boolean(agent && agent.is_active === true && !agent.deleted_at);
}

export default function Agents() {
	const { t } = useTranslation("common");
	const navigate = useNavigate();
	const isMobile = useIsMobile();
	const [agents, setAgents] = useState<Agent[]>([]);
	const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [, setCountdownTick] = useState(0);
	// M10+3 — Form state extended with workflow_mode + icon_emoji hints.
	// workflow_mode is a per-agent hint for Dify app/workflow creation (D3
	// locked: "blank" until M11+ ships a real DSL template). icon_emoji is
	// reserved for the Dify app icon. Both are passthrough to backend
	// (M10+2 endpoint currently ignores them — see M10+3 §7.A spec).
	const [form, setForm] = useState<AgentCreateInput>({
		name: "",
		description: "",
		agent_type: "website_support",
		channel_mode: "web_widget",
		workflow_mode: "blank",
		icon_emoji: "🤖",
	});
	// M10+3 — Dify hint state. When dify_enabled and a new agent is created
	// with a dify_app_id, show the "go configure graph in Dify Studio" hint
	// instead of (or in addition to) the KB setup wizard.
	const [difyHint, setDifyHint] = useState<{
		agentId: string;
		publishStatus: string;
		difyAppId: string | null;
		difyApiBase: string | null;
	} | null>(null);
	const [onboardingAgentId, setOnboardingAgentId] = useState<string | null>(
		null,
	);
	// M10+3 §7.D — gate Dify-specific UI on workspace.dify_enabled.
	const { dify_enabled: difyEnabled, dify_api_base: difyApiBase } =
		useWorkspaceConfig();
	const { recheck: recheckOnboardingKbStatus } =
		useAgentKbStatus(onboardingAgentId);
	const selectedAgent = useMemo(
		() => agents.find((agent) => agent.id === selectedAgentId) || null,
		[agents, selectedAgentId],
	);
	const selectedOpenableAgent = isOpenableAgent(selectedAgent)
		? selectedAgent
		: null;

	const agentNameDisplayWidth = getAgentNameDisplayWidth(form.name.trim());
	const isAgentNameValid =
		Boolean(form.name.trim()) &&
		agentNameDisplayWidth <= AGENT_NAME_MAX_DISPLAY_WIDTH;

	const loadAgents = async () => {
		setLoading(true);
		setError(null);
		try {
			const data = await api.listAgents();
			setAgents(data.agents);
			setSelectedAgentId((current) => {
				if (current && data.agents.some((agent) => agent.id === current)) {
					return current;
				}
				return (
					data.agents.find((agent) => isOpenableAgent(agent))?.id ||
					data.agents[0]?.id ||
					null
				);
			});
		} catch (err) {
			setError(err instanceof Error ? err.message : t("errors.networkError"));
		} finally {
			setLoading(false);
		}
	};

	useEffect(() => {
		loadAgents();
	}, []);

	useEffect(() => {
		const timer = window.setInterval(
			() => setCountdownTick((value) => value + 1),
			60_000,
		);
		return () => window.clearInterval(timer);
	}, []);

	const handleSelect = (agentId: string) => {
		setSelectedAgentId(agentId);
	};

	const handleCreate = async (event: FormEvent) => {
		event.preventDefault();
		const name = form.name.trim();
		const description = form.description?.trim() || undefined;
		if (
			!isAgentNameValid ||
			(description?.length || 0) > AGENT_DESCRIPTION_MAX_LENGTH
		)
			return;

		setSaving(true);
		setError(null);
		try {
			const created = await api.createAgent({
				...form,
				name,
				description,
				widget_title: name,
			});
			setAgents((prev) => [created, ...prev]);
			setSelectedAgentId(created.id);
			setForm({
				name: "",
				description: "",
				agent_type: "website_support",
				channel_mode: "web_widget",
				workflow_mode: "blank",
				icon_emoji: "🤖",
			});
			// M10+3 §7.A — branching on dify_enabled:
			//   - dify_enabled + dify_app_id present → show "go configure in
			//     Dify Studio" hint, skip KB wizard (D6=a 最小化).
			//   - otherwise → keep legacy KBSetupWizard flow (Plan B compat).
			if (difyEnabled && created.dify_app_id) {
				setDifyHint({
					agentId: created.id,
					publishStatus: created.dify_publish_status ?? "draft",
					difyAppId: created.dify_app_id,
					difyApiBase: difyApiBase,
				});
			} else {
				setOnboardingAgentId(created.id);
			}
		} catch (err) {
			setError(err instanceof Error ? err.message : t("errors.networkError"));
		} finally {
			setSaving(false);
		}
	};

	const handleDeactivate = async (agent: Agent) => {
		setSaving(true);
		setError(null);
		try {
			await api.deleteAgent(agent.id);
			await loadAgents();
		} catch (err) {
			setError(err instanceof Error ? err.message : t("errors.networkError"));
		} finally {
			setSaving(false);
		}
	};

	const handleRestore = async (agent: Agent) => {
		setSaving(true);
		setError(null);
		try {
			const restored = await api.restoreAgent(agent.id);
			api.setSelectedAgentId(restored.id);
			await loadAgents();
			setSelectedAgentId(restored.id);
		} catch (err) {
			setError(err instanceof Error ? err.message : t("errors.networkError"));
		} finally {
			setSaving(false);
		}
	};

	const finishCreatedAgentOnboarding = async () => {
		if (!onboardingAgentId) return;
		const agentId = onboardingAgentId;
		await recheckOnboardingKbStatus();
		api.setSelectedAgentId(agentId);
		setOnboardingAgentId(null);
		navigate(`/agents/${agentId}/dashboard`);
	};

	return (
		<AdminLayout>
			<div
				style={{
					padding: isMobile ? "var(--space-4)" : "var(--space-8)",
					maxWidth: "1200px",
					margin: "0 auto",
				}}
			>
				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						gap: "var(--space-4)",
						alignItems: "flex-start",
						marginBottom: "var(--space-6)",
					}}
				>
					<div>
						<h1
							style={{
								fontSize: "var(--text-3xl)",
								fontWeight: 700,
								color: "var(--color-text-primary)",
								marginBottom: "var(--space-2)",
							}}
						>
							{t("agents.title")}
						</h1>
						<p
							style={{
								color: "var(--color-text-secondary)",
								fontSize: "var(--text-sm)",
							}}
						>
							{t("agents.subtitle")}
						</p>
					</div>
					{selectedOpenableAgent && (
						<button
							onClick={() =>
								navigate(`/agents/${selectedOpenableAgent.id}/dashboard`)
							}
							style={{
								border: "1px solid var(--color-border)",
								background: "var(--color-bg-secondary)",
								color: "var(--color-text-primary)",
								borderRadius: "var(--radius-md)",
								padding: "var(--space-3) var(--space-4)",
								cursor: "pointer",
							}}
						>
							{t("agents.open")}
						</button>
					)}
				</div>

				{error && (
					<div
						style={{
							padding: "var(--space-4)",
							border: "1px solid rgba(239, 68, 68, 0.3)",
							background: "rgba(239, 68, 68, 0.08)",
							color: "var(--color-error)",
							borderRadius: "var(--radius-md)",
							marginBottom: "var(--space-5)",
						}}
					>
						{error}
					</div>
				)}

				<div
					style={{
						display: "grid",
						gridTemplateColumns: isMobile
							? "1fr"
							: "minmax(0, 1.25fr) minmax(320px, 0.75fr)",
						gap: "var(--space-5)",
					}}
				>
					<section
						className="liquid-glass-card"
						style={{ padding: "var(--space-5)" }}
					>
						<h2
							style={{
								color: "var(--color-text-primary)",
								fontSize: "var(--text-xl)",
								marginBottom: "var(--space-4)",
							}}
						>
							{t("agents.allAgents")}
						</h2>
						{loading ? (
							<div style={{ color: "var(--color-text-muted)" }}>
								{t("status.loading")}
							</div>
						) : agents.length === 0 ? (
							<div
								style={{
									color: "var(--color-text-muted)",
									padding: "var(--space-8)",
									textAlign: "center",
								}}
							>
								{t("agents.empty")}
							</div>
						) : (
							<div style={{ display: "grid", gap: "var(--space-3)" }}>
								{agents.map((agent) => (
									<div
										key={agent.id}
										style={{
											display: "grid",
											gridTemplateColumns: isMobile ? "1fr" : "1fr auto",
											gap: "var(--space-3)",
											alignItems: "start",
											padding: "var(--space-4)",
											border: `1px solid ${agent.id === selectedAgentId ? "var(--color-accent-primary)" : "var(--color-border)"}`,
											borderRadius: "var(--radius-md)",
											background:
												agent.id === selectedAgentId
													? "hsla(188deg, 90%, 50%, 0.08)"
													: "var(--color-bg-secondary)",
										}}
									>
										<button
											onClick={() => handleSelect(agent.id)}
											style={{
												width: "100%",
												display: "flex",
												flexDirection: "column",
												alignItems: "flex-start",
												textAlign: "left",
												background: "transparent",
												border: "none",
												color: "inherit",
												cursor: "pointer",
												padding: 0,
											}}
										>
											<div
												style={{
													display: "flex",
													alignItems: "center",
													gap: "var(--space-3)",
													marginBottom: "var(--space-2)",
													width: "100%",
												}}
											>
												<span
													style={{
														width: 36,
														height: 36,
														borderRadius: "var(--radius-md)",
														display: "inline-flex",
														alignItems: "center",
														justifyContent: "center",
														background: "var(--color-accent-gradient)",
														color: "var(--color-text-inverse)",
														fontWeight: 700,
													}}
												>
													{agent.name.charAt(0).toUpperCase()}
												</span>
												<div>
													<div
														style={{
															color: "var(--color-text-primary)",
															fontWeight: 700,
														}}
													>
														{agent.name}
													</div>
													<div
														style={{
															color: "var(--color-text-muted)",
															fontSize: "var(--text-xs)",
														}}
													>
														{agent.id}
													</div>
												</div>
											</div>
											<div
												style={{
													display: "flex",
													flexDirection: "column",
													alignItems: "flex-start",
													width: "100%",
												}}
											>
												<div
													style={{
														color: "var(--color-text-secondary)",
														fontSize: "var(--text-sm)",
														width: "100%",
														whiteSpace: "normal",
													}}
												>
													{agent.description || t("agents.noDescription")}
												</div>
												{agent.deleted_at && (
													<div
														style={{
															display: "block",
															width: "100%",
															marginTop: "var(--space-2)",
															lineHeight: 1.4,
															color: "var(--color-error)",
															fontSize: "var(--text-xs)",
															fontWeight: 600,
															wordBreak: "break-word",
															whiteSpace: "normal",
														}}
													>
														{t("agents.autoDeleteCountdown", {
															time:
																formatPurgeCountdown(agent.purge_after, t) ||
																t("status.pending"),
														})}
													</div>
												)}
											</div>
										</button>
										<div
											style={{
												display: "flex",
												gap: "var(--space-2)",
												justifyContent: isMobile ? "flex-start" : "flex-end",
											}}
										>
											{isOpenableAgent(agent) && (
												<button
													onClick={() =>
														navigate(`/agents/${agent.id}/dashboard`)
													}
													style={{
														padding: "var(--space-2) var(--space-3)",
														borderRadius: "var(--radius-md)",
														border: "1px solid var(--color-border)",
														background: "transparent",
														color: "var(--color-text-primary)",
														cursor: "pointer",
													}}
												>
													{t("agents.open")}
												</button>
											)}
											{agent.deleted_at ? (
												<button
													onClick={() => handleRestore(agent)}
													disabled={saving}
													style={{
														padding: "var(--space-2) var(--space-3)",
														borderRadius: "var(--radius-md)",
														border: "1px solid rgba(16, 185, 129, 0.3)",
														background: "transparent",
														color: "var(--color-success)",
														cursor: saving ? "not-allowed" : "pointer",
													}}
												>
													{t("agents.restore")}
												</button>
											) : (
												<button
													onClick={() => handleDeactivate(agent)}
													disabled={saving}
													style={{
														padding: "var(--space-2) var(--space-3)",
														borderRadius: "var(--radius-md)",
														border: "1px solid rgba(239, 68, 68, 0.3)",
														background: "transparent",
														color: "var(--color-error)",
														cursor: saving ? "not-allowed" : "pointer",
													}}
												>
													{t("agents.deactivate")}
												</button>
											)}
										</div>
									</div>
								))}
							</div>
						)}
					</section>

					<form
						onSubmit={handleCreate}
						className="liquid-glass-card"
						style={{ padding: "var(--space-5)", alignSelf: "start" }}
					>
						<h2
							style={{
								color: "var(--color-text-primary)",
								fontSize: "var(--text-xl)",
								marginBottom: "var(--space-4)",
							}}
						>
							{t("agents.createTitle")}
						</h2>
						<label
							style={{
								display: "block",
								color: "var(--color-text-secondary)",
								fontSize: "var(--text-sm)",
								marginBottom: "var(--space-2)",
							}}
						>
							{t("labels.agentName")}
						</label>
						<input
							value={form.name}
							onChange={(event) =>
								setForm((prev) => ({
									...prev,
									name: trimToAgentNameMaxDisplayWidth(event.target.value),
								}))
							}
							maxLength={AGENT_NAME_MAX_DISPLAY_WIDTH}
							placeholder={t("agents.namePlaceholder")}
							style={{
								width: "100%",
								marginBottom: "var(--space-2)",
								padding: "var(--space-3)",
								borderRadius: "var(--radius-md)",
								border: "1px solid var(--color-border)",
								background: "var(--color-bg-secondary)",
								color: "var(--color-text-primary)",
							}}
						/>
						<div
							style={{
								display: "flex",
								justifyContent: "flex-end",
								color: "var(--color-text-muted)",
								fontSize: "var(--text-xs)",
								marginBottom: "var(--space-4)",
							}}
						>
							{t("agents.characterCount", {
								count: agentNameDisplayWidth,
								max: AGENT_NAME_MAX_DISPLAY_WIDTH,
							})}
						</div>
						<label
							style={{
								display: "block",
								color: "var(--color-text-secondary)",
								fontSize: "var(--text-sm)",
								marginBottom: "var(--space-2)",
							}}
						>
							{t("agents.type")}
						</label>
						<div
							style={{
								display: "grid",
								gap: "var(--space-2)",
								marginBottom: "var(--space-4)",
							}}
						>
							{agentTypeOptions.map((option) => (
								<button
									key={option.value}
									type="button"
									onClick={() =>
										setForm((prev) => ({ ...prev, agent_type: option.value }))
									}
									style={{
										textAlign: "left",
										padding: "var(--space-3)",
										borderRadius: "var(--radius-md)",
										border: `1px solid ${form.agent_type === option.value ? "var(--color-accent-primary)" : "var(--color-border)"}`,
										background:
											form.agent_type === option.value
												? "hsla(188deg, 90%, 50%, 0.08)"
												: "transparent",
										cursor: "pointer",
									}}
								>
									<div
										style={{
											color: "var(--color-text-primary)",
											fontWeight: 600,
										}}
									>
										{t(option.labelKey)}
									</div>
									<div
										style={{
											color: "var(--color-text-muted)",
											fontSize: "var(--text-xs)",
										}}
									>
										{t(option.descriptionKey)}
									</div>
								</button>
							))}
						</div>
						<label
							style={{
								display: "block",
								color: "var(--color-text-secondary)",
								fontSize: "var(--text-sm)",
								marginBottom: "var(--space-2)",
							}}
						>
							{t("labels.description")}
						</label>
						<textarea
							value={form.description}
							onChange={(event) =>
								setForm((prev) => ({
									...prev,
									description: event.target.value.slice(
										0,
										AGENT_DESCRIPTION_MAX_LENGTH,
									),
								}))
							}
							maxLength={AGENT_DESCRIPTION_MAX_LENGTH}
							rows={4}
							placeholder={t("agents.descriptionPlaceholder")}
							style={{
								width: "100%",
								marginBottom: "var(--space-2)",
								padding: "var(--space-3)",
								borderRadius: "var(--radius-md)",
								border: "1px solid var(--color-border)",
								background: "var(--color-bg-secondary)",
								color: "var(--color-text-primary)",
								resize: "vertical",
							}}
						/>
						<div
							style={{
								display: "flex",
								justifyContent: "flex-end",
								color: "var(--color-text-muted)",
								fontSize: "var(--text-xs)",
								marginBottom: "var(--space-4)",
							}}
						>
							{t("agents.characterCount", {
								count: form.description?.length || 0,
								max: AGENT_DESCRIPTION_MAX_LENGTH,
							})}
						</div>
						{/* M10+3 §7.A — Dify workflow + icon fields, gated on
						    workspace.dify_enabled. Hidden entirely for Plan B
						    workspaces (dify_enabled=false). */}
						{difyEnabled && (
							<div
								data-testid="dify-form-section"
								style={{
									marginBottom: "var(--space-4)",
									padding: "var(--space-3)",
									borderRadius: "var(--radius-md)",
									border: "1px dashed var(--color-border)",
									background: "var(--color-bg-secondary)",
								}}
							>
								<label
									style={{
										display: "block",
										color: "var(--color-text-secondary)",
										fontSize: "var(--text-sm)",
										marginBottom: "var(--space-2)",
									}}
								>
									{t("agents.difyWorkflowMode")}
								</label>
								<select
									data-testid="dify-workflow-mode"
									value={form.workflow_mode ?? "blank"}
									onChange={(event) =>
										setForm((prev) => ({
											...prev,
											workflow_mode: event.target.value as WorkflowMode,
										}))
									}
									style={{
										width: "100%",
										marginBottom: "var(--space-3)",
										padding: "var(--space-3)",
										borderRadius: "var(--radius-md)",
										border: "1px solid var(--color-border)",
										background: "var(--color-bg-primary)",
										color: "var(--color-text-primary)",
									}}
								>
									<option value="blank">
										{t("agents.difyWorkflowModeBlank")}
									</option>
									<option value="template_v1">
										{t("agents.difyWorkflowModeTemplate")}
									</option>
								</select>
								<label
									style={{
										display: "block",
										color: "var(--color-text-secondary)",
										fontSize: "var(--text-sm)",
										marginBottom: "var(--space-2)",
									}}
								>
									{t("agents.difyIconEmoji")}
								</label>
								<input
									data-testid="dify-icon-emoji"
									type="text"
									value={form.icon_emoji ?? ""}
									maxLength={4}
									onChange={(event) =>
										setForm((prev) => ({
											...prev,
											icon_emoji: event.target.value.slice(0, 4),
										}))
									}
									style={{
										width: "100%",
										padding: "var(--space-3)",
										borderRadius: "var(--radius-md)",
										border: "1px solid var(--color-border)",
										background: "var(--color-bg-primary)",
										color: "var(--color-text-primary)",
									}}
								/>
							</div>
						)}
						<button
							type="submit"
							disabled={
								saving ||
								!isAgentNameValid ||
								(form.description?.trim().length || 0) >
									AGENT_DESCRIPTION_MAX_LENGTH
							}
							style={{
								width: "100%",
								padding: "var(--space-3)",
								borderRadius: "var(--radius-md)",
								border: "none",
								background: "var(--color-accent-gradient)",
								color: "var(--color-text-inverse)",
								fontWeight: 700,
								cursor: saving || !isAgentNameValid ? "not-allowed" : "pointer",
								opacity: saving || !isAgentNameValid ? 0.6 : 1,
							}}
						>
							{saving ? t("status.saving") : t("agents.create")}
						</button>
					</form>
				</div>
			</div>
			{onboardingAgentId && (
				<div
					data-testid="kb-onboarding-modal"
					style={{
						position: "fixed",
						inset: 0,
						zIndex: 9999,
						background: "rgba(0,0,0,0.55)",
						display: "flex",
						alignItems: "center",
						justifyContent: "center",
						padding: "var(--space-4)",
					}}
					role="dialog"
					aria-modal="true"
					aria-label={t("agents.kbOnboardingTitle")}
				>
					<div
						style={{
							maxWidth: 720,
							width: "100%",
							maxHeight: "calc(100vh - 32px)",
							overflowY: "auto",
						}}
					>
						<KBSetupWizard
							agentId={onboardingAgentId}
							containerTestId="kb-wizard"
							cancelLabel={t("agents.kbOnboardingSkip")}
							onCancel={finishCreatedAgentOnboarding}
							onSetupComplete={finishCreatedAgentOnboarding}
						/>
					</div>
				</div>
			)}
			{/* M10+3 §7.A — Dify hint modal. Shown when dify_enabled and a new
			    agent was created with a dify_app_id. Directs the admin to
			    Dify Studio to add nodes + publish the workflow. */}
			{difyHint && (
				<div
					data-testid="dify-hint-modal"
					style={{
						position: "fixed",
						inset: 0,
						zIndex: 9999,
						background: "rgba(0,0,0,0.55)",
						display: "flex",
						alignItems: "center",
						justifyContent: "center",
						padding: "var(--space-4)",
					}}
					role="dialog"
					aria-modal="true"
					aria-label={t("agents.difyHintTitle")}
				>
					<div
						className="liquid-glass-card"
						style={{
							maxWidth: 520,
							width: "100%",
							padding: "var(--space-5)",
							color: "var(--color-text-primary)",
						}}
					>
						<h2
							style={{
								fontSize: "var(--text-xl)",
								marginBottom: "var(--space-3)",
							}}
						>
							{t("agents.difyHintTitle")}
						</h2>
						<p
							style={{
								marginBottom: "var(--space-4)",
								color: "var(--color-text-secondary)",
							}}
						>
							{t("agents.difyHintBody", {
								status: difyHint.publishStatus,
							})}
						</p>
						<div
							style={{
								display: "flex",
								gap: "var(--space-3)",
								justifyContent: "flex-end",
							}}
						>
							{difyHint.difyAppId && difyHint.difyApiBase && (
								<a
									data-testid="dify-open-studio-link"
									href={`${difyHint.difyApiBase.replace(
										/\/+$/,
										"",
									)}/app/${difyHint.difyAppId}/workflow`}
									target="_blank"
									rel="noopener noreferrer"
									style={{
										padding: "var(--space-2) var(--space-4)",
										borderRadius: "var(--radius-md)",
										background: "var(--color-accent-primary)",
										color: "var(--color-text-inverse)",
										fontWeight: 600,
										textDecoration: "none",
									}}
								>
									{t("agents.difyHintOpenStudio")} ↗
								</a>
							)}
							<button
								type="button"
								data-testid="dify-hint-close"
								onClick={() => {
									const agentId = difyHint.agentId;
									setDifyHint(null);
									api.setSelectedAgentId(agentId);
									navigate(`/agents/${agentId}/dashboard`);
								}}
								style={{
									padding: "var(--space-2) var(--space-4)",
									borderRadius: "var(--radius-md)",
									border: "1px solid var(--color-border)",
									background: "var(--color-bg-secondary)",
									color: "var(--color-text-primary)",
									cursor: "pointer",
								}}
							>
								{t("common.close") ?? "Close"}
							</button>
						</div>
					</div>
				</div>
			)}
		</AdminLayout>
	);
}

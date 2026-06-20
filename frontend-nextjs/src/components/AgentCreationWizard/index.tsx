"use client";

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../../services/api";
import type {
	Agent,
	WorkflowPreviewResponse,
	WorkflowTemplateMeta,
} from "../../services/api";
import { useAuth } from "../../context/AuthContext";
import Stepper from "./Stepper";
import Step1BasicInfo, { type BasicInfo } from "./Step1BasicInfo";
import Step2TemplateSelect from "./Step2TemplateSelect";
import Step3ParamsForm from "./Step3ParamsForm";
import Step4Preview from "./Step4Preview";
import Step5Confirm from "./Step5Confirm";

const TOTAL_STEPS = 5;

/**
 * M12 PR-3 — 5 步 wizard state machine。
 *
 * 流程:BasicInfo → TemplateSelect → ParamsForm → Preview → Confirm
 * - step 4 第一次进:直传 params_overrides 调 preview(不走 LLM,确定性高)
 * - step 5 user_requirements 改了 → 走 LLM 路径重生成
 * - submit → POST /agents 带 template_id + template_params
 */
export default function AgentCreationWizard() {
	const { t } = useTranslation("common");
	const navigate = useNavigate();
	const { admin } = useAuth();

	const [step, setStep] = useState(1);
	const [basicInfo, setBasicInfo] = useState<BasicInfo>({ name: "", description: "" });

	const [templates, setTemplates] = useState<WorkflowTemplateMeta[]>([]);
	const [templatesLoading, setTemplatesLoading] = useState(false);
	const [templatesError, setTemplatesError] = useState<string | null>(null);
	const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

	const [paramsValues, setParamsValues] = useState<Record<string, unknown>>({});
	const [paramsErrors, setParamsErrors] = useState<Record<string, string>>({});

	const [preview, setPreview] = useState<WorkflowPreviewResponse | null>(null);
	const [previewLoading, setPreviewLoading] = useState(false);
	const [previewError, setPreviewError] = useState<string | null>(null);

	const [userRequirements, setUserRequirements] = useState("");
	const [regenerating, setRegenerating] = useState(false);
	const [regenerateError, setRegenerateError] = useState<string | null>(null);

	const [submitting, setSubmitting] = useState(false);
	const [submitError, setSubmitError] = useState<string | null>(null);

	const selectedTemplate = useMemo(
		() => templates.find((tpl) => tpl.id === selectedTemplateId) ?? null,
		[templates, selectedTemplateId],
	);

	// 加载模板列表(step 2 进场时)
	useEffect(() => {
		if (step !== 2 || templates.length > 0 || templatesLoading) return;
		setTemplatesLoading(true);
		setTemplatesError(null);
		api
			.listTemplates()
			.then((resp) => {
				setTemplates(resp.templates);
				if (resp.templates.length > 0 && !selectedTemplateId) {
					setSelectedTemplateId(resp.templates[0].id);
				}
			})
			.catch((err: Error) => {
				setTemplatesError(err.message || t("wizard.errors.loadTemplates"));
			})
			.finally(() => setTemplatesLoading(false));
	}, [step, templates.length, templatesLoading, selectedTemplateId, t]);

	// 模板切换 → 重置 params + preview
	useEffect(() => {
		if (!selectedTemplate) return;
		const props = (selectedTemplate.params_schema_json.properties ?? {}) as Record<
			string,
			{ type?: string; minLength?: number; default?: unknown }
		>;
		const defaults: Record<string, unknown> = {};
		for (const [key, prop] of Object.entries(props)) {
			const schemaProp = prop as { default?: unknown };
			if (schemaProp.default !== undefined) {
				defaults[key] = schemaProp.default;
			}
		}
		setParamsValues(defaults);
		setParamsErrors({});
		setPreview(null);
		setPreviewError(null);
	}, [selectedTemplateId]); // eslint-disable-line react-hooks/exhaustive-deps

	// step 3 → step 4 自动跑 preview(直传路径)
	useEffect(() => {
		if (step !== 4 || !selectedTemplate || preview || previewLoading) return;
		void runPreview(false);
	}, [step]); // eslint-disable-line react-hooks/exhaustive-deps

	const runPreview = async (useLlm: boolean) => {
		if (!selectedTemplate) return;
		if (useLlm) {
			setRegenerating(true);
			setRegenerateError(null);
		} else {
			setPreviewLoading(true);
			setPreviewError(null);
		}
		try {
			const resp = await api.generateWorkflowPreview({
				template_id: selectedTemplate.id,
				user_requirements: useLlm ? userRequirements : undefined,
				params_overrides: useLlm ? undefined : paramsValues,
			});
			setPreview(resp);
		} catch (err) {
			const msg = err instanceof Error ? err.message : t("wizard.errors.loadPreview");
			if (useLlm) {
				setRegenerateError(msg);
			} else {
				setPreviewError(msg);
			}
		} finally {
			if (useLlm) {
				setRegenerating(false);
			} else {
				setPreviewLoading(false);
			}
		}
	};

	const validateStep1 = (): boolean => {
		if (!basicInfo.name.trim()) return false;
		return true;
	};

	const validateStep3 = (): boolean => {
		if (!selectedTemplate) return false;
		const props = (selectedTemplate.params_schema_json.properties ?? {}) as Record<
			string,
			{ type?: string; minLength?: number; default?: unknown }
		>;
		const required = (selectedTemplate.params_schema_json.required ?? []) as string[];
		const errs: Record<string, string> = {};
		let hasError = false;
		for (const key of required) {
			const v = paramsValues[key];
			const prop = props[key] as { type?: string; minLength?: number } | undefined;
			if (v === undefined || v === null || v === "") {
				errs[key] = t("wizard.errors.paramsInvalid");
				hasError = true;
			} else if (prop?.type === "string" && typeof v === "string") {
				if (prop.minLength && v.length < prop.minLength) {
					errs[key] = t("wizard.errors.paramsInvalid");
					hasError = true;
				}
			}
		}
		setParamsErrors(errs);
		return !hasError;
	};

	const handleNext = () => {
		if (step === 1 && !validateStep1()) {
			return;
		}
		if (step === 3 && !validateStep3()) {
			return;
		}
		setStep((s) => Math.min(TOTAL_STEPS, s + 1));
	};

	const handleBack = () => {
		setStep((s) => Math.max(1, s - 1));
	};

	const handleSubmit = async () => {
		if (!selectedTemplate || !admin) return;
		setSubmitting(true);
		setSubmitError(null);
		try {
			const created: Agent = await api.createAgent({
				name: basicInfo.name.trim(),
				description: basicInfo.description.trim() || undefined,
				agent_type: "website_support",
				channel_mode: "web_widget",
				template_id: selectedTemplate.id,
				template_params: paramsValues,
				user_requirements: userRequirements.trim() || undefined,
				widget_title: basicInfo.name.trim(),
			});
			navigate(`/agents/${created.id}/dashboard`);
		} catch (err) {
			setSubmitError(err instanceof Error ? err.message : t("wizard.errors.createAgent"));
		} finally {
			setSubmitting(false);
		}
	};

	if (!admin) {
		return (
			<div style={{ padding: "var(--space-6)" }}>
				{t("auth.unauthenticated")}
			</div>
		);
	}

	return (
		<div
			data-testid="agent-creation-wizard"
			style={{
				display: "flex",
				flexDirection: "column",
				gap: "var(--space-5)",
				padding: "var(--space-6)",
				maxWidth: 880,
				margin: "0 auto",
			}}
		>
			<header>
				<h1
					style={{
						color: "var(--color-text-primary)",
						fontSize: "var(--text-2xl)",
						fontWeight: 700,
						marginBottom: "var(--space-1)",
					}}
				>
					{t("wizard.title")}
				</h1>
				<p
					style={{
						color: "var(--color-text-secondary)",
						fontSize: "var(--text-sm)",
					}}
				>
					{t("wizard.subtitle")}
				</p>
			</header>

			<Stepper current={step} total={TOTAL_STEPS} />

			<div
				className="liquid-glass-card"
				data-testid={`wizard-step-panel-${step}`}
				style={{ padding: "var(--space-6)" }}
			>
				{step === 1 && (
					<Step1BasicInfo
						value={basicInfo}
						onChange={setBasicInfo}
						errorName={
							basicInfo.name.trim() === "" ? t("wizard.errors.nameRequired") : null
						}
					/>
				)}
				{step === 2 && (
					<Step2TemplateSelect
						templates={templates}
						selectedId={selectedTemplateId}
						onSelect={setSelectedTemplateId}
						loading={templatesLoading}
						error={templatesError}
					/>
				)}
				{step === 3 && selectedTemplate && (
					<Step3ParamsForm
						schema={selectedTemplate.params_schema_json}
						values={paramsValues}
						onChange={setParamsValues}
						errors={paramsErrors}
					/>
				)}
				{step === 4 && selectedTemplate && (
					<Step4Preview
						preview={preview}
						loading={previewLoading}
						error={previewError}
						ymlPreviewFallback={selectedTemplate.yml_preview}
						templateName={selectedTemplate.name}
					/>
				)}
				{step === 5 && (
					<Step5Confirm
						generating={regenerating}
						previewError={regenerateError}
						onRegenerate={() => runPreview(true)}
						userRequirements={userRequirements}
						onUserRequirementsChange={setUserRequirements}
					/>
				)}
			</div>

			{submitError && (
				<div
					style={{
						padding: "var(--space-3) var(--space-4)",
						borderRadius: "var(--radius-md)",
						border: "1px solid var(--color-error)",
						background: "var(--color-error-bg)",
						color: "var(--color-error)",
						fontSize: "var(--text-sm)",
					}}
				>
					{submitError}
				</div>
			)}

			<div style={{ display: "flex", gap: "var(--space-3)", justifyContent: "flex-end" }}>
				<button
					type="button"
					onClick={() => navigate("/agents")}
					className="btn-secondary"
				>
					{t("wizard.cancel")}
				</button>
				{step > 1 && (
					<button
						type="button"
						data-testid="wizard-back"
						onClick={handleBack}
						className="btn-secondary"
						disabled={submitting}
					>
						{t("wizard.back")}
					</button>
				)}
				{step < TOTAL_STEPS ? (
					<button
						type="button"
						data-testid="wizard-next"
						onClick={handleNext}
						className="btn-primary"
						disabled={
							(step === 2 && !selectedTemplateId) ||
							(step === 3 && !selectedTemplate)
						}
					>
						{t("wizard.next")}
					</button>
				) : (
					<button
						type="button"
						data-testid="wizard-submit"
						onClick={handleSubmit}
						className="btn-primary"
						disabled={submitting || !selectedTemplate}
					>
						{submitting && (
							<div
								className="spinner"
								style={{
									width: 14,
									height: 14,
									borderWidth: 2,
									borderColor: "rgba(255,255,255,0.3)",
									borderTopColor: "white",
								}}
							/>
						)}
						{t("wizard.submit")}
					</button>
				)}
			</div>
		</div>
	);
}
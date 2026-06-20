"use client";

import { useTranslation } from "react-i18next";
import type { WorkflowTemplateMeta } from "../../services/api";

type Props = {
	templates: WorkflowTemplateMeta[];
	selectedId: string | null;
	onSelect: (id: string) => void;
	loading: boolean;
	error: string | null;
};

/**
 * M12 PR-3 — Step 2: 4 卡片网格选择模板。
 */
export default function Step2TemplateSelect({
	templates,
	selectedId,
	onSelect,
	loading,
	error,
}: Props) {
	const { t } = useTranslation("common");

	if (loading) {
		return (
			<div
				data-testid="wizard-step2-loading"
				style={{ color: "var(--color-text-muted)", padding: "var(--space-6)" }}
			>
				{t("status.loading")}
			</div>
		);
	}

	if (error) {
		return (
			<div
				data-testid="wizard-step2-error"
				style={{
					padding: "var(--space-4)",
					borderRadius: "var(--radius-md)",
					border: "1px solid var(--color-error)",
					background: "var(--color-error-bg)",
					color: "var(--color-error)",
				}}
			>
				{error}
			</div>
		);
	}

	if (templates.length === 0) {
		return (
			<div
				data-testid="wizard-step2-empty"
				style={{ color: "var(--color-text-muted)", padding: "var(--space-6)" }}
			>
				{t("wizard.noTemplates")}
			</div>
		);
	}

	return (
		<div
			data-testid="wizard-step2"
			style={{
				display: "grid",
				gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
				gap: "var(--space-3)",
			}}
		>
			{templates.map((tpl) => {
				const selected = tpl.id === selectedId;
				return (
					<button
						key={tpl.id}
						type="button"
						data-testid={`wizard-template-${tpl.id}`}
						onClick={() => onSelect(tpl.id)}
						style={{
							textAlign: "left",
							padding: "var(--space-4)",
							borderRadius: "var(--radius-md)",
							border: `1px solid ${selected ? "var(--color-accent-primary)" : "var(--color-border)"}`,
							background: selected
								? "hsla(188deg, 90%, 50%, 0.08)"
								: "var(--color-bg-secondary)",
							cursor: "pointer",
							color: "inherit",
							display: "flex",
							flexDirection: "column",
							gap: "var(--space-2)",
						}}
					>
						<div
							style={{
								display: "flex",
								alignItems: "center",
								justifyContent: "space-between",
							}}
						>
							<div
								style={{
									color: "var(--color-text-primary)",
									fontWeight: 700,
									fontSize: "var(--text-base)",
								}}
							>
								{tpl.name}
							</div>
							<span
								style={{
									padding: "2px var(--space-2)",
									borderRadius: "var(--radius-sm)",
									background: "var(--color-bg-primary)",
									border: "1px solid var(--color-border)",
									color: "var(--color-text-muted)",
									fontSize: "var(--text-xs)",
								}}
							>
								{t(`wizard.templateCategory.${tpl.category}` as const)}
							</span>
						</div>
						<div
							style={{
								color: "var(--color-text-secondary)",
								fontSize: "var(--text-sm)",
								lineHeight: 1.5,
							}}
						>
							{tpl.description}
						</div>
						<div
							style={{
								color: "var(--color-text-muted)",
								fontSize: "var(--text-xs)",
								marginTop: "auto",
							}}
						>
							Dify ≥ {tpl.min_dify_version}
						</div>
					</button>
				);
			})}
		</div>
	);
}
"use client";

import { useTranslation } from "react-i18next";

type Props = {
	current: number;
	total: number;
};

/**
 * M12 PR-3 — 5 步 wizard 的进度条。
 * 内置在 AgentCreationWizard 内,不抽公共组件。
 */
export default function Stepper({ current, total }: Props) {
	const { t } = useTranslation("common");
	const labels = [
		t("wizard.step1"),
		t("wizard.step2"),
		t("wizard.step3"),
		t("wizard.step4"),
		t("wizard.step5"),
	];

	return (
		<div
			data-testid="wizard-stepper"
			style={{
				display: "flex",
				alignItems: "center",
				gap: "var(--space-2)",
				padding: "var(--space-3) var(--space-4)",
				borderRadius: "var(--radius-md)",
				background: "var(--color-bg-secondary)",
			}}
		>
			{labels.slice(0, total).map((label, idx) => {
				const stepNum = idx + 1;
				const isCurrent = stepNum === current;
				const isDone = stepNum < current;
				const color = isCurrent
					? "var(--color-accent-primary)"
					: isDone
						? "var(--color-success)"
						: "var(--color-text-muted)";
				return (
					<div
						key={label}
						data-testid={`wizard-step-${stepNum}`}
						style={{
							display: "flex",
							alignItems: "center",
							gap: "var(--space-2)",
							flex: 1,
						}}
					>
						<div
							style={{
								width: 28,
								height: 28,
								borderRadius: "50%",
								display: "inline-flex",
								alignItems: "center",
								justifyContent: "center",
								border: `2px solid ${color}`,
								color,
								fontWeight: 600,
								fontSize: "var(--text-sm)",
								background: isCurrent ? "hsla(188deg, 90%, 50%, 0.1)" : "transparent",
								flexShrink: 0,
							}}
						>
							{stepNum}
						</div>
						<span
							style={{
								color: isCurrent ? "var(--color-text-primary)" : "var(--color-text-secondary)",
								fontSize: "var(--text-sm)",
								fontWeight: isCurrent ? 600 : 400,
								whiteSpace: "nowrap",
							}}
						>
							{label}
						</span>
						{stepNum < total && (
							<div
								style={{
									flex: 1,
									height: 2,
									background: isDone
										? "var(--color-success)"
										: "var(--color-border)",
								}}
							/>
						)}
					</div>
				);
			})}
		</div>
	);
}
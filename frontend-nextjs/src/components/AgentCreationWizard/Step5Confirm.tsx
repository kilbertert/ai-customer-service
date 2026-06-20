"use client";

import { useTranslation } from "react-i18next";

type Props = {
	generating: boolean;
	previewError: string | null;
	onRegenerate: () => void;
	userRequirements: string;
	onUserRequirementsChange: (v: string) => void;
};

/**
 * M12 PR-3 — Step 5: 确认页。
 * - user_requirements 文本框 → 触发重新生成(可选)
 * - "重新生成" 按钮调 DSLGenerator 重新走一遍
 * - 失败显示错误
 */
export default function Step5Confirm({
	generating,
	previewError,
	onRegenerate,
	userRequirements,
	onUserRequirementsChange,
}: Props) {
	const { t } = useTranslation("common");

	return (
		<div data-testid="wizard-step5" style={{ display: "grid", gap: "var(--space-4)" }}>
			<div>
				<label
					style={{
						display: "block",
						marginBottom: "var(--space-2)",
						fontSize: "var(--text-sm)",
						fontWeight: 500,
						color: "var(--color-text-secondary)",
					}}
				>
					user_requirements
				</label>
				<textarea
					data-testid="wizard-user-requirements"
					rows={4}
					value={userRequirements}
					onChange={(e) => onUserRequirementsChange(e.target.value)}
					placeholder="例如:电商客服,需要礼貌回答退货问题"
					style={{ width: "100%", resize: "vertical" }}
				/>
				<div
					style={{
						marginTop: "var(--space-1)",
						fontSize: "var(--text-xs)",
						color: "var(--color-text-muted)",
					}}
				>
					可选。给 LLM 的自然语言补充;留空则直接用 step 3 填的参数。
				</div>
			</div>

			<button
				type="button"
				data-testid="wizard-regenerate"
				onClick={onRegenerate}
				disabled={generating}
				className="btn-secondary"
				style={{ justifySelf: "start" }}
			>
				{generating && (
					<div
						className="spinner"
						style={{
							width: 14,
							height: 14,
							borderWidth: 2,
							borderColor: "rgba(0,0,0,0.2)",
							borderTopColor: "currentColor",
						}}
					/>
				)}
				{generating ? t("wizard.regenerating") : t("wizard.regenerate")}
			</button>

			{previewError && (
				<div
					data-testid="wizard-regenerate-error"
					style={{
						padding: "var(--space-3) var(--space-4)",
						borderRadius: "var(--radius-md)",
						border: "1px solid var(--color-error)",
						background: "var(--color-error-bg)",
						color: "var(--color-error)",
						fontSize: "var(--text-sm)",
					}}
				>
					{previewError}
				</div>
			)}
		</div>
	);
}
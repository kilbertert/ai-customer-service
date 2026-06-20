"use client";

import { useTranslation } from "react-i18next";
import {
	AGENT_NAME_MAX_DISPLAY_WIDTH,
	getAgentNameDisplayWidth,
	trimToAgentNameMaxDisplayWidth,
} from "../../lib/agentNameLength";

const AGENT_DESCRIPTION_MAX_LENGTH = 200;

export type BasicInfo = {
	name: string;
	description: string;
};

type Props = {
	value: BasicInfo;
	onChange: (next: BasicInfo) => void;
	errorName?: string | null;
};

/**
 * M12 PR-3 — Step 1: 基础信息(name + description)。
 */
export default function Step1BasicInfo({ value, onChange, errorName }: Props) {
	const { t } = useTranslation("common");
	const displayWidth = getAgentNameDisplayWidth(value.name.trim());
	const isValid = Boolean(value.name.trim()) && displayWidth <= AGENT_NAME_MAX_DISPLAY_WIDTH;

	return (
		<div data-testid="wizard-step1" style={{ display: "grid", gap: "var(--space-4)" }}>
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
					{t("wizard.fields.name")}
				</label>
				<input
					data-testid="wizard-name-input"
					type="text"
					value={value.name}
					onChange={(e) =>
						onChange({
							...value,
							name: trimToAgentNameMaxDisplayWidth(e.target.value),
						})
					}
					style={{ width: "100%" }}
				/>
				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						marginTop: "var(--space-1)",
						fontSize: "var(--text-xs)",
						color: isValid
							? "var(--color-text-muted)"
							: "var(--color-error)",
					}}
				>
					<span>{t("wizard.fields.nameHint")}</span>
					<span>
						{t("agents.characterCount", {
							count: displayWidth,
							max: AGENT_NAME_MAX_DISPLAY_WIDTH,
						})}
					</span>
				</div>
				{errorName && (
					<div
						style={{
							marginTop: "var(--space-2)",
							color: "var(--color-error)",
							fontSize: "var(--text-xs)",
						}}
					>
						{errorName}
					</div>
				)}
			</div>

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
					{t("wizard.fields.description")}
				</label>
				<textarea
					data-testid="wizard-description-input"
					value={value.description}
					onChange={(e) =>
						onChange({
							...value,
							description: e.target.value.slice(0, AGENT_DESCRIPTION_MAX_LENGTH),
						})
					}
					rows={3}
					style={{ width: "100%", resize: "vertical" }}
				/>
				<div
					style={{
						marginTop: "var(--space-1)",
						fontSize: "var(--text-xs)",
						color: "var(--color-text-muted)",
						textAlign: "right",
					}}
				>
					{t("agents.characterCount", {
						count: value.description.length,
						max: AGENT_DESCRIPTION_MAX_LENGTH,
					})}
				</div>
			</div>
		</div>
	);
}
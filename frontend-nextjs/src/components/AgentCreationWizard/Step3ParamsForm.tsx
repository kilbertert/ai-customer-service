"use client";

import { useTranslation } from "react-i18next";

type ParamType = "string" | "number" | "integer" | "boolean" | "array";

type JsonSchemaProperty = {
	type?: ParamType | string;
	title?: string;
	description?: string;
	default?: unknown;
	minimum?: number;
	maximum?: number;
	minLength?: number;
	maxLength?: number;
	enum?: unknown[];
};

type JsonSchema = {
	type?: "object";
	properties?: Record<string, JsonSchemaProperty>;
	required?: string[];
};

type Props = {
	schema: JsonSchema;
	values: Record<string, unknown>;
	onChange: (next: Record<string, unknown>) => void;
	errors?: Record<string, string>;
};

const KNOWN_FIELD_KEYS = new Set([
	"system_prompt",
	"user_prompt_template",
	"model_name",
	"temperature",
	"knowledge_base_ids",
	"router_conditions",
	"tool_name",
	"tool_input_vars",
]);

/**
 * M12 PR-3 — Step 3: 从 params_schema_json 动态渲染表单。
 * 支持 string / number / integer / boolean / list[str] 五种类型。
 * 4 模板共 ~16 字段,手写渲染器比 react-hook-form 简单。
 */
export default function Step3ParamsForm({ schema, values, onChange, errors }: Props) {
	const { t } = useTranslation("common");
	const props = schema.properties ?? {};
	const required = new Set(schema.required ?? []);

	const setField = (key: string, value: unknown) => {
		onChange({ ...values, [key]: value });
	};

	const fieldLabelKey = (key: string): string =>
		KNOWN_FIELD_KEYS.has(key) ? `wizard.fields.${key}` : key;

	return (
		<div data-testid="wizard-step3" style={{ display: "grid", gap: "var(--space-4)" }}>
			{Object.entries(props).map(([key, prop]) => {
				const isRequired = required.has(key);
				const label = t(fieldLabelKey(key));
				const description = prop.description;
				const error = errors?.[key];

				return (
					<div key={key} data-testid={`wizard-param-${key}`}>
						<label
							style={{
								display: "block",
								marginBottom: "var(--space-2)",
								fontSize: "var(--text-sm)",
								fontWeight: 500,
								color: "var(--color-text-secondary)",
							}}
						>
							{label}
							{isRequired && (
								<span style={{ color: "var(--color-error)", marginLeft: 4 }}>*</span>
							)}
						</label>
						{renderField(key, prop, values[key], (v) => setField(key, v))}
						{description && (
							<div
								style={{
									marginTop: "var(--space-1)",
									fontSize: "var(--text-xs)",
									color: "var(--color-text-muted)",
								}}
							>
								{description}
							</div>
						)}
						{error && (
							<div
								style={{
									marginTop: "var(--space-1)",
									color: "var(--color-error)",
									fontSize: "var(--text-xs)",
								}}
							>
								{error}
							</div>
						)}
					</div>
				);
			})}
		</div>
	);
}

function renderField(
	key: string,
	prop: JsonSchemaProperty,
	current: unknown,
	setValue: (v: unknown) => void,
) {
	const type = prop.type ?? "string";

	if (type === "number" || type === "integer") {
		const numValue =
			current === undefined || current === null
				? ""
				: typeof current === "number"
					? String(current)
					: String(current);
		return (
			<input
				data-testid={`wizard-input-${key}`}
				type="number"
				value={numValue}
				min={prop.minimum}
				max={prop.maximum}
				step={type === "integer" ? 1 : 0.1}
				onChange={(e) => {
					const v = e.target.value;
					if (v === "") {
						setValue(undefined);
					} else {
						setValue(type === "integer" ? parseInt(v, 10) : parseFloat(v));
					}
				}}
				style={{ width: "100%" }}
			/>
		);
	}

	if (type === "boolean") {
		return (
			<label
				style={{
					display: "inline-flex",
					alignItems: "center",
					gap: "var(--space-2)",
				}}
			>
				<input
					data-testid={`wizard-input-${key}`}
					type="checkbox"
					checked={Boolean(current)}
					onChange={(e) => setValue(e.target.checked)}
				/>
				<span>{current ? "true" : "false"}</span>
			</label>
		);
	}

	if (type === "array") {
		// 数组用逗号分隔的 input 简化处理
		const arr = Array.isArray(current)
			? current
			: typeof current === "string"
				? current.split(",").map((s) => s.trim())
				: [];
		const displayValue = arr.join(", ");
		return (
			<input
				data-testid={`wizard-input-${key}`}
				type="text"
				value={displayValue}
				onChange={(e) => {
					const split = e.target.value
						.split(",")
						.map((s) => s.trim())
						.filter(Boolean);
					setValue(split);
				}}
				placeholder="value1, value2"
				style={{ width: "100%" }}
			/>
		);
	}

	// 默认 string(text 或 textarea)
	const strValue = typeof current === "string" ? current : current == null ? "" : String(current);
	const isLong =
		(prop.maxLength ?? 0) >= 500 || key === "system_prompt" || key === "tool_input_vars";

	if (isLong) {
		return (
			<textarea
				data-testid={`wizard-input-${key}`}
				value={strValue}
				rows={4}
				onChange={(e) => setValue(e.target.value)}
				maxLength={prop.maxLength}
				style={{ width: "100%", resize: "vertical", fontFamily: "inherit" }}
			/>
		);
	}

	return (
		<input
			data-testid={`wizard-input-${key}`}
			type="text"
			value={strValue}
			onChange={(e) => setValue(e.target.value)}
			maxLength={prop.maxLength}
			style={{ width: "100%" }}
		/>
	);
}
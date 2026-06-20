"use client";

import { useTranslation } from "react-i18next";
import type { WorkflowPreviewResponse } from "../../services/api";
import WorkflowSummary, {
	type WorkflowEdge,
	type WorkflowNode,
} from "./WorkflowSummary";

type Props = {
	preview: WorkflowPreviewResponse | null;
	loading: boolean;
	error: string | null;
	ymlPreviewFallback: string;
	templateName: string;
};

/**
 * M12 PR-3 — Step 4: 工作流预览(节点列表 + 边箭头 + yml 折叠区)。
 * 节点 + 边从 yml_text 简单解析(粗粒度,4 模板节点数 ≤ 6,够用)。
 */
export default function Step4Preview({
	preview,
	loading,
	error,
	ymlPreviewFallback,
	templateName,
}: Props) {
	const { t } = useTranslation("common");

	if (loading) {
		return (
			<div
				data-testid="wizard-step4-loading"
				style={{ color: "var(--color-text-muted)", padding: "var(--space-6)" }}
			>
				{t("status.loading")}
			</div>
		);
	}

	if (error) {
		return (
			<div
				data-testid="wizard-step4-error"
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

	if (!preview) {
		return (
			<div
				data-testid="wizard-step4-fallback"
				style={{
					padding: "var(--space-4)",
					borderRadius: "var(--radius-md)",
					border: "1px dashed var(--color-border)",
					color: "var(--color-text-muted)",
				}}
			>
				<div
					style={{
						color: "var(--color-text-primary)",
						fontWeight: 600,
						marginBottom: "var(--space-2)",
					}}
				>
					{templateName}
				</div>
				<pre
					style={{
						whiteSpace: "pre-wrap",
						fontSize: "var(--text-xs)",
						margin: 0,
					}}
				>
					{ymlPreviewFallback}
				</pre>
			</div>
		);
	}

	const parsed = parseYaml(preview.yml_text);

	return (
		<div data-testid="wizard-step4" style={{ display: "grid", gap: "var(--space-4)" }}>
			<WorkflowSummary nodes={parsed.nodes} edges={parsed.edges} />

			<details>
				<summary
					style={{
						cursor: "pointer",
						color: "var(--color-text-secondary)",
						fontSize: "var(--text-sm)",
						fontWeight: 500,
					}}
				>
					{t("wizard.preview.ymlTitle")} ({preview.yml_text.length} chars,{" "}
					{preview.attempt_count} attempt{preview.attempt_count === 1 ? "" : "s"})
				</summary>
				<pre
					data-testid="wizard-yml-preview"
					style={{
						marginTop: "var(--space-2)",
						padding: "var(--space-3)",
						background: "var(--color-bg-secondary)",
						borderRadius: "var(--radius-md)",
						border: "1px solid var(--color-border)",
						overflowX: "auto",
						maxHeight: 240,
						fontSize: "var(--text-xs)",
						whiteSpace: "pre-wrap",
					}}
				>
					{preview.yml_text}
				</pre>
			</details>
		</div>
	);
}

/**
 * 极简 YAML 解析:只关心节点 id/title/type + 边 source/target。
 * 用正则替代完整 yaml 解析,4 个模板 yml 格式固定,够用。
 */
function parseYaml(yml: string): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
	const nodes: WorkflowNode[] = [];
	const edges: WorkflowEdge[] = [];

	const nodeIdRe = /- id: ['"]?([\w-]+)['"]?\s*\n\s+data:\s*\n\s+type: (\w+)\s*\n\s+title: (.+)/g;
	let m: RegExpExecArray | null;
	while ((m = nodeIdRe.exec(yml)) !== null) {
		nodes.push({ id: m[1], type: m[2], title: m[3].trim() });
	}

	const edgeRe = /source: ['"]?([\w-]+)['"]?\s*\n\s+target: ['"]?([\w-]+)['"]?/g;
	while ((m = edgeRe.exec(yml)) !== null) {
		edges.push({ source: m[1], target: m[2] });
	}

	return { nodes, edges };
}
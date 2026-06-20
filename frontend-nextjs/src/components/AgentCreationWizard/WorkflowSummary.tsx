"use client";

import { useTranslation } from "react-i18next";

export type WorkflowNode = {
	id: string;
	title: string;
	type: string;
};

export type WorkflowEdge = {
	source: string;
	target: string;
};

type Props = {
	nodes: WorkflowNode[];
	edges: WorkflowEdge[];
};

/**
 * M12 PR-3 — 节点 + 边列表(纯卡片,不画图)。
 * 4 个 MVP 模板节点数都 ≤ 6,纯列表够用,不引 react-flow。
 */
export default function WorkflowSummary({ nodes, edges }: Props) {
	const { t } = useTranslation("common");

	return (
		<div data-testid="workflow-summary" style={{ display: "grid", gap: "var(--space-4)" }}>
			<section>
				<h4
					style={{
						color: "var(--color-text-primary)",
						fontSize: "var(--text-sm)",
						fontWeight: 600,
						marginBottom: "var(--space-2)",
					}}
				>
					{t("wizard.preview.nodesTitle")}{" "}
					<span
						style={{
							color: "var(--color-text-muted)",
							fontWeight: 400,
							marginLeft: "var(--space-2)",
						}}
					>
						{t("wizard.preview.nodeCount", { count: nodes.length })}
					</span>
				</h4>
				<div style={{ display: "grid", gap: "var(--space-2)" }}>
					{nodes.map((n, idx) => {
						const next = nodes[idx + 1];
						return (
							<div key={n.id}>
								<div
									data-testid={`workflow-node-${n.id}`}
									style={{
										padding: "var(--space-3) var(--space-4)",
										borderRadius: "var(--radius-md)",
										border: "1px solid var(--color-border)",
										background: "var(--color-bg-secondary)",
										display: "flex",
										alignItems: "center",
										gap: "var(--space-3)",
									}}
								>
									<div
										style={{
											width: 28,
											height: 28,
											borderRadius: "var(--radius-sm)",
											background: "var(--color-accent-gradient)",
											color: "var(--color-text-inverse)",
											display: "inline-flex",
											alignItems: "center",
											justifyContent: "center",
											fontSize: "var(--text-xs)",
											fontWeight: 700,
											flexShrink: 0,
										}}
									>
										{n.type.toUpperCase().slice(0, 3)}
									</div>
									<div style={{ flex: 1, minWidth: 0 }}>
										<div
											style={{
												color: "var(--color-text-primary)",
												fontWeight: 600,
												fontSize: "var(--text-sm)",
											}}
										>
											{n.title}
										</div>
										<div
											style={{
												color: "var(--color-text-muted)",
												fontSize: "var(--text-xs)",
											}}
										>
											{n.id}
										</div>
									</div>
								</div>
								{next && (
									<div
										style={{
											display: "flex",
											justifyContent: "center",
											color: "var(--color-text-muted)",
											fontSize: "var(--text-lg)",
											lineHeight: 1,
											padding: "var(--space-1) 0",
										}}
									>
										↓
									</div>
								)}
							</div>
						);
					})}
				</div>
			</section>

			{edges.length > 0 && (
				<section>
					<h4
						style={{
							color: "var(--color-text-primary)",
							fontSize: "var(--text-sm)",
							fontWeight: 600,
							marginBottom: "var(--space-2)",
						}}
					>
						{t("wizard.preview.edgesTitle")}
					</h4>
					<div
						style={{
							display: "flex",
							flexWrap: "wrap",
							gap: "var(--space-2)",
						}}
					>
						{edges.map((e, idx) => (
							<span
								key={`${e.source}-${e.target}-${idx}`}
								data-testid={`workflow-edge-${e.source}-${e.target}`}
								style={{
									padding: "var(--space-1) var(--space-3)",
									borderRadius: "var(--radius-sm)",
									background: "var(--color-bg-secondary)",
									border: "1px solid var(--color-border)",
									color: "var(--color-text-secondary)",
									fontSize: "var(--text-xs)",
								}}
							>
								{e.source} → {e.target}
							</span>
						))}
					</div>
				</section>
			)}
		</div>
	);
}
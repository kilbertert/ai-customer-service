"use client";

import { useEffect, useState } from "react";

interface Props {
	password: string;
	onAcknowledge: () => void;
}

const REVEAL_SECONDS = 30;

export const PasswordRevealModal = ({ password, onAcknowledge }: Props) => {
	const [masked, setMasked] = useState(false);
	const [secondsLeft, setSecondsLeft] = useState(REVEAL_SECONDS);

	useEffect(() => {
		const interval = window.setInterval(() => {
			setSecondsLeft((s) => {
				if (s <= 1) {
					window.clearInterval(interval);
					setMasked(true);
					return 0;
				}
				return s - 1;
			});
		}, 1000);
		return () => window.clearInterval(interval);
	}, []);

	return (
		<div
			className="modal-overlay"
			role="dialog"
			aria-modal="true"
			aria-labelledby="password-reveal-title"
			style={{
				position: "fixed",
				inset: 0,
				background: "rgba(0, 0, 0, 0.6)",
				display: "flex",
				alignItems: "center",
				justifyContent: "center",
				zIndex: 9999,
				padding: "var(--space-6)",
			}}
		>
			<div
				className="modal-content liquid-glass-card"
				style={{
					width: "100%",
					maxWidth: "440px",
					padding: "var(--space-8)",
				}}
			>
				<h2
					id="password-reveal-title"
					style={{
						fontSize: "var(--text-xl)",
						fontWeight: 600,
						marginBottom: "var(--space-3)",
					}}
				>
					Dify workspace 创建成功
				</h2>
				<p
					style={{
						color: "var(--color-text-secondary)",
						fontSize: "var(--text-sm)",
						marginBottom: "var(--space-2)",
					}}
				>
					这是您 Dify workspace 的初始密码，30 秒后自动隐藏。
				</p>
				<p
					style={{
						color: "var(--color-text-muted)",
						fontSize: "var(--text-xs)",
						marginBottom: "var(--space-6)",
					}}
				>
					请妥善保存，丢失需通过 Dify forgot_password 流找回。
				</p>

				<div
					className="password-display"
					style={{
						background: "var(--color-bg-input, rgba(0,0,0,0.04))",
						border: "1px solid var(--color-border)",
						borderRadius: "var(--radius-md)",
						padding: "var(--space-4)",
						marginBottom: "var(--space-6)",
						display: "flex",
						alignItems: "center",
						justifyContent: "space-between",
						gap: "var(--space-4)",
					}}
				>
					{masked ? (
						<code
							data-testid="password-masked"
							style={{
								fontFamily: "monospace",
								fontSize: "var(--text-lg)",
								letterSpacing: "0.1em",
							}}
						>
							{"•".repeat(32)}
						</code>
					) : (
						<>
							<code
								data-testid="password-revealed"
								style={{
									fontFamily: "monospace",
									fontSize: "var(--text-lg)",
									wordBreak: "break-all",
								}}
							>
								{password}
							</code>
							<span
								className="countdown"
								data-testid="password-countdown"
								style={{
									color: "var(--color-text-muted)",
									fontSize: "var(--text-xs)",
									whiteSpace: "nowrap",
								}}
							>
								{secondsLeft}s 后隐藏
							</span>
						</>
					)}
				</div>

				<button
					type="button"
					onClick={onAcknowledge}
					className="btn-primary"
					style={{
						width: "100%",
						padding: "var(--space-4)",
						fontSize: "var(--text-base)",
					}}
				>
					我已保存，进入 dashboard
				</button>
			</div>
		</div>
	);
};

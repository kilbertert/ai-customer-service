"use client";

import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth, ApiError } from "../context/AuthContext";
import { useTranslation } from "react-i18next";
import { PasswordRevealModal } from "../components/PasswordRevealModal";

export const Signup = () => {
	const { t } = useTranslation("auth");
	const { signupAsTenant } = useAuth();
	const navigate = useNavigate();

	const [workspaceName, setWorkspaceName] = useState("");
	const [name, setName] = useState("");
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [confirmPassword, setConfirmPassword] = useState("");
	const [termsAccepted, setTermsAccepted] = useState(false);
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(false);
	const [initialPassword, setInitialPassword] = useState<string | null>(null);
	const [hydrated, setHydrated] = useState(false);

	if (typeof window !== "undefined" && !hydrated) {
		setHydrated(true);
	}

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError("");

		if (password !== confirmPassword) {
			setError(t("errors.passwordMismatch"));
			return;
		}
		if (password.length < 8) {
			setError(t("errors.passwordTooShort"));
			return;
		}
		if (!termsAccepted) {
			setError(t("errors.termsRequired"));
			return;
		}

		setLoading(true);
		try {
			const result = await signupAsTenant({
				workspaceName,
				name,
				email,
				password,
				termsAccepted,
			});
			if (result.provisioning_status === "ready") {
				setInitialPassword(result.dify_initial_password);
			} else {
				navigate("/", { replace: true });
			}
		} catch (err: unknown) {
			// M11 PR4: 把 HTTP 状态码映射到 i18n key
			// 409 Conflict → "该邮箱已被注册" (errors.emailExists)
			// 其他错误 → 通用 signupFailed
			if (err instanceof ApiError && err.status === 409) {
				setError(t("errors.emailExists"));
			} else {
				const message =
					err instanceof Error ? err.message : t("errors.signupFailed");
				setError(message);
			}
		} finally {
			setLoading(false);
		}
	};

	return (
		<div
			style={{
				minHeight: "100vh",
				display: "flex",
				alignItems: "center",
				justifyContent: "center",
				padding: "var(--space-6)",
				position: "relative",
			}}
		>
			{/* Liquid blob background */}
			<div className="liquid-blob-container">
				<div
					className="liquid-blob-1"
					style={{ top: "8%", left: "8%", width: "40vw", height: "40vw" }}
				/>
				<div
					className="liquid-blob-2"
					style={{ bottom: "8%", right: "8%", width: "45vw", height: "45vw" }}
				/>
			</div>

			<div
				style={{
					width: "100%",
					maxWidth: "460px",
					animation: "fadeIn 0.6s cubic-bezier(0.25, 1.1, 0.5, 1.15) forwards",
				}}
			>
				{/* Logo & title */}
				<div
					style={{
						textAlign: "center",
						marginBottom: "var(--space-8)",
					}}
				>
					<div
						style={{
							display: "inline-flex",
							alignItems: "center",
							justifyContent: "center",
							width: "80px",
							height: "80px",
							marginBottom: "var(--space-6)",
							filter: "drop-shadow(0 0 20px hsla(265deg, 90%, 65%, 0.3))",
						}}
					>
						<img
							src="/logo.png"
							alt="Basjoo Logo"
							style={{
								width: "100%",
								height: "100%",
								objectFit: "contain",
							}}
						/>
					</div>
					<h1
						style={{
							fontSize: "var(--text-3xl)",
							fontWeight: 700,
							marginBottom: "var(--space-3)",
							background:
								"linear-gradient(135deg, hsl(188deg, 90%, 50%) 0%, hsl(265deg, 90%, 65%) 100%)",
							WebkitBackgroundClip: "text",
							backgroundClip: "text",
							WebkitTextFillColor: "transparent",
						}}
					>
						{t("tenantSignup.title")}
					</h1>
					<p
						style={{
							color: "var(--color-text-secondary)",
							fontSize: "var(--text-base)",
						}}
					>
						{t("tenantSignup.subtitle")}
					</p>
				</div>

				{/* Signup form card */}
				<div
					className="liquid-glass-card"
					style={{
						padding: "var(--space-8)",
					}}
				>
					{error && (
						<div
							style={{
								background: "var(--color-error-bg)",
								color: "var(--color-error)",
								padding: "var(--space-4)",
								borderRadius: "var(--radius-md)",
								marginBottom: "var(--space-6)",
								fontSize: "var(--text-sm)",
								display: "flex",
								alignItems: "center",
								gap: "var(--space-3)",
								border: "1px solid hsla(350deg, 85%, 58%, 0.2)",
							}}
						>
							<svg
								width="18"
								height="18"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								strokeWidth="2"
							>
								<circle cx="12" cy="12" r="10" />
								<line x1="12" y1="8" x2="12" y2="12" />
								<line x1="12" y1="16" x2="12.01" y2="16" />
							</svg>
							{error}
						</div>
					)}

					<form onSubmit={handleSubmit}>
						{/* workspaceName */}
						<div style={{ marginBottom: "var(--space-5)" }}>
							<label
								htmlFor="workspaceName"
								style={{
									display: "block",
									marginBottom: "var(--space-2)",
									fontSize: "var(--text-sm)",
									fontWeight: 500,
									color: "var(--color-text-secondary)",
								}}
							>
								{t("tenantSignup.workspaceName")}
							</label>
							<input
								id="workspaceName"
								name="workspaceName"
								type="text"
								value={workspaceName}
								onChange={(e) => setWorkspaceName(e.target.value)}
								placeholder={t("tenantSignup.workspaceNamePlaceholder")}
								required
								disabled={loading}
								minLength={3}
								maxLength={50}
								style={{ width: "100%", paddingLeft: "var(--space-4)" }}
							/>
						</div>

						{/* name */}
						<div style={{ marginBottom: "var(--space-5)" }}>
							<label
								htmlFor="name"
								style={{
									display: "block",
									marginBottom: "var(--space-2)",
									fontSize: "var(--text-sm)",
									fontWeight: 500,
									color: "var(--color-text-secondary)",
								}}
							>
								{t("tenantSignup.name")}
							</label>
							<input
								id="name"
								name="name"
								type="text"
								value={name}
								onChange={(e) => setName(e.target.value)}
								placeholder={t("tenantSignup.namePlaceholder")}
								required
								disabled={loading}
								style={{ width: "100%", paddingLeft: "var(--space-4)" }}
							/>
						</div>

						{/* email */}
						<div style={{ marginBottom: "var(--space-5)" }}>
							<label
								htmlFor="email"
								style={{
									display: "block",
									marginBottom: "var(--space-2)",
									fontSize: "var(--text-sm)",
									fontWeight: 500,
									color: "var(--color-text-secondary)",
								}}
							>
								{t("tenantSignup.email")}
							</label>
							<input
								id="email"
								name="email"
								type="email"
								value={email}
								onChange={(e) => setEmail(e.target.value)}
								placeholder={t("tenantSignup.emailPlaceholder")}
								required
								disabled={loading}
								style={{ width: "100%", paddingLeft: "var(--space-4)" }}
							/>
						</div>

						{/* password */}
						<div style={{ marginBottom: "var(--space-5)" }}>
							<label
								htmlFor="password"
								style={{
									display: "block",
									marginBottom: "var(--space-2)",
									fontSize: "var(--text-sm)",
									fontWeight: 500,
									color: "var(--color-text-secondary)",
								}}
							>
								{t("tenantSignup.password")}
							</label>
							<input
								id="password"
								name="password"
								type="password"
								value={password}
								onChange={(e) => setPassword(e.target.value)}
								placeholder={t("tenantSignup.passwordPlaceholder")}
								required
								disabled={loading}
								minLength={8}
								style={{ width: "100%", paddingLeft: "var(--space-4)" }}
							/>
						</div>

						{/* confirmPassword */}
						<div style={{ marginBottom: "var(--space-5)" }}>
							<label
								htmlFor="confirmPassword"
								style={{
									display: "block",
									marginBottom: "var(--space-2)",
									fontSize: "var(--text-sm)",
									fontWeight: 500,
									color: "var(--color-text-secondary)",
								}}
							>
								{t("tenantSignup.confirmPassword")}
							</label>
							<input
								id="confirmPassword"
								name="confirmPassword"
								type="password"
								value={confirmPassword}
								onChange={(e) => setConfirmPassword(e.target.value)}
								placeholder={t("tenantSignup.confirmPasswordPlaceholder")}
								required
								disabled={loading}
								minLength={8}
								style={{ width: "100%", paddingLeft: "var(--space-4)" }}
							/>
						</div>

						{/* terms */}
						<div style={{ marginBottom: "var(--space-6)" }}>
							<label
								htmlFor="terms"
								style={{
									display: "flex",
									alignItems: "center",
									gap: "var(--space-3)",
									fontSize: "var(--text-sm)",
									color: "var(--color-text-secondary)",
									cursor: "pointer",
								}}
							>
								<input
									id="terms"
									name="terms"
									type="checkbox"
									checked={termsAccepted}
									onChange={(e) => setTermsAccepted(e.target.checked)}
									disabled={loading}
									required
								/>
								<span>{t("tenantSignup.terms")}</span>
							</label>
						</div>

						<button
							type="submit"
							disabled={loading || !hydrated}
							className="btn-primary"
							style={{
								width: "100%",
								padding: "var(--space-4)",
								fontSize: "var(--text-base)",
							}}
						>
							{loading ? (
								<>
									<div className="spinner" />
									{t("tenantSignup.submitInProgress")}
								</>
							) : (
								<>
									{t("tenantSignup.submitButton")}
									<svg
										width="18"
										height="18"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										strokeWidth="2"
									>
										<path d="M5 12h14M12 5l7 7-7 7" />
									</svg>
								</>
							)}
						</button>
					</form>
				</div>

				<p
					style={{
						textAlign: "center",
						marginTop: "var(--space-6)",
						color: "var(--color-text-secondary)",
						fontSize: "var(--text-sm)",
					}}
				>
					{t("tenantSignup.haveAccount")}{" "}
					<Link
						to="/login"
						style={{
							color: "var(--color-accent-primary)",
							fontWeight: 500,
							textDecoration: "none",
							transition: "color var(--transition-fast)",
						}}
					>
						{t("tenantSignup.loginLink")}
					</Link>
				</p>

				<div
					style={{
						textAlign: "center",
						marginTop: "var(--space-10)",
						paddingTop: "var(--space-6)",
						borderTop: "1px solid var(--color-border)",
					}}
				>
					<p
						style={{
							fontSize: "var(--text-xs)",
							color: "var(--color-text-muted)",
						}}
					>
						{t("login.footer")}
					</p>
				</div>
			</div>

			{initialPassword && (
				<PasswordRevealModal
					password={initialPassword}
					onAcknowledge={() => {
						setInitialPassword(null);
						navigate("/", { replace: true });
					}}
				/>
			)}
		</div>
	);
};

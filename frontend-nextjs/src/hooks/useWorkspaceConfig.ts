import { useCallback, useEffect, useState } from "react";
import { api, type WorkspaceConfig } from "../services/api";

export interface UseWorkspaceConfigResult {
	loading: boolean;
	error: string | null;
	// Always-defined defaults so consumers can read fields unconditionally.
	// Per D6=a (M10+3 minimum scope), we treat "endpoint unreachable" as
	// "Dify disabled" — the UI hides Dify elements until proven enabled.
	dify_enabled: boolean;
	dify_api_base: string | null;
	dify_admin_configured: boolean;
	recheck: () => Promise<void>;
}

const DEFAULT_CONFIG: WorkspaceConfig = {
	dify_enabled: false,
	dify_api_base: null,
	dify_admin_configured: false,
};

export function useWorkspaceConfig(): UseWorkspaceConfigResult {
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [config, setConfig] = useState<WorkspaceConfig>(DEFAULT_CONFIG);

	const fetchConfig = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const next = await api.getWorkspaceConfig();
			setConfig(next);
		} catch (err) {
			// D6=a — treat fetch failure as "Dify disabled" so the UI stays
			// usable for legacy workspaces that pre-date the endpoint. We log
			// the error so admins can debug, but do not block the form.
			setConfig(DEFAULT_CONFIG);
			setError(err instanceof Error ? err.message : "Failed to load workspace config");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		fetchConfig();
	}, [fetchConfig]);

	return {
		loading,
		error,
		...config,
		recheck: fetchConfig,
	};
}

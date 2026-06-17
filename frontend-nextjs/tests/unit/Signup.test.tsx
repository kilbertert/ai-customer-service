// @ts-nocheck
// @vitest-environment jsdom
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Signup } from "../../src/views/Signup";

let signupAsTenantMock: any;
vi.mock("../../src/context/AuthContext", () => ({
	useAuth: () => ({
		admin: null,
		token: null,
		login: vi.fn(),
		logout: vi.fn(),
		register: vi.fn(),
		signupAsTenant: signupAsTenantMock,
		isLoading: false,
	}),
}));

const fakeLocalStorage = (() => {
	let store: Record<string, string> = {};
	return {
		getItem: (key: string) => store[key] ?? null,
		setItem: (key: string, value: string) => {
			store[key] = value;
		},
		removeItem: (key: string) => {
			delete store[key];
		},
		clear: () => {
			store = {};
		},
		get length() {
			return Object.keys(store).length;
		},
		key: (index: number) => Object.keys(store)[index] ?? null,
	};
})();

Object.defineProperty(globalThis, "localStorage", {
	value: fakeLocalStorage,
	writable: true,
	configurable: true,
});

vi.mock("react-i18next", () => ({
	useTranslation: () => ({ t: (key: string) => key }),
}));

const fakeAuth = (signupImpl: any) => {
	signupAsTenantMock = vi.fn(signupImpl);
	return { signupAsTenant: signupAsTenantMock };
};

beforeEach(() => {
	vi.clearAllMocks();
	localStorage.clear();
});

afterEach(() => {
	vi.restoreAllMocks();
	localStorage.clear();
});

function fillForm({
	workspaceName = "Acme Co",
	name = "Alice",
	email = "alice@acme.com",
	password = "password123",
	confirmPassword = "password123",
	terms = true,
} = {}) {
	fireEvent.change(screen.getByPlaceholderText("tenantSignup.workspaceNamePlaceholder"), {
		target: { value: workspaceName },
	});
	fireEvent.change(screen.getByPlaceholderText("tenantSignup.namePlaceholder"), {
		target: { value: name },
	});
	fireEvent.change(screen.getByPlaceholderText("tenantSignup.emailPlaceholder"), {
		target: { value: email },
	});
	fireEvent.change(screen.getByPlaceholderText("tenantSignup.passwordPlaceholder"), {
		target: { value: password },
	});
	fireEvent.change(screen.getByPlaceholderText("tenantSignup.confirmPasswordPlaceholder"), {
		target: { value: confirmPassword },
	});
	if (terms) {
		fireEvent.click(screen.getByRole("checkbox", { name: "tenantSignup.terms" }));
	}
}

function renderSignup(authValue: any, initialPath = "/signup") {
	const router = createMemoryRouter(
		[
			{ path: "/signup", element: <Signup /> },
			{ path: "/", element: <div>Home page</div> },
			{ path: "/login", element: <div>Login page</div> },
		],
		{ initialEntries: [initialPath] },
	);
	render(<RouterProvider router={router} />);
	return router;
}

describe("Signup.tsx (PR4: tenant registration)", () => {
	it("shows passwordMismatch error and does not call signupAsTenant when passwords differ", async () => {
		const auth = fakeAuth(vi.fn());
		renderSignup(auth);

		fillForm({ password: "password123", confirmPassword: "different-pw" });
		fireEvent.click(
			screen.getByRole("button", { name: "tenantSignup.submitButton" }),
		);

		await waitFor(() => {
			expect(screen.getByText("errors.passwordMismatch")).toBeInTheDocument();
		});
		expect(auth.signupAsTenant).not.toHaveBeenCalled();
	});

	it("opens PasswordRevealModal when backend returns provisioning_status=ready", async () => {
		const auth = fakeAuth(async () => ({
			access_token: "tok-1",
			workspace_id: 7,
			dify_initial_password: "Dify-Init-Pass-9x2!",
			provisioning_status: "ready",
			correlation_id: "corr-1",
		}));
		const router = renderSignup(auth);

		fillForm();
		fireEvent.click(
			screen.getByRole("button", { name: "tenantSignup.submitButton" }),
		);

		expect(await screen.findByTestId("password-revealed")).toHaveTextContent(
			"Dify-Init-Pass-9x2!",
		);
		expect(screen.getByTestId("password-countdown")).toBeInTheDocument();
		expect(router.state.location.pathname).toBe("/signup");
	});

	it("navigates to / and skips modal when backend returns provisioning_status=provisioning", async () => {
		const auth = fakeAuth(async () => ({
			access_token: "tok-2",
			workspace_id: 8,
			dify_initial_password: null,
			provisioning_status: "provisioning",
			correlation_id: "corr-2",
		}));
		const router = renderSignup(auth);

		fillForm();
		fireEvent.click(
			screen.getByRole("button", { name: "tenantSignup.submitButton" }),
		);

		await waitFor(() => {
			expect(router.state.location.pathname).toBe("/");
		});
		expect(screen.queryByTestId("password-revealed")).not.toBeInTheDocument();
	});
});

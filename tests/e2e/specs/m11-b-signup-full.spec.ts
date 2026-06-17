/**
 * E2E smoke test: M11 PR4 — B-end tenant signup full flow.
 *
 * @smoke
 *
 * 覆盖范围 (docs/m11/m11-pr4-frontend-routing.md §5):
 *   1. /signup 页 6 字段表单可填可提交
 *   2. 提交后 /api/v1/tenants/register 返回 ready → 弹出 PasswordRevealModal
 *   3. Modal 30s 倒计时显示 + 显示 dify_initial_password 明文
 *   4. 点 "我已保存" → 关 modal → 跳到 dashboard
 *   5. localStorage 同时存 token + workspace_id
 *
 * 策略: 用 page.route 拦截 /api/v1/tenants/register 返回 200 ready 响应, 避免真打 Dify。
 */
import { test, expect } from '@playwright/test';

const TEST_PASSWORD = 'Dify-Init-Pass-E2E-2026';

test.describe('M11 B-end tenant signup (PR4)', () => {
  test('signup with ready provisioning opens PasswordRevealModal and lands on dashboard', async ({ page }) => {
    // 拦截 /api/v1/tenants/register, 返回 ready + 初始密码
    await page.route('**/api/v1/tenants/register', async (route) => {
      const req = route.request();
      const body = req.postDataJSON() || {};
      const wsId = 12345;
      const token = 'fake-signup-jwt-' + Date.now();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: token,
          workspace_id: wsId,
          dify_initial_password: TEST_PASSWORD,
          provisioning_status: 'ready',
          correlation_id: 'corr-e2e-001',
        }),
      });
      // 防止 unused warning
      void body;
    });

    // 拦截 /api/admin/me, 让 AuthContext 拿到 admin 信息
    await page.route('**/api/admin/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 1,
          email: 'tenant-owner@acme.com',
          name: 'Acme Owner',
          role: 'admin',
        }),
      });
    });

    await page.goto('/signup');
    await expect(page.getByText(/Sign up for B-end account|注册 B 端账号/)).toBeVisible({
      timeout: 10_000,
    });

    // 填 6 字段
    await page.locator('input[name="workspaceName"]').fill('Acme E2E Co');
    await page.locator('input[name="name"]').fill('Acme Owner');
    await page.locator('input[name="email"]').fill('tenant-owner@acme.com');
    await page.locator('input[name="password"]').fill('OwnerP@ssword-123');
    await page.locator('input[name="confirmPassword"]').fill('OwnerP@ssword-123');
    await page.locator('input[name="terms"]').check();

    // 提交
    await page.getByRole('button', { name: /Sign up|注册/ }).click();

    // 1. PasswordRevealModal 出现, 含 dify_initial_password 明文 + 倒计时
    const revealed = page.getByTestId('password-revealed');
    await expect(revealed).toBeVisible({ timeout: 10_000 });
    await expect(revealed).toHaveText(TEST_PASSWORD);
    await expect(page.getByTestId('password-countdown')).toBeVisible();

    // 2. 关 modal → 跳到 /
    await page.getByRole('button', { name: /我已保存/ }).click();
    await page.waitForURL((url) => !url.pathname.startsWith('/signup'), {
      timeout: 10_000,
    });
    await expect(page).not.toHaveURL(/\/signup/, { timeout: 5_000 });

    // 3. localStorage 持久化 token + workspace_id
    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();
    const wsId = await page.evaluate(() => localStorage.getItem('workspace_id'));
    expect(wsId).toBe('12345');
  });
});

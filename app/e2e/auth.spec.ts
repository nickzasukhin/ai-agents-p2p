import { test, expect } from '@playwright/test'

const BASE = 'https://agents.devpunks.io'

test.describe('Authentication Flow', () => {

  test('submit email shows "Check your email" confirmation', async ({ page }) => {
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })

    // Enter a test email
    const emailInput = page.locator('input[type="email"]')
    await emailInput.fill('test-e2e@devpunks.io')

    // Click send
    const sendButton = page.locator('button:has-text("Send Magic Link")')
    await sendButton.click()

    // Should show confirmation screen
    await expect(page.locator('text=Check your email')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('text=test-e2e@devpunks.io')).toBeVisible()
    await expect(page.locator('text=Link expires in 15 minutes')).toBeVisible()
  })

  test('"Use different email" button returns to form', async ({ page }) => {
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })

    // Submit email first
    await page.locator('input[type="email"]').fill('test-e2e@devpunks.io')
    await page.locator('button:has-text("Send Magic Link")').click()
    await expect(page.locator('text=Check your email')).toBeVisible({ timeout: 10000 })

    // Click "Use different email"
    await page.locator('text=Use different email').click()

    // Should be back to sign in form
    await expect(page.locator('text=Sign in')).toBeVisible()
    await expect(page.locator('input[type="email"]')).toBeVisible()
  })

  test('invalid magic link token shows error', async ({ page }) => {
    await page.goto(`${BASE}/app?token=invalid-token-12345`, { waitUntil: 'networkidle' })

    // Should show error message
    await expect(page.locator('text=/invalid|expired|error/i')).toBeVisible({ timeout: 10000 })
  })

  test('magic link request hits orchestrator API', async ({ request }) => {
    const response = await request.post(`${BASE}/orch/auth/request-magic-link`, {
      data: { email: 'api-test@devpunks.io' },
      headers: { 'Content-Type': 'application/json' },
    })
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.ok).toBe(true)
    expect(body.message).toContain('Magic link sent')
  })

  test('verify endpoint rejects bad token', async ({ request }) => {
    const response = await request.get(`${BASE}/orch/auth/verify?token=bad-token`)
    expect(response.status()).toBe(400)
  })

  test('/auth/me requires authentication', async ({ request }) => {
    const response = await request.get(`${BASE}/orch/auth/me`)
    expect(response.status()).toBe(401)
  })
})

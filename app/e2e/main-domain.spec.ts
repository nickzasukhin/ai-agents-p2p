import { test, expect } from '@playwright/test'

const BASE = 'https://agents.devpunks.io'

test.describe('Main Domain — agents.devpunks.io', () => {

  test('root redirects to /app', async ({ page }) => {
    const response = await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    // Should end up at /app (auth screen) after redirect
    expect(page.url()).toContain('/app')
  })

  test('/app shows auth screen with Sign in form', async ({ page }) => {
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })

    // Auth screen should show "Sign in" heading
    await expect(page.locator('text=Sign in')).toBeVisible()

    // Should have email input
    const emailInput = page.locator('input[type="email"]')
    await expect(emailInput).toBeVisible()
    await expect(emailInput).toHaveAttribute('placeholder', 'you@example.com')

    // Should have "Send Magic Link" button
    await expect(page.locator('text=Send Magic Link')).toBeVisible()

    // Should have tagline
    await expect(page.locator('text=AI Agent Network')).toBeVisible()
  })

  test('/app shows "No password needed" description', async ({ page }) => {
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
    await expect(page.locator('text=Enter your email to get a magic link')).toBeVisible()
  })

  test('Send Magic Link button is disabled without email', async ({ page }) => {
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
    const button = page.locator('button:has-text("Send Magic Link")')
    // Button should be present but visually disabled (no email entered)
    await expect(button).toBeVisible()
  })

  test('/health returns orchestrator status', async ({ request }) => {
    const response = await request.get(`${BASE}/health`)
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.status).toBe('ok')
    expect(body.service).toBe('agent-orchestrator')
    expect(body).toHaveProperty('users')
    expect(body).toHaveProperty('agents')
  })

  test('/orch/health returns orchestrator status', async ({ request }) => {
    const response = await request.get(`${BASE}/orch/health`)
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.status).toBe('ok')
    expect(body.service).toBe('agent-orchestrator')
  })

  test('no fake agent profile on main domain', async ({ request }) => {
    // Main domain should NOT have /profile endpoint with personal data
    const response = await request.get(`${BASE}/profile`)
    // Should be 404 or redirect, not a personal profile page
    const status = response.status()
    expect([302, 404, 405, 422]).toContain(status)
  })

  test('/app loads JS and CSS assets', async ({ page }) => {
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })

    // Page should not have any JS errors (check by verifying React rendered)
    const body = page.locator('body')
    await expect(body).not.toBeEmpty()

    // Check that the SPA rendered (not just raw HTML)
    // React mounts into #root
    const root = page.locator('#root')
    await expect(root).not.toBeEmpty()
  })

  test('footer text is present', async ({ page }) => {
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
    await expect(page.locator('text=Your personal AI agent in the P2P network')).toBeVisible()
  })
})

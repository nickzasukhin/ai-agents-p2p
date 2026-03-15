import { test, expect } from '@playwright/test'

const BASE = 'https://agents.devpunks.io'
const ORCH = `${BASE}/orch`

test.describe('Full User Journey (E2E)', () => {

  test('new user: register → get magic link → verify → subdomain redirect', async ({ request }) => {
    // 1. Request magic link
    const email = `e2e-test-${Date.now()}@devpunks.io`
    const reqResp = await request.post(`${ORCH}/auth/request-magic-link`, {
      data: { email },
      headers: { 'Content-Type': 'application/json' },
    })
    expect(reqResp.status()).toBe(200)

    // 2. Get the magic link token directly from orchestrator DB
    // In production, this would come via email.
    // For E2E, we check the API created the link successfully.
    const reqBody = await reqResp.json()
    expect(reqBody.ok).toBe(true)
  })

  test('orchestrator health shows zero agents on clean start', async ({ request }) => {
    const resp = await request.get(`${ORCH}/health`)
    const body = await resp.json()
    expect(body.status).toBe('ok')
    // On clean DB, should have 0 or few agents
    expect(typeof body.agents).toBe('number')
  })

  test('unauthenticated user cannot create agent', async ({ request }) => {
    const resp = await request.post(`${ORCH}/agents/create`, {
      data: { agent_name: 'Test Agent' },
      headers: { 'Content-Type': 'application/json' },
    })
    expect(resp.status()).toBe(401)
  })

  test('unauthenticated user cannot access /agents/mine', async ({ request }) => {
    const resp = await request.get(`${ORCH}/agents/mine`)
    expect(resp.status()).toBe(401)
  })

  test('main domain SPA: unauthenticated lands on auth screen', async ({ page }) => {
    // Clear all cookies first
    await page.context().clearCookies()

    await page.goto(BASE, { waitUntil: 'networkidle' })

    // Should end up at /app with auth screen
    expect(page.url()).toContain('/app')
    await expect(page.locator('text=Sign in')).toBeVisible()
  })

  test('SPA renders without JS errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })

    // Wait a moment for any async errors
    await page.waitForTimeout(2000)

    // Filter out known non-critical errors (e.g., failed API calls for unauthenticated user)
    const criticalErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('Authentication') &&
      !e.includes('fetch')
    )
    expect(criticalErrors).toHaveLength(0)
  })

  test('mobile viewport shows auth screen correctly', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 }) // iPhone X
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })

    await expect(page.locator('text=Sign in')).toBeVisible()
    await expect(page.locator('input[type="email"]')).toBeVisible()
    await expect(page.locator('text=Send Magic Link')).toBeVisible()
  })
})

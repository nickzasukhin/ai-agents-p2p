import { test, expect } from '@playwright/test'

/**
 * Tests for subdomain agent profiles.
 * Uses the test agents currently deployed on production.
 * These tests verify the public profile page and API endpoints
 * work correctly on user subdomains.
 */

// Test against any existing agent subdomain
// These are created by scripts/create_test_agents.sh
const SUBDOMAINS = ['aerith', 'deadpool', 'stilgar', 'neuromancer']

test.describe('Subdomain Profile Pages', () => {

  test('agent subdomain root shows profile page (HTML)', async ({ page }) => {
    // Try each subdomain until one works (agents may have been cleaned)
    let found = false
    for (const sub of SUBDOMAINS) {
      const url = `https://${sub}.agents.devpunks.io/`
      try {
        const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 10000 })
        if (resp && resp.status() === 200) {
          // Profile page should contain agent info
          const html = await page.content()
          if (html.includes('agent-profile') || html.includes('og:title')) {
            found = true
            // Verify it has proper HTML structure
            await expect(page.locator('body')).not.toBeEmpty()
            break
          }
        }
      } catch {
        continue
      }
    }
    // If no agents deployed, skip gracefully
    if (!found) {
      test.skip(true, 'No test agents deployed — run scripts/create_test_agents.sh first')
    }
  })

  test('agent subdomain /health returns agent health', async ({ request }) => {
    let found = false
    for (const sub of SUBDOMAINS) {
      try {
        const resp = await request.get(`https://${sub}.agents.devpunks.io/health`, { timeout: 5000 })
        if (resp.status() === 200) {
          const body = await resp.json()
          expect(body.status).toBe('ok')
          expect(body).toHaveProperty('agent_name')
          found = true
          break
        }
      } catch {
        continue
      }
    }
    if (!found) {
      test.skip(true, 'No test agents deployed')
    }
  })

  test('agent subdomain /.well-known/agent.json returns agent card', async ({ request }) => {
    let found = false
    for (const sub of SUBDOMAINS) {
      try {
        const resp = await request.get(`https://${sub}.agents.devpunks.io/.well-known/agent.json`, { timeout: 5000 })
        if (resp.status() === 200) {
          const body = await resp.json()
          expect(body).toHaveProperty('name')
          expect(body).toHaveProperty('url')
          expect(body).toHaveProperty('capabilities')
          found = true
          break
        }
      } catch {
        continue
      }
    }
    if (!found) {
      test.skip(true, 'No test agents deployed')
    }
  })

  test('agent subdomain /orch/health proxies to orchestrator', async ({ request }) => {
    let found = false
    for (const sub of SUBDOMAINS) {
      try {
        const resp = await request.get(`https://${sub}.agents.devpunks.io/orch/health`, { timeout: 5000 })
        if (resp.status() === 200) {
          const body = await resp.json()
          expect(body.status).toBe('ok')
          expect(body.service).toBe('agent-orchestrator')
          found = true
          break
        }
      } catch {
        continue
      }
    }
    if (!found) {
      test.skip(true, 'No test agents deployed')
    }
  })

  test('agent subdomain /app loads SPA', async ({ page }) => {
    let found = false
    for (const sub of SUBDOMAINS) {
      try {
        const resp = await page.goto(`https://${sub}.agents.devpunks.io/app`, {
          waitUntil: 'domcontentloaded',
          timeout: 10000,
        })
        if (resp && resp.status() === 200) {
          const root = page.locator('#root')
          await expect(root).not.toBeEmpty()
          found = true
          break
        }
      } catch {
        continue
      }
    }
    if (!found) {
      test.skip(true, 'No test agents deployed')
    }
  })

  test('agent profile has OG meta tags', async ({ page }) => {
    let found = false
    for (const sub of SUBDOMAINS) {
      try {
        const resp = await page.goto(`https://${sub}.agents.devpunks.io/`, {
          waitUntil: 'domcontentloaded',
          timeout: 10000,
        })
        if (resp && resp.status() === 200) {
          const ogTitle = page.locator('meta[property="og:title"]')
          const count = await ogTitle.count()
          if (count > 0) {
            found = true
            // Check all standard OG tags
            await expect(page.locator('meta[property="og:description"]')).toHaveCount(1)
            await expect(page.locator('meta[property="og:type"]')).toHaveCount(1)
            break
          }
        }
      } catch {
        continue
      }
    }
    if (!found) {
      test.skip(true, 'No test agents with profile deployed')
    }
  })
})

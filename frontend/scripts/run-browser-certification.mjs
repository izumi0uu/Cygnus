#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { basename, dirname, resolve } from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright'

const REQUIRED_ARGS = new Set([
  '--report',
  '--git-sha',
  '--backend-image',
  '--frontend-image',
  '--alembic-head',
])

const STATIC_CONSOLE_ROUTES = [
  '/console',
  '/console/copilot',
  '/console/queue',
  '/console/objects',
  '/console/sources',
  '/console/tickets',
  '/console/audience',
  '/console/drift',
  '/console/propagation',
  '/console/audit',
  '/console/employees',
  '/console/roles',
  '/console/settings',
]
const EXPECTED_EMPTY_404_PATHS = new Set([
  '/api/recovery/overview',
  '/api/publish-preview',
])

function parseArgs(argv) {
  const values = new Map()
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index]
    const value = argv[index + 1]
    if (!REQUIRED_ARGS.has(name) || value === undefined || value.startsWith('--')) {
      throw new Error(`usage error near ${name ?? '<missing argument>'}`)
    }
    if (values.has(name)) throw new Error(`duplicate argument: ${name}`)
    values.set(name, value)
  }
  for (const name of REQUIRED_ARGS) {
    if (!values.get(name)?.trim()) throw new Error(`${name} is required`)
  }
  return Object.fromEntries([...values].map(([name, value]) => [name.slice(2), value]))
}

function requiredEnv(primaryName, fallbackName) {
  const value = process.env[primaryName]?.trim() || process.env[fallbackName]?.trim()
  if (!value) throw new Error(`${primaryName} or ${fallbackName} is required`)
  return value
}

function resolveBaseUrl() {
  const configured = requiredEnv('CYGNUS_BROWSER_BASE_URL', 'PORTAL_BASE_URL')
  const url = new URL(configured)
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('browser base URL must be an origin without credentials, query, hash, or path')
  }
  const production = process.env.ENVIRONMENT?.toLowerCase() === 'production'
  if (production) {
    const portal = new URL(requiredEnv('PORTAL_BASE_URL', 'PORTAL_BASE_URL'))
    if (url.href !== portal.href || url.protocol !== 'https:') {
      throw new Error('production browser target must exactly match the HTTPS PORTAL_BASE_URL')
    }
  } else if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '::1'].includes(url.hostname))) {
    throw new Error('non-production HTTP browser targets must be loopback-only')
  }
  return url.origin
}

function boundedTimeout() {
  const raw = process.env.CYGNUS_BROWSER_E2E_TIMEOUT_MS?.trim() || '30000'
  if (!/^\d+$/.test(raw)) throw new Error('CYGNUS_BROWSER_E2E_TIMEOUT_MS must be an integer')
  const timeout = Number(raw)
  if (timeout < 5_000 || timeout > 120_000) {
    throw new Error('CYGNUS_BROWSER_E2E_TIMEOUT_MS must be between 5000 and 120000')
  }
  return timeout
}

function safeError(error, secrets) {
  let message = error instanceof Error ? error.message : String(error)
  for (const secret of secrets) {
    if (secret) message = message.replaceAll(secret, '[REDACTED]')
  }
  return message.slice(0, 2_000)
}

function addCheck(checks, name, details) {
  checks.push({ name, passed: true, ...(details ? { details } : {}) })
}

async function sha256(path) {
  return createHash('sha256').update(await readFile(path)).digest('hex')
}

async function assertConsolePage(page, baseUrl, route) {
  await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded' })
  await page.locator('#main-content').waitFor({ state: 'visible' })
  const heading = page.locator('#main-content h1').first()
  await heading.waitFor({ state: 'attached' })
  const headingText = (await heading.textContent())?.trim()
  if (!headingText) throw new Error(`${route} rendered an empty primary heading`)
  const actual = new URL(page.url())
  const expected = new URL(route, baseUrl)
  if (actual.pathname !== expected.pathname || actual.search !== expected.search) {
    throw new Error(`${route} resolved to ${actual.pathname}${actual.search}`)
  }
  if (!(await page.title()).includes('Cygnus')) throw new Error(`${route} has an unexpected document title`)
  if (await page.locator('vite-error-overlay, #webpack-dev-server-client-overlay, [data-nextjs-dialog-overlay]').count()) {
    throw new Error(`${route} rendered a framework error overlay`)
  }
}

async function run() {
  const args = parseArgs(process.argv.slice(2))
  const reportPath = resolve(args.report)
  const baseUrl = resolveBaseUrl()
  const adminEmail = requiredEnv('CYGNUS_BROWSER_ADMIN_EMAIL', 'DEFAULT_ADMIN_EMAIL')
  const adminPassword = requiredEnv('CYGNUS_BROWSER_ADMIN_PASSWORD', 'DEFAULT_ADMIN_PASSWORD')
  const timeout = boundedTimeout()
  const checks = []
  const runtimeErrors = []
  const expectedEmptyResponses = new Set()
  const screenshotPaths = []
  let activeCheck = 'browser-launch'
  let browser

  try {
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      locale: 'zh-CN',
      colorScheme: 'light',
    })
    const page = await context.newPage()
    page.setDefaultTimeout(timeout)
    page.setDefaultNavigationTimeout(timeout)
    page.on('console', (message) => {
      if (message.type() !== 'error' || message.text().startsWith('Failed to load resource')) return
      const location = message.location()
      const source = location.url ? ` @ ${location.url}:${location.lineNumber + 1}` : ''
      runtimeErrors.push(`console: ${message.text()}${source}`)
    })
    page.on('pageerror', (error) => runtimeErrors.push(`pageerror: ${error.message}`))
    page.on('response', (response) => {
      if (response.status() < 400) return
      const responseUrl = new URL(response.url())
      if (response.status() === 404 && EXPECTED_EMPTY_404_PATHS.has(responseUrl.pathname)) {
        expectedEmptyResponses.add(responseUrl.pathname)
        return
      }
      runtimeErrors.push(`http ${response.status()}: ${response.url()}`)
    })

    activeCheck = 'unauthenticated-deep-link-redirect'
    const deepLink = '/console/audit?phase=publish#top'
    await page.goto(`${baseUrl}${deepLink}`, { waitUntil: 'domcontentloaded' })
    await page.waitForURL((url) => url.pathname === '/login')
    await page.locator('#login-email').waitFor({ state: 'visible' })
    addCheck(checks, activeCheck, { requested_path: deepLink, redirect_path: '/login' })

    activeCheck = 'admin-login-deep-link-resume'
    await page.locator('#login-email').fill(adminEmail)
    await page.locator('#login-password').fill(adminPassword)
    await page.locator('button[type="submit"]').click()
    await page.waitForURL((url) => `${url.pathname}${url.search}${url.hash}` === deepLink)
    await page.locator('#main-content h1').first().waitFor({ state: 'attached' })
    addCheck(checks, activeCheck, { resumed_path: deepLink })

    activeCheck = 'admin-static-route-smoke'
    for (const route of STATIC_CONSOLE_ROUTES) await assertConsolePage(page, baseUrl, route)
    addCheck(checks, activeCheck, { route_count: STATIC_CONSOLE_ROUTES.length, routes: STATIC_CONSOLE_ROUTES })

    activeCheck = 'command-palette-keyboard'
    await page.goto(`${baseUrl}/console`, { waitUntil: 'domcontentloaded' })
    await page.locator('#main-content h1').first().waitFor({ state: 'attached' })
    await page.keyboard.press('Control+K')
    await page.locator('#command-palette').waitFor({ state: 'visible' })
    const desktopScreenshot = reportPath.replace(/\.json$/u, '') + '.desktop.png'
    await page.screenshot({ path: desktopScreenshot, fullPage: false })
    screenshotPaths.push(desktopScreenshot)
    await page.keyboard.press('Escape')
    await page.locator('#command-palette').waitFor({ state: 'detached' })
    addCheck(checks, activeCheck, { shortcut: 'Control+K', closed_with: 'Escape' })

    activeCheck = 'mobile-navigation-and-overflow'
    await page.setViewportSize({ width: 390, height: 844 })
    await assertConsolePage(page, baseUrl, '/console')
    const trigger = page.locator('button[aria-controls="bp-nav-drawer"]')
    await trigger.click()
    const drawer = page.locator('#bp-nav-drawer')
    await drawer.waitFor({ state: 'visible' })
    if ((await drawer.getAttribute('data-open')) !== 'true') throw new Error('mobile navigation drawer did not open')
    const mobileScreenshot = reportPath.replace(/\.json$/u, '') + '.mobile.png'
    await page.screenshot({ path: mobileScreenshot, fullPage: false })
    screenshotPaths.push(mobileScreenshot)
    await drawer.locator('a[href="/console/queue"]').click()
    await page.waitForURL((url) => url.pathname === '/console/queue')
    if ((await drawer.getAttribute('data-open')) !== 'false') throw new Error('mobile navigation drawer did not close after routing')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    if (overflow > 1) throw new Error(`mobile console overflows horizontally by ${overflow}px`)
    addCheck(checks, activeCheck, { viewport: '390x844', destination: '/console/queue', horizontal_overflow_px: overflow })

    activeCheck = 'browser-runtime-health'
    if (runtimeErrors.length) throw new Error(runtimeErrors.join('\n'))
    addCheck(checks, activeCheck, {
      console_errors: 0,
      page_errors: 0,
      unexpected_http_errors: 0,
      expected_empty_surfaces: [...expectedEmptyResponses].sort(),
    })

    activeCheck = 'screenshot-evidence'
    const screenshots = []
    for (const path of screenshotPaths) screenshots.push({ file: basename(path), sha256: await sha256(path) })
    addCheck(checks, activeCheck, { screenshots })

    const report = {
      report_format: 'cygnus-browser-e2e-report/v1',
      status: 'passed',
      git_sha: args['git-sha'],
      generated_at: new Date().toISOString(),
      release_identity: {
        git_commit: args['git-sha'],
        backend_image_ref: args['backend-image'],
        frontend_image_ref: args['frontend-image'],
        alembic_head: args['alembic-head'],
      },
      target: { origin: baseUrl },
      browser: { engine: 'chromium', version: browser.version(), headless: true },
      checks,
    }
    await mkdir(dirname(reportPath), { recursive: true })
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
    console.log(`[browser-certification] OK: ${checks.length} checks, ${STATIC_CONSOLE_ROUTES.length} routes`)
  } catch (error) {
    checks.push({ name: activeCheck, passed: false, error: safeError(error, [adminEmail, adminPassword]) })
    const report = {
      report_format: 'cygnus-browser-e2e-report/v1',
      status: 'failed',
      git_sha: args['git-sha'],
      generated_at: new Date().toISOString(),
      release_identity: {
        git_commit: args['git-sha'],
        backend_image_ref: args['backend-image'],
        frontend_image_ref: args['frontend-image'],
        alembic_head: args['alembic-head'],
      },
      target: { origin: baseUrl },
      checks,
    }
    await mkdir(dirname(reportPath), { recursive: true })
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
    console.error(`[browser-certification] FAILED: ${safeError(error, [adminEmail, adminPassword])}`)
    process.exitCode = 1
  } finally {
    await browser?.close()
  }
}

await run()

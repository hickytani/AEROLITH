/**
 * Sprint 6 Full Acceptance Runner
 * Launches:
 * 1. FastAPI on 127.0.0.1:8000
 * 2. Next.js on 127.0.0.1:3000
 * 3. Headless Chrome on 127.0.0.1:9222
 * 4. Executes scripts/browser-acceptance-sprint6.mjs
 * 5. Cleans up all child processes on exit.
 */
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { waitForApiReady } from './api-readiness.mjs';

const ROOT = resolve('.');
const ARTIFACTS = resolve(ROOT, 'artifacts');
await mkdir(ARTIFACTS, { recursive: true });

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const CHROME_USER_DATA = resolve(ARTIFACTS, 'sprint6-chrome-profile');

const processes = [];

function killAll() {
  console.log('Shutting down runner processes...');
  for (const proc of processes) {
    try {
      if (proc && !proc.killed) {
        // On Windows, child.kill() may leave descendant processes alive; spawn taskkill
        proc.kill('SIGTERM');
        if (proc.pid) {
          spawn('taskkill', ['/pid', String(proc.pid), '/f', '/t'], { stdio: 'ignore' });
        }
      }
    } catch (_) {}
  }
}

process.on('SIGINT', () => { killAll(); process.exit(1); });
process.on('SIGTERM', () => { killAll(); process.exit(1); });

async function run() {
  try {
    // 1. Start FastAPI backend
    console.log('[Runner] Starting FastAPI on 127.0.0.1:8000...');
    const apiProc = spawn(
      resolve(ROOT, '.venv/Scripts/python.exe'),
      ['-m', 'uvicorn', 'aeropkmech.main:app', '--app-dir', 'services/api', '--host', '127.0.0.1', '--port', '8000'],
      { stdio: ['ignore', 'pipe', 'pipe'] }
    );
    processes.push(apiProc);
    apiProc.stdout?.on('data', (d) => process.stdout.write(`[API] ${d}`));
    apiProc.stderr?.on('data', (d) => process.stderr.write(`[API-ERR] ${d}`));

    await waitForApiReady({ url: 'http://127.0.0.1:8000/api/v1/health', timeoutMs: 30000 });
    console.log('[Runner] FastAPI is ready.');

    // 2. Start Next.js frontend
    console.log('[Runner] Starting Next.js on 127.0.0.1:3000...');
    const nextProc = spawn(
      process.execPath,
      ['node_modules/next/dist/bin/next', 'dev', 'apps/web', '--hostname', '127.0.0.1', '--port', '3000'],
      { stdio: ['ignore', 'pipe', 'pipe'] }
    );
    processes.push(nextProc);
    nextProc.stdout?.on('data', (d) => process.stdout.write(`[Web] ${d}`));
    nextProc.stderr?.on('data', (d) => process.stderr.write(`[Web-ERR] ${d}`));

    await waitForApiReady({ url: 'http://127.0.0.1:3000/api/v1/health', timeoutMs: 30000 });
    console.log('[Runner] Next.js frontend is ready.');

    // 3. Start headless Chrome
    console.log('[Runner] Starting headless Chrome on 127.0.0.1:9222...');
    const chromeProc = spawn(
      CHROME_PATH,
      [
        '--remote-debugging-port=9222',
        '--headless=new',
        `--user-data-dir=${CHROME_USER_DATA}`,
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-gpu',
        '--disable-extensions',
        'about:blank',
      ],
      { stdio: 'ignore' }
    );
    processes.push(chromeProc);

    // Wait for Chrome remote debugging
    const chromeDeadline = Date.now() + 20000;
    let chromeReady = false;
    while (Date.now() < chromeDeadline) {
      try {
        const r = await fetch('http://127.0.0.1:9222/json/version');
        if (r.ok) { chromeReady = true; break; }
      } catch (_) {}
      await new Promise((res) => setTimeout(res, 200));
    }
    if (!chromeReady) throw new Error('Chrome remote debugging port 9222 did not become ready.');
    console.log('[Runner] Chrome debugging endpoint is ready.');

    // 4. Run browser acceptance test
    console.log('[Runner] Executing browser-acceptance-sprint6.mjs...');
    const testProc = spawn(process.execPath, ['scripts/browser-acceptance-sprint6.mjs'], {
      stdio: 'inherit',
      env: { ...process.env, AEROPKMECH_BROWSER_BASE: 'http://127.0.0.1:3000' },
    });

    const exitCode = await new Promise((resolve) => {
      testProc.on('exit', (code) => resolve(code ?? 0));
    });

    console.log(`[Runner] Browser acceptance exited with code: ${exitCode}`);
    if (exitCode !== 0) {
      process.exitCode = exitCode;
    }
  } catch (err) {
    console.error('[Runner] Error during execution:', err);
    process.exitCode = 1;
  } finally {
    killAll();
  }
}

await run();

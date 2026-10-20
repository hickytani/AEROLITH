import { spawn } from 'node:child_process';
import { waitForApiReady } from './api-readiness.mjs';

const production = process.argv.includes('production');
const apiOrigin = process.env.AEROPKMECH_API_ORIGIN || 'http://127.0.0.1:8000';
const startupController = new AbortController();
const api = spawn('uv', [
  'run', '--cache-dir', '.uv-cache', 'uvicorn', 'aeropkmech.main:app',
  '--app-dir', 'services/api', '--host', '127.0.0.1', '--port', '8000',
], { stdio: 'inherit' });
let web;
let closing = false;
function stop(code = 0) {
  if (closing) return;
  closing = true;
  startupController.abort();
  api.kill();
  web?.kill();
  process.exitCode = code;
}
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));
api.on('error', error => { console.error('Could not start uv API service:', error.message); stop(1); });
api.on('exit', code => { if (!closing) stop(code ?? 1); });

try {
  await waitForApiReady({ url: `${apiOrigin}/api/v1/health`, signal: startupController.signal });
  if (closing) process.exitCode = 1;
  else {
    console.log('API readiness confirmed; starting Next.js.');
    const nextArgs = [
      'node_modules/next/dist/bin/next', production ? 'start' : 'dev', 'apps/web',
      '--hostname', '127.0.0.1', '--port', '3000',
    ];
    web = spawn(process.execPath, nextArgs, { stdio: 'inherit' });
    web.on('error', error => { console.error('Could not start Next.js:', error.message); stop(1); });
    web.on('exit', code => { if (!closing) stop(code ?? 1); });
  }
} catch (error) {
  console.error(error.message);
  stop(1);
}

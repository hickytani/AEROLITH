import { spawn } from 'node:child_process';

const production = process.argv.includes('production');
const api = spawn('uv', [
  'run', '--cache-dir', '.uv-cache', 'uvicorn', 'aeropkmech.main:app',
  '--app-dir', 'services/api', '--host', '127.0.0.1', '--port', '8000',
], { stdio: 'inherit' });
const nextArgs = [
  'node_modules/next/dist/bin/next', production ? 'start' : 'dev', 'apps/web',
  '--hostname', '127.0.0.1', '--port', '3000',
];
const web = spawn(process.execPath, nextArgs, { stdio: 'inherit' });
let closing = false;
function stop(code = 0) {
  if (closing) return;
  closing = true;
  api.kill();
  web.kill();
  process.exitCode = code;
}
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));
api.on('error', error => { console.error('Could not start uv API service:', error.message); stop(1); });
web.on('error', error => { console.error('Could not start Next.js:', error.message); stop(1); });
api.on('exit', code => { if (!closing) stop(code ?? 1); });
web.on('exit', code => { if (!closing) stop(code ?? 1); });

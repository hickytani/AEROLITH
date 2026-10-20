import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const base = 'http://127.0.0.1:3000';
const targets = await (await fetch('http://127.0.0.1:9222/json')).json();
const target = targets.find((item) => item.type === 'page' && item.url === `${base}/`);
if (!target) throw new Error('Chrome has no Studio page target.');

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});
let nextId = 0;
const pending = new Map();
const consoleErrors = [];
const failedResponses = [];
const geometryResponses = [];
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  } else if (message.method === 'Runtime.exceptionThrown') {
    consoleErrors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
  } else if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
    consoleErrors.push(message.params.entry.text);
  } else if (message.method === 'Network.responseReceived' && message.params.response.status >= 400) {
    failedResponses.push({ status: message.params.response.status, url: message.params.response.url });
  } else if (message.method === 'Network.responseReceived' && message.params.response.url.includes('/api/v1/geometry/')) {
    const response = message.params.response;
    const headers = Object.fromEntries(Object.entries(response.headers || {}).filter(([name]) => /x-(design|geometry|artifact)|content-type/i.test(name)));
    geometryResponses.push({ status: response.status, url: response.url, mimeType: response.mimeType, headers });
  }
});

function call(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
    setTimeout(() => {
      if (!pending.has(id)) return;
      pending.delete(id);
      reject(new Error(`CDP timeout: ${method}`));
    }, 45_000).unref?.();
  });
}

async function evaluate(expression, awaitPromise = false) {
  const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}

async function waitForReady(revision) {
  const result = await evaluate(`new Promise((resolve) => {
    const started = Date.now();
    const poll = () => {
      const state = document.querySelector('#geometry-state')?.textContent || '';
      const rev = document.querySelector('#geometry-rev')?.textContent || '';
      const loading = document.querySelector('#loading')?.textContent || '';
      if ((state.includes('COMPONENT MESHES') && rev.includes('REVISION ${revision}')) || loading.includes('Could not load design') || document.querySelector('#error')?.textContent) {
        resolve({ state, rev, loading, error: document.querySelector('#error')?.textContent || '', elapsedMs: Date.now() - started });
      } else if (Date.now() - started > 30000) resolve({ timeout: true, state, rev, loading });
      else setTimeout(poll, 100);
    };
    poll();
  })`, true);
  if (result.timeout || !result.state.includes('2 COMPONENT MESHES')) throw new Error(`Studio failed to load two meshes: ${JSON.stringify({ ...result, consoleErrors, failedResponses })}`);
  return result;
}

async function screenshot(path) {
  const result = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  const bytes = Buffer.from(result.data, 'base64');
  await writeFile(path, bytes);
  return createHash('sha256').update(bytes).digest('hex');
}

await call('Page.enable');
await call('Runtime.enable');
await call('Network.enable');
await call('Log.enable');
await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await call('Page.reload', { ignoreCache: true });
const initialProject = await evaluate(`fetch('/api/v1/project').then(r => r.json()).then(p => ({ revision: p.revision, pinion: p.components[0].teeth, gear: p.components[1].teeth, module: p.requirements.module_mm }))`, true);
const ready = await waitForReady(initialProject.revision);
const initial = await evaluate(`(() => {
  const canvas = document.querySelector('#viewport canvas');
  const rect = canvas?.getBoundingClientRect();
  const gl = canvas?.getContext('webgl2') || canvas?.getContext('webgl');
  return {
    title: document.title,
    dimensions: { innerWidth, innerHeight, dpr: devicePixelRatio },
    viewport: (() => { const r = document.querySelector('#viewport').getBoundingClientRect(); return { width: r.width, height: r.height }; })(),
    canvas: rect ? { width: rect.width, height: rect.height, backingWidth: canvas.width, backingHeight: canvas.height, webgl: Boolean(gl) } : null,
    state: document.querySelector('#geometry-state').textContent,
    revision: document.querySelector('#geometry-rev').textContent,
    errors: document.querySelector('#geometry-errors').textContent,
    fields: { pinion: document.querySelector('#pinion').value, gear: document.querySelector('#gear').value, module: document.querySelector('#module').value },
    fontSize: getComputedStyle(document.body).fontSize,
  };
})()`);
const outputDir = new URL('../artifacts/', import.meta.url);
await mkdir(outputDir, { recursive: true });
const defaultShot = new URL('../artifacts/p0-studio-default.png', import.meta.url);
const initialScreenshotSha256 = await screenshot(defaultShot);
if (!initial.canvas?.webgl || initial.canvas.width <= 0 || initial.canvas.height <= 0 || initial.errors) {
  throw new Error(`Canvas/WebGL or geometry errors prevent visible Studio rendering: ${JSON.stringify(initial)}`);
}

const viewHashes = {};
for (const view of ['iso', 'top', 'front', 'reset']) {
  await evaluate(`document.querySelector(${JSON.stringify(view === 'reset' ? '#reset' : `[data-view="${view}"]`)}).click()`);
  await new Promise((resolve) => setTimeout(resolve, 250));
  viewHashes[view] = await screenshot(new URL(`../artifacts/p0-view-${view}.png`, import.meta.url));
}
if (viewHashes.iso === viewHashes.top || viewHashes.top === viewHashes.front || viewHashes.front === viewHashes.iso) {
  throw new Error(`Camera presets did not produce distinct rendered views: ${JSON.stringify(viewHashes)}`);
}

const rect = await evaluate(`(() => { const r = document.querySelector('#viewport canvas').getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
const orbitBefore = await screenshot(new URL('../artifacts/p0-orbit-before.png', import.meta.url));
await call('Input.dispatchMouseEvent', { type: 'mousePressed', x: rect.x, y: rect.y, button: 'left', buttons: 1 });
await call('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rect.x + 90, y: rect.y + 45, button: 'left', buttons: 1 });
await call('Input.dispatchMouseEvent', { type: 'mouseReleased', x: rect.x + 90, y: rect.y + 45, button: 'left', buttons: 0 });
await new Promise((resolve) => setTimeout(resolve, 300));
const orbitAfter = await screenshot(new URL('../artifacts/p0-orbit-after.png', import.meta.url));
await call('Input.dispatchMouseEvent', { type: 'mousePressed', x: rect.x, y: rect.y, button: 'right', buttons: 2 });
await call('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rect.x + 35, y: rect.y + 25, button: 'right', buttons: 2 });
await call('Input.dispatchMouseEvent', { type: 'mouseReleased', x: rect.x + 35, y: rect.y + 25, button: 'right', buttons: 0 });
await new Promise((resolve) => setTimeout(resolve, 300));
const panAfter = await screenshot(new URL('../artifacts/p0-pan-after.png', import.meta.url));
await call('Input.dispatchMouseEvent', { type: 'mouseWheel', x: rect.x, y: rect.y, deltaY: -120, deltaX: 0, buttons: 0 });
await new Promise((resolve) => setTimeout(resolve, 300));
const zoomAfter = await screenshot(new URL('../artifacts/p0-zoom-after.png', import.meta.url));
if (orbitBefore === orbitAfter || orbitAfter === panAfter || panAfter === zoomAfter) throw new Error('Orbit, pan, or zoom input did not change rendered pixels.');
await evaluate(`document.querySelector('#reset').click()`);
await new Promise((resolve) => setTimeout(resolve, 250));

const visibleBefore = await screenshot(new URL('../artifacts/p0-both-visible.png', import.meta.url));
await evaluate(`document.querySelector('.eye[data-visibility="pinion"]').click()`);
const hiddenPinionPressed = await evaluate(`document.querySelector('.eye[data-visibility="pinion"]').getAttribute('aria-pressed')`);
const hiddenScreenshot = await screenshot(new URL('../artifacts/p0-pinion-hidden.png', import.meta.url));
await evaluate(`document.querySelector('.eye[data-visibility="pinion"]').click()`);
await evaluate(`document.querySelector('.component-select[data-id="gear"]').click()`);
const selectedGearPressed = await evaluate(`document.querySelector('.component-select[data-id="gear"]').getAttribute('aria-pressed')`);
const selectedScreenshot = await screenshot(new URL('../artifacts/p0-gear-selected.png', import.meta.url));
if (visibleBefore === hiddenScreenshot || visibleBefore === selectedScreenshot) throw new Error('Visibility or selection did not change rendered pixels.');

const demoProject = await evaluate(`(async () => {
  const before = await fetch('/api/v1/project').then(r => r.json());
  document.querySelector('#restore-demo').click();
  for (let i = 0; i < 100; i += 1) {
    await new Promise(resolve => setTimeout(resolve, 100));
    try {
      const project = await fetch('/api/v1/project').then(r => r.json());
      if (project.revision > before.revision) return project;
    } catch {}
  }
  throw new Error('Return to demo did not commit.');
})()`, true);
if (demoProject.components[0].teeth !== 18 || demoProject.components[1].teeth !== 54) throw new Error('Demo reset returned unexpected gear inputs.');
const editedProject = await evaluate(`(async () => {
  const before = await fetch('/api/v1/project').then(r => r.json());
  document.querySelector('#pinion').value = '12';
  document.querySelector('#gear').value = '30';
  document.querySelector('#module').value = '2';
  document.querySelector('#apply').click();
  for (let i = 0; i < 100; i += 1) {
    await new Promise(resolve => setTimeout(resolve, 100));
    try {
      const project = await fetch('/api/v1/project').then(r => r.json());
      if (project.revision > before.revision) return { revision: project.revision, previousRevision: before.revision, pinion: project.components[0].teeth, gear: project.components[1].teeth, module: project.requirements.module_mm, ratio: project.derived.gear_ratio, center: project.derived.center_distance_mm };
    } catch {}
  }
  throw new Error('Studio did not persist the 12/30 revision.');
})()`, true);
if (editedProject.revision !== demoProject.revision + 1) throw new Error(`One Apply click advanced more than one revision: demo R${demoProject.revision}, applied R${editedProject.revision}.`);
const editedReady = await waitForReady(editedProject.revision);
const editShot = new URL('../artifacts/p0-studio-12-30.png', import.meta.url);
const editedScreenshotSha256 = await screenshot(editShot);

await call('Page.reload', { ignoreCache: true });
const persistedReady = await waitForReady(editedProject.revision);
const persisted = await evaluate(`({ revision: document.querySelector('#rev').textContent, pinion: document.querySelector('#pinion').value, gear: document.querySelector('#gear').value, module: document.querySelector('#module').value, resultRevision: document.querySelector('#result-rev').textContent, geometryRevision: document.querySelector('#geometry-rev').textContent, state: document.querySelector('#geometry-state').textContent, errors: document.querySelector('#geometry-errors').textContent })`);
const finalShot = new URL('../artifacts/p0-studio-accepted.png', import.meta.url);
const finalScreenshotSha256 = await screenshot(finalShot);
await call('Emulation.setDeviceMetricsOverride', { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
await new Promise((resolve) => setTimeout(resolve, 400));
const laptopLayout = await evaluate(`(() => {
  const viewport = document.querySelector('#viewport').getBoundingClientRect();
  const canvas = document.querySelector('#viewport canvas').getBoundingClientRect();
  return { innerWidth, innerHeight, viewport: { top: viewport.top, bottom: viewport.bottom, width: viewport.width, height: viewport.height }, canvas: { top: canvas.top, bottom: canvas.bottom, width: canvas.width, height: canvas.height }, state: document.querySelector('#geometry-state').textContent };
})()`);
const laptopScreenshot = new URL('../artifacts/p0-studio-1280x720.png', import.meta.url);
const laptopScreenshotSha256 = await screenshot(laptopScreenshot);
if (laptopLayout.state !== `2 COMPONENT MESHES · REVISION ${editedProject.revision}` || laptopLayout.viewport.bottom > laptopLayout.innerHeight) {
  throw new Error(`Studio does not fit the 1280x720 viewport: ${JSON.stringify(laptopLayout)}`);
}
const acceptedMeshes = geometryResponses.filter((response) => response.url.includes(`revision=${editedProject.revision}`));
for (const component of ['pinion', 'gear']) {
  if (!acceptedMeshes.some((response) => response.status === 200 && response.mimeType === 'model/stl' && response.headers['x-geometry-component-id'] === component && response.headers['x-design-revision'] === String(editedProject.revision) && response.headers['x-geometry-units'] === 'mm')) {
    throw new Error(`No successful current-revision browser mesh response for ${component}.`);
  }
}

console.log(JSON.stringify({
  ready,
  initialProject,
  initial,
  initialScreenshot: { path: decodeURIComponent(defaultShot.pathname), sha256: initialScreenshotSha256 },
  cameraScreenshotSha256: viewHashes,
  interactions: { hiddenPinionPressed, selectedGearPressed },
  editedProject,
  editedReady,
  editedScreenshotSha256,
  persistedReady,
  persisted,
  finalScreenshot: { path: decodeURIComponent(finalShot.pathname), sha256: finalScreenshotSha256 },
  laptopLayout,
  laptopScreenshot: { path: decodeURIComponent(laptopScreenshot.pathname), sha256: laptopScreenshotSha256 },
  consoleErrors,
  failedResponses,
  geometryResponses,
}, null, 2));
socket.close();

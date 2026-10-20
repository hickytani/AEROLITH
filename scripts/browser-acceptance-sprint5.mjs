import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';

const base = process.env.AEROPKMECH_BROWSER_BASE || 'http://127.0.0.1:3000';
const outputDir = new URL('../artifacts/', import.meta.url);
await mkdir(outputDir, { recursive: true });

const target = await fetch(`http://127.0.0.1:9222/json/new?${encodeURIComponent(base + '/')}`, { method: 'PUT' }).then((r) => r.json());
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});

let nextId = 0;
const pending = new Map();
const geometryResponses = [];
const browserErrors = [];
const failedResponses = [];
socket.addEventListener('message', ({ data }) => {
  const message = JSON.parse(data);
  if (message.id) {
    const entry = pending.get(message.id);
    if (entry) {
      pending.delete(message.id);
      message.error ? entry.reject(new Error(message.error.message)) : entry.resolve(message.result);
    }
    return;
  }
  if (message.method === 'Network.responseReceived' && /\/api\/v1\/geometry\/.+\.stl/.test(message.params.response.url)) {
    geometryResponses.push({ url: message.params.response.url, status: message.params.response.status });
  }
  if (message.method === 'Network.responseReceived' && message.params.response.status >= 400) {
    failedResponses.push({ url: message.params.response.url, status: message.params.response.status });
  }
  if (message.method === 'Runtime.exceptionThrown') browserErrors.push(message.params.exceptionDetails.text);
  if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') browserErrors.push(message.params.entry.text);
});

function cdp(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

async function waitFor(expression, description, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const diagnostics = await evaluate('({url:location.href,body:document.body?.innerText.slice(0,1400),intake:document.querySelector("#intake-result")?.textContent,reviewHidden:document.querySelector("#specification-review")?.hidden})').catch((error) => ({ error: error.message }));
  throw new Error(`Timed out waiting for ${description}: ${JSON.stringify(diagnostics)}`);
}

try {
  await Promise.all([cdp('Page.enable'), cdp('Runtime.enable'), cdp('Network.enable'), cdp('Log.enable')]);
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url: base });
  await waitFor("document.querySelector('#request-text') && /^REVISION \\d+/.test(document.querySelector('#rev')?.textContent || '') && document.querySelector('#geometry-state')?.textContent.includes('COMPONENT MESHES')", 'Studio page and initial geometry ready');
  await evaluate(`(() => { const input=document.querySelector('#request-text'); input.value='Generate a two-seater sports car, electric powered, 4.2 m long, 1.8 m wide, with a 300 km range. Include the necessary mechanical and electrical systems.'; input.dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('#parse-request').click(); return true; })()`);
  await waitFor("document.querySelector('#specification-review') && !document.querySelector('#specification-review').hidden", 'rendered vehicle proposal');
  const proposal = await evaluate(`({family:document.querySelector('.specification-family')?.textContent, parameters:[...document.querySelectorAll('.specification-parameter')].map(row=>({label:row.innerText,input:row.querySelector('input')?.value,status:row.querySelector('small')?.textContent})), readiness:document.querySelector('#specification-readiness')?.textContent, intake:document.querySelector('#intake-result')?.textContent, commitDisabled:document.querySelector('#specification-commit')?.disabled})`);
  assert.match(proposal.family, /electric_vehicle/);
  assert.ok(proposal.parameters.length >= 15, `Expected prompted values plus editable geometry defaults, got ${proposal.parameters.length}`);
  assert.equal(proposal.commitDisabled, false, JSON.stringify(proposal));
  const startingRevision = await evaluate("Number(document.querySelector('#rev').textContent.match(/\\d+/)?.[0])");
  await evaluate("document.querySelector('#specification-commit').click()");
  const expectedRevision = startingRevision + 1;
  await waitFor(`document.querySelector('#family-label')?.textContent.includes('ELECTRIC VEHICLE') && document.querySelector('#rev')?.textContent.includes('REVISION ${String(expectedRevision).padStart(2,'0')}') && document.querySelector('#geometry-state')?.textContent.includes('27 COMPONENT MESHES') && document.querySelector('#geometry-state')?.textContent.includes('REVISION ${expectedRevision}')`, 'new committed vehicle revision and all 27 component meshes');
  const project = await fetch('http://127.0.0.1:8000/api/v1/project').then((r) => r.json());
  assert.equal(project.family, 'electric_vehicle');
  assert.equal(project.revision, expectedRevision);
  assert.equal(project.derived.components.length, 27);
  await waitFor('document.querySelectorAll("#components .component").length === 27', '27 generated component rows');
  const toggleResult = await evaluate(`(() => { const eye=document.querySelector('[data-visibility="tire-front-left"]'); const select=document.querySelector('.component-select[data-id="tire-front-left"]'); if(!eye||!select) return null; select.click(); const selected=select.getAttribute('aria-pressed'); eye.click(); const hidden=eye.getAttribute('aria-pressed'); eye.click(); return {selected,hidden,visibleAgain:eye.getAttribute('aria-pressed')}; })()`);
  assert.deepEqual(toggleResult, { selected: 'true', hidden: 'false', visibleAgain: 'true' });
  await evaluate(`(() => { const input=document.querySelector('#component-question'); input.value='What role does this selected component have?'; document.querySelector('#component-ask').click(); })()`);
  await waitFor("document.querySelector('#component-answer')?.textContent.includes('revision')", 'selected-component answer grounded in the current project');
  const componentAnswer = await evaluate("document.querySelector('#component-answer').textContent");
  assert.match(componentAnswer, /tire-front-left|tire|revision/i);
  const impactPreview = await fetch('http://127.0.0.1:8000/api/v1/project/change-impact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: project.revision, changed_parameters: ['overall_width_mm'] }) }).then((r) => r.json());
  assert.equal(impactPreview.design_mutated, false);
  assert.equal(impactPreview.source_revision, project.revision);
  await evaluate(`document.querySelector('[data-view="front"]').click(); document.querySelector('[data-view="iso"]').click()`);
  const desktopLayout = await evaluate('({viewport:[innerWidth,innerHeight],scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,canvas:!!document.querySelector("#viewport canvas")})');
  assert.ok(desktopLayout.canvas, 'WebGL canvas exists');
  await cdp('Page.captureScreenshot').then(({ data }) => writeFile(new URL('sprint5-ev-desktop.png', outputDir), Buffer.from(data, 'base64')));

  const artifactChecks = await evaluate(`(async () => { const paths=['/api/v1/vehicle/layout.pdf','/api/v1/vehicle/manifest.json','/api/v1/vehicle/bom.json','/api/v1/export/step','/api/v1/export/stl']; const results=[]; for(const path of paths){const response=await fetch(path); const bytes=new Uint8Array(await response.arrayBuffer()); const head=Array.from(bytes.slice(0,8)).map(x=>String.fromCharCode(x)).join(''); let detail=null; if(path.endsWith('.json')&&response.ok) {const data=JSON.parse(new TextDecoder().decode(bytes)); detail={componentCount:data.components?.length ?? data.items?.length ?? null,revision:data.revision};} results.push({path,status:response.status,revision:response.headers.get('x-design-revision'),sha256:response.headers.get('x-artifact-sha256'),bytes:bytes.length,signature:head,detail,error:response.ok?null:new TextDecoder().decode(bytes).slice(0,300)});} return results; })()`);
  assert.equal(artifactChecks.length, 5);
  for (const artifact of artifactChecks) {
    assert.equal(artifact.status, 200, `${artifact.path} status`);
    assert.ok(artifact.revision, `${artifact.path} revision header`);
    assert.ok(artifact.sha256, `${artifact.path} checksum header`);
    assert.ok(artifact.bytes > 500, `${artifact.path} nonempty payload`);
    assert.equal(Number(artifact.revision), project.revision, `${artifact.path} current revision`);
  }
  assert.ok(artifactChecks[0].signature.startsWith('%PDF-'), 'layout export is a PDF');
  assert.equal(artifactChecks[1].detail.componentCount, 27, 'manifest component count');
  assert.equal(artifactChecks[2].detail.componentCount, 27, 'BOM item count');

  await cdp('Emulation.setDeviceMetricsOverride', { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
  await waitFor('innerWidth === 1280 && innerHeight === 720', 'laptop viewport resize');
  const laptopLayout = await evaluate('({viewport:[innerWidth,innerHeight],scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,canvas:!!document.querySelector("#viewport canvas")})');
  assert.ok(laptopLayout.canvas, 'WebGL canvas remains present at laptop size');
  await cdp('Page.captureScreenshot').then(({ data }) => writeFile(new URL('sprint5-ev-1280x720.png', outputDir), Buffer.from(data, 'base64')));
  const expectedGeometryPaths = new Set(project.derived.components.map((component) => `/api/v1/geometry/${component.id}.stl`));
  const vehicleGeometryResponses = geometryResponses.filter((entry) => expectedGeometryPaths.has(new URL(entry.url).pathname));
  const uniqueGeometryResponses = new Map(vehicleGeometryResponses.map((entry) => [new URL(entry.url).pathname, entry]));
  assert.equal(uniqueGeometryResponses.size, 27, `Expected one endpoint per component, got ${uniqueGeometryResponses.size}`);
  assert.ok(vehicleGeometryResponses.every((entry) => entry.status === 200), 'Every vehicle component geometry response succeeds');
  assert.ok([...uniqueGeometryResponses.values()].every((entry) => new URL(entry.url).searchParams.get('revision') === String(project.revision)), 'All final vehicle mesh responses are current revision');
  const evidence = { family: project.family, revision: project.revision, components: project.derived.components.length, proposal, toggleResult, componentAnswer, impactPreview, desktopLayout, laptopLayout, geometryResponses, artifactChecks, browserErrors, failedResponses };
  assert.deepEqual(browserErrors, [], 'No browser console errors or runtime exceptions');
  await writeFile(new URL('sprint5-browser-acceptance.json', outputDir), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
} finally {
  socket.close();
  await fetch(`http://127.0.0.1:9222/json/close/${target.id}`).catch(() => {});
}

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { BufferGeometry, Float32BufferAttribute, Uint16BufferAttribute } from 'three';
import { loadLessonProgress, saveLessonProgress } from '../apps/web/app/lib/learning.mjs';
import { copyText, listOpenApiOperations } from '../apps/web/app/lib/platform.mjs';
import { loadComponentMesh, loadComponentSet, MeshLoadError, validateMeshGeometry } from '../public/mesh-loader.js';
import { cameraFitPose, unionBounds } from '../public/camera-fit.js';

function tetrahedronStl() {
  const triangles = [
    [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    [[0, 0, 0], [0, 1, 0], [0, 0, 1]],
    [[0, 0, 0], [0, 0, 1], [1, 0, 0]],
    [[1, 0, 0], [0, 0, 1], [0, 1, 0]],
  ];
  const bytes = new ArrayBuffer(84 + triangles.length * 50);
  const view = new DataView(bytes);
  view.setUint32(80, triangles.length, true);
  triangles.forEach((triangle, index) => {
    const offset = 84 + index * 50;
    for (let vertex = 0; vertex < 3; vertex += 1) {
      for (let axis = 0; axis < 3; axis += 1) view.setFloat32(offset + 12 + vertex * 12 + axis * 4, triangle[vertex][axis], true);
    }
  });
  return bytes;
}

async function meshResponse(componentId = 'pinion', revision = 4, payload = tetrahedronStl()) {
  const digest = await crypto.subtle.digest('SHA-256', payload);
  const sha256 = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  const headers = {
    'content-type': 'model/stl',
    'x-design-revision': String(revision),
    'x-geometry-revision': String(revision),
    'x-geometry-component-id': componentId,
    'x-geometry-units': 'mm',
    'x-geometry-format': 'stl',
    'x-artifact-id': `${componentId}:r${revision}:${sha256.slice(0, 16)}`,
    'x-artifact-sha256': sha256,
  };
  return new Response(payload, { headers });
}

test('Studio parses and validates a revision and component bound binary STL response', async () => {
  const geometry = await loadComponentMesh({
    componentId: 'pinion', revision: 4,
    fetchImpl: async () => meshResponse(),
  });
  assert.equal(geometry.attributes.position.count, 12);
  assert.deepEqual(geometry.boundingBox.min.toArray(), [0, 0, 0]);
  assert.deepEqual(geometry.boundingBox.max.toArray(), [1, 1, 1]);
  geometry.dispose();
});

test('a failed component mesh does not block its valid assembly partner', async () => {
  const rendered = [];
  const errors = [];
  const results = await loadComponentSet([
    { id: 'pinion', name: 'Pinion' }, { id: 'gear', name: 'Driven gear' },
  ], 4, {
    fetchImpl: async (url) => url.includes('/gear.stl')
      ? new Response(JSON.stringify({ detail: 'CadQuery failed.' }), { status: 500, headers: { 'content-type': 'application/json' } })
      : meshResponse('pinion'),
    onGeometry(component, geometry) { rendered.push(component.id); geometry.dispose(); },
    onError(component, error) { errors.push([component.id, error.status]); },
  });
  assert.deepEqual(results, [true, false]);
  assert.deepEqual(rendered, ['pinion']);
  assert.deepEqual(errors, [['gear', 500]]);
});

test('FIT frames the union of visible component bounds and camera presets remain distinct', () => {
  const bounds = unionBounds([
    { min: [-20, -20, -6], max: [20, 20, 6] },
    { min: [16, -56, -6], max: [128, 56, 6] },
  ]);
  assert.deepEqual(bounds, { min: [-20, -56, -6], max: [128, 56, 6] });
  const iso = cameraFitPose(bounds.min, bounds.max, 1.5, 36, 'iso');
  const top = cameraFitPose(bounds.min, bounds.max, 1.5, 36, 'top');
  const front = cameraFitPose(bounds.min, bounds.max, 1.5, 36, 'front');
  for (const pose of [iso, top, front]) {
    assert.deepEqual(pose.target, [54, 0, 0]);
    assert.ok(pose.distance > 0);
    assert.ok(pose.far > pose.distance);
  }
  assert.deepEqual(top.up, [0, 1, 0]);
  assert.notDeepEqual(iso.position, top.position);
  assert.notDeepEqual(front.position, top.position);
  assert.equal(unionBounds([]), null);
});

test('Studio reports stale revisions, wrong component contracts, and malformed meshes', async () => {
  await assert.rejects(loadComponentMesh({
    componentId: 'gear', revision: 4,
    fetchImpl: async () => new Response(JSON.stringify({ detail: 'Requested revision is stale.' }), {
      status: 409, headers: { 'content-type': 'application/json', 'x-design-revision': '5' },
    }),
  }), (error) => error instanceof MeshLoadError && error.stale && error.currentRevision === 5);
  await assert.rejects(loadComponentMesh({
    componentId: 'gear', revision: 4,
    fetchImpl: async () => meshResponse('pinion'),
  }), /returned geometry for pinion/);
  await assert.rejects(loadComponentMesh({
    componentId: 'pinion', revision: 4,
    fetchImpl: async () => meshResponse('pinion', 4, new ArrayBuffer(32)),
  }), /payload is too short/);
  const invalidVertices = tetrahedronStl();
  new DataView(invalidVertices).setFloat32(96, Number.NaN, true);
  await assert.rejects(loadComponentMesh({
    componentId: 'pinion', revision: 4,
    fetchImpl: async () => meshResponse('pinion', 4, invalidVertices),
  }), /non-finite vertex/);
  const trusted = await meshResponse();
  const alteredBytes = tetrahedronStl();
  new DataView(alteredBytes).setFloat32(100, 2, true);
  await assert.rejects(loadComponentMesh({
    componentId: 'pinion', revision: 4,
    fetchImpl: async () => new Response(alteredBytes, { headers: Object.fromEntries(trusted.headers) }),
  }), /do not match their SHA-256/);
  const indexed = new BufferGeometry();
  indexed.setAttribute('position', new Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 1], 3));
  indexed.setIndex(new Uint16BufferAttribute([0, 1, 3], 1));
  assert.throws(() => validateMeshGeometry(indexed, 'gear'), /out-of-range triangle index/);
  indexed.dispose();
});

test('Learn progress is local, versioned, and round-trips per lesson', () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  assert.equal(loadLessonProgress('ratio', storage), false);
  assert.equal(saveLessonProgress('ratio', true, storage), true);
  assert.equal(loadLessonProgress('ratio', storage), true);
  assert.equal(saveLessonProgress('ratio', false, storage), true);
  assert.equal(loadLessonProgress('ratio', storage), false);
});

test('Platform endpoint inventory comes from live OpenAPI paths', () => {
  const operations = listOpenApiOperations({ paths: {
    '/api/v1/project': { get: { summary: 'Get project', responses: { 200: {} } }, patch: { summary: 'Edit project', responses: { 422: {} } } },
    '/ignored': { parameters: [{ name: 'id' }] },
  } });
  assert.deepEqual(operations.map(({ method, path }) => [method, path]), [
    ['GET', '/api/v1/project'], ['PATCH', '/api/v1/project'],
  ]);
});

test('Platform copy interaction calls the browser clipboard API', async () => {
  let copied = '';
  await copyText('curl http://127.0.0.1:8000/api/v1/project', { writeText: async (text) => { copied = text; } });
  assert.equal(copied, 'curl http://127.0.0.1:8000/api/v1/project');
  await assert.rejects(copyText('secret', undefined), /Clipboard access is unavailable/);
});

test('Studio regression contract keeps the component element and dynamic ratio in sync', async () => {
  const [markup, script, nextConfig] = await Promise.all([
    readFile(new URL('../public/index.html', import.meta.url), 'utf8'),
    readFile(new URL('../public/app.js', import.meta.url), 'utf8'),
    readFile(new URL('../apps/web/next.config.mjs', import.meta.url), 'utf8'),
  ]);
  assert.match(markup, /class="components" id="components"/);
  assert.match(markup, /href="\/learn"/);
  assert.match(markup, /href="\/platform"/);
  assert.match(script, /required\('gear-label'\)\.textContent = `OUTPUT · \$\{derived\.gear_ratio\.toFixed\(2\)\}:1`/);
  assert.doesNotMatch(script, /OUTPUT · 3:1/);
  assert.match(script, /sequence !== buildSequence \|\| project\.revision !== revision/);
  assert.match(script, /const committed = await request\('\/project'/);
  assert.match(script, /project = await request\('\/project'\)/);
  assert.match(script, /loadComponentSet/);
  assert.match(script, /geometry-errors/);
  assert.match(script, /disposeStudio/);
  assert.match(nextConfig, /source:\s*'\/mesh-loader\.js'/);
  assert.match(nextConfig, /source:\s*'\/camera-fit\.js'/);
});

test('Studio and product surfaces use local readable type without sub-12px text', async () => {
  const [studioCss, productCss] = await Promise.all([
    readFile(new URL('../public/style.css', import.meta.url), 'utf8'),
    readFile(new URL('../apps/web/app/experiences.css', import.meta.url), 'utf8'),
  ]);
  assert.doesNotMatch(studioCss, /fonts\.googleapis\.com/);
  for (const stylesheet of [studioCss, productCss]) {
    const declarations = [...stylesheet.matchAll(/\bfont(?:-size)?\s*:\s*([^;}]+)/g)];
    const sizes = declarations.map(([, declaration]) => Number(declaration.match(/([\d.]+)px/)?.[1])).filter(Number.isFinite);
    assert.ok(sizes.length > 0);
    assert.ok(sizes.every((size) => size >= 12), `Found text smaller than 12px: ${sizes.filter((size) => size < 12).join(', ')}`);
  }
  assert.match(studioCss, /--muted:\s*#[0-9a-f]{6}/i);
  assert.match(productCss, /font-size:\s*15px/);
});

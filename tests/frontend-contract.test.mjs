import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadLessonProgress, saveLessonProgress } from '../apps/web/app/lib/learning.mjs';
import { copyText, listOpenApiOperations } from '../apps/web/app/lib/platform.mjs';

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
  const [markup, script] = await Promise.all([
    readFile(new URL('../public/index.html', import.meta.url), 'utf8'),
    readFile(new URL('../public/app.js', import.meta.url), 'utf8'),
  ]);
  assert.match(markup, /class="components" id="components"/);
  assert.match(markup, /href="\/learn"/);
  assert.match(markup, /href="\/platform"/);
  assert.match(script, /required\('gear-label'\)\.textContent = `OUTPUT · \$\{derived\.gear_ratio\.toFixed\(2\)\}:1`/);
  assert.doesNotMatch(script, /OUTPUT · 3:1/);
  assert.match(script, /sequence !== buildSequence \|\| project\.revision !== revision/);
  assert.match(script, /const committed = await request\('\/project'/);
  assert.match(script, /project = await request\('\/project'\)/);
});

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

// Exercise the browser API boundary with Node's fetch types, without another test runtime.
const source = await readFile(new URL('../src/api.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
} }).outputText;
const { executeSql, fetchCatalog, fetchFlightSensors, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);

test('sensor playback requests the selected flight through the authenticated backend', async t => {
  const controller = new AbortController();
  const result = { seconds: 3, series: { alt: [0, null, 42000] }, query_identity: 'engineering_analyst' };
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/flights/sensors?id=A%2FB%20%26%20C');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.signal, controller.signal);
    assert.equal(options.body, undefined);
    return Response.json(result);
  });
  assert.deepEqual(await fetchFlightSensors('A/B & C', controller.signal), result);
});

test('SQL sends only the statement with session credentials and preserves server values/identity', async t => {
  const result = {
    columns: [{ name: 'value', type: 'json' }], rows: [[null], [false], [[1, 2]], [{ a: 1 }]],
    truncated: true, ms: 123, query_identity: 'engineering_analyst',
  };
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/sql');
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), { sql: 'SELECT current_user' });
    return Response.json(result);
  });
  assert.deepEqual(await executeSql('SELECT current_user'), result);
});

test('catalog uses the backend role-scoped columns, including omitted restricted columns', async t => {
  const result = { tables: { 'iceberg.gold.flight_summary': [{ name: 'flight_id', type: 'varchar' }] }, query_identity: 'operations_analyst' };
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/catalog');
    assert.equal(options.credentials, 'same-origin');
    return Response.json(result);
  });
  assert.deepEqual(await fetchCatalog(), result);
});

for (const [status, message] of [[401, 'Sign in again.'], [403, 'Access Denied: Cannot select touchdown_peak_g'],
  [400, "Column 'missing' cannot be resolved"], [408, 'The query ran longer than 30 s and was cancelled.']]) {
  test(`HTTP ${status} preserves the backend error instead of generating a result`, async t => {
    t.mock.method(globalThis, 'fetch', async () => Response.json({ error: message }, { status }));
    await assert.rejects(executeSql('SELECT x'), error => error instanceof ApiError && error.status === status && error.message === message);
  });
}

test('unreachable backend reports an error without falling back to demo data', async t => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(executeSql('SELECT 1'), error => error instanceof ApiError && error.status === 0);
});

test('stopping a request forwards the abort signal and preserves AbortError', async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, 'fetch', (_path, options) => new Promise((_resolve, reject) => {
    assert.equal(options.signal, controller.signal);
    options.signal.addEventListener('abort', () => reject(new DOMException('Stopped waiting', 'AbortError')), { once: true });
  }));
  const pending = executeSql('SELECT 1', controller.signal);
  controller.abort();
  await assert.rejects(pending, error => error.name === 'AbortError' && !(error instanceof ApiError));
});

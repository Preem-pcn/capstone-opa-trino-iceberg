import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/sensors.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { sensorPath, displaySample, recordingUtc } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);

test('missing sensor samples create separate segments, including during downsampling', () => {
  const series = Array(10000).fill(1);
  series[100] = null;
  const result = sensorPath(series);
  assert.equal(result.path.split('M').length - 1, 2);
  assert.equal(result.path.includes('NaN'), false);
  assert.deepEqual(sensorPath([null, null]), { path: '', min: null, max: null });
});

test('brief peaks survive reducing a full recording to display width', () => {
  const series = Array(40000).fill(1);
  series[15671] = 2;
  series[15672] = 0.5;
  const result = sensorPath(series);
  assert.equal(result.min, 0.5);
  assert.equal(result.max, 2);
  assert.match(result.path, /,6\.0(?:L|$)/);
  assert.match(result.path, /,74\.0(?:L|$)/);
  assert.ok(result.path.length < series.length);
});

test('missing values stay unavailable; a real zero stays zero', () => {
  assert.equal(displaySample(null), '—');
  assert.equal(displaySample(undefined), '—');
  assert.equal(displaySample(NaN), '—');
  assert.equal(displaySample(0, 1), '0.0');
});

test('playback UTC follows each recording start, including day boundaries', () => {
  assert.equal(recordingUtc('2022-03-22 23:59:59', 2), '2022-03-23 00:00:01 UTC');
  assert.equal(recordingUtc('2022-08-26T01:00:00+07:00', 0), '2022-08-25 18:00:00 UTC');
  assert.equal(recordingUtc(null, 100), '—');
  assert.equal(recordingUtc('invalid', 100), '—');
});

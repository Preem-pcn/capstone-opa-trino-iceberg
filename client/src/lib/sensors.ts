// Keep gaps and retain each display column's actual extrema so a brief peak
// survives downsampling a recording that spans hours.
export function sensorPath(values: (number | null)[], width = 310, height = 80) {
  let min = Infinity, max = -Infinity;
  for (const v of values) {
    if (v === null || !Number.isFinite(v)) continue;
    min = Math.min(min, v); max = Math.max(max, v);
  }
  if (!Number.isFinite(min)) return { path: '', min: null, max: null };
  const range = max - min || 1;
  const x = (i: number) => 6 + i / Math.max(1, values.length - 1) * (width - 12);
  const y = (v: number) => 6 + (1 - (v - min) / range) * (height - 12);
  const stride = Math.max(1, Math.ceil(values.length / (width - 12)));
  let path = '', start = 0;
  while (start < values.length) {
    if (values[start] === null || !Number.isFinite(values[start])) { start++; continue; }
    let end = start + 1;
    while (end < values.length && values[end] !== null && Number.isFinite(values[end])) end++;
    let first = true;
    for (let i = start; i < end; i += stride) {
      const stop = Math.min(end, i + stride);
      let low = i, high = i;
      for (let j = i + 1; j < stop; j++) {
        if (values[j]! < values[low]!) low = j;
        if (values[j]! > values[high]!) high = j;
      }
      for (const j of [...new Set([i, low, high, stop - 1])].sort((a, b) => a - b)) {
        path += `${first ? 'M' : 'L'}${x(j).toFixed(1)},${y(values[j]!).toFixed(1)}`;
        first = false;
      }
    }
    start = end;
  }
  return { path, min, max };
}

export const displaySample = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function recordingUtc(start: string | null, offset: number) {
  if (!start) return '—';
  // Trino timestamps without a suffix are UTC in this dataset.
  const iso = /(?:Z|[+-]\d{2}:\d{2})$/.test(start) ? start : `${start.replace(' ', 'T')}Z`;
  const epoch = new Date(iso).getTime();
  return Number.isFinite(epoch) ? `${new Date(epoch + Math.floor(offset) * 1000).toISOString().slice(0, 19).replace('T', ' ')} UTC` : '—';
}

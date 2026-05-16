export function createSearchParams(obj: Record<string, unknown>) {
  const res: Record<string, string> = {};
  for (const key in obj) {
    if (typeof obj[key] === 'undefined') continue;
    if (Array.isArray(obj[key])) {
      res[key] = obj[key].map((v: unknown) => String(v)).join(',');
      continue;
    }
    res[key] = String(obj[key]);
  }
  return new URLSearchParams(res);
}

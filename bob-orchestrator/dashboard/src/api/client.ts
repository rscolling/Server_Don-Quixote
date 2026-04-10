const BASE = '/dashboard/api';

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!resp.ok) throw new Error(`API ${resp.status}: ${resp.statusText}`);
  return resp.json();
}

export function apiPatch<T>(path: string, body: Record<string, any>): Promise<T> {
  return apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) });
}

import { vi } from 'vitest'

type Handler = (init?: RequestInit) => unknown
type Routes = Record<string, Handler | object>

/** Stub fetch with a map of "METHOD /api/path" -> JSON response (or handler). */
export function mockApi(routes: Routes) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(input)}`
    if (!(key in routes)) return new Response(null, { status: 404 })
    const route = routes[key]
    const body = typeof route === 'function' ? (route as Handler)(init) : route
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

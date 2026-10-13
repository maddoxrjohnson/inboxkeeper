export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`)
  if (!resp.ok) {
    throw new ApiError(resp.status, `GET ${path} failed with ${resp.status}`)
  }
  return (await resp.json()) as T
}

export interface Health {
  status: string
  version: string
}

export const getHealth = () => apiGet<Health>('/health')

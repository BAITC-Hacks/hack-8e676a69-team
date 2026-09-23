const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
    ...options,
  })

  const payload = await response.json().catch(() => null)

  if (!response.ok) {
    const message = payload?.error?.message ?? payload?.detail ?? response.statusText
    const error = new Error(message)
    error.status = response.status
    error.code = payload?.error?.code
    error.payload = payload
    throw error
  }

  return payload
}

export function fetchBootstrap() {
  return requestJson('/api/bootstrap')
}

export function createForecastTicket(input) {
  return requestJson('/api/tickets', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function pollForecastTicket(ticketId) {
  return requestJson(`/api/tickets/${ticketId}`)
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : detail?.message || detail?.code || `錯誤 ${status}`)
    this.status = status
    this.detail = detail
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    const detail = data?.detail
    if (Array.isArray(detail)) {
      throw new ApiError(res.status, detail.map((d) => d.msg).join('；'))
    }
    throw new ApiError(res.status, detail ?? data?.error ?? `錯誤 ${res.status}`)
  }
  return data
}

export const money = (v, currency = 'TWD') =>
  v === null || v === undefined ? '—' : `${currency} ${Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 2 })}`

export const dt = (v) => (v ? new Date(v).toLocaleString('zh-TW', { hour12: false }) : '—')

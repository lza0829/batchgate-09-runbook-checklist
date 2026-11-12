export async function getJSON(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function postJSON(url, body = {}) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function patchJSON(url, body) {
  const r = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function deleteJSON(url) {
  const r = await fetch(url, { method: 'DELETE' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function errorDetail(e) {
  const text = String(e?.message || e)
  try {
    const parsed = JSON.parse(text)
    const d = parsed?.detail
    if (d && typeof d === 'object') {
      return {
        message: d.reasons?.join('；') || '请求被拒绝',
        detail: d,
      }
    }
    if (typeof d === 'string') return { message: d, detail: null }
  } catch {
    /* not json */
  }
  return { message: text, detail: null }
}

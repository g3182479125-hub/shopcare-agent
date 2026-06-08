const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export async function postChat(message: string, orderId?: string) {
  const res = await fetch(`${API_BASE}/api/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, order_id: orderId || undefined })
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSummary() {
  const res = await fetch(`${API_BASE}/api/dashboard/summary`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

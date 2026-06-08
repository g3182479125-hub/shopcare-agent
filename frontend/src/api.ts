const API_BASE = import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? 'https://shopcare-agent-api.vercel.app' : 'http://localhost:8000')

export async function postChat(message: string, orderId?: string, image?: File | null, sessionId?: string) {
  const init: RequestInit = { method: 'POST' }
  if (image) {
    const formData = new FormData()
    formData.append('message', message)
    if (orderId) formData.append('order_id', orderId)
    if (sessionId) formData.append('session_id', sessionId)
    formData.append('image', image)
    init.body = formData
  } else {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify({ message, order_id: orderId || undefined, session_id: sessionId || undefined })
  }
  const res = await fetch(`${API_BASE}/api/agent/chat`, init)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Activity, Bot, CheckCircle2, Database, FileSearch, GitBranch, Loader2, Search, ShieldAlert, TicketCheck, UserRound } from 'lucide-react'
import { getSummary, postChat } from './api'

type ChatResult = {
  answer: string
  intent: string
  decision: Record<string, any>
  order?: Record<string, any>
  user_profile?: Record<string, any>
  similar_cases: Record<string, any>[]
  policy_evidence: Record<string, any>[]
  traces: { tool_name: string; input: any; output: any; status: string; elapsed_ms: number }[]
  llm_used: boolean
}

const examples = [
  { orderId: '3000010', text: '订单还没发货，我想取消并退款' },
  { orderId: '3000012', text: '这个 MacBook 功能异常，无法正常使用，可以售后吗？' },
  { orderId: '3000029', text: '食品包装破损了，能不能仅退款？' },
  { orderId: '3000025', text: '手机坏了，我是老用户，能不能换货或者退货？' }
]

function fmt(value: any) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function compactNumber(value: any) {
  const num = Number(value || 0)
  if (num >= 10000) return `${(num / 10000).toFixed(1)}万`
  return num.toLocaleString('zh-CN')
}

export default function App() {
  const [message, setMessage] = useState(examples[0].text)
  const [orderId, setOrderId] = useState(examples[0].orderId)
  const [result, setResult] = useState<ChatResult | null>(null)
  const [summary, setSummary] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getSummary().then(setSummary).catch(() => setSummary(null))
  }, [])

  const decisionTone = useMemo(() => {
    const status = result?.decision?.status
    if (status === 'approved') return 'approved'
    if (status === 'escalated') return 'escalated'
    return 'pending'
  }, [result])

  async function submit() {
    setLoading(true)
    try {
      const data = await postChat(message, orderId)
      setResult(data)
    } finally {
      setLoading(false)
    }
  }

  function useExample(item: { orderId: string; text: string }) {
    setOrderId(item.orderId)
    setMessage(item.text)
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><Bot size={22} /></div>
          <div>
            <h1>ShopCare Agent</h1>
            <p>电商售后智能决策台</p>
          </div>
        </div>

        <section className="metric-grid">
          <Metric icon={<Database size={18} />} label="订单" value={compactNumber(summary?.orders?.count)} />
          <Metric icon={<UserRound size={18} />} label="用户" value={compactNumber(summary?.users?.count)} />
          <Metric icon={<TicketCheck size={18} />} label="售后" value={compactNumber(summary?.aftersales?.count)} />
          <Metric icon={<Activity size={18} />} label="退款额" value={compactNumber(summary?.aftersales?.refund_sum)} />
        </section>

        <section className="side-section">
          <h2>样例问题</h2>
          <div className="example-list">
            {examples.map((item) => (
              <button key={item.orderId} onClick={() => useExample(item)}>
                <span>{item.orderId}</span>
                {item.text}
              </button>
            ))}
          </div>
        </section>

        <section className="side-section">
          <h2>售后原因 Top</h2>
          <div className="rank-list">
            {(summary?.aftersales?.reason_top || []).slice(0, 6).map((item: any) => (
              <div className="rank-row" key={item.name}>
                <span>{item.name}</span>
                <b>{compactNumber(item.value)}</b>
              </div>
            ))}
          </div>
        </section>
      </aside>

      <section className="workspace">
        <div className="query-panel">
          <div className="query-fields">
            <label>
              订单号
              <input value={orderId} onChange={(event) => setOrderId(event.target.value)} placeholder="如 3000010" />
            </label>
            <label className="message-field">
              售后问题
              <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={3} />
            </label>
          </div>
          <button className="primary-button" onClick={submit} disabled={loading}>
            {loading ? <Loader2 className="spin" size={18} /> : <Search size={18} />}
            开始分析
          </button>
        </div>

        <div className="content-grid">
          <section className="main-panel answer-panel">
            <div className="panel-title">
              <Bot size={20} />
              <h2>Agent 答复</h2>
              {result && <span className="pill">{result.llm_used ? 'LLM' : '规则兜底'}</span>}
            </div>
            <pre className="answer-text">{result?.answer || '输入订单号和售后问题后，系统会查询订单、用户、相似案例和政策，并输出处理建议。'}</pre>
          </section>

          <section className={`decision-panel ${decisionTone}`}>
            <div className="panel-title">
              {decisionTone === 'approved' ? <CheckCircle2 size={20} /> : <ShieldAlert size={20} />}
              <h2>决策结果</h2>
            </div>
            <div className="decision-grid">
              <Info label="状态" value={result?.decision?.status} />
              <Info label="方案" value={result?.decision?.resolution} />
              <Info label="优先级" value={result?.decision?.priority} />
              <Info label="退款" value={result?.decision?.refund_amount} />
              <Info label="补偿" value={result?.decision?.compensation_amount} />
              <Info label="人工" value={result?.decision?.need_human_review ? '需要' : '否'} />
            </div>
          </section>

          <section className="main-panel">
            <div className="panel-title"><Database size={20} /><h2>订单画像</h2></div>
            <div className="info-grid">
              <Info label="订单" value={result?.order?.order_id} />
              <Info label="状态" value={result?.order?.order_status} />
              <Info label="商品" value={result?.order?.product_name} />
              <Info label="类目" value={result?.order?.category} />
              <Info label="金额" value={result?.order?.amount} />
              <Info label="履约小时" value={result?.order?.fulfillment_time} />
              <Info label="用户等级" value={result?.user_profile?.user_tier} />
              <Info label="累计消费" value={result?.user_profile?.total_purchase_amount} />
            </div>
          </section>

          <section className="main-panel">
            <div className="panel-title"><GitBranch size={20} /><h2>工具调用轨迹</h2></div>
            <div className="trace-list">
              {(result?.traces || []).map((trace, index) => (
                <div className="trace-row" key={`${trace.tool_name}-${index}`}>
                  <span className="trace-index">{index + 1}</span>
                  <div>
                    <b>{trace.tool_name}</b>
                    <p>{trace.status} · {trace.elapsed_ms} ms</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="main-panel wide-panel">
            <div className="panel-title"><FileSearch size={20} /><h2>政策与相似案例</h2></div>
            <div className="evidence-grid">
              <div>
                <h3>政策依据</h3>
                {(result?.policy_evidence || []).map((item) => (
                  <article className="evidence-item" key={item.title}>
                    <b>{item.title}</b>
                    <p>{item.content}</p>
                  </article>
                ))}
              </div>
              <div>
                <h3>相似案例</h3>
                {(result?.similar_cases || []).slice(0, 4).map((item) => (
                  <article className="evidence-item" key={item.case_id}>
                    <b>{item.case_id} · {item.reason_code}</b>
                    <p>{item.user_description}，处理：{item.resolution}</p>
                  </article>
                ))}
              </div>
            </div>
          </section>
        </div>
      </section>
    </main>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="metric"><span>{icon}</span><p>{label}</p><b>{value || '-'}</b></div>
}

function Info({ label, value }: { label: string; value: any }) {
  return <div className="info-item"><span>{label}</span><b>{fmt(value)}</b></div>
}

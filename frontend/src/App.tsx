import { useEffect, useMemo, useRef, useState, type DragEvent, type ClipboardEvent, type ReactNode } from 'react'
import { Activity, Bot, Camera, CheckCircle2, Database, FileSearch, GitBranch, Loader2, Search, ShieldAlert, TicketCheck, UserRound, X } from 'lucide-react'
import { getSummary, postChat } from './api'

type ImageAnalysis = {
  product_condition: string
  damage_details: string[]
  severity: '轻微' | '中等' | '严重' | string
  evidence_valid: boolean
  evidence_description?: string
  suggested_action?: string
}

type ChatResult = {
  answer: string
  intent: string
  decision: Record<string, any>
  order?: Record<string, any>
  user_profile?: Record<string, any>
  similar_cases: Record<string, any>[]
  policy_evidence: Record<string, any>[]
  traces: { tool_name: string; label?: string; input: any; output: any; status: string; elapsed_ms: number; summary?: string }[]
  llm_used: boolean
  image_analysis?: ImageAnalysis | null
}

const MAX_IMAGE_SIZE = 5 * 1024 * 1024

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

function formatFileSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  return `${Math.max(1, Math.round(size / 1024))}KB`
}

export default function App() {
  const [message, setMessage] = useState(examples[0].text)
  const [orderId, setOrderId] = useState(examples[0].orderId)
  const [result, setResult] = useState<ChatResult | null>(null)
  const [summary, setSummary] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [uploadedImage, setUploadedImage] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [progressText, setProgressText] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    getSummary().then(setSummary).catch(() => setSummary(null))
  }, [])

  useEffect(() => {
    if (!uploadedImage) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(uploadedImage)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [uploadedImage])

  const decisionTone = useMemo(() => {
    const status = result?.decision?.status
    if (status === 'approved') return 'approved'
    if (status === 'escalated') return 'escalated'
    return 'pending'
  }, [result])

  function acceptImage(file: File | null | undefined) {
    if (!file) return
    if (!file.type.startsWith('image/')) return
    if (file.size > MAX_IMAGE_SIZE) {
      window.alert('图片不能超过5MB')
      return
    }
    setUploadedImage(file)
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const imageItem = Array.from(event.clipboardData.items).find((item) => item.type.startsWith('image/'))
    if (!imageItem) return
    event.preventDefault()
    acceptImage(imageItem.getAsFile())
  }

  function handleDrop(event: DragEvent<HTMLTextAreaElement>) {
    event.preventDefault()
    setDragActive(false)
    const file = Array.from(event.dataTransfer.files).find((item) => item.type.startsWith('image/'))
    acceptImage(file)
  }

  async function submit() {
    setLoading(true)
    setProgressText(uploadedImage ? '图片上传中...' : '')
    const timers: number[] = []
    if (uploadedImage) {
      timers.push(window.setTimeout(() => setProgressText('Kimi视觉Agent分析图片...'), 500))
      timers.push(window.setTimeout(() => setProgressText('DeepSeek综合决策中...'), 1400))
    }
    try {
      const data = await postChat(message, orderId, uploadedImage)
      setResult(data)
      if (uploadedImage) setProgressText('完成')
    } finally {
      timers.forEach(window.clearTimeout)
      setLoading(false)
      if (uploadedImage) window.setTimeout(() => setProgressText(''), 1200)
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
              {progressText && <div className="progress-banner">{progressText}</div>}
              <textarea
                className={dragActive ? 'drag-active' : ''}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onPaste={handlePaste}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragActive(true)
                }}
                onDragLeave={() => setDragActive(false)}
                onDrop={handleDrop}
                rows={3}
                placeholder="可输入文字，也可以粘贴或拖拽商品问题图片"
              />
              {uploadedImage && previewUrl && (
                <div className="image-preview">
                  <div className="image-thumb-wrap">
                    <img src={previewUrl} alt="售后凭证预览" />
                    <button type="button" aria-label="清除图片" onClick={() => setUploadedImage(null)}>
                      <X size={14} />
                    </button>
                  </div>
                  <div>
                    <b>{uploadedImage.name}</b>
                    <p>{formatFileSize(uploadedImage.size)}</p>
                  </div>
                </div>
              )}
            </label>
          </div>
          <div className="query-actions">
            <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={(event) => acceptImage(event.target.files?.[0])} />
            <button className="secondary-button" type="button" onClick={() => fileInputRef.current?.click()} disabled={loading}>
              <Camera size={18} />
              上传图片
            </button>
            <button className="primary-button" onClick={submit} disabled={loading}>
              {loading ? <Loader2 className="spin" size={18} /> : <Search size={18} />}
              开始分析
            </button>
          </div>
        </div>

        <div className="content-grid">
          <section className="main-panel answer-panel">
            <div className="panel-title">
              <Bot size={20} />
              <h2>Agent 答复</h2>
              {result && <span className="pill">{result.llm_used ? 'LLM' : '规则兜底'}</span>}
            </div>
            {result?.image_analysis && <ImageAnalysisCard analysis={result.image_analysis} />}
            <pre className="answer-text">{result?.answer || '输入订单号和售后问题后，系统会查询订单、用户、相似案例和政策，并输出处理建议。支持粘贴、拖拽或上传商品问题图片作为售后凭证。'}</pre>
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
                    <b>{trace.label || trace.tool_name}</b>
                    <p>{trace.status} · {trace.elapsed_ms} ms{trace.summary ? ` · ${trace.summary}` : ''}</p>
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

function ImageAnalysisCard({ analysis }: { analysis: ImageAnalysis }) {
  const severityClass = analysis.severity === '严重' ? 'severe' : analysis.severity === '中等' ? 'medium' : 'light'
  return (
    <div className="image-analysis-card">
      <div className="analysis-title"><Camera size={16} /> 图片分析结果（Kimi视觉Agent）</div>
      <div>商品状态：{analysis.product_condition}</div>
      <div>损坏详情：{(analysis.damage_details || []).join('、') || '-'}</div>
      <div>严重程度：<span className={`severity-tag ${severityClass}`}>{analysis.severity || '-'}</span></div>
      <div>凭证有效：{analysis.evidence_valid ? '是' : '否'}</div>
      {analysis.evidence_description && <div>凭证说明：{analysis.evidence_description}</div>}
    </div>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="metric"><span>{icon}</span><p>{label}</p><b>{value || '-'}</b></div>
}

function Info({ label, value }: { label: string; value: any }) {
  return <div className="info-item"><span>{label}</span><b>{fmt(value)}</b></div>
}

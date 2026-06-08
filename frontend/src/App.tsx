import { useMemo, useRef, useState, type ChangeEvent, type ClipboardEvent, type DragEvent } from 'react'
import {
  Bot,
  Camera,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  ImagePlus,
  Loader2,
  PackageCheck,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  X
} from 'lucide-react'
import { postChat } from './api'

type ImageAnalysis = {
  product_condition: string
  damage_details: string[]
  severity: '轻微' | '中等' | '严重' | string
  evidence_valid: boolean
  evidence_description?: string
  suggested_action?: string
}

type Trace = {
  tool_name: string
  label?: string
  input: unknown
  output: unknown
  status: string
  elapsed_ms: number
  summary?: string
}

type ChatResult = {
  answer: string
  intent: string
  decision: Record<string, any>
  order?: Record<string, any>
  user_profile?: Record<string, any>
  similar_cases: Record<string, any>[]
  policy_evidence: Record<string, any>[]
  traces: Trace[]
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

const statusMap: Record<string, string> = {
  approved: '已通过',
  rejected: '暂不通过',
  need_info: '需补充资料',
  escalated: '人工复核'
}

const resolutionMap: Record<string, string> = {
  refund_only: '仅退款',
  return_refund: '退货退款',
  exchange: '换货',
  manual_review: '人工复核',
  reject: '拒绝售后',
  replacement: '补发/换新'
}

function display(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function money(value: unknown) {
  const num = Number(value)
  if (!Number.isFinite(num)) return display(value)
  return `¥${num.toFixed(2)}`
}

function cleanText(text = '') {
  return text.replace(/\*\*/g, '').trim()
}

function fileSize(size: number) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
}

export default function App() {
  const [orderId, setOrderId] = useState(examples[2].orderId)
  const [message, setMessage] = useState(examples[2].text)
  const [result, setResult] = useState<ChatResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState('')
  const [uploadedImage, setUploadedImage] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const decision = result?.decision || {}
  const statusKey = String(decision.status || '')
  const decisionTone = statusKey === 'approved' ? 'success' : statusKey === 'rejected' ? 'danger' : 'attention'
  const answerParagraphs = useMemo(() => cleanText(result?.answer || '').split(/\n+/).filter(Boolean), [result])

  function setExample(item: (typeof examples)[number]) {
    setOrderId(item.orderId)
    setMessage(item.text)
    setResult(null)
    setError('')
  }

  function acceptImage(file?: File | null) {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('请上传图片格式的凭证。')
      return
    }
    if (file.size > MAX_IMAGE_SIZE) {
      setError('图片不能超过 5 MB。')
      return
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setUploadedImage(file)
    setPreviewUrl(URL.createObjectURL(file))
    setError('')
  }

  function removeImage() {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setUploadedImage(null)
    setPreviewUrl('')
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    acceptImage(event.target.files?.[0])
    event.target.value = ''
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const imageItem = Array.from(event.clipboardData.items).find((item) => item.type.startsWith('image/'))
    if (!imageItem) return
    event.preventDefault()
    acceptImage(imageItem.getAsFile())
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragActive(false)
    const file = Array.from(event.dataTransfer.files).find((item) => item.type.startsWith('image/'))
    acceptImage(file)
  }

  async function submit() {
    const trimmedMessage = message.trim()
    const trimmedOrderId = orderId.trim()
    if (!trimmedMessage || !trimmedOrderId) {
      setError('请填写订单号和售后问题。')
      return
    }

    setLoading(true)
    setError('')
    setProgress(uploadedImage ? '正在识别图片凭证' : '正在核验订单')
    const timers = [
      window.setTimeout(() => setProgress('正在匹配售后政策'), 650),
      window.setTimeout(() => setProgress('正在生成处理建议'), 1300)
    ]

    try {
      const data = await postChat(trimmedMessage, trimmedOrderId, uploadedImage)
      setResult(data)
      setProgress('已生成处理结果')
    } catch (err) {
      setError(err instanceof Error ? err.message : '服务暂时不可用，请稍后重试。')
    } finally {
      timers.forEach(window.clearTimeout)
      window.setTimeout(() => setProgress(''), 900)
      setLoading(false)
    }
  }

  return (
    <main className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">
            <Bot size={24} />
          </div>
          <div>
            <strong>ShopCare Agent</strong>
            <span>电商售后智能助手</span>
          </div>
        </div>
        <div className="topbar-chips">
          <span><ShieldCheck size={15} /> 订单核验</span>
          <span><Camera size={15} /> 图片凭证</span>
          <span><Sparkles size={15} /> AI 决策</span>
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">Customer After-Sales Assistant</p>
          <h1>提交售后问题，马上得到处理建议</h1>
          <p className="hero-copy">
            系统会结合订单、用户等级、售后政策、历史案例和商品图片凭证，输出可解释的退款、退货、换货或人工复核建议。
          </p>
        </div>
        <div className="hero-status">
          <PackageCheck size={18} />
          <span>当前接入公开演示数据，可直接在线体验</span>
        </div>
      </section>

      <section className="assistant-grid">
        <section className="request-panel">
          <div className="section-title">
            <ClipboardCheck size={20} />
            <div>
              <h2>申请售后</h2>
              <p>填写订单号、描述问题，并上传商品照片作为凭证。</p>
            </div>
          </div>

          <div className="form-row">
            <label>
              订单号
              <input value={orderId} onChange={(event) => setOrderId(event.target.value)} placeholder="例如 3000029" />
            </label>
          </div>

          <label className="problem-box">
            售后问题
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onPaste={onPaste}
              placeholder="例如：食品包装破损了，能不能仅退款？"
              rows={5}
            />
          </label>

          <div
            className={`upload-zone ${dragActive ? 'dragging' : ''}`}
            onDragOver={(event) => {
              event.preventDefault()
              setDragActive(true)
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={onDrop}
          >
            <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={onFileChange} />
            {previewUrl && uploadedImage ? (
              <div className="image-preview">
                <img src={previewUrl} alt="售后凭证预览" />
                <div>
                  <strong>{uploadedImage.name}</strong>
                  <span>{fileSize(uploadedImage.size)}</span>
                </div>
                <button type="button" onClick={removeImage} aria-label="移除图片">
                  <X size={16} />
                </button>
              </div>
            ) : (
              <button type="button" className="upload-empty" onClick={() => fileInputRef.current?.click()}>
                <ImagePlus size={20} />
                <span>上传或拖入商品问题图片</span>
              </button>
            )}
          </div>

          <div className="example-row">
            {examples.map((item) => (
              <button key={item.orderId} type="button" onClick={() => setExample(item)}>
                {item.orderId}
              </button>
            ))}
          </div>

          {error && <p className="error-text">{error}</p>}

          <button className="submit-button" type="button" onClick={submit} disabled={loading}>
            {loading ? <Loader2 className="spin" size={19} /> : <Search size={19} />}
            {loading ? progress || '正在分析' : '开始分析'}
          </button>
        </section>

        <aside className={`result-panel ${result ? decisionTone : ''}`}>
          <div className="section-title">
            {decisionTone === 'success' ? <CheckCircle2 size={20} /> : <RotateCcw size={20} />}
            <div>
              <h2>处理结果</h2>
              <p>{result ? '已生成可解释的售后建议。' : '提交后会在这里展示结论。'}</p>
            </div>
          </div>

          <div className="decision-summary">
            <SummaryItem label="状态" value={statusMap[statusKey] || display(decision.status)} />
            <SummaryItem label="方案" value={resolutionMap[String(decision.resolution)] || display(decision.resolution)} />
            <SummaryItem label="优先级" value={display(decision.priority)} />
            <SummaryItem label="退款金额" value={decision.refund_amount === undefined ? '-' : money(decision.refund_amount)} />
          </div>

          {result?.image_analysis && <ImageCard analysis={result.image_analysis} />}
        </aside>
      </section>

      <section className="answer-section">
        <div className="section-title">
          <Bot size={20} />
          <div>
            <h2>Agent 答复</h2>
            <p>{result?.llm_used ? '由大模型综合生成。' : '由规则引擎快速兜底生成。'}</p>
          </div>
        </div>
        {answerParagraphs.length ? (
          <div className="answer-body">
            {answerParagraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
          </div>
        ) : (
          <div className="empty-answer">这里会展示给用户看的售后答复。</div>
        )}
      </section>

      {result && (
        <section className="details-section">
          <details>
            <summary>查看订单画像与 Agent 调用轨迹 <ChevronDown size={17} /></summary>
            <div className="detail-grid">
              <div className="detail-card">
                <h3>订单画像</h3>
                <Info label="订单" value={result.order?.order_id} />
                <Info label="状态" value={result.order?.order_status} />
                <Info label="商品" value={result.order?.product_name} />
                <Info label="类目" value={result.order?.category} />
                <Info label="金额" value={money(result.order?.amount)} />
                <Info label="用户等级" value={result.user_profile?.user_tier} />
              </div>
              <div className="detail-card">
                <h3>调用轨迹</h3>
                {(result.traces || []).map((trace, index) => (
                  <div className="trace" key={`${trace.tool_name}-${index}`}>
                    <b>{index + 1}. {trace.label || trace.tool_name}</b>
                    <span>{trace.status} · {trace.elapsed_ms} ms{trace.summary ? ` · ${trace.summary}` : ''}</span>
                  </div>
                ))}
              </div>
            </div>
          </details>

          <details>
            <summary>查看政策依据与相似案例 <ChevronDown size={17} /></summary>
            <div className="evidence-grid">
              <div className="detail-card">
                <h3>政策依据</h3>
                {(result.policy_evidence || []).map((item, index) => (
                  <article key={`${item.title}-${index}`}>
                    <b>{item.title}</b>
                    <p>{item.content}</p>
                  </article>
                ))}
              </div>
              <div className="detail-card">
                <h3>相似案例</h3>
                {(result.similar_cases || []).slice(0, 4).map((item, index) => (
                  <article key={`${item.case_id}-${index}`}>
                    <b>{item.case_id || '案例'} · {item.reason_code || '售后'}</b>
                    <p>{item.user_description || item.description || '-'}，处理：{item.resolution || '-'}</p>
                  </article>
                ))}
              </div>
            </div>
          </details>
        </section>
      )}
    </main>
  )
}

function SummaryItem({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{display(value)}</strong>
    </div>
  )
}

function Info({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="info-line">
      <span>{label}</span>
      <strong>{display(value)}</strong>
    </div>
  )
}

function ImageCard({ analysis }: { analysis: ImageAnalysis }) {
  return (
    <div className="image-card">
      <div className="image-card-title">
        <Camera size={16} />
        图片凭证分析
      </div>
      <p>{analysis.product_condition}</p>
      <div className="image-tags">
        <span>{analysis.severity || '中等'}</span>
        <span>{analysis.evidence_valid ? '凭证有效' : '需补充图片'}</span>
      </div>
      {analysis.damage_details?.length > 0 && <small>{analysis.damage_details.join('、')}</small>}
    </div>
  )
}

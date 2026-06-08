import { useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import {
  Bell,
  Bot,
  Check,
  ClipboardList,
  Copy,
  Headphones,
  HelpCircle,
  Home,
  ImagePlus,
  Loader2,
  MessageSquare,
  Package,
  RefreshCw,
  Search,
  Send,
  ShoppingBag,
  Star,
  Truck,
  Undo2,
  UserRound,
  X
} from 'lucide-react'
import { postChat } from './api'

type ImageAnalysis = {
  product_condition: string
  damage_details: string[]
  severity: string
  evidence_valid: boolean
  evidence_description?: string
  suggested_action?: string
}

type Trace = {
  tool_name: string
  label?: string
  status: string
  elapsed_ms: number
  summary?: string
}

type ChatResult = {
  answer: string
  decision: Record<string, any>
  order?: Record<string, any>
  user_profile?: Record<string, any>
  traces: Trace[]
  llm_used: boolean
  llm_provider?: string | null
  image_analysis?: ImageAnalysis | null
}

type ChatMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  time: string
  imageUrl?: string
  imageName?: string
}

const MAX_IMAGE_SIZE = 5 * 1024 * 1024
const DEFAULT_ORDER = '3000029'
const DEFAULT_TEXT = '我收到的商品有破损，想申请退款怎么办？'

const quickActions = [
  { label: '申请退款', icon: Undo2, text: '我想申请退款，请帮我判断能否通过。' },
  { label: '申请换货', icon: RefreshCw, text: '我想申请换货，请帮我看一下流程。' },
  { label: '联系人工客服', icon: Headphones, text: '请帮我转人工客服处理。' }
]

const navItems = [
  { label: '首页', icon: Home },
  { label: '售后咨询', icon: MessageSquare, active: true },
  { label: '我的订单', icon: ClipboardList },
  { label: '退款/退货', icon: Undo2 },
  { label: '物流查询', icon: Truck },
  { label: '帮助中心', icon: HelpCircle }
]

function createSessionId() {
  const existing = window.localStorage.getItem('shopcare_session_id')
  if (existing) return existing
  const next = `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
  window.localStorage.setItem('shopcare_session_id', next)
  return next
}

function now() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function cleanText(text = '') {
  return text.replace(/\*\*/g, '').trim()
}

function money(value: unknown) {
  const num = Number(value)
  return Number.isFinite(num) ? `¥${num.toFixed(2)}` : '-'
}

function statusText(status?: string) {
  const map: Record<string, string> = {
    approved: '已通过',
    rejected: '暂不通过',
    need_info: '补充资料',
    escalated: '人工复核'
  }
  return map[status || ''] || '待提交'
}

function resolutionText(value?: string) {
  const map: Record<string, string> = {
    refund_only: '仅退款',
    return_refund: '退货退款',
    exchange: '换货',
    manual_review: '人工复核',
    reship: '补发',
    need_order_id: '补充订单'
  }
  return map[value || ''] || '-'
}

export default function App() {
  const [sessionId] = useState(createSessionId)
  const [orderId, setOrderId] = useState(DEFAULT_ORDER)
  const [input, setInput] = useState(DEFAULT_TEXT)
  const [result, setResult] = useState<ChatResult | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome-1',
      role: 'assistant',
      content: '您好，我是安心购智能售后助手。请描述商品问题，我会结合订单、售后政策和图片凭证帮您判断处理方式。',
      time: '10:21'
    },
    {
      id: 'welcome-2',
      role: 'assistant',
      content: '如果商品有破损、漏发、质量异常，可以直接上传照片。我会记住本轮对话的上下文，后续问题可以继续追问。',
      time: '10:21'
    }
  ])
  const [image, setImage] = useState<File | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement | null>(null)
  const chatEndRef = useRef<HTMLDivElement | null>(null)

  const order = result?.order
  const decision = result?.decision || {}
  const answerSource = result?.llm_provider === 'kimi' ? 'Kimi 图片模型' : result?.llm_provider === 'deepseek' ? 'DeepSeek 文本模型' : '规则引擎'

  const productName = order?.product_name || 'Daily Fresh Snack Box'
  const orderAmount = money(order?.amount ?? 159.8)
  const orderStatus = decision.status ? statusText(String(decision.status)) : '已签收'
  const refundAmount = money(decision.refund_amount ?? order?.amount ?? 159.8)

  const progressSteps = useMemo(() => {
    const status = String(decision.status || '')
    const active = status === 'approved' ? 2 : status === 'need_info' || status === 'escalated' ? 1 : 0
    return [
      { label: '提交申请', done: true, sub: '当前会话' },
      { label: '商家审核', done: active >= 1, active: active === 1, sub: active >= 1 ? '进行中' : '' },
      { label: '退款中', done: active >= 2, sub: active >= 2 ? '处理中' : '' },
      { label: '退款完成', done: false, sub: '' }
    ]
  }, [decision.status])

  function acceptFile(file?: File | null) {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('请上传图片格式的凭证。')
      return
    }
    if (file.size > MAX_IMAGE_SIZE) {
      setError('图片不能超过 5 MB。')
      return
    }
    if (imageUrl) URL.revokeObjectURL(imageUrl)
    setImage(file)
    setImageUrl(URL.createObjectURL(file))
    setError('')
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    acceptFile(event.target.files?.[0])
    event.target.value = ''
  }

  function removeImage() {
    if (imageUrl) URL.revokeObjectURL(imageUrl)
    setImage(null)
    setImageUrl('')
  }

  async function submit(customText?: string) {
    const text = (customText || input).trim()
    const currentOrder = orderId.trim()
    if (!text || !currentOrder) {
      setError('请填写订单号和咨询内容。')
      return
    }

    const userImageUrl = imageUrl
    const userImageName = image?.name
    const userMessage: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      time: now(),
      imageUrl: userImageUrl || undefined,
      imageName: userImageName
    }
    setMessages((items) => [...items, userMessage])
    setInput('')
    setLoading(true)
    setError('')

    window.setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 60)

    try {
      const data = await postChat(text, currentOrder, image, sessionId)
      setResult(data)
      const assistantMessage: ChatMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: cleanText(data.answer),
        time: now()
      }
      setMessages((items) => [...items, assistantMessage])
      removeImage()
      window.setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 80)
    } catch (err) {
      setError(err instanceof Error ? err.message : '服务暂时不可用，请稍后再试。')
    } finally {
      setLoading(false)
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <main className="commerce-app">
      <header className="commerce-header">
        <div className="brand">
          <div className="bag-logo"><ShoppingBag size={28} /></div>
          <div>
            <strong>安心购</strong>
            <span>品质好物 · 售后无忧</span>
          </div>
        </div>
        <label className="search-box">
          <input placeholder="搜索商品、订单、帮助内容" />
          <Search size={22} />
        </label>
        <div className="user-tools">
          <button className="message-button" type="button"><MessageSquare size={18} /> 消息 <b>2</b></button>
          <div className="avatar">张</div>
          <span>张小北</span>
        </div>
      </header>

      <div className="commerce-layout">
        <aside className="left-nav">
          <nav>
            {navItems.map((item) => {
              const Icon = item.icon
              return <button key={item.label} className={item.active ? 'active' : ''} type="button"><Icon size={21} /> {item.label}</button>
            })}
          </nav>
          <section className="assurance-card">
            <div><Star size={18} /> 安心购 · 售后保障</div>
            <p><Check size={15} /> 7天无理由退货</p>
            <p><Check size={15} /> 极速退款</p>
            <p><Check size={15} /> 专业客服团队</p>
            <a>了解更多</a>
          </section>
        </aside>

        <section className="chat-card">
          <div className="chat-header">
            <div className="agent-avatar"><Bot size={34} /></div>
            <div>
              <h1>智能售后助手 <span>AI</span></h1>
              <p>24小时在线 · 专业 · 高效 · 贴心 · {answerSource}</p>
            </div>
            <button className="review-button" type="button"><Star size={17} /> 评价助手</button>
          </div>

          <div className="chat-body">
            {messages.map((item) => (
              <article key={item.id} className={`chat-row ${item.role}`}>
                {item.role === 'assistant' && <div className="mini-bot"><Bot size={18} /></div>}
                <div className="bubble-wrap">
                  <div className="bubble">
                    {item.content.split(/\n+/).map((line, index) => <p key={index}>{line}</p>)}
                  </div>
                  {item.imageUrl && (
                    <div className="sent-images">
                      <span>已上传图片</span>
                      <img src={item.imageUrl} alt={item.imageName || '售后凭证'} />
                    </div>
                  )}
                </div>
                <time>{item.time}</time>
                {item.role === 'user' && <div className="user-avatar">张</div>}
              </article>
            ))}
            {loading && (
              <article className="chat-row assistant">
                <div className="mini-bot"><Bot size={18} /></div>
                <div className="bubble typing"><Loader2 className="spin" size={17} /> 正在结合上下文分析...</div>
              </article>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="quick-actions">
            {quickActions.map((item) => {
              const Icon = item.icon
              return <button key={item.label} type="button" onClick={() => submit(item.text)} disabled={loading}><Icon size={17} /> {item.label}</button>
            })}
          </div>

          <div className="composer">
            <input className="order-input" value={orderId} onChange={(event) => setOrderId(event.target.value)} placeholder="订单号" />
            <input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={onKeyDown} placeholder="请输入您想咨询的问题..." />
            <input ref={fileRef} hidden type="file" accept="image/*" onChange={onFileChange} />
            {imageUrl ? (
              <button className="image-chip" type="button" onClick={removeImage}><X size={15} /> 已选图片</button>
            ) : (
              <button className="icon-button" type="button" onClick={() => fileRef.current?.click()}><ImagePlus size={19} /></button>
            )}
            <button className="send-button" type="button" onClick={() => submit()} disabled={loading}><Send size={20} /></button>
          </div>
          {error && <p className="error-line">{error}</p>}
        </section>

        <aside className="order-panel">
          <div className="panel-head">
            <h2>订单详情</h2>
            <a>查看订单</a>
          </div>
          <div className="order-meta">
            <p><span>订单号：</span>{order?.order_id || orderId}<button type="button"><Copy size={14} /> 复制</button></p>
            <p><span>下单时间：</span>2024-05-20 15:30:45</p>
            <p><span>订单状态：</span><b>{orderStatus}</b></p>
          </div>

          <div className="product-card">
            <div className="product-art"><Package size={42} /></div>
            <div>
              <h3>{productName}</h3>
              <p>{orderAmount}</p>
            </div>
            <span>x1</span>
          </div>

          <div className="progress-card">
            <h3>退款进度</h3>
            <div className="steps">
              {progressSteps.map((step) => (
                <div className={`step ${step.done ? 'done' : ''} ${step.active ? 'current' : ''}`} key={step.label}>
                  <i>{step.done ? <Check size={13} /> : ''}</i>
                  <span>{step.label}</span>
                  <small>{step.sub}</small>
                </div>
              ))}
            </div>
          </div>

          <div className="logistics-card">
            <h3><Truck size={18} /> 物流信息 <b>已签收</b></h3>
            <p>中通快递　77305234123456 <button type="button">复制</button></p>
            <p>签收时间：2024-05-21 14:35:20</p>
            <p>签收人：本人签收</p>
          </div>

          <div className="side-actions">
            <button type="button" onClick={() => submit('我想申请退款，请基于前面的情况继续处理。')}>申请退款</button>
            <button type="button" onClick={() => submit('我想申请换货，请基于前面的情况继续处理。')}>申请换货</button>
            <button type="button" onClick={() => submit('请联系人工客服，并带上前面的售后上下文。')}>联系客服</button>
          </div>
        </aside>
      </div>
    </main>
  )
}

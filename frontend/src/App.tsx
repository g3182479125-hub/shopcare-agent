import { useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import {
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
import { postChat, type ConversationHistoryItem } from './api'

type ImageAnalysis = {
  product_condition: string
  damage_details: string[]
  severity: string
  evidence_valid: boolean
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

type ModalState = {
  title: string
  body: string
}

const MAX_IMAGE_SIZE = 5 * 1024 * 1024
const DEFAULT_ORDER = '3000029'
const DEFAULT_TEXT = '我收到的商品有破损，想申请退款怎么办？'
const STORAGE_KEY = 'shopcare_chat_messages_v2'

const navItems = [
  { label: '首页', icon: Home, action: 'home' },
  { label: '售后咨询', icon: MessageSquare, action: 'support' },
  { label: '我的订单', icon: ClipboardList, action: 'orders' },
  { label: '退款/退货', icon: Undo2, action: 'refunds' },
  { label: '物流查询', icon: Truck, action: 'logistics' },
  { label: '帮助中心', icon: HelpCircle, action: 'help' }
]

const quickActions = [
  { label: '申请退款', icon: Undo2, text: '我想申请退款，请基于前面的售后情况继续处理。' },
  { label: '申请换货', icon: RefreshCw, text: '我想申请换货，请基于前面的售后情况继续处理。' },
  { label: '联系人工客服', icon: Headphones, text: '请联系人工客服，并带上前面的售后上下文。' }
]

const initialMessages: ChatMessage[] = [
  {
    id: 'welcome-1',
    role: 'assistant',
    content: '你好呀，我是安心购的智能售后助手。商品破损、退款、换货、物流异常这些事，都可以先丢给我看。',
    time: '10:21'
  },
  {
    id: 'welcome-2',
    role: 'assistant',
    content: '你不用一次把话说得特别完整，先讲大概情况就行；后面直接问“那能换货吗”“要不要补图”，我会接着前面的上下文继续处理。',
    time: '10:21'
  }
]


function NeoBrutalLoginPage({ onEnter }: { onEnter: () => void }) {
  const features = ['ORDER TOOLS', 'VISION AGENT', 'POLICY RAG', 'HUMAN HANDOFF']

  return (
    <main className="neo-login-page">
      <div className="neo-grid-bg" />
      <div className="neo-noise-bg" />

      <header className="neo-login-nav">
        <button className="neo-logo" type="button" onClick={onEnter}>
          <span>SHOPCARE</span>
          <b>AGENT</b>
        </button>
        <nav className="neo-links" aria-label="Login navigation">
          <button type="button">DEMO</button>
          <button type="button">TOOLS</button>
          <button type="button">CASES</button>
        </nav>
        <button className="neo-small-cta" type="button" onClick={onEnter}>ENTER APP</button>
      </header>

      <section className="neo-hero">
        <div className="neo-hero-copy">
          <div className="neo-sticker neo-sticker-red">AFTER-SALES OS</div>
          <h1>
            MAKE REFUNDS
            <span>LOUDER.</span>
          </h1>
          <p>
            一个电商售后智能体项目：订单查询、用户画像、政策检索、图片凭证和决策轨迹，
            全部放进一个能直接演示的 Agent 工作台。
          </p>
          <div className="neo-hero-actions">
            <button className="neo-primary-btn" type="button" onClick={onEnter}>开始使用</button>
            <button className="neo-secondary-btn" type="button" onClick={onEnter}>查看 Demo</button>
          </div>
        </div>

        <aside className="neo-login-card" aria-label="Login preview">
          <div className="neo-card-badge">LIVE</div>
          <h2>登录入口</h2>
          <label>
            <span>账号</span>
            <input value="intern-demo@shopcare.ai" readOnly />
          </label>
          <label>
            <span>项目</span>
            <input value="ShopCare Agent" readOnly />
          </label>
          <button className="neo-card-submit" type="button" onClick={onEnter}>
            进入售后工作台
          </button>
          <div className="neo-feature-list">
            {features.map((item) => <span key={item}>{item}</span>)}
          </div>
        </aside>

        <div className="neo-shape neo-shape-yellow">AI</div>
        <div className="neo-shape neo-shape-violet">RAG</div>
        <div className="neo-shape neo-shape-red">KIMI</div>
      </section>
    </main>
  )
}

function createSessionId() {
  const existing = window.localStorage.getItem('shopcare_session_id')
  if (existing) return existing
  const next = `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
  window.localStorage.setItem('shopcare_session_id', next)
  return next
}

function loadMessages() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return initialMessages
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) && parsed.length ? parsed : initialMessages
  } catch {
    return initialMessages
  }
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
  return map[status || ''] || '已签收'
}

function historyFromMessages(items: ChatMessage[]): ConversationHistoryItem[] {
  return items
    .filter((item) => item.content && !item.id.startsWith('welcome'))
    .slice(-12)
    .map((item) => ({ role: item.role, content: item.content }))
}

export default function App() {
  const [showLogin, setShowLogin] = useState(true)
  const [sessionId] = useState(createSessionId)
  const [activeNav, setActiveNav] = useState('support')
  const [orderId, setOrderId] = useState(DEFAULT_ORDER)
  const [input, setInput] = useState(DEFAULT_TEXT)
  const [result, setResult] = useState<ChatResult | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages)
  const [image, setImage] = useState<File | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [modal, setModal] = useState<ModalState | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const chatEndRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-40)))
  }, [messages])

  const order = result?.order
  const decision = result?.decision || {}
  const answerSource = result?.llm_provider === 'kimi' ? 'Kimi 图片模型' : result?.llm_provider === 'deepseek' ? 'DeepSeek 文本模型' : '规则引擎'

  const productName = order?.product_name || 'Daily Fresh Snack Box'
  const orderAmount = money(order?.amount ?? 159.8)
  const orderStatus = decision.status ? statusText(String(decision.status)) : '已签收'

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

  function notify(text: string) {
    setToast(text)
    window.setTimeout(() => setToast(''), 1800)
  }

  function openNav(action: string) {
    setActiveNav(action)
    const copy: Record<string, ModalState> = {
      home: { title: '首页', body: '这里展示售后首页概览。当前演示聚焦智能售后咨询，你可以从左侧随时回到咨询页。' },
      support: { title: '售后咨询', body: '当前页面就是可多轮追问的智能售后咨询窗口。' },
      orders: { title: '我的订单', body: `当前演示订单为 ${order?.order_id || orderId}，商品为 ${productName}，金额 ${orderAmount}。` },
      refunds: { title: '退款/退货', body: `当前售后状态：${orderStatus}。你可以点击右侧“申请退款”或“申请换货”继续办理。` },
      logistics: { title: '物流查询', body: '中通快递 77305234123456，签收时间：2024-05-21 14:35:20，签收人：本人签收。' },
      help: { title: '帮助中心', body: '支持咨询退款、退货、换货、补发、物流异常和人工客服。系统会记住当前会话上下文。' }
    }
    setModal(copy[action])
  }

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
    notify('图片已添加')
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

    const userMessage: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      time: now(),
      imageUrl: imageUrl || undefined,
      imageName: image?.name
    }
    const history = historyFromMessages(messages)
    setMessages((items) => [...items, userMessage])
    setInput('')
    setLoading(true)
    setError('')
    window.setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 60)

    try {
      const data = await postChat(text, currentOrder, image, sessionId, history)
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

  async function copyText(text: string, label = '已复制') {
    try {
      await navigator.clipboard.writeText(text)
      notify(label)
    } catch {
      notify('复制失败，请手动复制')
    }
  }

  function clearChat() {
    setMessages(initialMessages)
    setResult(null)
    window.localStorage.removeItem(STORAGE_KEY)
    notify('会话已清空')
  }

  if (showLogin) {
    return <NeoBrutalLoginPage onEnter={() => setShowLogin(false)} />
  }

  return (
    <main className="commerce-app">
      <header className="commerce-header">
        <button className="brand" type="button" onClick={() => openNav('home')}>
          <div className="bag-logo"><ShoppingBag size={28} /></div>
          <div>
            <strong>安心购</strong>
            <span>品质好物 · 售后无忧</span>
          </div>
        </button>
        <label className="search-box">
          <input placeholder="搜索商品、订单、帮助内容" onKeyDown={(event) => {
            if (event.key === 'Enter') setModal({ title: '搜索结果', body: `已搜索：${event.currentTarget.value || '售后帮助'}。当前演示会把搜索结果接入售后助手。` })
          }} />
          <Search size={22} />
        </label>
        <div className="user-tools">
          <button className="message-button" type="button" onClick={() => setModal({ title: '消息中心', body: '你有 2 条售后提醒：退款申请待补充凭证、物流签收已完成。' })}><MessageSquare size={18} /> 消息 <b>2</b></button>
          <button className="avatar-button" type="button" onClick={() => setModal({ title: '个人中心', body: `用户：张小北。当前会话 ID：${sessionId}` })}><div className="avatar">张</div><span>张小北</span></button>
        </div>
      </header>

      <div className="commerce-layout">
        <aside className="left-nav">
          <nav>
            {navItems.map((item) => {
              const Icon = item.icon
              return <button key={item.label} className={activeNav === item.action ? 'active' : ''} type="button" onClick={() => openNav(item.action)}><Icon size={21} /> {item.label}</button>
            })}
          </nav>
          <section className="assurance-card">
            <button type="button" onClick={() => setModal({ title: '售后保障', body: '安心购支持 7 天无理由退货、极速退款、专业客服团队。食品生鲜类按平台食品安全售后策略处理。' })}><Star size={18} /> 安心购 · 售后保障</button>
            <p><Check size={15} /> 7天无理由退货</p>
            <p><Check size={15} /> 极速退款</p>
            <p><Check size={15} /> 专业客服团队</p>
            <a onClick={() => openNav('help')}>了解更多</a>
          </section>
        </aside>

        <section className="chat-card">
          <div className="chat-header">
            <div className="agent-avatar"><Bot size={34} /></div>
            <div>
              <h1>智能售后助手 <span>AI</span></h1>
              <p>24小时在线 · 专业 · 高效 · 贴心 · {answerSource}</p>
            </div>
            <button className="review-button" type="button" onClick={() => setModal({ title: '评价助手', body: '感谢评价。当前演示版本已记录你的反馈入口，后续可以接入评分接口。' })}><Star size={17} /> 评价助手</button>
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
            <button type="button" onClick={clearChat}><X size={17} /> 清空会话</button>
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
            <button type="button" onClick={() => openNav('orders')}>查看订单</button>
          </div>
          <div className="order-meta">
            <p><span>订单号：</span>{order?.order_id || orderId}<button type="button" onClick={() => copyText(order?.order_id || orderId, '订单号已复制')}><Copy size={14} /> 复制</button></p>
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
                <button className={`step ${step.done ? 'done' : ''} ${step.active ? 'current' : ''}`} key={step.label} type="button" onClick={() => setModal({ title: step.label, body: step.sub || '等待售后流程推进。' })}>
                  <i>{step.done ? <Check size={13} /> : ''}</i>
                  <span>{step.label}</span>
                  <small>{step.sub}</small>
                </button>
              ))}
            </div>
          </div>

          <div className="logistics-card">
            <h3><Truck size={18} /> 物流信息 <b>已签收</b></h3>
            <p>中通快递　77305234123456 <button type="button" onClick={() => copyText('77305234123456', '物流单号已复制')}>复制</button></p>
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

      {toast && <div className="toast">{toast}</div>}
      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <section className="modal-card" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" type="button" onClick={() => setModal(null)}><X size={18} /></button>
            <h2>{modal.title}</h2>
            <p>{modal.body}</p>
          </section>
        </div>
      )}
    </main>
  )
}

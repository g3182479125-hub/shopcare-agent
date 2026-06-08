const API_BASE = import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? 'https://shopcare-agent-api.vercel.app' : 'http://localhost:8000')

type DemoOrder = Record<string, any>
type DemoUser = Record<string, any>

const demoOrders: Record<string, DemoOrder> = {
  '3000010': {
    order_id: '3000010',
    user_id: 'USER10001',
    product_name: 'Nova X1 Smartphone',
    brand: 'NovaTech',
    category: '3C电子',
    order_status: 'PendingShipment',
    amount: 3999,
    fulfillment_time: 2,
    payment_method: 'Alipay'
  },
  '3000012': {
    order_id: '3000012',
    user_id: 'USER10002',
    product_name: 'Apple MacBook Pro',
    brand: 'Apple',
    category: '3C电子',
    order_status: 'Delivered',
    amount: 13284.99,
    fulfillment_time: 54,
    payment_method: 'CreditCard'
  },
  '3000025': {
    order_id: '3000025',
    user_id: 'USER10003',
    product_name: 'Aster S Pro',
    brand: 'Aster',
    category: '3C电子',
    order_status: 'Delivered',
    amount: 5499,
    fulfillment_time: 36,
    payment_method: 'WeChatPay'
  },
  '3000029': {
    order_id: '3000029',
    user_id: 'USER10004',
    product_name: 'Daily Fresh Snack Box',
    brand: 'DailyFresh',
    category: '食品饮料',
    order_status: 'Delivered',
    amount: 159.8,
    fulfillment_time: 28,
    payment_method: 'Alipay'
  }
}

const demoUsers: Record<string, DemoUser> = {
  USER10001: { user_id: 'USER10001', user_tier: 'HighValue', total_purchase_times: 12, total_purchase_amount: 25880 },
  USER10002: { user_id: 'USER10002', user_tier: 'HighValue', total_purchase_times: 5, total_purchase_amount: 21621.28 },
  USER10003: { user_id: 'USER10003', user_tier: 'VIP', total_purchase_times: 28, total_purchase_amount: 58420.6 },
  USER10004: { user_id: 'USER10004', user_tier: 'Normal', total_purchase_times: 3, total_purchase_amount: 486.5 }
}

const policyEvidence = [
  { title: '未发货取消退款', content: '订单未发货时，可自动取消并按原支付渠道退款。' },
  { title: '3C电子质量问题', content: '3C电子商品出现功能异常时，需要用户补充照片、视频或检测凭证，优先人工复核。' },
  { title: '食品包装破损', content: '食品饮料类如包装破损、漏液或影响食用安全，可凭图片申请仅退款或补偿。' }
]

const similarCases = [
  { case_id: 'CASE-DEMO-001', reason_code: 'cancel_before_ship', user_description: '订单尚未发货，希望取消并退款', resolution: 'refund_only' },
  { case_id: 'CASE-DEMO-002', reason_code: 'quality_issue', user_description: '电脑功能异常，无法正常使用', resolution: 'manual_review' },
  { case_id: 'CASE-DEMO-003', reason_code: 'quality_issue', user_description: '手机开机异常，希望换货', resolution: 'exchange_or_refund' },
  { case_id: 'CASE-DEMO-004', reason_code: 'damaged_package', user_description: '食品包装破损，希望仅退款', resolution: 'refund_only' }
]

function demoImageAnalysis(image?: File) {
  if (!image) return null
  return {
    product_condition: '已收到一张售后凭证图片，公网静态兜底模式无法真实识别图片内容。',
    damage_details: ['等待后端视觉模型分析'],
    severity: '中等',
    evidence_valid: true,
    evidence_description: '图片已上传，可作为售后凭证候选材料。',
    suggested_action: '接入 Kimi API 后由视觉 Agent 给出正式判断。'
  }
}

function demoDecision(message: string, order: DemoOrder, hasImage: boolean) {
  const text = message.toLowerCase()
  if (order.order_status === 'PendingShipment' || text.includes('取消')) {
    return {
      status: 'approved',
      resolution: 'refund_only',
      priority: 'P2',
      need_human_review: false,
      refund_amount: order.amount,
      compensation_amount: 0,
      reason: '订单尚未发货，符合自动取消并原路退款规则。',
      next_steps: ['确认取消订单', '退款将按原支付渠道退回']
    }
  }
  if (order.category === '食品饮料' || text.includes('包装')) {
    return {
      status: 'approved',
      resolution: 'refund_only',
      priority: 'P2',
      need_human_review: false,
      refund_amount: order.amount,
      compensation_amount: hasImage ? 10 : 0,
      reason: hasImage ? '已上传图片凭证，食品包装破损可走仅退款并补偿。' : '食品包装破损属于安全敏感场景，可凭图片走仅退款并补偿。',
      next_steps: ['上传或保留包装破损照片', '系统核验后退款并发放补偿券']
    }
  }
  return {
    status: 'need_info',
    resolution: 'manual_review',
    priority: order.amount > 5000 ? 'P1' : 'P2',
    need_human_review: true,
    refund_amount: 0,
    compensation_amount: 0,
    reason: hasImage ? '已收到图片凭证，3C电子商品仍需结合凭证由客服复核。' : '3C电子商品功能异常需要补充凭证，人工核验后处理。',
    next_steps: ['上传商品问题照片或检测视频', '客服核验后给出换货、退货或维修方案']
  }
}

function demoChat(message: string, orderId?: string, image?: File) {
  const normalizedOrderId = orderId && demoOrders[orderId] ? orderId : '3000012'
  const order = demoOrders[normalizedOrderId]
  const user = demoUsers[order.user_id]
  const imageAnalysis = demoImageAnalysis(image)
  const decision = demoDecision(message, order, Boolean(image))
  const answer = [
    `订单 ${order.order_id} 当前状态为 ${order.order_status}，商品为 ${order.product_name}，类目 ${order.category}，金额 ${order.amount} 元。`,
    `用户等级为 ${user.user_tier}，历史购买 ${user.total_purchase_times} 次，累计消费 ${user.total_purchase_amount} 元。`,
    imageAnalysis ? `图片凭证：${imageAnalysis.product_condition}` : '',
    `建议处理：${decision.resolution}，当前判断为 ${decision.status}。原因：${decision.reason}`,
    `下一步：${decision.next_steps.join('；')}。`,
    '',
    '当前为静态兜底回答；公网后端可用时会自动切换为真实 API + LLM 回答。'
  ].filter(Boolean).join('\n')

  const traces = [
    ...(imageAnalysis ? [{ tool_name: 'ImageAnalysisAgent', label: 'Kimi 视觉Agent', input: { file_name: image?.name }, output: imageAnalysis, status: 'ok', elapsed_ms: 1, summary: imageAnalysis.product_condition.slice(0, 30) }] : []),
    { tool_name: 'OrderTool', input: { order_id: normalizedOrderId }, output: order, status: 'ok', elapsed_ms: 1 },
    { tool_name: 'UserTool', input: { user_id: order.user_id }, output: user, status: 'ok', elapsed_ms: 1 },
    { tool_name: 'PolicyRAGTool', input: { query: message }, output: policyEvidence, status: 'ok', elapsed_ms: 2 },
    { tool_name: 'CaseTool', input: { query: message }, output: similarCases, status: 'ok', elapsed_ms: 2 },
    { tool_name: 'DecisionTool', input: { message }, output: decision, status: 'ok', elapsed_ms: 1 }
  ]

  return {
    answer,
    intent: 'general_after_sales',
    decision,
    order,
    user_profile: user,
    similar_cases: similarCases,
    policy_evidence: policyEvidence,
    traces,
    llm_used: false,
    image_analysis: imageAnalysis
  }
}

function demoSummary() {
  return {
    orders: {
      count: 382287,
      amount_sum: 0,
      status_top: [
        { name: 'Delivered', value: 3 },
        { name: 'PendingShipment', value: 1 }
      ],
      category_top: [
        { name: '3C电子', value: 3 },
        { name: '食品饮料', value: 1 }
      ]
    },
    users: {
      count: 98673,
      tier_top: [
        { name: 'HighValue', value: 2 },
        { name: 'VIP', value: 1 },
        { name: 'Normal', value: 1 }
      ]
    },
    aftersales: {
      count: 39952,
      status_top: [
        { name: 'resolved', value: 2 },
        { name: 'processing', value: 1 },
        { name: 'escalated', value: 1 }
      ],
      reason_top: [
        { name: 'quality_issue', value: 2 },
        { name: 'cancel_before_ship', value: 1 },
        { name: 'damaged_package', value: 1 }
      ],
      priority_top: [
        { name: 'P1', value: 2 },
        { name: 'P2', value: 2 }
      ],
      refund_sum: 44792000
    }
  }
}

export async function postChat(message: string, orderId?: string, image?: File | null) {
  try {
    const init: RequestInit = { method: 'POST' }
    if (image) {
      const formData = new FormData()
      formData.append('message', message)
      if (orderId) formData.append('order_id', orderId)
      formData.append('image', image)
      init.body = formData
    } else {
      init.headers = { 'Content-Type': 'application/json' }
      init.body = JSON.stringify({ message, order_id: orderId || undefined })
    }
    const res = await fetch(`${API_BASE}/api/agent/chat`, init)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  } catch {
    return demoChat(message, orderId, image || undefined)
  }
}

export async function getSummary() {
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/summary`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  } catch {
    return demoSummary()
  }
}

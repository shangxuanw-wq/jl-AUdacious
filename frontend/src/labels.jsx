export const RFQ_STATUS = {
  received: ['待報價', 'bg-sky-50 text-sky-700 ring-sky-200'],
  quoting: ['報價中', 'bg-amber-50 text-amber-700 ring-amber-200'],
  quoted: ['已報價', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  closed: ['已結案', 'bg-stone-100 text-stone-600 ring-stone-200'],
}

export const QUOTE_STATUS = {
  draft: ['草稿', 'bg-stone-100 text-stone-700 ring-stone-200'],
  sending: ['送出中', 'bg-amber-50 text-amber-700 ring-amber-200'],
  sent: ['已送出', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  failed: ['送出失敗', 'bg-red-50 text-red-700 ring-red-200'],
  superseded: ['已被新版取代', 'bg-stone-100 text-stone-500 ring-stone-200'],
}

export const DISPATCH_STATUS = {
  pending: ['排隊中', 'bg-stone-100 text-stone-700 ring-stone-200'],
  sending: ['送出中', 'bg-amber-50 text-amber-700 ring-amber-200'],
  retry_wait: ['等待重送', 'bg-amber-50 text-amber-700 ring-amber-200'],
  accepted: ['對方已收（待審）', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  duplicate: ['對方已收（重送）', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  published: ['對方已發布', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  rejected: ['被拒收', 'bg-red-50 text-red-700 ring-red-200'],
  not_found: ['對方找不到詢價編號', 'bg-red-50 text-red-700 ring-red-200'],
  conflict: ['狀態衝突', 'bg-red-50 text-red-700 ring-red-200'],
  gave_up: ['已放棄（重送 5 次）', 'bg-red-50 text-red-700 ring-red-200'],
  blocked: ['已擋下（正式站）', 'bg-red-50 text-red-700 ring-red-200'],
}

export const CANDIDATE_STATUS = {
  pending: ['待審', 'bg-amber-50 text-amber-700 ring-amber-200'],
  published: ['已發布', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  superseded: ['已取代', 'bg-stone-100 text-stone-500 ring-stone-200'],
  rejected: ['已退回', 'bg-red-50 text-red-700 ring-red-200'],
}

export const ISSUE_TEXT = {
  quantity_mismatch: '數量跟詢價不同',
  unit_mismatch: '單位跟詢價不同',
  item_mismatch: '品名或材質跟詢價信不同',
  amount_mismatch: '小計對不上 單價 × 數量',
  total_mismatch: '合計跟小計對不上',
  tax_unknown: '沒說含不含稅',
  expired: '有效期已過',
  promised_in_past: '承諾交貨日已過',
  older_revision: '修訂版次比已發布的舊',
  revision_unknown: '比不出修訂版次新舊',
  revision_reused: '同一個版次換了數字',
  event_conflict: '同一個 event_id 送過不同內容',
  event_in_flight: '同一個 event_id 正在處理',
  send_pending: '對方寄送結果確認中',
  closed: '對方詢價單已結案',
  status: '對方詢價單還沒寄出',
  no_snapshot: '對方沒有寄出紀錄',
  partner_prod_blocked: '防呆：沒開放打澳得仕正式站',
  timeout: '逾時',
  rate_limited: '太頻繁（429）',
  not_found: '對方找不到詢價編號',
  invalid_number: '數字格式錯',
  rfq_invalid: '詢價編號格式錯',
}

export const issueText = (code) => ISSUE_TEXT[code] || code

export function Badge({ map, value }) {
  const [text, cls] = map[value] || [value, 'bg-stone-100 text-stone-700 ring-stone-200']
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}>{text}</span>
}

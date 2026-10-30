export const RFQ_STATUS = {
  received: ['待報價', 'chip-mute'],
  quoting: ['報價中', 'chip-hot'],
  quoted: ['已報價', 'chip-hot'],
  closed: ['已結案', 'chip-mute'],
}

export const QUOTE_STATUS = {
  draft: ['草稿', 'chip-mute'],
  sending: ['送出中', 'chip-hot'],
  sent: ['已送出', 'chip-hot'],
  failed: ['送出失敗', 'chip-bad'],
  superseded: ['已被新版取代', 'chip-mute'],
}

export const DISPATCH_STATUS = {
  pending: ['排隊中', 'chip-mute'],
  sending: ['送出中', 'chip-hot'],
  retry_wait: ['等待重送', 'chip-hot'],
  accepted: ['對方已收（待審）', 'chip-hot'],
  duplicate: ['對方已收（重送）', 'chip-hot'],
  published: ['對方已發布', 'chip-hot'],
  rejected: ['被拒收', 'chip-bad'],
  not_found: ['對方找不到詢價編號', 'chip-bad'],
  conflict: ['狀態衝突', 'chip-bad'],
  gave_up: ['已放棄（共試 7 次，轉人工）', 'chip-bad'],
  blocked: ['已擋下（正式站）', 'chip-bad'],
}

export const CANDIDATE_STATUS = {
  pending: ['待審', 'chip-hot'],
  published: ['已發布', 'chip-hot'],
  superseded: ['已取代', 'chip-mute'],
  rejected: ['已退回', 'chip-bad'],
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
  partner_prod_blocked: '防呆：沒開放送正式站',
  timeout: '逾時',
  rate_limited: '太頻繁（429）',
  not_found: '對方找不到詢價編號',
  invalid_number: '數字格式錯',
  rfq_invalid: '詢價編號格式錯',
  too_long: '欄位太長（對方整筆拒收）',
  rfq_revision_unknown: '規格版次不是對方寄出過的',
  not_test_rfq: '不是測試單（自我測試只能打測試單）',
  spec_unbound: '沒帶規格版次，對方要人工指定',
  spec_outdated: '報價對應的規格版次比目前舊',
  endpoint_disabled: '對方端點還沒啟用（503 disabled，不重送）',
  maintenance: '對方維修中（503，稍後重送）',
  invalid_integer: '整數格式錯',
  event_id_mismatch: '標頭與內容的 event_id 不一致',
}

export const MAIL_STATUS = {
  pending: ['寄送中', 'chip-hot'],
  sent: ['已寄出', 'chip-hot'],
  failed: ['寄送失敗', 'chip-bad'],
}

export const issueText = (code) => ISSUE_TEXT[code] || code

export function Badge({ map, value }) {
  const [text, cls] = map[value] || [value, 'chip-mute']
  return <span className={cls}>{text}</span>
}

const clock = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})
export function formatTime(value?: string | number | null) {
  if (value == null || value === '') return '未记录'
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? clock.format(date) : '时间未知'
}

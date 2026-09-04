const koreanDate = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

const koreanDateTime = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : koreanDate.format(date)
}

export function formatDateTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : koreanDateTime.format(date)
}

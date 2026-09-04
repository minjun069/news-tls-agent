export interface ServerSentEvent {
  event: string
  data: string
}

function parseBlock(block: string): ServerSentEvent | null {
  let event = 'message'
  const data: string[] = []

  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    let value = separator === -1 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }

  return data.length > 0 ? { event, data: data.join('\n') } : null
}

export async function consumeEventStream(
  response: Response,
  onEvent: (event: ServerSentEvent) => void,
): Promise<void> {
  if (!response.body) throw new Error('스트리밍 응답 본문이 없습니다.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatchCompleteBlocks = () => {
    let boundary = buffer.match(/\r?\n\r?\n/)
    while (boundary?.index !== undefined) {
      const block = buffer.slice(0, boundary.index)
      buffer = buffer.slice(boundary.index + boundary[0].length)
      const event = parseBlock(block)
      if (event) onEvent(event)
      boundary = buffer.match(/\r?\n\r?\n/)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    dispatchCompleteBlocks()
  }

  buffer += decoder.decode()
  dispatchCompleteBlocks()
  const finalEvent = parseBlock(buffer)
  if (finalEvent) onEvent(finalEvent)
}

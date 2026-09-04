import { consumeEventStream } from './sse'
import type {
  Article,
  ChatDoneEvent,
  ChatHistoryItem,
  ChatTokenEvent,
  ChatToolEvent,
  ClarificationEvent,
  GenerationDone,
  GenerationRequest,
  GenerationStage,
  IssueDetail,
  IssueSummary,
  StreamError,
} from './types'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const API_BASE_URL = (configuredBaseUrl || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json()
    if (isRecord(payload) && typeof payload.detail === 'string') return payload.detail
    if (isRecord(payload) && typeof payload.message === 'string') return payload.message
  } catch {
    // JSON이 아닌 오류 응답은 상태 코드 기반 문구를 사용한다.
  }
  return `요청에 실패했습니다. (HTTP ${response.status})`
}

async function requestJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status)
  return (await response.json()) as T
}

async function postEventStream(
  path: string,
  body: unknown,
  onEvent: (event: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status)

  await consumeEventStream(response, ({ event, data }) => {
    let payload: unknown
    try {
      payload = JSON.parse(data)
    } catch {
      throw new ApiError('서버의 스트리밍 응답을 해석하지 못했습니다.', 502)
    }
    if (!isRecord(payload)) throw new ApiError('서버 응답 형식이 올바르지 않습니다.', 502)
    onEvent(event, payload)
  })
}

export async function listIssues(signal?: AbortSignal): Promise<IssueSummary[]> {
  const payload = await requestJson<{ issues: IssueSummary[] }>('/issues', signal)
  return payload.issues
}

export function getIssue(issueId: number, signal?: AbortSignal): Promise<IssueDetail> {
  return requestJson<IssueDetail>(`/issues/${issueId}`, signal)
}

export function getArticle(articleId: number, signal?: AbortSignal): Promise<Article> {
  return requestJson<Article>(`/articles/${articleId}`, signal)
}

interface GenerationHandlers {
  stage: (payload: GenerationStage) => void
  clarify: (payload: ClarificationEvent) => void
  done: (payload: GenerationDone) => void
  error: (payload: StreamError) => void
}

export function createIssue(
  request: GenerationRequest,
  handlers: GenerationHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return postEventStream(
    '/issues',
    request,
    (event, payload) => {
      if (event === 'stage') handlers.stage(payload as unknown as GenerationStage)
      if (event === 'clarify') handlers.clarify(payload as unknown as ClarificationEvent)
      if (event === 'done') handlers.done(payload as unknown as GenerationDone)
      if (event === 'error') handlers.error(payload as unknown as StreamError)
    },
    signal,
  )
}

interface ChatHandlers {
  tool: (payload: ChatToolEvent) => void
  token: (payload: ChatTokenEvent) => void
  done: (payload: ChatDoneEvent) => void
  error: (payload: StreamError) => void
}

export function chatWithIssue(
  issueId: number,
  message: string,
  history: ChatHistoryItem[],
  handlers: ChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return postEventStream(
    `/issues/${issueId}/chat`,
    { message, history },
    (event, payload) => {
      if (event === 'tool') handlers.tool(payload as unknown as ChatToolEvent)
      if (event === 'token') handlers.token(payload as unknown as ChatTokenEvent)
      if (event === 'done') handlers.done(payload as unknown as ChatDoneEvent)
      if (event === 'error') handlers.error(payload as unknown as StreamError)
    },
    signal,
  )
}

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

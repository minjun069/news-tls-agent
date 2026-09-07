export interface IssueSummary {
  issue_id: number
  topic: string
  title: string
  generated_at: string
  event_count: number
}

export interface EventArticle {
  article_id: number
  title: string
  service_date: string
  relevance_score: number | null
}

export interface PrimaryArticle {
  article_id: number
  title: string
  service_date: string
}

export interface TimelineEvent {
  event_order: number
  event_date: string
  title: string
  summary: string
  primary_article: PrimaryArticle
  articles: EventArticle[]
}

export interface IssueDetail {
  issue_id: number
  topic: string
  title: string
  summary: string
  generated_at: string
  events: TimelineEvent[]
}

export interface Article {
  article_id: number
  title: string
  sub_title: string
  service_date: string
  summary: string
  content: string
  url: string
  truncated: boolean
}

export interface GenerationRequest {
  topic: string
  clarification: string | null
  clarification_count: number
}

export interface GenerationStage {
  stage: string
  message: string
  round?: number
  found?: number
  selected?: number
}

export interface ClarificationEvent {
  question: string
  attempt: number
}

export interface GenerationDone {
  issue_id: number
  termination: string | null
}

export interface StreamError {
  reason: string
  message: string
  retryable: boolean
}

export interface ChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export type ChatSource = 'article' | 'general'

export interface ChatToolEvent {
  name: string
  label: string
}

export interface ChatTokenEvent {
  text: string
  source: ChatSource
}

export interface ExportResult {
  format: 'pdf' | 'notion'
  file_name?: string
  download_url?: string
  page_id?: string
  url?: string
}

export interface ChatDoneEvent {
  article_ids: number[]
  exports: ExportResult[]
}

export interface ExportRequest {
  format: 'pdf' | 'notion'
  parent_page_id?: string
}

export interface GraphNode {
  id: number
  name: string
  type: string
}

export interface GraphEdge {
  id: number
  source: number
  target: number
  type: string
}

export interface ArticleGraph {
  article_id: number
  article_title: string
  article_service_date: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface GraphStageEvent {
  stage: 'extracting'
  remaining: number
}

export interface GraphDoneEvent {
  graphs: ArticleGraph[]
}

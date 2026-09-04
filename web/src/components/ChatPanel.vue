<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { chatWithIssue, resolveApiUrl } from '../api/client'
import type {
  ChatHistoryItem,
  ChatSource,
  ExportResult,
  StreamError,
} from '../api/types'

const props = defineProps<{ issueId: number }>()

const emit = defineEmits<{
  openArticle: [articleId: number]
}>()

interface ChatSegment {
  source: ChatSource
  text: string
}

interface ConversationItem {
  id: number
  role: 'user' | 'assistant'
  content?: string
  segments?: ChatSegment[]
  articleIds?: number[]
  exports?: ExportResult[]
  error?: string
}

const input = ref('')
const pending = ref(false)
const toolLabel = ref('')
const waiting = ref(false)
const history = ref<ChatHistoryItem[]>([])
const messages = ref<ConversationItem[]>([])
let nextMessageId = 1
let waitTimer: ReturnType<typeof setTimeout> | undefined

const canSend = computed(() => input.value.trim().length > 0 && !pending.value)

function clearWaitTimer() {
  if (waitTimer) clearTimeout(waitTimer)
  waitTimer = undefined
  waiting.value = false
}

function appendToken(item: ConversationItem, text: string, source: ChatSource) {
  const segments = item.segments ?? (item.segments = [])
  const last = segments.at(-1)
  if (last?.source === source) last.text += text
  else segments.push({ source, text })
}

function errorCopy(error: StreamError): string {
  if (error.reason === 'data_unavailable') {
    return '자료를 불러오지 못했습니다. 다시 시도해 주세요.'
  }
  return error.message || '답변 생성에 실패했습니다. 다시 시도해 주세요.'
}

function exportHref(result: ExportResult): string {
  const path = result.download_url || result.url || ''
  return path ? resolveApiUrl(path) : '#'
}

async function sendMessage() {
  const question = input.value.trim()
  if (!question || pending.value) return

  const requestHistory = [...history.value]
  const userItem: ConversationItem = {
    id: nextMessageId++,
    role: 'user',
    content: question,
  }
  const answerItem: ConversationItem = {
    id: nextMessageId++,
    role: 'assistant',
    segments: [],
  }
  messages.value.push(userItem, answerItem)
  input.value = ''
  pending.value = true
  toolLabel.value = ''
  waitTimer = setTimeout(() => {
    waiting.value = true
  }, 5000)

  let completed = false
  try {
    await chatWithIssue(props.issueId, question, requestHistory, {
      tool: (event) => {
        toolLabel.value = `${event.label} 중…`
      },
      token: (event) => {
        clearWaitTimer()
        toolLabel.value = ''
        appendToken(answerItem, event.text, event.source)
      },
      done: (event) => {
        completed = true
        answerItem.articleIds = event.article_ids
        answerItem.exports = event.exports
      },
      error: (event) => {
        answerItem.error = errorCopy(event)
      },
    })
    if (completed && !answerItem.error) {
      const answerText = (answerItem.segments ?? []).map((segment) => segment.text).join('')
      history.value.push(
        { role: 'user', content: question },
        { role: 'assistant', content: answerText },
      )
    }
  } catch (caught) {
    answerItem.error = caught instanceof Error ? caught.message : '답변을 불러오지 못했습니다.'
  } finally {
    clearWaitTimer()
    toolLabel.value = ''
    pending.value = false
    if (answerItem.error) input.value = question
  }
}

onBeforeUnmount(clearWaitTimer)
</script>

<template>
  <aside class="chat-panel" aria-labelledby="chat-title">
    <header class="chat-header">
      <div>
        <p class="eyebrow">Evidence chat</p>
        <h2 id="chat-title">이 이슈에 질문하기</h2>
      </div>
      <span class="live-dot" :class="{ active: pending }" aria-hidden="true"></span>
    </header>

    <div class="chat-messages" aria-live="polite">
      <div v-if="messages.length === 0" class="chat-empty">
        <p>기사에 나온 사실이나 배경 개념을 물어보세요.</p>
        <small>답변은 기사 근거와 일반 설명을 구분해 표시합니다.</small>
      </div>

      <article
        v-for="message in messages"
        :key="message.id"
        class="chat-message"
        :class="message.role"
      >
        <p v-if="message.role === 'user'">{{ message.content }}</p>
        <template v-else>
          <p v-if="message.error" class="chat-error">{{ message.error }}</p>
          <div
            v-for="(segment, index) in message.segments"
            :key="index"
            class="answer-segment"
            :class="segment.source"
          >
            <span class="source-label">
              {{ segment.source === 'article' ? '기사 근거' : '기사에서 확인되지 않은 설명' }}
            </span>
            <p>{{ segment.text }}</p>
          </div>
          <div v-if="message.articleIds?.length" class="citation-list">
            <span>참조</span>
            <button
              v-for="articleId in message.articleIds"
              :key="articleId"
              type="button"
              @click="emit('openArticle', articleId)"
            >
              기사 #{{ articleId }}
            </button>
          </div>
          <div v-if="message.exports?.length" class="export-list">
            <a
              v-for="result in message.exports"
              :key="result.download_url || result.url || result.page_id"
              :href="exportHref(result)"
              target="_blank"
              rel="noopener noreferrer"
            >
              {{ result.file_name || `${result.format.toUpperCase()} 결과 열기` }}
            </a>
          </div>
        </template>
      </article>

      <div v-if="toolLabel" class="tool-progress"><span></span>{{ toolLabel }}</div>
      <p v-if="waiting" class="waiting-message">응답을 기다리는 중</p>
    </div>

    <form class="chat-form" @submit.prevent="sendMessage">
      <label for="chat-input" class="sr-only">질문</label>
      <textarea
        id="chat-input"
        v-model="input"
        rows="3"
        placeholder="예: 이 결정이 내려진 배경은 무엇인가요?"
        :disabled="pending"
        @keydown.meta.enter.prevent="sendMessage"
        @keydown.ctrl.enter.prevent="sendMessage"
      ></textarea>
      <div class="chat-form-footer">
        <small>Ctrl/⌘ + Enter로 전송</small>
        <button class="icon-button" type="submit" :disabled="!canSend">
          <span>보내기</span><span aria-hidden="true">↗</span>
        </button>
      </div>
    </form>
  </aside>
</template>

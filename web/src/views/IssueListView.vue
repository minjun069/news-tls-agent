<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { createIssue, listIssues } from '../api/client'
import type {
  GenerationRequest,
  GenerationStage,
  IssueSummary,
  StreamError,
} from '../api/types'
import { formatDateTime } from '../utils/format'

const router = useRouter()
const issues = ref<IssueSummary[]>([])
const loadingIssues = ref(true)
const listError = ref('')

const topic = ref('')
const pending = ref(false)
const progress = ref<GenerationStage | null>(null)
const generationError = ref('')
const retryable = ref(false)
const clarificationQuestion = ref('')
const clarificationReply = ref('')
const clarificationAttempt = ref(0)
const activeTopic = ref('')
const lastRequest = ref<GenerationRequest | null>(null)

const progressCopy = computed(() => {
  const current = progress.value
  if (!current) return ''
  const round = current.round ? `${current.round}번째 ` : ''
  const count = current.selected ?? current.found
  return `${round}${current.message}${count === undefined ? '' : ` · 기사 ${count}건 확보`}`
})

function generationErrorCopy(error: StreamError): string {
  if (error.reason === 'no_articles') {
    return '관련 기사를 찾지 못했습니다. 다른 토픽으로 시도해 보세요.'
  }
  if (error.reason === 'generation_failed') {
    return '생성에 실패했습니다. 다시 시도할 수 있습니다.'
  }
  if (error.reason === 'rate_limited') {
    return '요청이 많아 잠시 후 다시 시도해 주세요.'
  }
  return error.message || '요청을 처리하지 못했습니다.'
}

async function loadIssues() {
  loadingIssues.value = true
  listError.value = ''
  try {
    issues.value = await listIssues()
  } catch (caught) {
    listError.value = caught instanceof Error ? caught.message : '이슈 목록을 불러오지 못했습니다.'
  } finally {
    loadingIssues.value = false
  }
}

async function runGeneration(request: GenerationRequest) {
  pending.value = true
  progress.value = { stage: 'intent', message: '요청을 준비하는 중' }
  generationError.value = ''
  retryable.value = false
  clarificationQuestion.value = ''
  lastRequest.value = request

  try {
    await createIssue(request, {
      stage: (event) => {
        progress.value = event
      },
      clarify: (event) => {
        clarificationQuestion.value = event.question
        clarificationAttempt.value = event.attempt
        progress.value = null
      },
      done: (event) => {
        void router.push(`/issues/${event.issue_id}`)
      },
      error: (event) => {
        generationError.value = generationErrorCopy(event)
        retryable.value = event.retryable
        progress.value = null
      },
    })
  } catch (caught) {
    generationError.value =
      caught instanceof Error ? caught.message : 'API 서버에 연결하지 못했습니다.'
    retryable.value = true
    progress.value = null
  } finally {
    pending.value = false
  }
}

function submitTopic() {
  const value = topic.value.trim()
  if (!value || pending.value) return
  activeTopic.value = value
  clarificationReply.value = ''
  clarificationAttempt.value = 0
  void runGeneration({ topic: value, clarification: null, clarification_count: 0 })
}

function submitClarification() {
  const answer = clarificationReply.value.trim()
  if (!answer || pending.value) return
  void runGeneration({
    topic: activeTopic.value,
    clarification: answer,
    clarification_count: clarificationAttempt.value,
  })
}

function retryGeneration() {
  if (lastRequest.value) void runGeneration(lastRequest.value)
}

onMounted(loadIssues)
</script>

<template>
  <main>
    <section class="hero-section">
      <div class="hero-copy">
        <p class="eyebrow">News archive · verifiable timeline</p>
        <h1>흩어진 기사를<br />하나의 흐름으로.</h1>
        <p>
          궁금한 사건을 입력하면 뉴스 아카이브를 탐색해 날짜순 타임라인을 만들고,
          각 분기점의 근거 기사를 연결합니다.
        </p>
      </div>

      <div class="creation-card">
        <form @submit.prevent="submitTopic">
          <label for="topic">어떤 사건의 흐름이 궁금한가요?</label>
          <div class="topic-input-row">
            <input
              id="topic"
              v-model="topic"
              type="text"
              maxlength="500"
              placeholder="예: SK텔레콤 유심 정보 유출 사태"
              :disabled="pending"
            />
            <button class="primary-button" type="submit" :disabled="!topic.trim() || pending">
              타임라인 만들기
            </button>
          </div>
        </form>

        <div v-if="progress" class="generation-progress" aria-live="polite">
          <span class="progress-spinner" aria-hidden="true"></span>
          <div>
            <strong>{{ progressCopy }}</strong>
            <small>기사를 비교하며 사건의 앞뒤를 확인하고 있습니다.</small>
          </div>
        </div>

        <form
          v-if="clarificationQuestion"
          class="clarification-box"
          @submit.prevent="submitClarification"
        >
          <div class="clarification-question">
            <span aria-hidden="true">?</span>
            <div>
              <small>의도를 조금 더 알려주세요</small>
              <strong>{{ clarificationQuestion }}</strong>
            </div>
          </div>
          <div class="topic-input-row">
            <input
              v-model="clarificationReply"
              type="text"
              maxlength="500"
              placeholder="답변을 입력하세요"
              :disabled="pending"
              aria-label="되묻기 답변"
            />
            <button class="secondary-button" type="submit" :disabled="!clarificationReply.trim()">
              답변하고 계속
            </button>
          </div>
        </form>

        <div v-if="generationError" class="generation-error" role="alert">
          <p>{{ generationError }}</p>
          <button v-if="retryable" type="button" @click="retryGeneration">다시 시도</button>
        </div>
      </div>
    </section>

    <section class="archive-section" aria-labelledby="archive-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Timeline archive</p>
          <h2 id="archive-title">생성된 이슈</h2>
        </div>
        <span>{{ issues.length }} timelines</span>
      </div>

      <div v-if="loadingIssues" class="issue-grid" aria-label="이슈 목록 불러오는 중">
        <div v-for="index in 3" :key="index" class="issue-card skeleton-card"></div>
      </div>
      <div v-else-if="listError" class="empty-state">
        <p>{{ listError }}</p>
        <button type="button" @click="loadIssues">목록 다시 불러오기</button>
      </div>
      <div v-else-if="issues.length === 0" class="empty-state">
        <strong>아직 생성된 타임라인이 없습니다.</strong>
        <p>위에서 첫 사건을 입력해 뉴스의 흐름을 만들어 보세요.</p>
      </div>
      <div v-else class="issue-grid">
        <RouterLink
          v-for="issue in issues"
          :key="issue.issue_id"
          class="issue-card"
          :to="`/issues/${issue.issue_id}`"
        >
          <div class="issue-card-topline">
            <span>{{ issue.event_count }}개 분기점</span>
            <span aria-hidden="true">↗</span>
          </div>
          <h3>{{ issue.title }}</h3>
          <p>{{ issue.topic }}</p>
          <time :datetime="issue.generated_at">{{ formatDateTime(issue.generated_at) }}</time>
        </RouterLink>
      </div>
    </section>
  </main>
</template>

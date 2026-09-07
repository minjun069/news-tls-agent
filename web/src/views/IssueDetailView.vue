<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { getIssue } from '../api/client'
import type { IssueDetail, TimelineEvent } from '../api/types'
import { formatDate, formatDateTime } from '../utils/format'
import ChatPanel from '../components/ChatPanel.vue'
import ExportMenu from '../components/ExportMenu.vue'
import KnowledgeGraphPanel from '../components/KnowledgeGraphPanel.vue'
import MarkdownContent from '../components/MarkdownContent.vue'
import TimelineEventPanel from '../components/TimelineEventPanel.vue'

const route = useRoute()
const issue = ref<IssueDetail | null>(null)
const loading = ref(true)
const error = ref('')
const selectedOrder = ref<number | null>(null)
const focusedArticleId = ref<number | null>(null)

const issueId = computed(() => Number(route.params.issueId))
const selectedEvent = computed<TimelineEvent | null>(() => {
  if (!issue.value) return null
  return (
    issue.value.events.find((event) => event.event_order === selectedOrder.value) ??
    issue.value.events[0] ??
    null
  )
})

async function loadIssue(id: number) {
  loading.value = true
  error.value = ''
  issue.value = null
  if (!Number.isInteger(id) || id < 1) {
    error.value = '올바르지 않은 이슈 주소입니다.'
    loading.value = false
    return
  }
  try {
    issue.value = await getIssue(id)
    selectedOrder.value = issue.value.events[0]?.event_order ?? null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '이슈를 불러오지 못했습니다.'
  } finally {
    loading.value = false
  }
}

function selectEvent(event: TimelineEvent) {
  selectedOrder.value = event.event_order
  focusedArticleId.value = null
}

async function focusArticle(articleId: number) {
  const owner = issue.value?.events.find((event) =>
    event.articles.some((article) => article.article_id === articleId),
  )
  if (!owner) return
  selectedOrder.value = owner.event_order
  focusedArticleId.value = articleId
  await nextTick()
  document.getElementById(`article-${articleId}`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
  })
}

watch(issueId, loadIssue, { immediate: true })
</script>

<template>
  <main class="detail-main">
    <div v-if="loading" class="detail-loading" aria-label="이슈 상세 불러오는 중">
      <span></span><span></span><span></span>
    </div>
    <section v-else-if="error" class="detail-error">
      <p>{{ error }}</p>
      <RouterLink to="/">이슈 목록으로 돌아가기</RouterLink>
    </section>

    <template v-else-if="issue">
      <nav class="breadcrumb" aria-label="현재 위치">
        <RouterLink to="/">이슈 목록</RouterLink><span aria-hidden="true">/</span>
        <span>{{ issue.topic }}</span>
      </nav>

      <header class="issue-header">
        <div class="issue-header-top">
          <div>
            <p class="eyebrow">Issue timeline · {{ issue.events.length }} events</p>
            <h1>{{ issue.title }}</h1>
          </div>
          <ExportMenu :issue-id="issue.issue_id" />
        </div>
        <div class="issue-meta">
          <span>{{ issue.topic }}</span>
          <time :datetime="issue.generated_at">{{ formatDateTime(issue.generated_at) }} 생성</time>
        </div>
      </header>

      <section v-if="issue.summary" class="issue-summary" aria-labelledby="summary-title">
        <p id="summary-title" class="eyebrow">Summary</p>
        <MarkdownContent :source="issue.summary" />
      </section>

      <div class="detail-layout">
        <section class="timeline-section" aria-labelledby="timeline-title">
          <div class="section-heading compact">
            <div>
              <p class="eyebrow">Chronology</p>
              <h2 id="timeline-title">사건 타임라인</h2>
            </div>
            <span>날짜 오름차순</span>
          </div>

          <div v-if="issue.events.length" class="timeline-workspace">
            <ol class="timeline-nav">
              <li v-for="event in issue.events" :key="event.event_order">
                <button
                  type="button"
                  :class="{ active: selectedEvent?.event_order === event.event_order }"
                  :aria-pressed="selectedEvent?.event_order === event.event_order"
                  @click="selectEvent(event)"
                >
                  <time :datetime="event.event_date">{{ formatDate(event.event_date) }}</time>
                  <span>{{ event.title }}</span>
                </button>
              </li>
            </ol>

            <TimelineEventPanel
              v-if="selectedEvent"
              :event="selectedEvent"
              :focused-article-id="focusedArticleId"
              @select-article="focusArticle"
            />
          </div>
        </section>

        <ChatPanel :issue-id="issue.issue_id" @open-article="focusArticle" />
      </div>

      <KnowledgeGraphPanel
        :issue-id="issue.issue_id"
        :event-count="issue.events.length"
        @open-article="focusArticle"
      />
    </template>
  </main>
</template>

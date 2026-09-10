<script setup lang="ts">
import { ref } from 'vue'
import { streamIssueGraph } from '../api/client'
import { presentStreamError } from '../api/streamErrors'
import type { StreamErrorAction } from '../api/streamErrors'
import type { ArticleGraph } from '../api/types'
import ArticleGraphCard from './ArticleGraphCard.vue'

const props = defineProps<{ issueId: number; eventCount: number }>()
const emit = defineEmits<{ openArticle: [articleId: number] }>()

const opened = ref(false)
const loading = ref(false)
const remaining = ref(0)
const graphs = ref<ArticleGraph[]>([])
const error = ref('')
const errorAction = ref<StreamErrorAction>('none')

async function loadGraph() {
  if (loading.value || props.eventCount <= 1) return
  opened.value = true
  loading.value = true
  error.value = ''
  errorAction.value = 'none'
  graphs.value = []
  try {
    await streamIssueGraph(props.issueId, {
      stage: (event) => {
        remaining.value = event.remaining
      },
      done: (event) => {
        graphs.value = event.graphs
      },
      error: (event) => {
        const presentation = presentStreamError(event)
        error.value = presentation.message
        errorAction.value = presentation.action
      },
    })
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '지식 그래프를 불러오지 못했습니다.'
    errorAction.value = 'retry'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section v-if="eventCount > 1" class="knowledge-section" aria-labelledby="graph-title">
    <div class="section-heading compact">
      <div>
        <p class="eyebrow">Knowledge graph</p>
        <h2 id="graph-title">기사별 인물·기관·사건 관계</h2>
      </div>
      <button v-if="!opened" class="graph-open-button" type="button" @click="loadGraph">
        지식 그래프 열기
      </button>
    </div>

    <div v-if="loading" class="graph-progress" aria-live="polite">
      <span class="progress-spinner" aria-hidden="true"></span>
      <div>
        <strong>관계를 분석하는 중</strong>
        <small>남은 기사 {{ remaining }}건</small>
      </div>
    </div>
    <div v-else-if="error" class="graph-error">
      <p>{{ error }}</p>
      <button v-if="errorAction === 'retry'" type="button" @click="loadGraph">다시 시도</button>
    </div>
    <div v-else-if="graphs.length" class="graph-grid">
      <ArticleGraphCard
        v-for="graph in graphs"
        :key="graph.article_id"
        :graph="graph"
        @open-article="emit('openArticle', $event)"
      />
    </div>
  </section>
</template>

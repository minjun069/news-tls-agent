<script setup lang="ts">
import { ref, watch } from 'vue'
import { getArticle } from '../api/client'
import type { Article } from '../api/types'
import { formatDate } from '../utils/format'

const props = defineProps<{
  articleId: number
  eyebrow?: string
}>()

const article = ref<Article | null>(null)
const loading = ref(true)
const error = ref('')

watch(
  () => props.articleId,
  async (articleId, _previous, onCleanup) => {
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    article.value = null
    error.value = ''
    loading.value = true
    try {
      article.value = await getArticle(articleId, controller.signal)
    } catch (caught) {
      if ((caught as Error).name !== 'AbortError') {
        error.value = caught instanceof Error ? caught.message : '기사를 불러오지 못했습니다.'
      }
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  },
  { immediate: true },
)
</script>

<template>
  <article :id="`article-${articleId}`" class="article-detail" aria-live="polite">
    <div v-if="loading" class="article-skeleton" aria-label="기사 불러오는 중">
      <span></span><span></span><span></span>
    </div>
    <p v-else-if="error" class="inline-error">{{ error }}</p>
    <template v-else-if="article">
      <div class="article-heading">
        <div>
          <p class="eyebrow">{{ eyebrow || '기사 근거' }}</p>
          <h4>{{ article.title }}</h4>
          <p v-if="article.sub_title" class="article-subtitle">{{ article.sub_title }}</p>
        </div>
        <time :datetime="article.service_date">{{ formatDate(article.service_date) }}</time>
      </div>
      <p v-if="article.summary" class="article-summary">{{ article.summary }}</p>
      <div class="article-content">{{ article.content }}</div>
      <p v-if="article.truncated" class="truncated-note">일부만 표시됨</p>
      <a
        v-if="article.url"
        class="original-link"
        :href="article.url"
        target="_blank"
        rel="noopener noreferrer"
      >
        원문 기사 열기 <span aria-hidden="true">↗</span>
      </a>
    </template>
  </article>
</template>

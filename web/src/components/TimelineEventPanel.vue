<script setup lang="ts">
import { computed } from 'vue'
import type { TimelineEvent } from '../api/types'
import { formatDate } from '../utils/format'
import ArticleDetail from './ArticleDetail.vue'

const props = defineProps<{
  event: TimelineEvent
  focusedArticleId: number | null
}>()

const emit = defineEmits<{
  selectArticle: [articleId: number]
}>()

const otherArticles = computed(() =>
  props.event.articles.filter(
    (article) => article.article_id !== props.event.primary_article.article_id,
  ),
)

const focusedSupportingArticle = computed(() => {
  if (!props.focusedArticleId) return null
  if (props.focusedArticleId === props.event.primary_article.article_id) return null
  return props.event.articles.find((article) => article.article_id === props.focusedArticleId) ?? null
})
</script>

<template>
  <section class="event-panel">
    <header class="event-panel-header">
      <time :datetime="event.event_date">{{ formatDate(event.event_date) }}</time>
      <h3>{{ event.title }}</h3>
      <p>{{ event.summary }}</p>
    </header>

    <ArticleDetail :article-id="event.primary_article.article_id" eyebrow="대표 기사" />

    <details v-if="otherArticles.length" class="supporting-articles">
      <summary>근거 기사 {{ otherArticles.length }}건 더 보기</summary>
      <ul>
        <li v-for="article in otherArticles" :key="article.article_id">
          <button type="button" @click="emit('selectArticle', article.article_id)">
            <span>{{ article.title }}</span>
            <time :datetime="article.service_date">{{ formatDate(article.service_date) }}</time>
          </button>
        </li>
      </ul>
    </details>

    <ArticleDetail
      v-if="focusedSupportingArticle"
      :article-id="focusedSupportingArticle.article_id"
      eyebrow="선택한 근거 기사"
    />
  </section>
</template>

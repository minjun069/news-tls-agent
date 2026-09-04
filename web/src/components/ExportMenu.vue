<script setup lang="ts">
import { computed, ref } from 'vue'
import { exportIssue, resolveApiUrl } from '../api/client'
import type { ExportResult } from '../api/types'

const props = defineProps<{ issueId: number }>()

const parentPageId = ref('')
const pendingFormat = ref<'pdf' | 'notion' | null>(null)
const error = ref('')
const result = ref<ExportResult | null>(null)

const resultHref = computed(() => {
  if (!result.value) return '#'
  if (result.value.download_url) return resolveApiUrl(result.value.download_url)
  return result.value.url || '#'
})

async function runExport(format: 'pdf' | 'notion') {
  if (pendingFormat.value) return
  pendingFormat.value = format
  error.value = ''
  result.value = null
  try {
    result.value = await exportIssue(props.issueId, {
      format,
      ...(format === 'notion' && parentPageId.value.trim()
        ? { parent_page_id: parentPageId.value.trim() }
        : {}),
    })
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '브리핑을 내보내지 못했습니다.'
  } finally {
    pendingFormat.value = null
  }
}
</script>

<template>
  <details class="export-menu">
    <summary>내보내기 <span aria-hidden="true">↓</span></summary>
    <div class="export-popover">
      <p class="export-intro">이슈 전체 요약과 타임라인, 근거 기사를 브리핑으로 저장합니다.</p>
      <button type="button" :disabled="pendingFormat !== null" @click="runExport('pdf')">
        <span>PDF 파일</span>
        <small>{{ pendingFormat === 'pdf' ? '생성 중…' : '다운로드 링크 만들기' }}</small>
      </button>
      <label for="notion-parent">Notion 상위 페이지 ID <small>선택</small></label>
      <input
        id="notion-parent"
        v-model="parentPageId"
        type="text"
        placeholder="비우면 서버 기본값 사용"
        :disabled="pendingFormat !== null"
      />
      <button type="button" :disabled="pendingFormat !== null" @click="runExport('notion')">
        <span>Notion 페이지</span>
        <small>{{ pendingFormat === 'notion' ? '저장 중…' : '페이지 생성하기' }}</small>
      </button>
      <p v-if="error" class="export-error">{{ error }}</p>
      <a
        v-if="result"
        class="export-result"
        :href="resultHref"
        target="_blank"
        rel="noopener noreferrer"
      >
        {{ result.file_name || '생성된 Notion 페이지 열기' }} <span aria-hidden="true">↗</span>
      </a>
    </div>
  </details>
</template>

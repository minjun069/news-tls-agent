import type { StreamError } from './types'

export type StreamErrorAction = 'edit_topic' | 'retry' | 'none'

export interface StreamErrorPresentation {
  message: string
  action: StreamErrorAction
}

export function presentStreamError(error: StreamError): StreamErrorPresentation {
  let message: string
  if (error.reason === 'search_no_hits') {
    message = '검색 결과가 없습니다. 기간이나 핵심어를 바꿔 다시 입력해 주세요.'
  } else if (error.reason === 'selection_rejected_all') {
    message = '검색된 기사가 토픽의 근거로 충분하지 않았습니다. 토픽을 더 구체적으로 입력해 주세요.'
  } else if (error.reason === 'model_unavailable') {
    message = error.retryable
      ? '모델 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.'
      : '현재 모델 설정을 사용할 수 없습니다. 관리자에게 문의해 주세요.'
  } else if (error.reason === 'output_validation_failed') {
    message = '모델 응답 형식을 확인하지 못했습니다. 다시 시도해 주세요.'
  } else if (error.reason === 'generation_failed') {
    message = '생성에 실패했습니다. 다시 시도할 수 있습니다.'
  } else if (error.reason === 'rate_limited') {
    message = '요청이 많아 잠시 후 다시 시도해 주세요.'
  } else {
    message = error.message || '요청을 처리하지 못했습니다.'
  }

  if (error.reason === 'search_no_hits' || error.reason === 'selection_rejected_all') {
    return { message, action: 'edit_topic' }
  }
  return { message, action: error.retryable ? 'retry' : 'none' }
}

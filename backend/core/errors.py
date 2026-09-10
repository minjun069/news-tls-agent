"""S5 파이프라인이 어댑터 구현과 무관하게 전달하는 오류."""

from __future__ import annotations


class TimelineGenerationError(Exception):
    """저장하면 안 되는 타임라인 생성 실패의 공통 기반."""


class LLMGenerationError(TimelineGenerationError):
    """세부 정책이 없는 LLM API·빈 응답 실패."""


class LLMModelConfigurationError(LLMGenerationError):
    """설정한 모델을 현재 API에서 호출할 수 없는 비재시도 실패."""


class LLMRateLimitError(LLMGenerationError):
    """호출 한도 초과로 재시도 가능한 LLM 실패."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMServiceUnavailableError(LLMGenerationError):
    """503 재시도 예산을 소진한 일시적 모델 서비스 실패."""


class LLMOutputValidationError(LLMGenerationError):
    """구조화 출력의 응답 타입·원본·검증 실패 지점을 보존한다."""

    def __init__(
        self,
        message: str,
        *,
        response_type: str,
        validation_error: str,
        raw_output: object | None,
        invalid_endpoints: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        self.response_type = response_type
        self.validation_error = validation_error
        self.raw_output = raw_output
        self.invalid_endpoints = invalid_endpoints


class PipelineInvariantError(TimelineGenerationError):
    """인용 검증 뒤 저장 가능한 이벤트가 남지 않는 등 내부 불변식 위반."""


class DataAccessError(Exception):
    """MCP 프로세스·전송·저장소를 통해 자료를 읽지 못했다."""


class IssueNotFoundError(Exception):
    """그래프·내보내기 대상 이슈가 존재하지 않는다."""


class InsufficientEventsError(Exception):
    """이벤트가 1건 이하여서 지식 그래프를 제공할 수 없다."""


class GraphExtractionError(Exception):
    """기사별 엔티티·관계를 완전한 상태로 만들지 못했다."""


class ExportNotConfiguredError(Exception):
    """PDF 글꼴 또는 Notion 연결처럼 요청 형식에 필요한 설정이 없다."""


class BriefingExportError(Exception):
    """브리핑 변환이나 외부 저장에 실패했다."""

"""S5 파이프라인이 어댑터 구현과 무관하게 전달하는 오류."""

from __future__ import annotations


class TimelineGenerationError(Exception):
    """저장하면 안 되는 타임라인 생성 실패의 공통 기반."""


class LLMGenerationError(TimelineGenerationError):
    """LLM API·빈 응답·구조 검증 실패."""


class LLMRateLimitError(LLMGenerationError):
    """호출 한도 초과로 재시도 가능한 LLM 실패."""


class PipelineInvariantError(TimelineGenerationError):
    """인용 검증 뒤 저장 가능한 이벤트가 남지 않는 등 내부 불변식 위반."""


class DataAccessError(Exception):
    """MCP 프로세스·전송·저장소를 통해 자료를 읽지 못했다."""

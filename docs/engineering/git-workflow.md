# Git·커밋·PR 규칙

## 브랜치

`main`에는 직접 push하지 않는다. 작업 브랜치와 PR을 사용한다.

```text
feat/<스프린트>-<요약>    feat/s2-data-layer
fix/<요구사항-ID>         fix/ISS-003
docs/<주제>               docs/agent-guidance
chore/<주제>
```

## 커밋 메시지

```text
<type>(<scope>): <한국어 요약>

<필요한 경우 왜 바꿨는지와 중요한 제약>

<관련 ADR 또는 요구사항>
```

- type: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
- 사용자 기능 구현의 scope는 대표 요구사항 ID를 쓴다. 예: `feat(ISS-003): MS-SQL 데이터 계층 구현`.
- 기능 하나로 대표하기 어려운 문서·하네스·CI 변경은 `docs`, `harness`, `ci`, `build`처럼 작업 영역을 쓴다.
- GitHub 이슈 번호 표기인 `#2`와 `[FEAT]` 접두 형식은 이 저장소에서 사용하지 않는다.
- 제목은 명령형보다 완료된 변경을 명확히 설명하고, 서로 다른 논리 단위는 커밋을 나눈다.
- 코드와 그 코드가 바꾼 계약 문서는 같은 커밋에 둔다.

## 커밋 전

1. `git status`뿐 아니라 변경 대상 파일의 실제 내용과 실행 상태를 확인한다.
2. `git diff`와 스테이징 범위를 검토한다.
3. `make check`를 통과시킨다. 필요한 경우 통합 검사도 실행한다.
4. 사용자 소유의 관련 없는 변경은 포함하지 않는다.

## PR

- 스프린트 단위 또는 그보다 작게 연다.
- 제목은 커밋 형식과 같은 `type(scope): 요약`을 쓴다.
- 본문에는 `docs/engineering/roadmap.md`의 충족한 완료 기준, 검증 결과, 미검증 항목을 적는다.
- required status check가 통과하고 리뷰 요건을 충족한 뒤 병합한다.
- 이미 원격에 올린 커밋을 고치면 대상 해시와 변경 범위를 확인하고 `--force-with-lease`만 사용한다.

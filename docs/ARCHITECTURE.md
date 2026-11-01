# 수집 코드 구조

핵심 규칙과 실행 흐름은 외부 라이브러리나 저장 형식을 몰라도 동작합니다. 구체적인 구현의 선택은 `semo/cli.py`에서만 합니다.

```text
daily_collect.py / Airflow DAG / probe.py
                ↓
           cli.py (구현 연결)
                ↓
      application.py → domain.py
                ↑
  adapters/sejong.py · http.py · storage.py
```

| 파일 | 책임 | 수정하는 경우 |
|---|---|---|
| `semo/domain.py` | 정규화·해시·일정 필터링, 수집 결과 데이터 | 문서 규칙이나 날짜 조회 기준 변경 |
| `semo/content.py` | 병합 셀의 문맥을 유지한 표 렌더링·문단 청크 | 텍스트 표현·분할 정책 변경 |
| `semo/application.py` | 수집원 실행, 모두 성공한 후 저장, 의존성 interface | 수집 실행 순서·정책 변경 |
| `semo/adapters/sejong.py` | 세종대 URL·HTML 파싱·기존 공지 재확인 | 사이트 구조나 대상 게시판 변경 |
| `semo/adapters/http.py` | HTTP·robots·호출 간격, 저장된 HTML 읽기 | HTTP 도구 교체·샘플 읽기 변경 |
| `semo/adapters/storage.py` | PostgreSQL 트랜잭션·변경 비교·JSON 내보내기 | 저장 방식 변경 |
| `semo/cli.py` | 인자 처리·구체적인 구현 선택·현재 시각 전달 | 실행 옵션이나 구현 연결 변경 |

`probe.py`는 접근성 검증 도구입니다. 운영 수집 코드가 이 도구를 import하지 않습니다. 공통 파서와 HTTP 구현은 패키지 안에 한 번만 둡니다. Airflow는 기존 CLI를 실행하며 수집 규칙을 중복 구현하지 않습니다.

## 확장 interface

**HTML 읽기**는 `Callable[[str], str]`입니다. 실제 HTTP와 저장된 HTML은 같은 interface를 사용합니다. Selenium이 필요한 페이지가 생기면 이 형태의 reader를 구현해 연결할 수 있습니다. 페이지 수집 정책과 오류 처리는 reader가 유지해야 합니다.

**수집원**은 `Source.read(read_html, previous) -> CollectionBatch`를 구현합니다. 기존 `CalendarSource`와 `NoticeSource`처럼 새 사이트의 파서를 별도 모듈에 두고 CLI의 수집원 목록에 추가하면 됩니다. 핵심 실행 흐름은 수정하지 않습니다.

- 문서 ID는 수집원 안에서 안정적이어야 하며 전체 수집원 사이에서도 고유해야 합니다.
- 문서는 `id`, `kind`, `title`, `published_at`, `content`, `url`, `content_hash`를 제공합니다. 일정 문서는 `start_date`, `end_date`를 추가합니다.
- `replace_kinds`는 완전한 스냅샷을 받은 문서 종류만 지정합니다. 현재 학사일정은 전체 교체하고 공지는 누적 갱신합니다. 새 수집원은 자체 kind를 사용해야 다른 자료를 지우지 않습니다.
- 누락된 오프라인 파일은 `MissingSnapshot`입니다. 샘플 실행에서 이 오류만 생략하고 일반 `KeyError`나 파싱 오류는 실패로 전달합니다.

**저장소**는 `DocumentRepository.load()`와 `save(batch, checked_at, sample_only)`를 구현합니다. 수집 흐름은 PostgreSQL·파일 경로를 직접 다루지 않습니다. 문서 ID·해시·JSON export 형식은 유지합니다. 기존 자료는 JSON export로 PostgreSQL에 가져올 수 있습니다. 설정과 이전 절차는 [POSTGRES.md](POSTGRES.md)를 참고하세요.

## 검증과 남은 제약

네트워크·파일 없이 수집원의 조합과 실패 시 저장하지 않는 동작을 테스트합니다. PostgreSQL 통합 테스트는 재실행·수정 반영·스냅샷 교체 실패의 롤백을 확인합니다. 별도 HTTP 테스트는 robots와 호출 간격을 확인합니다. 실제 HTML 54건은 변경 전후 내용과 해시까지 비교했습니다.

PostgreSQL과 JSON은 하나의 원자적 트랜잭션이 아닙니다. DB 커밋 뒤 JSON 내보내기가 실패하면 작업을 다시 실행해야 합니다. 원문에서 삭제된 공지의 판별과 재확인 범위는 다음 기능 작업에서 정해야 합니다.

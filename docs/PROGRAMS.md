# 취업·비교과 자료와 현재 모집 조회

## 구현한 범위와 수집 제한

| 출처 | 구현 | 확인 범위 |
|---|---|---|
| 두드림 | 공개 목록에서 상세 URL 발견, 상세 본문·표·신청 회차별 모집/운영 시각·대상 추출 | 저장된 목록과 상세 1건으로 확인 |
| 유드림 | 첫 화면 요약 및 프로그램 목록의 공개 상세 본문·신청 시각·참여 대상 추출 | 실제 공개 상세 14건 확인. 외부 접수로 신청 시각이 없는 항목은 현재 모집 후보에서 제외 |

두드림은 회차별 `program:do:프로그램ID:회차ID`를 사용하고, 유드림은 목록의 `pgdx`/`rcdx`를 사용합니다. 본문·기간·대상·마감 상태를 포함한 정규화 데이터로 변경 해시를 계산합니다. 신청 기간을 작성일이나 행사 운영 기간으로 대체하지 않습니다. 첨부·이미지 파일은 다운로드하지 않습니다.

2026-11-05 직접 HTTP 요청으로 재확인했습니다. 두 사이트의 robots.txt는 여전히 루트(`/`) 외 경로를 금지하지만, 두드림 공개 목록과 프로그램 4380, 유드림 첫 화면과 첫 프로그램 링크 목적지는 모두 HTTP 200으로 HTML을 반환했습니다. robots.txt에 따른 수집 중단과 서버의 기술적 접근 차단을 구분해야 합니다. 자동 수집 코드는 기존처럼 robots.txt 지침에 따라 중단합니다. [기존 검증 기록](PROBE_RESULTS.md)을 참고하세요.

두드림 4380(컴퓨터공학과 학술제)은 기존 파서로 신청 기간·본문·대상 설명을 추출했습니다. 상단 대상 필드는 전체 학생/전체 학과지만 본문은 컴퓨터공학과 재학생·휴학생으로 제한하므로, 개인별 자격 판단에서 상단 필드만 신뢰하면 안 됩니다. 유드림 첫 화면은 기존 파서로 11건을 추출했으며, `pgdx` 링크 목적지는 신청 기간이 표시된 프로그램 목록이었습니다. 실제 상세 본문과 신청 자격은 추가 검증이 필요합니다. 원본과 확인 결과는 Git에서 제외된 `artifacts/programs-live-check/`에 보관했으며 PostgreSQL·ChromaDB에는 아직 적재하지 않았습니다.

2026-11-05 공개 HTML을 직접 요청해 두드림 22회차와 유드림 상세 14건을 추출했습니다. 원격 오류 화면 1건은 건너뛰었습니다. 검증한 36문서의 실제 수집 export는 `artifacts/programs-live-check/documents.json`에 있습니다. PostgreSQL 적재·Chroma 색인과 Airflow 정기 실행 성공 여부는 별도로 확인해야 합니다. 유드림 첫 화면 요약이나 외부 접수로 신청 시각이 없는 문서는 “현재 신청 가능” 후보로 쓰지 않습니다. HTML 주석 안의 과거 카드도 수집하지 않습니다.

## 수집부터 챗봇 반영까지 한 번에 실행

```bash
bash scripts/sync_programs.sh
```

API·Airflow를 재빌드한 뒤 공개 프로그램 수집 → PostgreSQL 저장 → 변경 문서 Chroma 색인 → 동기화 상태 확인을 실행합니다. 하나라도 실패하면 중단합니다. 기존 학사·공지 문서는 삭제하지 않습니다.

이미 수집한 export를 반영하려면 경로를 전달합니다. export의 실제 확인 시각을 유지하므로 36시간이 지난 자료는 현재 모집 후보에 포함되지 않습니다.

```bash
bash scripts/sync_programs.sh artifacts/programs-live-check/documents.json
```

## Airflow 일 수집 연결

로컬 `.env`에서 선택 수집원을 설정합니다. 기본값은 비어 있어 기존 학사 수집을 유지합니다.

```dotenv
SEMO_PROGRAM_SOURCES=do,udream
SEMO_DIRECT_PROGRAM_FETCH=true
```

```bash
docker compose up --build -d airflow api
docker compose exec airflow airflow dags trigger semo_daily
```

기존 DAG가 매일 06:00 KST에 수집 후 색인합니다. 수집 단계 출력의 `source_status`와 JSON export에서 각 출처의 `collected`, `listing_only`, `blocked_by_robots`, `source_unavailable`을 확인할 수 있습니다. robots 제한이나 네트워크 오류가 난 선택 수집원은 기존 데이터를 보존하고, 다른 학사 자료 수집을 계속합니다. 파싱 실패는 기존 데이터에 덮어쓰지 않고 실행을 실패시킵니다.

수동 실행은 다음과 같습니다. 새 문서는 PostgreSQL에 저장한 뒤 기존 색인 명령으로 Chroma에 반영합니다.

```bash
docker compose exec -w /opt/semo airflow python daily_collect.py --output /opt/airflow/semo-data --program-sources do,udream
docker compose exec -w /opt/semo airflow python -m semo.index_cli
```

기본 수집은 robots.txt를 먼저 검사합니다. `--direct-program-fetch` 또는 `SEMO_DIRECT_PROGRAM_FETCH=true`는 명시적으로 선택한 두드림·유드림 공개 HTML에 한해 robots 규칙 검사를 생략합니다. 공식 홈페이지 규칙, HTTPS·호스트 제한, 리다이렉트 차단과 최소 3초 요청 간격은 유지합니다. 로그인·CAPTCHA·차단 회피는 수행하지 않습니다. 목록에서 사라진 두드림·유드림 상세도 저장된 URL을 다시 확인합니다. 원격 오류 페이지는 기존 자료와 시각을 유지하고 `partial` 상태로 기록하며, 구조 변경으로 인한 파싱 오류는 전체 저장을 중단합니다.

## “지금 신청 가능한 활동”

현재 모집 조회는 벡터 유사도에 의존하지 않고 PostgreSQL의 구조화 필드를 사용합니다.

- `application_start <= 현재 시각 <= application_end`를 만족해야 합니다.
- 두 시각 모두 타임존이 있어야 하며 행사 `event_start/end`와 구분합니다.
- 모집 마감·취소·정원 초과가 확인된 회차는 제외합니다.
- 마지막 성공 확인이 조회 시각보다 미래이거나 36시간보다 오래되면 제외합니다.
- 신청 시각이 없는 유드림 목록 요약도 제외합니다.

결과는 마감이 빠른 최대 20건이며 `total`은 필터를 통과한 전체 수입니다. **모집 기간 기준 후보**이므로 학생 개인의 자격, 실시간 잔여 정원, 수집 이후의 조기 마감은 보장하지 않습니다. 응답에는 확인 시각과 원문 링크를 제공합니다.

OpenAI 호출 없이 조회:

```bash
docker compose exec -w /opt/semo airflow python -m semo.index_cli --programs
```

시간을 고정하려면 `--at 2026-10-29T15:00:00+09:00`처럼 타임존을 포함하세요. 해당 시각의 신선도 조건을 만족하는 데이터가 있어야 결과가 나옵니다. 과거 자료 스냅샷을 복원하는 기능은 아닙니다.

HTTP 조회는 `GET /api/programs`입니다. OpenAI 키 없이 사용할 수 있으며 PostgreSQL 연결이 필요합니다. `items`, `total`, `as_of`, `reason`, `notice`를 반환합니다. 자료가 없거나 오래되면 빈 목록과 사유를 반환하며, 이를 “학교에서 모집 중인 활동이 없음”으로 해석하지 않습니다.

웹의 **지금 신청할 수 있는 활동은?** 예시나 다음 명령으로 질문하면 같은 기간 필터를 통과한 후보를 근거로 답합니다.

```bash
docker compose exec -w /opt/semo airflow python -m semo.index_cli --answer "지금 신청 가능한 비교과·취업 프로그램을 알려줘"
```

이 분기는 임베딩 검색을 하지 않습니다. 후보가 있으면 신청 시각·대상과 문서 본문 최대 6,000자를 답변 모델에 전달합니다. 본문의 학과·학년 제한이 상단 요약과 다를 수 있으므로 상단 필드만으로 자격을 단정하지 않습니다. 후보가 없으면 유료 생성 호출 없이 수집 자료의 한계를 안내합니다. 일반 질문은 기존 벡터 검색을 유지합니다. `--answer --on`으로 과거 날짜를 주면 그 날짜의 00:00 KST를 조회 기준으로 사용합니다. 오늘은 현재 시각을 사용합니다.

현재는 “지금/현재/오늘/모집 중/신청 가능”과 “활동/프로그램/비교과/취업/진로” 등의 명시적 표현을 인식합니다. 모든 자연어 시간 표현이나 개인별 맞춤 추천은 포함하지 않습니다. 직접 신청·로그인·학생 정보 수집도 하지 않습니다.

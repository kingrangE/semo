# 학사일정·학사안내 수집

자료는 `calendar`(학사일정), `academic_guide`(상시 학사안내), `notice`(공지사항)로 구분합니다. 학사일정은 6개월마다, 공지·선택한 프로그램은 매일 수집합니다. 상시 학사안내는 `--academic-guides` 명령으로 필요할 때만 수동 수집합니다.

| 자료 | 실행 방식 | 시각(KST) |
|---|---|---|
| 학사일정 | `semo_calendar` DAG | 매년 1월 1일·7월 1일 오전 6시 |
| 공지·선택한 취업/비교과 | `semo_daily` DAG | 매일 오전 6시 |
| 상시 학사안내 | `--academic-guides` 수동 명령 | 필요할 때 |

## 수집 범위

- 학사일정: 공식 연간일정의 각 항목을 시작일·종료일과 함께 별도 문서로 저장합니다. 표시된 다음 연도 1~2월 일정도 명시된 연도로 처리합니다.
- 학사안내 20페이지: 교과과정 이수, 학점이수, 수강신청, 계절학기, 등록, 휴학·복학, 제적·자퇴·재입학, 전과, 전공배정, 복수·부·제2전공, 연계융합전공, 자기설계전공, 학업성적, 졸업, 조기졸업, 백분율 환산, 교직이수, 장학 주요사항, 교내·국가장학금.
- 학사안내는 메뉴·하단 공통 영역을 제외한 `#cms-content`만 추출하며 문단과 표를 유지합니다. 페이지마다 `.content-box` 유무가 달라 그 하위 요소에 의존하지 않습니다. 작성일을 확인할 수 없으므로 수집일을 작성일로 대신하지 않습니다.
- 학사안내 문서 ID는 URL의 주제에 고정하고, 제목·본문·표 내용이 바뀌면 해시를 갱신합니다. 수집 확인 시각은 `checked_at`에 별도로 저장합니다.

이 자료는 대학 홈페이지의 학사안내입니다. 규정집의 학칙·시행세칙 PDF 원문 전체를 추출한 것은 아닙니다. 첨부파일은 수집하지 않으며, 안내 페이지에서 확인할 수 없는 조항·개인별 적용 여부를 만들어 답하면 안 됩니다.

기존 코드도 학사일정을 수집했으며 보관된 샘플에는 50건이 있습니다. 이전에는 총 문서 수만 출력해 자료 종류를 구별하기 어려웠습니다. 사용자 환경의 PostgreSQL에 일정이 실제로 있는지는 아래 조회 명령으로 확인할 수 있습니다.

## 반영과 확인

```bash
docker compose up --build -d airflow api
docker compose exec airflow airflow dags trigger semo_calendar
```

`semo_calendar`는 `0 6 1 1,7 *`와 Asia/Seoul 타임존을 사용하고 과거 실행은 소급하지 않습니다. 최초 데이터가 없거나 중간 변경을 반영해야 할 때만 위 명령으로 수동 실행하세요. 수집 후 색인 단계가 이어집니다. 일 수집에서는 학사일정 페이지를 요청하지 않으며 기존 일정 문서를 유지합니다.

수집 단계의 `documents_by_kind`에서 DB에 저장된 종류별 건수를, `source_status`에서 이번에 실행한 출처의 상태를 확인하세요. 반기 일정 수집에서는 `calendar`, 수동 학사안내 수집에서는 `academic_guide`가 표시됩니다. 검색 필터에도 `academic_guide`를 추가했으므로 정상 적재 후 학사안내가 검색 대상에서 빠지지 않습니다. 기존 v2 컬렉션을 그대로 사용합니다.

일정만 CLI로 수집하려면 `daily_collect.py --calendar --output /opt/airflow/semo-data`를 사용하세요. 기본 CLI 실행은 공지·선택한 프로그램의 일 수집입니다.

현재 PostgreSQL 문서의 종류별 건수와 제목·원문 링크·일정 날짜 확인(크롤링/OpenAI 호출 없음):

```bash
docker compose exec -w /opt/semo airflow python daily_collect.py --inspect
```

학사안내만 수동 수집하고 색인하기(DAG 실행 아님):

```bash
docker compose exec -w /opt/semo airflow python daily_collect.py --academic-guides --output /opt/airflow/semo-data
docker compose exec -w /opt/semo airflow python -m semo.index_cli
```

JSON export에서 기준일부터 30일 이내 학사일정 확인:

```bash
docker compose exec -w /opt/semo airflow python daily_collect.py --output /opt/airflow/semo-data --on 2026-11-03
```

답변 확인 예시:

```bash
docker compose exec -w /opt/semo airflow python -m semo.index_cli --answer "일반휴학 신청 방법과 유의사항을 알려줘"
docker compose exec -w /opt/semo airflow python -m semo.index_cli --answer "앞으로 다가오는 학사일정을 알려줘"
```

원문은 [학사일정](https://www.sejong.ac.kr/kor/academics/academic-calendar.do), [휴학·복학](https://www.sejong.ac.kr/kor/academics/leave-return.do), [졸업](https://www.sejong.ac.kr/kor/academics/graduation.do) 등입니다. 현재 학사일정 필터는 종료된 일정을 기본 검색에서 제외하므로 과거 날짜 질문에는 `--history`를 사용하세요.

## 실패와 보존

robots.txt와 10초 요청 간격을 유지합니다. 학사안내 수동 수집에는 약 3분 이상 걸리지만 일 수집 시간에는 추가되지 않습니다. 페이지 구조나 네트워크 오류로 수집이 실패하면 전체 배치를 DB에 쓰지 않습니다. 일 수집 실패는 Airflow가 재시도하며, 학사안내 수동 수집 실패는 명령을 다시 실행합니다. 이미 저장된 학사안내는 일 수집에서 지우지 않으며 변경되지 않은 청크는 재임베딩하지 않습니다.

학사일정은 반기 수집이 성공했을 때 연간 스냅샷으로 교체하며, 학사안내·공지는 문서 ID로 갱신합니다. 두 DAG의 색인은 PostgreSQL advisory lock으로 직렬화해 같은 Chroma 컬렉션의 동시 동기화를 방지합니다. JSON export도 실행별 임시 파일을 사용합니다. 학사안내 원문에서 삭제된 페이지의 자동 삭제와 모든 과거 연도의 일정 수집은 포함하지 않았습니다. 샘플 재생에서는 없는 학사안내 HTML을 생략하고 `partial_samples`로 표시합니다.

## 이번 작업에서 직접 받은 자료

`artifacts/academics-live/`에는 공식 페이지에서 받은 HTML, robots.txt, URL manifest, 추출 문서 `documents.json`, 브라우저용 `preview.html`을 보관합니다. 이 폴더는 Git과 Docker 이미지에서 제외됩니다.

```bash
open artifacts/academics-live/preview.html
```

현재 로컬 스냅샷을 다시 크롤링하지 않고 DB에 합치려면, 먼저 위의 이미지 빌드 명령을 실행한 뒤 다음을 사용하세요. 기존 공지·프로그램은 유지하고 같은 ID의 학사 자료를 갱신합니다. 이후 학사일정은 반기 DAG로, 학사안내는 수동 명령으로 갱신합니다.

```bash
docker compose cp ./artifacts/academics-live/documents.json airflow:/tmp/semo-academics.json
docker compose exec -w /opt/semo airflow python daily_collect.py --import-json /tmp/semo-academics.json --output /opt/airflow/semo-data
docker compose exec -w /opt/semo airflow python -m semo.index_cli
```

이 가져오기는 문서 ID별 갱신이므로 다른 연도의 과거 일정까지 삭제하지 않습니다. 완전한 현재 학사일정 스냅샷 교체는 반기 일정 수집에서 수행됩니다.

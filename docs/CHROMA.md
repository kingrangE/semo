# PostgreSQL → 검색 → 근거 기반 답변

PostgreSQL은 원문 저장소이며 ChromaDB에는 검색용 청크와 출처 정보를 저장합니다. CLI에서 자연어 답변을 생성할 수 있습니다. 학생용 웹 화면과 대화 이력은 아직 연결하지 않았습니다.

## 모델과 설정

- 임베딩: `text-embedding-3-small`.
- 답변: `gpt-6-luna` 기본값. `.env`의 `OPENAI_CHAT_MODEL`로 계정에서 사용 가능한 Responses API·구조화 출력 지원 모델을 지정할 수 있습니다.
- `OPENAI_API_KEY`는 기존 `.env`에 저장합니다. 답변 생성은 임베딩과 별도로 API 비용이 발생합니다.

```dotenv
OPENAI_API_KEY=your-local-api-key
OPENAI_CHAT_MODEL=gpt-6-luna
```

PostgreSQL 초기 설정·이전 절차는 [POSTGRES.md](POSTGRES.md)를 참고하세요. 키나 비밀번호를 Git에 올리지 않습니다.

## v2로 갱신

이번 버전은 HTML 인라인 태그 사이에 강제 줄바꿈을 넣지 않고 문단 경계만 유지합니다. 표의 병합 셀은 각 행에 필요한 문맥을 반복하고, 표 JSON을 본문에 덧붙이지 않습니다. PostgreSQL 문서에 `content_blocks`를 저장하고 문단·표 행을 가능한 한 유지한 채 최대 1,600자로 묶습니다. 긴 문단이나 행은 단어 경계에서 나눕니다.

**기존 PostgreSQL 자료는 한 번 다시 수집해야 문단과 표 정리가 완전히 적용됩니다.** 기존 자료만 다시 색인하면 줄바꿈은 합칠 수 있지만 잃어버린 문단·표 행 경계를 복원할 수는 없습니다.

```sh
docker compose up --build -d
docker compose exec airflow airflow dags trigger semo_daily
docker compose exec airflow airflow dags list-runs semo_daily --output json
```

수집과 색인 작업이 `success`가 된 뒤 검색·답변 명령을 실행하세요. Chroma 컬렉션은 `semo-text-embedding-3-small-v2`이며 최초 v2 실행은 새 임베딩을 생성합니다. v1 컬렉션은 삭제하지 않으며 현재 검색에서는 사용하지 않습니다. Chroma 데이터는 기존 `chroma-data` 볼륨을 유지합니다.

필요하면 PostgreSQL 자료의 색인만 따로 실행할 수 있습니다.

```sh
docker compose exec airflow bash -c 'cd /opt/semo && python -m semo.index_cli'
```

## 검색과 답변

활성 컬렉션과 청크 건수는 OpenAI 호출 없이 확인할 수 있습니다.

```sh
docker compose exec airflow bash -c 'cd /opt/semo && python -m semo.index_cli --status'
```

v2 컬렉션의 `chunks`가 0이면 먼저 재수집·색인을 완료해야 합니다. 답변 보류 시 `reason=no_search_results`는 검색 결과가 없었음을, `reason=insufficient_evidence`는 검색된 자료를 모델이 근거 부족으로 판단했음을 뜻합니다. `generation_used`는 답변 생성 모델의 실제 호출 여부를 나타내며, 질문 임베딩 호출과는 별개입니다.

```sh
docker compose exec airflow bash -c 'cd /opt/semo && python -m semo.index_cli --query "복수전공 신청 기간"'
docker compose exec airflow bash -c 'cd /opt/semo && python -m semo.index_cli --answer "복수전공 신청 기간과 신청 방법을 알려줘"'
```

`--query`는 검색 청크와 원문 메타데이터, `--answer`는 한국어 답변·인용 번호·원문 링크·기준일·사용 모델을 반환합니다. 문장마다 출처 번호를 검증하고 실제 원문 URL만 붙입니다. 근거가 없거나 모델이 답할 수 없다고 판단하면 답변을 보류합니다. 인용 검증은 사실 정확성을 완전히 보장하지 않습니다.

기본 기준일은 **Asia/Seoul의 오늘**입니다. 종료된 학사일정은 검색 전에 제외합니다. 후보는 최대 15개에서 문서당 최대 2개씩, 전체 최대 5개 청크로 구성해 한 문서의 중복 청크가 모든 근거를 차지하지 않도록 합니다.

공지에는 신청 종료일이 별도로 추출되지 않았으므로 작성일만으로 오래된 공지를 제거하지 않습니다. 모델은 본문에 명시된 기간을 기준일과 비교하며 학생 신청·학과 내부 접수·이수 포기를 구분하도록 지시받습니다. 모집 상태나 개인 자격을 실시간으로 확인하는 기능은 아닙니다.

기준일을 지정하거나 과거 학사일정도 검색하려면:

```sh
docker compose exec airflow bash -c 'cd /opt/semo && python -m semo.index_cli --answer "복수전공 신청 기간" --on 2026-11-01'
docker compose exec airflow bash -c 'cd /opt/semo && python -m semo.index_cli --query "2026년 5월 복수전공 신청 기간" --history'
```

`--on`은 검색 기준일입니다. 이전 버전과 달리 학사일정만 30일 범위로 제한하지 않고 공지도 함께 검색합니다. `--history`는 종료된 학사일정도 포함합니다. 질문에 과거 연도를 적는 것만으로 날짜 필터를 자동 해제하지는 않습니다.

검색 결과의 `distance`는 벡터 거리이며 정확도·신뢰도 점수가 아닙니다. 관련 자료가 검색됐다는 사실만으로 신청 가능 여부를 단정하지 않습니다.

## 동기화와 제한

- 문서 해시·메타데이터·분할 결과로 청크 ID를 구성하며 존재하는 청크는 다시 임베딩하지 않습니다.
- 새 청크는 최대 32개씩 요청합니다. 이미지뿐인 공지와 빈 본문은 제외합니다.
- 새 청크 적재가 모두 성공한 뒤 PostgreSQL에서 사라지거나 변경된 문서의 이전 청크를 제거합니다. 원문 저장소가 0건이면 기존 색인 삭제를 막기 위해 중단합니다.
- 전체 작업은 원자적이지 않습니다. 실패 중에는 이전·신규 청크가 함께 남을 수 있으므로 재실행 후 갱신된 색인을 사용해야 합니다. 수동 색인과 Airflow 색인을 동시에 실행하지 마세요.
- 대규모 자료에서는 ID 조회와 청크 생성의 메모리 사용을 줄일 필요가 있습니다. 현재는 전체를 메모리에 모읍니다.

Airflow는 기존처럼 오전 6시에 `collect_public_html → index_documents`를 실행합니다. 수집 실패 시 색인하지 않으며 키가 없으면 색인 작업만 건너뜁니다.

요청에 따라 테스트 작성·실행을 생략했습니다. 이번 v2 재수집·검색 품질과 생성 모델의 실제 응답은 아직 확인하지 않았습니다.

모델과 구조화 출력은 [OpenAI 모델 문서](https://developers.openai.com/api/docs/models/gpt-6-luna), [구조화 출력 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를 참고했습니다.

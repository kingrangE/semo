# PostgreSQL 수집 데이터 저장

수집 데이터 저장소를 PostgreSQL로 교체했습니다. `documents` 테이블에 문서 ID·종류·해시와 JSONB 원문을 저장합니다. 기존 JSON 내보내기 형식과 CLI 수집 옵션은 유지합니다. 다음 단계의 벡터 적재와 검색은 [CHROMA.md](CHROMA.md)를 참고하세요.

이번 변경은 **수집 데이터 저장소**에 적용됩니다. 이미 실행 중인 Airflow의 내부 메타데이터 DB와 실행 이력은 기존 `airflow-state` 볼륨에 그대로 둡니다.

## 설정

```sh
cp .env.example .env
```

`.env`의 `POSTGRES_PASSWORD`에 비밀번호를 입력하세요. 실제 `.env`는 Git과 Docker 빌드 컨텍스트에서 제외됩니다. PostgreSQL은 호스트에 포트를 공개하지 않고 Compose 내부에서만 연결됩니다.

Airflow 컨테이너는 `DATABASE_URL=postgresql://semo@postgres:5432/semo`와 별도의 `PGPASSWORD`를 사용합니다. 비밀번호를 URL에 삽입하지 않아 특수문자 인코딩이 필요하지 않습니다. DB가 연결 가능한 상태가 된 후 Airflow를 시작합니다.

## 기존 79건을 가져오기

현재 Airflow 데이터 볼륨에 있는 `/opt/airflow/semo-data/documents.json`을 사용합니다. 기존 SQLite 파일을 삭제하거나 수정하지 않습니다. 수집과 가져오기가 겹치지 않게 먼저 Airflow를 중지합니다.

```sh
docker compose stop airflow
docker compose build airflow
docker compose up -d postgres
```

기존 JSON을 복사한 후 PostgreSQL로 가져옵니다. 이 명령은 초기 이전용입니다. 운영 수집을 재개한 뒤 이전 파일을 다시 가져오면 같은 ID의 최신 문서를 덮어쓸 수 있습니다.

```sh
docker compose run --rm airflow bash -ec '
  cp /opt/airflow/semo-data/documents.json /opt/airflow/semo-data/documents.before-postgres.json
  python /opt/semo/daily_collect.py --output /opt/airflow/semo-data --import-json /opt/airflow/semo-data/documents.before-postgres.json
'
```

가져오기는 기존 문서 ID·내용·해시와 export의 확인 시각을 사용하며, DB의 다른 문서 종류를 일괄 삭제하지 않습니다. 필수 필드가 없는 파일은 저장 전에 거부합니다. 파일이 없는 신규 환경은 이 단계를 건너뛰고 수집을 시작하세요.

```sh
docker compose exec postgres psql -U semo -d semo -c 'SELECT kind, count(*) FROM documents GROUP BY kind;'
docker compose up -d airflow
docker compose exec airflow airflow dags trigger semo_daily
docker compose exec airflow airflow dags list-runs semo_daily --output json
```

정상 이전 시 가져오기 결과에 `documents: 79`가 나타나야 합니다. 최초 수집 결과는 원문 변경·신규 게시물에 따라 달라질 수 있습니다. 비밀번호 변경은 기존 PostgreSQL 볼륨의 계정 비밀번호를 자동 변경하지 않습니다. 볼륨을 삭제해 비밀번호를 초기화하지 마세요.

## 로컬 Python 실행

```sh
.venv/bin/python -m pip install -r requirements.txt
export DATABASE_URL='postgresql://semo@your-db-host:5432/semo'
export PGPASSWORD='your-local-password'
.venv/bin/python daily_collect.py
```

연결 정보가 없으면 수집 전에 종료합니다. 스키마는 최초 `load/save` 시 생성하며 사용자에게 테이블 생성 권한이 필요합니다. `--on YYYY-MM-DD`는 이전처럼 JSON export를 읽어 DB 연결 없이 동작합니다. 저장된 HTML로 검증할 때는 운영 DB와 분리한 DB를 사용하세요.

## 테스트

일반 테스트는 PostgreSQL 없이 실행됩니다. PostgreSQL 통합 테스트는 `TEST_DATABASE_URL`이 없으면 명시적으로 생략합니다.

```sh
.venv/bin/python -m unittest -v
```

DB가 실행된 후 Compose 안에서 전체 테스트를 실행할 수 있습니다. 테스트마다 임시 schema를 만들고 삭제하므로 실제 `documents` 테이블은 건드리지 않습니다. 테스트 계정에는 schema 생성 권한이 필요합니다.

```sh
docker compose run --rm -e TEST_DATABASE_URL=postgresql://semo@postgres:5432/semo \
  -v "$PWD:/workspace:ro" -w /workspace airflow python -m unittest -v
```

통합 테스트는 실제 PostgreSQL에서 신규 저장·중복 실행·수정 반영·JSONB 한글 복원·스냅샷 교체·실패 시 롤백을 검증합니다. 현재 개발 환경에서는 일반 테스트 14개와 Compose 설정 검사가 통과했으며, Docker 접근 제한으로 통합 테스트 4개는 실행하지 못했습니다.

## 유지하는 동작과 제한

- 모든 수집원이 성공한 뒤 하나의 DB 트랜잭션으로 반영합니다.
- 학사일정은 전체 스냅샷을 교체하고 공지는 ID 기준으로 갱신합니다.
- 동시에 실행된 저장 작업은 테이블 잠금으로 순서대로 반영합니다.
- DB 커밋과 JSON export는 하나의 트랜잭션이 아닙니다. export 실패 시 작업을 재실행해야 합니다.
- 예약 실행 주기·사이트 접근 정책·첨부파일 제외 범위는 이전과 같습니다.

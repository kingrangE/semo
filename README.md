# 세종대학교 학사일정·공지 일 수집

BeautifulSoup으로 공식 홈페이지의 학사일정·일반공지·학사공지를 수집하고, 제목·작성일·내용의 SHA-256 해시로 변경을 비교합니다. 첨부파일과 이미지 파일은 다운로드하지 않습니다. Selenium 없이 대상 HTML의 일정·본문·표를 읽을 수 있었습니다.

구조와 확장 방법은 [ARCHITECTURE.md](ARCHITECTURE.md)에 정리했습니다. 핵심 실행 흐름은 HTML 파서·HTTP·SQLite 구현을 직접 참조하지 않으며 기존 CLI와 데이터 파일 형식은 유지합니다.

## 검증 결과 (2026-10-29)

- 실제 학사일정 HTML에서 일정 **50건** 추출: 시작일·종료일·일정명·원문 링크.
- 공지 상세 샘플 **4건** 추출: 제목·작성일·본문·표. 이 중 1건은 이미지뿐인 공지로 `image_only` 표시.
- 실제 HTML로 최초 실행 **54건 저장**, 동일 자료 재실행 **변경 0건** 확인.
- 날짜 경계·해시·재실행·저장 롤백·구현 교체 등 **14개 테스트 통과**.
- Airflow DAG 문법 검사, Docker Compose 설정 검사 통과. Airflow import/실행은 미검증.

샘플 실행은 목록에서 발견한 상세 URL 중 파일이 있는 4건만 처리했고, 나머지 상세 25건은 생략했습니다. 전체 목록의 본문 수집 성공을 의미하지 않습니다. 결과는 `artifacts/daily-sample/documents.json`과 `documents.sqlite3`에 있습니다.

직접 HTTP 요청으로 학사일정·학사공지 HTML 200 응답을 확인했습니다. 다만 현재 환경은 Python 내부의 HTTP 호출이 DNS 오류로 실패하고 Docker 소켓 접근도 제한됩니다. **사이트 응답과 오프라인 수집·저장은 검증했지만, Airflow가 매일 실시간 수집하는 상태로 기동되지는 않았습니다.**

## 로컬 실행

Python 3.10 이상과 curl이 필요합니다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest -v
.venv/bin/python daily_collect.py
```

기본 범위는 학사일정 전체와 일반공지·학사공지 각각 첫 페이지입니다. `--pages 2`로 게시판당 2페이지로 확장합니다. 초기 과거 자료 전체 수집은 하지 않습니다. 저장된 공지는 매번 다시 확인합니다. 저장 공지가 누적되면 재확인 범위와 주기를 조정해야 합니다.

게시물 ID는 문서 식별에, 콘텐츠 해시는 변경 감지에 사용합니다. 수집시각은 해시에 넣지 않으며 본문과 표의 셀·병합 정보를 포함합니다. 학사일정에는 작성일을 임의로 넣지 않습니다. 이미지 교체와 첨부 변경은 이번 범위에서 감지하지 않습니다.

네트워크 오류·파싱 실패 시 실패로 종료하고 기존 자료를 유지합니다. 공지 삭제 처리는 아직 자동화하지 않아 기존 URL이 사라지면 실패 원인을 확인해야 합니다. 매번 robots.txt와 요청 간격(현재 10초)을 확인합니다. 두드림·유드림은 이번 일 수집 대상에서 제외했습니다.

결과는 `artifacts/daily/documents.json`, `artifacts/daily/documents.sqlite3`입니다. JSON은 다음 ChromaDB 적재 단계의 입력입니다. 현재 VectorDB 적재·챗봇 생성은 포함하지 않습니다.

## 실제 샘플로 재실행

현재 작업 공간에 저장한 HTML과 URL 매핑으로 같은 저장 흐름을 검증할 수 있습니다.

```sh
.venv/bin/python daily_collect.py --sample-dir artifacts/probe --output artifacts/daily-sample
.venv/bin/python daily_collect.py --sample-dir artifacts/probe --output artifacts/daily-sample
.venv/bin/python daily_collect.py --output artifacts/daily-sample --on 2026-10-29
```

마지막 명령은 해당 날짜부터 30일 이내의 현재 진행·예정 일정을 출력합니다. 종료일을 포함하며 연말→연초와 2027년 표기도 처리합니다. 실제 결과 예:

| 일정 | 기간 |
|---|---|
| 복수·부전공, 연계융합전공 신청 | 2026-11-02 ~ 2026-11-26 |
| 2학기 중간고사 성적 열람 및 정정 | 2026-11-03 ~ 2026-11-07 |
| 세종인재자기설계전공 신청 | 2026-11-09 ~ 2026-12-18 |

학사일정 안내용으로 개인의 신청 자격·잔여 인원을 판단하지 않습니다. 공지의 신청 기간 자동 추론도 아직 포함하지 않았습니다. `sample_only=true`는 검증용 자료입니다. 샘플 파일은 현재 작업 공간에 있으며 Git에는 포함하지 않습니다.

## Airflow 자동화

`dags/semo_daily.py`는 [Airflow 3 Task SDK](https://airflow.apache.org/docs/task-sdk/stable/examples.html)로 정의했습니다. 매일 **오전 6시 KST**, 중복 실행 1개 제한, 과거 소급 실행 없음, 실패 시 5분 간격 2회 재시도, 실행 제한 2시간입니다.

Docker 접근과 외부 네트워크가 가능한 환경에서:

```sh
docker compose config --quiet
docker compose up --build -d
docker compose logs -f airflow
```

UI는 `http://localhost:8080`이며 로그인 정보는 standalone 시작 로그에서 확인합니다. 최초 즉시 실행:

```sh
docker compose exec airflow airflow dags list-import-errors
docker compose exec airflow airflow dags trigger semo_daily
```

Compose는 로컬 검증용 standalone 구성입니다. 데이터·Airflow 상태는 `airflow-state` 볼륨에, 수집 결과는 컨테이너의 `/opt/airflow/semo-data/`에 보관합니다. `docker compose down`으로 중지합니다. `down --volumes`는 저장 자료도 삭제합니다.

이전 접근성 조사 상세는 [PROBE_RESULTS.md](PROBE_RESULTS.md)에 있습니다. 이미지뿐인 공지는 원문 확인을 안내해야 하며, 일 수집에서는 원문 수정이 다음 수집까지 지연 반영될 수 있습니다.

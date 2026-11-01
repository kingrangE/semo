# PostgreSQL → OpenAI 임베딩 → ChromaDB

PostgreSQL 원문을 문단·표 행 청크로 구성하고 `text-embedding-3-small` 임베딩을 ChromaDB에 저장합니다.
기존 청크 ID는 다시 임베딩하지 않으며 새 청크를 모두 저장한 뒤 이전 청크를 제거합니다.
이미지뿐인 공지와 빈 본문은 제외합니다. PostgreSQL에 원문이 없으면 먼저 수집하거나 기존 JSON을 가져오세요.

기존 `.env`에 `OPENAI_API_KEY`를 추가하고 컨테이너를 다시 빌드합니다.

```sh
docker compose up --build -d
docker compose exec -w /opt/semo airflow python -m semo.index_cli
docker compose exec -w /opt/semo airflow python -m semo.index_cli --query "복수전공 신청 기간"
```

Airflow는 매일 오전 6시 수집 후 색인을 실행합니다. 키가 없으면 색인만 건너뜁니다.
컬렉션은 `semo-text-embedding-3-small-v2`이며 Chroma 데이터는 `chroma-data` 볼륨에 저장합니다.
입력·출처 메타데이터와 벡터를 같이 저장하고 검색 후보에서 문서당 최대 2개, 전체 최대 5개 청크를 선택합니다.

요청에 따라 테스트를 새로 작성하거나 실행하지 않습니다. 동기화는 여러 요청에 걸쳐 진행되므로 실패하면 재실행해야 합니다.

## 날짜 기준 검색

기본 기준일은 Asia/Seoul의 오늘이며 종료된 학사일정은 제외합니다.
공지의 마감일은 작성일만으로 추정하지 않습니다. `--on YYYY-MM-DD`로 기준일을 바꾸거나 `--history`로 과거 일정을 포함할 수 있습니다.

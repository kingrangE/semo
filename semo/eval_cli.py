"""Run a fixed-date question dataset through the real chat flow in Langfuse."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from semo.chat import MAX_QUESTION_CHARS, validate_conversation
from semo.evaluation import quality_scores


def load_dataset(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    rows = json.loads(raw)
    if not isinstance(rows, list) or not rows:
        raise ValueError("평가 데이터는 비어 있지 않은 JSON 배열이어야 합니다.")
    for number, row in enumerate(rows, 1):
        try:
            question = row["input"]["question"]
            if (
                not isinstance(question, str)
                or not 1 <= len(question.strip()) <= MAX_QUESTION_CHARS
            ):
                raise ValueError("질문은 1~1000자여야 합니다.")
            date.fromisoformat(row["input"]["as_of"])
            validate_conversation(row["input"].get("conversation"))
            if type(row["input"].get("include_history", False)) is not bool:
                raise ValueError("include_history는 boolean이어야 합니다.")
            expected = row["expected_output"]
            if type(expected["refuse"]) is not bool:
                raise ValueError("refuse는 boolean이어야 합니다.")
            if not isinstance(expected["answer"], str) or not expected["answer"].strip():
                raise ValueError("사람이 검토할 기대 답변이 필요합니다.")
            urls = expected.get("source_urls", [])
            if not isinstance(urls, list) or any(
                not isinstance(url, str) or not url.startswith("https://") for url in urls
            ):
                raise ValueError("source_urls는 HTTPS URL 배열이어야 합니다.")
            if not expected["refuse"] and not urls:
                raise ValueError("답변 가능한 질문에는 기대 출처가 필요합니다.")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"평가 데이터 {number}행: {error}") from error
    return rows, hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evals/sejong.json"))
    parser.add_argument("--name", default="semo-answer-quality")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Validate dataset without external calls or charges",
    )
    args = parser.parse_args()
    try:
        rows, version = load_dataset(args.dataset)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.validate_only:
        print(json.dumps({"items": len(rows), "dataset_sha256": version}))
        return

    from semo.adapters.langfuse import get_langfuse
    from semo.runtime import create_chat

    client = get_langfuse()
    if client is None:
        parser.error("LANGFUSE_ENABLED=true와 Langfuse 연결 정보를 설정하세요.")
    if not client.auth_check():
        parser.error("Langfuse 인증/연결을 확인하세요.")
    chat = create_chat()

    def task(*, item, **kwargs):
        data = item["input"]
        return chat.reply(
            data["question"], date.fromisoformat(data["as_of"]),
            data.get("include_history", False),
            conversation=data.get("conversation"),
        )

    try:
        result = client.run_experiment(
            name=args.name, data=rows, task=task, evaluators=[quality_scores],
            max_concurrency=1,
            metadata={"dataset_sha256": version, "model": chat.model},
        )
        print(result.format(include_item_results=True))
        failed = len(result.item_results) != len(rows) or any(
            item.output is None or not item.evaluations
            or any(score.value != 1 for score in item.evaluations)
            for item in result.item_results
        )
        if failed:
            raise SystemExit(1)
    finally:
        client.flush()


if __name__ == "__main__":
    main()

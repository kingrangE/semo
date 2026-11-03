"""Deterministic checks, not a replacement for semantic/human evaluation."""

import re


def quality_scores(*, output, expected_output, **kwargs):
    from langfuse import Evaluation

    refused = output["reason"] is not None
    ids = {source["id"] for source in output["sources"]}
    paragraphs = output["answer"].split("\n\n")
    cited = set(map(int, re.findall(r"\[(\d+)\]", output["answer"])))
    valid = (not ids and not cited) if refused else (
        bool(ids) and cited == ids
        and all(re.search(r"\[\d+\]$", p.strip()) for p in paragraphs)
    )
    scores = [
        Evaluation(name="citation_validity", value=int(valid),
                   comment="인용 형식과 출처 ID만 검사하며 사실 정확성을 보장하지 않음"),
        Evaluation(name="refusal_correctness",
                   value=int(refused == expected_output["refuse"]),
                   comment=f"expected refusal={expected_output['refuse']}, actual={refused}"),
    ]
    expected_urls = set(expected_output.get("source_urls", []))
    if expected_urls:
        actual_urls = {source["url"] for source in output["sources"]}
        scores.append(Evaluation(
            name="expected_source_recall",
            value=len(expected_urls & actual_urls) / len(expected_urls),
            comment="기대 출처 중 최종 답변에 인용된 비율; 검색 recall과 다름",
        ))
    return scores

"""Small synthetic held-fixed judge diagnostic, NOT a full system benchmark.

Default is dry-run. --run-models explicitly authorises up to one judge request per
case using configured credentials. No company data, drafts or raw responses saved.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextledger.llm_workflows import CitationReviewer
from src.answering import DEFAULT_MODEL


def evaluate(cases, reviewer, generation_model):
    results = []
    for case in cases:
        result = reviewer.review(case["question"], case["draft"], case["evidence"],
                                 generation_model, lambda: None, audit=case.get("audit", False))
        results.append({"id":case["id"], "expected":case["expected"], "diagnostics":result})
    # Only completed semantic verdicts enter the judge error-rate denominator.
    measured = [r for r in results if r["diagnostics"].get("attempts") == 1 and
                r["diagnostics"]["status"] in {"supported","unsupported","uncertain"}]
    negative = [r for r in measured if r["expected"] != "supported"]
    positive = [r for r in measured if r["expected"] == "supported"]
    return {"scope":"small synthetic independent-review diagnostic, not production accuracy",
        "cases":len(cases), "measured_verdicts":len(measured),
        "deterministic_rejections":sum(r["diagnostics"].get("attempts",0) == 0 and r["diagnostics"]["status"] == "unsupported" for r in results),
        "false_accept_count":sum(r["diagnostics"]["status"] == "supported" for r in negative),
        "negative_denominator":len(negative),
        "false_reject_count":sum(r["diagnostics"]["status"] != "supported" for r in positive),
        "positive_denominator":len(positive),
        "total_tokens_reported":sum(r["diagnostics"].get("usage",{}).get("total_tokens",0) for r in results),
        "api_calls":sum(r["diagnostics"].get("attempts",0) for r in results),
        "latency_ms":sum(r["diagnostics"].get("latency_ms",0) for r in results),
        "currency_cost":"not measured; apply verified provider prices separately", "results":results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-models", action="store_true")
    parser.add_argument("--config", type=Path, default=Path(".env"))
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[1] / "tests/fixtures/llm_review_cases.json")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if not args.run_models:
        print(json.dumps({"mode":"dry_run", "case_count":len(cases), "api_calls":0,
                          "maximum_api_calls":len(cases), "quality":"not measured"}, indent=2))
        return
    from dotenv import load_dotenv
    load_dotenv(args.config, override=False)
    reviewer = CitationReviewer(enabled=True)
    generation_model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    if not reviewer.stage.ready or reviewer.stage.model.casefold() == generation_model.casefold():
        raise SystemExit("Configure a different accessible LLM_REVIEW_MODEL before running the judge diagnostic")
    print(json.dumps(evaluate(cases, reviewer, generation_model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

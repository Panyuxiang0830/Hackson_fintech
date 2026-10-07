"""Part A command line.

    python -m contextledger build
    python -m contextledger augment
    python -m contextledger vectors
    python -m contextledger check
    python -m contextledger demo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contextledger.demo_app import serve
from contextledger.pipeline import build, check

DEFAULT_OUT = Path("runtime/part_a")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ContextLedger Part A ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="ingest both corpora into the canonical store")
    build_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    build_parser.add_argument("--limit", type=int, default=None, help="cap each source, for a smoke run")
    build_parser.add_argument(
        "--erag-slack-limit",
        type=int,
        default=3000,
        help="even sample of EnterpriseRAG Slack threads; 0 keeps all of them",
    )

    check_parser = sub.add_parser("check", help="ACL, freshness, FTS, and vector checks")
    check_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)

    augment_parser = sub.add_parser("augment", help="add PrivacyBench Slack/Drive and a Public Jira sample")
    augment_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    augment_parser.add_argument("--privacy-world", action="append", dest="worlds")
    augment_parser.add_argument("--jira-limit", type=int, default=1000)

    vectors_parser = sub.add_parser("vectors", help="embed chunks and build per-company RaBitQ indexes")
    vectors_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    vectors_parser.add_argument("--batch-size", type=int, default=256)

    rechunk_parser = sub.add_parser("rechunk", help="replace derived chunks; rebuild vectors afterwards")
    rechunk_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)

    demo_parser = sub.add_parser("demo", help="open the Part A search demo")
    demo_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    demo_parser.add_argument("--host", default="127.0.0.1")
    demo_parser.add_argument("--port", type=int, default=7860)

    eval_parser = sub.add_parser("eval", help="evaluate reference retrieval, latency, ACL/time boundaries and ANN agreement")
    eval_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    eval_parser.add_argument("--modes", nargs="+", choices=("keyword", "vector", "hybrid"), default=["keyword", "vector", "hybrid"])
    eval_parser.add_argument("--top-k", nargs="+", type=int, default=[1, 5, 10, 20])
    eval_parser.add_argument("--retrieval-depth", type=int, default=20, help="fixed ranking depth, independent of scoring cutoffs (1-80)")
    eval_parser.add_argument("--report", type=Path, default=None, help="JSON report path; default is OUT/evaluation.json")
    eval_parser.add_argument("--repeats", type=int, default=1)
    eval_parser.add_argument("--seed", type=int, default=42)
    eval_parser.add_argument("--limit", type=int, default=None, help="deterministic question sample; default runs all questions")
    eval_parser.add_argument("--ann-queries", type=int, default=32, help="exact chunk-neighbour comparisons; 0 disables")
    eval_parser.add_argument("--threads", type=int, default=1)
    eval_parser.add_argument("--questions", type=Path, default=None, help="override EnterpriseRAG questions with parquet/JSONL/JSON")

    args = parser.parse_args(argv)
    if args.command == "eval":
        from contextledger.evaluation import run_evaluation

        try:
            report = run_evaluation(args.out, modes=tuple(args.modes), cutoffs=tuple(args.top_k),
                                    repeats=args.repeats, seed=args.seed, limit=args.limit,
                                    ann_queries=args.ann_queries, questions_path=args.questions, threads=args.threads,
                                    retrieval_depth=args.retrieval_depth, report_path=args.report)
        except (ValueError, FileNotFoundError, RuntimeError) as error:
            parser.exit(1, f"Evaluation failed: {error}\n")
        scenarios = report["scenarios"]
        # Exit status covers execution and fixture failures, not final acceptance.
        passed = (scenarios["passed"] == scenarios["total"]
                  and scenarios["mvp_audit"]["passed"] == scenarios["mvp_audit"]["total"]
                  and scenarios["gates"]["extractive_prompt_and_answer_leak"] == "passed")
        return 0 if passed else 1
    if args.command == "build":
        slack_limit = None if args.erag_slack_limit == 0 else args.erag_slack_limit
        manifest = build(args.out, limit=args.limit, erag_slack_limit=slack_limit)
        print(json.dumps({"documents": manifest["documents"], "chunks": manifest["chunks"]}, indent=2))
        return 0
    if args.command == "vectors":
        from contextledger.vectors import build_vectors

        build_vectors(args.out, batch_size=args.batch_size)
        return 0
    if args.command == "rechunk":
        from contextledger.rechunk import rechunk

        print(json.dumps(rechunk(args.out), indent=2))
        return 0
    if args.command == "augment":
        from contextledger.supplemental import augment

        report = augment(args.out, worlds=args.worlds, jira_limit=args.jira_limit)
        print(json.dumps({"seconds": report["seconds"], "corpora": len(report["corpora"])}, indent=2))
        return 0
    if args.command == "demo":
        db_path = args.out / "canonical.sqlite"
        if not db_path.exists():
            print(f"missing {db_path}; run: python -m contextledger build")
            return 1
        print(f"Part A demo at http://{args.host}:{args.port}")
        serve(db_path, host=args.host, port=args.port)
        return 0
    report = check(args.out)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

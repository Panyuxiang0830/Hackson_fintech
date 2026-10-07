# Part A Quick Start

Requires Linux x86_64 (AVX2), Python 3.10, Git and a C++17/OpenMP compiler.

Run from the repository root:

```bash
bash scripts/part_a.sh setup
bash scripts/part_a.sh
```

Open <http://127.0.0.1:7860>.

Setup downloads the datasets and model. To restart, run only the second command.

Chunks preserve document titles and section paths and fit the embedding model's
256-token limit. Re-run setup to migrate an existing store, then restart the demo.

Compare chunking: `bash scripts/part_a.sh chunking`.

Evaluate the existing store:

```bash
bash scripts/part_a.sh eval
```

Results: `runtime/part_a/evaluation.json`. Compares keyword, vector and hybrid
retrieval, reports evidence coverage and latency, and tests ACL/time boundaries.
ANN agreement is separate from document recall. Answer quality and streaming
updates are not measured; pre-retrieval ACL isolation is currently unmet.

Tune evidence-document Recall@10 against the 90% target:

```bash
bash scripts/part_a.sh tune
```

Results: `runtime/part_a/retrieval_tuning.json`. Exits with code 1 if validation
misses the target. Candidate coverage is reported separately from final recall.

Refine saved rankings with conservative Qwen replacements:
`bash scripts/part_a.sh refine --help`. Provide the chunked store, baseline,
candidate cache and Qwen score cache listed in the command's help.

Refinement saves `retrieval_refinement.json` in the chunked store. It uses local
BGE/Qwen models (CUDA and Transformers 5.x), chooses conservative replacements
on development questions, and reports validation separately. Contextual vector
candidates are optional (`--vector-additions 40`); disabled by default after a
development comparison found no recall gain. This benchmark has
already been used for tuning; results are regression measurements. Serving is
unchanged.

The saved regression meets the 90% target under that development rule:
all 91.98%, development 96.67%, validation 91.40%, setting `slots2-margin1`.
Candidate-oracle coverage stays separate from final Recall@10.

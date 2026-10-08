# ToT vs. Self-Refine vs. Agentic Program Repair

A small experiment for a 10-minute demo: the same three task families, the same prompts, the same
2023-era models — only the **shape of the reasoning loop** changes.

| Method | Paper | Loop |
|---|---|---|
| `baseline` | — | one shot, no feedback (the floor) |
| `refine` | Self-Refine (Madaan et al. 2023) | linear chain: generate → self-critique → revise, until the model says SOLVED |
| `retry` | Agentic Program Repair (Maddila et al. 2025) | N independent attempts; a real verifier (tests / exact check) decides when to stop |
| `tree` | Tree of Thoughts (Yao et al. 2023) | keep several partials alive, score them, beam-search, stop on a verified answer |

**Tasks** (19 total, all machine-checked): 8 × Game of 24, 5 × Python function writing with tests,
6 × counting a letter in a tricky word.

**Cost axes:** generated tokens, prompt tokens, model calls, wall-clock seconds — per run, per
family, and per *solved* task (the axis that actually matters).

## Run it

```bash
uv sync
ollama serve            # or vLLM; anything OpenAI-compatible
uv run run.py --models llama2:7b-chat mistral:7b-instruct --n 5
```

Ollama tags of the two 2023 models: `ollama pull llama2:7b-chat` and `ollama pull mistral:7b-instruct`.

**Measured on an M2 MacBook (16 GB, Metal, Ollama): roughly 13 generated tokens/sec on a 7B model**,
so the full `--n 5` two-model sweep is about an hour. On a CUDA box with vLLM the same sweep is a few
minutes. Time budget estimates:

| Setup | Runs | Wall clock (M2) |
|---|---|---|
| `--n 1`, one 7B model, all 4 methods | 12 | ~21 min |
| `--n 1`, two 7B models, all 4 methods | 24 | ~42 min (measured) |
| `--n 5`, two 7B models, all 4 methods | 120 | ~3.5 h |
| `--n 1`, `llama3.2:latest` (3B) | 12 | ~7 min |

On the RTX box with vLLM, plan on minutes rather than hours: the reference run above moved ~10k
generated tokens in 42 minutes on the laptop, which is a few seconds of GPU time. `results.json` and
`demo-answers.md` in this repo are the output of the reference run.

Re-print the table from a finished run without re-running anything:

```bash
uv run run.py --summary results.json --models llama2:7b-chat mistral:7b-instruct
```

### On a CUDA box (vLLM, much faster)

```bash
pip install vllm
vllm serve mistralai/Mistral-7B-Instruct-v0.2 --port 8000
BASE_URL=http://localhost:8000/v1 API_KEY=x \
  uv run run.py --models mistralai/Mistral-7B-Instruct-v0.2 meta-llama/Llama-2-7b-chat-hf --n 5
```

`BASE_URL` defaults to `http://localhost:11434/v1` (Ollama) and `API_KEY` to `ollama`; vLLM ignores
the key. Model names are passed through verbatim, so use whatever the server calls them. No code
change is needed to switch machines, and only `uv sync` plus the model pulls are required on the
server.

### Useful flags

```bash
--n 5                  # tasks per family
--steps baseline refine retry tree
--kinds math program writing
--iters 4              # refine: critique/revise rounds
--candidates 3         # retry: independent attempts (the paper's SR@1 -> SR@5 story)
--depth 3 --expand 2 --beam 2   # tree: levels, children per node, partials kept
--max-calls 60         # hard per-task cap so one bad run cannot eat the budget
--show                 # print every model answer (good for the live demo)
--answers answers.md   # dump every full answer, timestamped by run
--out results.json
```

A fast dry run that still produces the full table (~7 min on a 3B model, M2):

```bash
uv run run.py --models llama3.2:latest --n 1
```

Sanity-check that every verifier still accepts its known-good answer, with no model and no server:

```bash
uv run run.py --selftest     # verifiers: 19/19 accept their golden answer
```

## Presenting it

1. **The pitch** (1 min): same model, same prompts, same tasks — only the shape of the loop changes.
   `refine` and `retry` are both linear; only `retry` has a symbolic verifier; only `tree` branches.
2. **The traces** (3 min): the sweep already wrote every raw answer to `demo-answers.md`; scroll
   through it live. Show the `mistral`+`tree` answer that claims 24 for an expression equal to 18,
   then the `llama2` answer that invents numbers and never converges.
3. **The table** (3 min): `uv run run.py --summary results.json --models llama2:7b-chat
   mistral:7b-instruct` re-prints it instantly — no model calls. Lead with solve rate, then
   generated tokens per *solved* task, then wall clock.
4. **The punchline** (3 min): the cheapest structure won, because the verifier — not the tree — is
   what turned extra compute into accuracy. That is the APR paper's 28.5% → 43.9% → 61.0% story in
   miniature, and it is also why ToT's own best results come from tasks with an exact `value` check.

## Things worth knowing before you present

- **Verification is free and exact** (`tasks.py`): unit tests for code, an exhaustive solver for 24, an
  exact letter count. Nothing is graded by a model, so the pass/fail column is trustworthy.
- **The tree scores intermediates, not answers.** Game of 24 gets an exact `can these numbers still
  reach 24?` check, so pruning should have signal; programming gets none, so the tree falls back to
  asking the model to grade its own partial work. That is a call the tree pays for and often gets
  wrong, and it is why `tree` burns tokens without converting them into solves.
- **`tree` is beam search, not full ToT.** ToT's BFS/DFS with MCTS-scale lookahead is out of budget on
  a 7B model; beam search is the paper's own practical choice (their Game of 24 uses BFS with b=5).
- **This is a demo, not a study.** 24 runs on two 7B models is directional only. Raise `--n` before
  quoting any number, and expect the ordering to shift as `n` grows.
- **The comparison is deliberately generous to `tree`:** `refine --iters 4` (the paper's default) and
  `retry --candidates 3`, so total attempts are roughly matched. `tree` also gets a hard
  `--max-calls` budget, which is why it stops after ~7 calls instead of exploding combinatorially.

## Reference run (2 × 7B models, 3 tasks, 24 runs, M2 laptop, 42 min)

Six runs per method (2 models × 3 tasks). Re-print this table straight from the committed results:

```bash
uv run run.py --summary results.json --models llama2:7b-chat mistral:7b-instruct
```

| method | solved | gen-tokens/run | calls/run | sec/run | gen-tokens per **solved** |
|---|---|---|---|---|---|
| baseline | 1/6 | 155 | 1.0 | 9.5 | 931 |
| refine | 1/6 | 690 | 6.2 | 216 | 4141 |
| retry | **2/6** | 381 | 2.5 | 31 | **1144** |
| tree | 2/6 | 741 | 7.2 | 163 | 2222 |

Solve rate by family: programming `retry` 1/2 and `tree` 1/2; writing `retry` 1/2 and `tree` 1/2;
math 0/2 for everything. Llama-2 7B chat scored 0/3 on all four methods; every point came from Mistral.

The story these numbers tell, in three beats:

1. **The verifier is what pays, not the tree.** `retry` (independent attempts, tests decide) matched
   `tree` on solve rate for about half the generated tokens and a fifth of the wall-clock time.
2. **Self-critique is the weakest feedback available.** `refine` was both the most expensive method
   and no better than one shot. Mistral's critique loop happily "confirmed" a strawberry count of 2
   seven times in a row; the model cannot see its own error, and the loop just amplifies confidence.
3. **Search needs a scoreable intermediate.** Math has an exact feasibility check; every method still
   failed it, and `tree` spent the most tokens doing so. Programming has no partial-credit signal, so
   `tree`'s pruning was mostly guesswork — exactly why the APR paper retries with test feedback
   instead of searching a patch tree.

A demo moment worth pausing on: `mistral` + `tree` on Game of 24 produced
`Answer: ((1 * 6) + (1 - 4)) * 6 = 24`, which is 18, not 24 — stated confidently, as a final answer,
after 1252 generated tokens. Fluency is not correctness, and that is the case for verifiers.

## Repository

```
tasks.py    19 tasks + their verifiers (tests, exhaustive search, exact answers) - the ground truth
llm.py      one OpenAI-compatible chat client + the cost bookkeeper
methods.py  the four reasoning strategies (~120 lines)
run.py      the experiment: loops, progress lines, results table
```

Papers: `tree-of-thoughts.pdf`, `self-refine.pdf`, `agent-program-repair.pdf`.

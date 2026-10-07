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

### On a CUDA box (vLLM, much faster)

```bash
pip install vllm
vllm serve mistralai/Mistral-7B-Instruct-v0.2 --port 8000
BASE_URL=http://localhost:8000/v1 API_KEY=x \
  uv run run.py --models mistralai/Mistral-7B-Instruct-v0.2 meta-llama/Llama-2-7b-chat-hf --n 5
```

`BASE_URL` defaults to `http://localhost:11434/v1` (Ollama) and `API_KEY` to `ollama`; vLLM ignores
the key. Model names are passed through verbatim, so use whatever the server calls them.

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
--out results.json
```

A fast dry run that still produces the full table (~1 min on a 3B model):

```bash
uv run run.py --models llama3.2:latest --n 1
```

## What to show in 10 minutes

1. **The pitch** (1 min): same model, same prompts, three papers' search strategies.
2. **One trace each** (3 min): `--show` prints every answer. The interesting one is `tree` on math,
   where the pruning score is an *exact* feasibility check, versus `tree` on programming, where
   there is no useful partial-credit signal and the search is mostly blind.
3. **The table** (3 min): solve rate, then generated tokens per *solved* task.
4. **The punchline** (3 min): where the extra tokens pay off and where they don't.

## Things worth knowing before you present

- **Where the gains come from.** `refine` and `retry` are both linear; only `retry` has a symbolic
  verifier, and only `tree` branches. So the three rows separate "better feedback" from "branching".
- **The tree scores intermediates, not answers.** Game of 24 gets an exact `can these numbers still
  reach 24?` check, so pruning has real signal. Programming gets none — a syntactic check of partial
  code is close to worthless — so the tree degrades to sampling. This is the honest reason the APR
  paper retries with test feedback instead of doing MCTS.
- **Verification is free and exact** (`tasks.py`): tests for code, an exhaustive solver for 24, an
  exact count for words. Nothing is graded by a model, so the pass/fail column is trustworthy.
- **`tree` is beam search, not full ToT.** ToT's BFS/DFS with MCTS-scale lookahead is out of budget on
  a 7B model; beam search is the paper's own practical choice (their Game of 24 uses BFS with b=5).
- **Small-model caveat.** A 7B model from 2023 fails these tasks stochastically. With `--n 5` and two
  models the table is directional, not a significance test. Raise `--n` for anything you quote.
- **Two knobs are deliberately aligned:** `refine --iters 4` (paper default) and `retry
  --candidates 3`. Total attempts are comparable, so the token-cost comparison is roughly fair.

## Repository

```
tasks.py    19 tasks + their verifiers (tests, exhaustive search, exact answers) - the ground truth
llm.py      one OpenAI-compatible chat client + the cost bookkeeper
methods.py  the four reasoning strategies (~120 lines)
run.py      the experiment: loops, progress lines, results table
```

Papers: `tree-of-thoughts.pdf`, `self-refine.pdf`, `agent-program-repair.pdf`.

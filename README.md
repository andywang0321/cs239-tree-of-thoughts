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
--jobs 8               # run several tasks concurrently; raise on a big GPU, keep 1 on a laptop
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

## Running it on the GPU box

Everything below is one-time setup. No code changes are needed to switch machines: the client reads
`BASE_URL` and `API_KEY` from the environment and passes `--models` straight to the server.

### 1. Install uv and the project

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env              # or: export PATH="$HOME/.local/bin:$PATH"
git clone <your-repo-url> tot && cd tot
uv sync                              # creates .venv with openai + seaborn + matplotlib
uv run run.py --selftest             # verifiers work with no model and no network
```

`uv sync` also installs the plotting dependencies, so you can render figures on the server or copy
`results.json` back and plot locally. If `$HOME` is not writable on the box, `plot.py` handles it by
keeping the matplotlib and fontconfig caches in `.mplcache/` beside the script.

### 2. Install Ollama and start it as a service

The installer script wants root. **If you do not have sudo, skip to "Without sudo" below** — Ollama
is one static binary and runs fine entirely out of your home directory.

#### With sudo

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl status ollama         # the installer starts it for you
```

Configure it for a headless box, then restart:

```bash
sudo systemctl edit ollama --force --full     # paste the unit below
```

```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_MODELS=/data/ollama/models"   # point this at the big disk, not $HOME
Environment="OLLAMA_KEEP_ALIVE=30m"               # keep weights resident between runs
Environment="OLLAMA_NUM_PARALLEL=4"               # serve concurrent requests (see --jobs below)
Environment="OLLAMA_MAX_LOADED_MODELS=2"          # both 7B models fit at once on a 6000-class card
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

#### Without sudo

Ollama ships a self-contained binary; the installer's only privileged steps are putting it in
`/usr/local/bin` and registering a systemd unit. Do both by hand in your home directory instead:

```bash
uv run serve.py --install     # resolves the latest GitHub release, unpacks into ~/ollama
export PATH="$HOME/bin:$PATH" # add to ~/.bashrc so it survives logout
```

**The archive layout matters.** It unpacks to `bin/ollama` plus `lib/ollama/*` (CUDA/cuBLAS
libraries), and the binary locates those libraries relative to itself. So it must be extracted
intact — never flattened with `--strip-components`, which both destroys the `bin/`/`lib/` pairing
and leaves a useless `lib/ollama` in your PATH directory. `serve.py --install` extracts into
`~/ollama` (override with `OLLAMA_PREFIX`) and drops a symlink at `~/bin/ollama` for PATH
convenience. The download is ~1.4 GB for amd64 because it bundles CUDA; ~1 GB for arm64.

To do it manually, note the asset is **`.tar.zst`, not `.tgz`** — the old
`ollama.com/download/ollama-linux-amd64.tgz` URL now 404s:

```bash
mkdir -p ~/ollama ~/ollama-models
tag=$(curl -s https://api.github.com/repos/ollama/ollama/releases/latest \
      | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
curl -fL -o /tmp/ollama.tar.zst \
  "https://github.com/ollama/ollama/releases/download/$tag/ollama-linux-amd64.tar.zst"
tar --zstd -xf /tmp/ollama.tar.zst -C ~/ollama      # gives ~/ollama/bin/ollama + ~/ollama/lib/*
~/ollama/bin/ollama --version
```

On an AMD GPU use `ollama-linux-amd64-rocm.tar.zst` instead (`OLLAMA_VARIANT=rocm uv run serve.py
--install`); on ARM use `ollama-linux-arm64.tar.zst`. If `tar --zstd` is unsupported on the box,
install the `zstandard` Python package and `serve.py --install` will use it.

#### "PermissionError: [Errno 13] Permission denied" right after installing

`serve.py --install` sets the file mode to 755 itself, so if exec still fails the *mount* is
refusing to run programs (`noexec`), which is common on managed cluster home directories. The
installer now detects this and says so; to confirm by hand:

```bash
findmnt -T ~/bin -o TARGET,SOURCE,OPTIONS     # look for noexec in OPTIONS
ls -l ~/bin/ollama                            # should be -rwxr-xr-x
file ~/bin/ollama                             # should be ELF 64-bit LSB executable
cp /bin/true ~/bin/_exectest && ~/bin/_exectest; rm -f ~/bin/_exectest
```

If `_exectest` fails too, the directory cannot execute anything. Fix it by installing on a mount
that allows exec — ask the admins, or try any scratch/local/tmp area you can write to and test the
same way:

```bash
for d in /scratch/$USER /local/$USER /tmp/$USER ~/tmp .; do
  mkdir -p "$d" 2>/dev/null && cp /bin/true "$d/_t" 2>/dev/null && "$d/_t" 2>/dev/null \
    && echo "EXEC OK: $d" ; rm -f "$d/_t"
done
```

```bash
OLLAMA_PREFIX=/scratch/$USER/ollama uv run serve.py --install
export PATH="$HOME/bin:$PATH"      # serve.py symlinks the binary into ~/bin
```

Note that `ollama` must *run* from an exec-capable mount, but the model store does not — only be
read — so `OLLAMA_MODELS` can stay on the bigger home filesystem:

Keep the server alive across logouts. `tmux` is the simplest option and is usually already installed;
`nohup` works if it is not:

```bash
tmux new -s ollama
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=$HOME/ollama-models \
  OLLAMA_KEEP_ALIVE=30m OLLAMA_NUM_PARALLEL=4 OLLAMA_MAX_LOADED_MODELS=2 \
  ~/bin/ollama serve
# Ctrl-b d to detach;  tmux attach -t ollama to come back
```

```bash
# no tmux on the box:
nohup env OLLAMA_MODELS=$HOME/ollama-models OLLAMA_KEEP_ALIVE=30m \
  ~/bin/ollama serve > ~/ollama.log 2>&1 &
```

The project wraps all of this in `serve.py`, so you can skip the environment juggling:

```bash
uv run serve.py --check     # binary, version, model store, endpoint, which tags are present
uv run serve.py             # runs `ollama serve` in the foreground, models in ~/ollama-models
uv run serve.py --pull      # downloads both 2023 models (~8 GB) into that store
uv run serve.py --gpu       # nvidia-smi plus whether ollama put the model on the GPU or the CPU
```

`serve.py` is optional — if you already have a server running, `run.py` just talks HTTP to it. Point
`BASE_URL` elsewhere (e.g. `BASE_URL=http://127.0.0.1:8000/v1` for vLLM) and nothing else changes.

#### Both cases: verify the GPU is really being used

```bash
ollama run llama2:7b-chat "say hi"           # then, in another shell:
uv run serve.py --gpu                        # or: ollama ps
```

`PROCESSOR` (or `serve.py`'s verdict) must read **100% GPU**. If it says CPU, your driver/CUDA
runtime is wrong; fix that before running the sweep, because a CPU fallback is 20-50x slower and will
make the `seconds` column meaningless.

### 3. Pull the two 2023 models

```bash
ollama pull llama2:7b-chat        # ~3.8 GB
ollama pull mistral:7b-instruct   # ~4.4 GB
ollama list
```

The names above are what `run.py` defaults to. If you use a different tag, pass it through `--models`.

### 4. Smoke test before the sweep

Run the two cheapest methods on one task per family and confirm the numbers look sane. If the
`PROCESSOR` column shows GPU and the tokens/sec are in the hundreds, you are ready.

```bash
uv run run.py --models llama2:7b-chat mistral:7b-instruct --n 1 \
  --steps baseline retry --jobs 4 --out smoke.json
```

Watch the `sec/run` and `gen-tok` columns in the summary: divide generated tokens by seconds to get
your real throughput, then use it to size the full run. The reference sweep generated roughly 600k
tokens for `--n 6` across two models, so at 400 tok/s that is about 25 minutes of pure generation.

### 5. The full sweep

```bash
uv run run.py \
  --models llama2:7b-chat mistral:7b-instruct \
  --n 6 \
  --jobs 6 \
  --out results-full.json \
  --answers answers-full.md
```

`--jobs` is the only knob that changes with the hardware. Ollama serves each model with
`OLLAMA_NUM_PARALLEL` slots, so keep `--jobs` at or below `NUM_PARALLEL x number of loaded models`,
or requests will queue and the wall-clock column will look worse than the tokens column suggests.
Note that every run inside one process shares nothing but the HTTP server, so `--jobs` is safe.

For a longer or shorter study, vary only `--n` (tasks per family, max 8 math / 5 program / 6 writing)
and `--candidates`/`--iters` if you want to push the retry and refine arms harder.

### 6. Plot

```bash
uv run plot.py --results results-full.json --out comparison.png
uv run plot.py --results results-full.json --metric seconds --out comparison-seconds.png
```

`plot.py` prints the same summary table as `run.py`, so you can check the numbers before you trust
the picture. Better still, copy the results file back to your laptop and plot there:

```bash
scp gpu-box:~/tot/results-full.json .
uv run plot.py --results results-full.json
```

The figure has four panels: (a) solve rate by method and model, (b) solve rate against generated
tokens *per solved task* with a Pareto frontier, (c) solve rate per task family, and (d) the token
distribution split by whether the task was solved. Panel (b) is the one that carries the argument.


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

## Main run (2 × 7B models, 19 tasks, 136 runs, 2 × RTX PRO 6000 Blackwell, ~20 min)

The full task set: 6 × Game of 24, 5 × Python-with-tests, 6 × letter counting, per model per method.

```bash
CUDA_VISIBLE_DEVICES=0,1 OLLAMA_NUM_PARALLEL=4 OLLAMA_KEEP_ALIVE=30m uv run run.py \
  --models llama2:7b-chat mistral:7b-instruct --steps baseline refine retry tree \
  --n 6 --jobs 6 --out results-full.json --answers answers-full.md
uv run plot.py --results results-full.json --out comparison.png --tables TABLES.md
```

| Method | llama2:7b-chat | mistral:7b-instruct | Overall | tokens/solve | calls/run | sec/run |
|---|---|---|---|---|---|---|
| Baseline (IO) | 6% | 35% | 21% | 606 | 1.0 | 2.1 |
| Self-Refine | 12% | 24% | 18% | 3,567 | 5.7 | 10.0 |
| Agentic-Program-Repair | 24% | 47% | **35%** | **1,340** | 2.5 | 6.1 |
| Tree-of-Thought | 6% | **53%** | 29% | 2,776 | 6.9 | 11.2 |

| Method | Game of 24 | Python + tests | letter counting |
|---|---|---|---|
| Baseline (IO) | 0% | 30% | 33% |
| Self-Refine | 0% | 20% | 33% |
| Agentic-Program-Repair | 0% | 40% | **67%** |
| Tree-of-Thought | **8%** | 40% | 42% |

What this run says, and where it differs from the laptop:

1. **Tree-of-Thought is the best method on a capable model and the worst value on a weak one.**
   It wins outright on Mistral (53% vs 47%) and collapses on Llama-2 (6%, *below* one-shot). Its
   cost per solve differs 9x between the two models (14,045 vs 1,524 tokens) for the same code and
   prompts — so ToT's payoff tracks how often the base model can actually produce a good thought.
2. **Agentic-Program-Repair wins on aggregate** (35%) at 1,340 tokens per solve, less than half of
   Self-Refine's 3,567. Retries plus an exact verifier is the best quality-per-token on every family
   except pure math.
3. **Self-Refine loses to one-shot on both models** (18% vs 21%). Linear self-critique, at 5.7x the
   calls and 5.9x the tokens, produced no net gain — the model's critique is only as good as the
   model.
4. **Game of 24 is out of reach for 7B models.** 71 of 72 attempts failed; ToT's single success is
   the only one. Verified it is not a format artifact: an unlabeled-answer scan found zero correct
   solutions rejected for missing the `Answer:` line.

Method naming follows the papers: Baseline (IO) = plain input-output prompting, Self-Refine
(Madaan et al. 2023), Agentic-Program-Repair (Maddila et al. 2025), Tree-of-Thought (Yao et al. 2023).

A demo moment worth pausing on: `mistral` + `tree` on Game of 24 produced
`Answer: ((1 * 6) + (1 - 4)) * 6 = 24`, which is 18, not 24 — stated confidently, as a final answer,
after 1252 generated tokens. Fluency is not correctness, and that is the case for verifiers.

## Repository

```
tasks.py    19 tasks + their verifiers (tests, exhaustive search, exact answers) - the ground truth
llm.py      one OpenAI-compatible chat client + the cost bookkeeper
methods.py  the four reasoning strategies (~120 lines)
run.py      the experiment: loops, progress lines, results table
serve.py    start Ollama without root, pull models, verify GPU offload
plot.py     the figure: solve rate, cost per solve, per family, token placement
```

Papers: `tree-of-thoughts.pdf`, `self-refine.pdf`, `agent-program-repair.pdf`.

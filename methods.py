"""The four strategies under comparison.

  baseline  - one shot, no feedback                       (the floor)
  refine    - Self-Refine: linear loop, the model critiques itself and revises
  retry     - Agentic repair: N independent attempts, a real verifier says when to stop
  tree      - Tree-of-Thoughts: keep several partials alive, verifier-guided beam search

Cost is tracked by llm.Budget (model calls, generated tokens, prompt tokens, wall time).
"""
import re

from llm import Budget, LLM
from tasks import _can_reach, _remaining, extract_code

METHODS = ["baseline", "refine", "retry", "tree"]


def template(t, artifact="your final answer", prev=None, expand=False):
    """One prompt builder shared by every task and method, so the only difference between
    methods is the shape of the search, not the wording of the question."""
    body = t.prompt
    if t.examples:
        shown = "\n\n".join(f"Example input: {e[0]}\nExample output:\n{e[-1]}" for e in t.examples)
        body = f"{shown}\n\nNow do this one.\n{body}"
    head = f"You are solving a {t.kind} problem. Work it out, then output {artifact}.\n"
    if prev is not None:
        body = f"Problem:\n{t.prompt}\n\nYour work so far:\n{prev}\n\n{body}"
        head += ("Do not start over. Continue from the work above and output the full updated "
                 "answer, keeping everything that was already correct.\n")
    else:
        head += "\n"
    if expand:
        body += ("\n\nTry a DIFFERENT approach or fix a mistake. Output the full result only, "
                 "no commentary.")
    return head + body


def state_of(t, text):
    """What the tree carries forward as a node: the checkable artifact, not the model's prose."""
    if t.kind == "program":
        return extract_code(text)
    if t.kind == "writing":
        m = re.search(r"^.*letters in order:.*$", text, re.I | re.M)
        return m.group(0).strip() if m else text.strip()
    return text.strip()


SCORE_PROMPT = """Score each candidate 0-9 for how promising it is toward solving the problem \
(9 = certainly on the right track). Reply with exactly one digit per candidate, in order, \
on a single line.

Problem: {p}
{opts}
Scores:"""

_seen = set()


def score_group(llm, t, texts):
    """One scoring call for a whole frontier, like the paper's vote prompt which analyzes several
    states at once. Math gets the exact feasibility check; everything else asks the model to grade
    its own partial work, which costs a call and is only as good as the model's judgment.
    Cached repeats rank below fresh states so the search keeps moving instead of looping."""
    scores, todo = [], []
    for txt in texts:
        key = (t.id, txt[:300])
        if t.kind == "math" and t.score:
            scores.append(1.0 if t.score(txt) else 0.0)   # exact, no model call needed
        elif key in _seen:
            scores.append(0.4)                            # already looked at: rank it lower
        else:
            _seen.add(key)
            todo.append(len(scores))
            scores.append(None)
    if todo:
        opts = "\n\n".join(f"Candidate {i + 1}:\n{texts[i][:900]}" for i in todo)
        raw = llm(SCORE_PROMPT.format(p=t.prompt, opts=opts),
                  system="You are a strict grader.", temperature=0.0, max_tokens=24)
        got = [int(d) / 9 for d in re.findall(r"\d", raw)][:len(todo)]
        for i, s in zip(todo, got + [0.0] * (len(todo) - len(got))):
            scores[i] = s
    return scores


# ------------------------------------------------------------------ the methods
def run_baseline(task, llm, **kw):
    return llm(template(task), system="You are a careful problem solver.", temperature=0.0, max_tokens=450)


def run_refine(task, llm, iters=4, **kw):
    """Self-Refine (Madaan et al. 2023): FEEDBACK then REFINE on the same single chain."""
    out = llm(template(task), system="You are a careful problem solver.", temperature=0.7, max_tokens=450)
    for _ in range(iters - 1):
        fb = llm(template(task, artifact="your critique", prev=state_of(task, out)) +
                 "\n\nCheck it against every requirement. If it is already fully correct reply with "
                 "exactly SOLVED. Otherwise give one specific fix and stop.",
                 system="You are a strict reviewer.", temperature=0.0, max_tokens=120)
        if "SOLVED" in fb.strip().upper()[:40]:
            break
        out = llm(template(task, prev=f"{state_of(task, out)}\n\nReviewer feedback:\n{fb}"),
                  system="You are a careful problem solver.", temperature=0.7, max_tokens=450)
    return out


RETRY_HINT = ("Start again from scratch with a DIFFERENT approach.\n"
              "The previous attempt was rejected by the automated verifier ({why}).\n"
              "Do not repeat it.\n\nRejected attempt:\n{prev}")


def run_retry(task, llm, n=3, why="it failed the tests", **kw):
    """The Agentic-Program-Repair shape: independent attempts, a symbolic verifier
    (tests / exact answer check) decides success, no refinement of a failed attempt."""
    out = ""
    for _ in range(n):
        prompt = template(task)
        if out:
            prompt += "\n\n" + RETRY_HINT.format(why=why, prev=state_of(task, out))
        out = llm(prompt, system="You are a careful problem solver.",
                  temperature=0.9, max_tokens=450)
        if task.final(out):
            return out
    return out


def run_tree(task, llm, depth=None, expand=2, beam=2, **kw):
    """Tree-of-Thoughts beam search: expand several partials, score them, keep the best,
    and stop as soon as a candidate passes the final check."""
    depth = depth or (3 if task.kind == "math" else 2)
    nodes = [None]
    for _ in range(depth):
        cands = [llm(template(task, prev=node, expand=True),
                     system="You are a careful problem solver.", temperature=0.8, max_tokens=450)
                 for node in nodes for _ in range(expand)]
        for c in cands:
            if task.final(c):
                return c
        states = {state_of(task, c): c for c in cands}
        unique = list(states)
        ranked = sorted(zip(unique, score_group(llm, task, unique)), key=lambda p: p[1], reverse=True)
        nodes = [states[s] for s, _ in ranked[:beam]]
    return nodes[0]


RUNNERS = {"baseline": run_baseline, "refine": run_refine, "retry": run_retry, "tree": run_tree}


def solve(method, task, model, max_calls=60, **params):
    """Run one method on one task. Returns (raw output, cost dict)."""
    budget = Budget(max_calls=max_calls)
    llm = LLM(model, budget)
    note = ""
    try:
        out = RUNNERS[method](task, llm, **params)
    except Exception as e:  # budget exhausted, or the model server hiccuped
        out, note = "", f"{type(e).__name__}: {e}"[:160]
    return out, {"calls": budget.calls, "gen_tokens": budget.gen_tokens,
                 "prompt_tokens": budget.prompt_tokens, "seconds": round(budget.seconds, 1),
                 "note": note}

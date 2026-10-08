"""Run the comparison: 4 strategies x 3 task families x N tasks x M small 2023-era models.

    uv run run.py --models llama2:7b-chat mistral:7b-instruct --n 5
    uv run run.py --models mistral:7b-instruct --steps baseline refine --kinds math --n 2
    uv run run.py --models llama2:7b-chat --kinds program --show     # print every answer

Server: any OpenAI-compatible endpoint, set BASE_URL (default http://localhost:11434/v1 = Ollama).
"""
import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import methods
from tasks import TASKS

TEMPLATE = "llama2:7b-chat mistral:7b-instruct"


GOLDEN = {
    "g24-0": "Answer: (1-1)+(4*6)", "g24-1": "Answer: 8/(3-8/3)", "g24-2": "Answer: (4-10)*(9-13)",
    "g24-3": "Answer: 5*(5-1/5)", "g24-4": "Answer: 12/(3-(5/2))", "g24-5": "Answer: 6+6+6+6",
    "g24-6": "Answer: 5*(5-1/5)", "g24-7": "Answer: (2*(7+9))-8",
    "prog-merge_intervals": "def merge_intervals(xs):\n    xs=sorted(xs); out=[]\n    for a,b in xs:\n"
                            "        if out and a<=out[-1][1]: out[-1][1]=max(out[-1][1],b)\n"
                            "        else: out.append([a,b])\n    return out",
    "prog-rotate": "def rotate(m):\n    m[:] = [list(r) for r in zip(*m[::-1])]",
    "prog-kth_largest": "def kth_largest(n, k):\n    return sorted(n, reverse=True)[k-1]",
    "prog-parse_formula": """def parse_formula(s):
    stack, cur, i = [{}], {}, 0
    while i < len(s):
        c = s[i]
        if c == "(":
            stack.append(cur); cur = {}
        elif c == ")":
            j = i + 1
            while j < len(s) and s[j].isdigit(): j += 1
            top, cur = cur, stack.pop()
            for k, v in top.items(): cur[k] = cur.get(k, 0) + v * int(s[i+1:j] or 1)
            i = j - 1
        elif c.isdigit():
            pass
        else:
            j = i + 1
            while j < len(s) and s[j].islower(): j += 1
            k = j
            while k < len(s) and s[k].isdigit(): k += 1
            cur[s[i:j]] = cur.get(s[i:j], 0) + int(s[j:k] or 1)
            i = k - 1
        i += 1
    return cur""",
    "prog-merge_sorted_arrays": "def merge_sorted_arrays(a, b):\n    out, i, j = [], 0, 0\n"
                                "    while i < len(a) and j < len(b):\n"
                                "        if a[i] <= b[j]: out.append(a[i]); i += 1\n"
                                "        else: out.append(b[j]); j += 1\n"
                                "    return out + a[i:] + b[j:]",
    "count-strawberry": "Letters in order: s t r a w b e r r y\nAnswer: 3",
    "count-raspberry": "Letters in order: r a s p b e r r y\nAnswer: 3",
    "count-Mississippi": "Letters in order: M i s s i s s i p p i\nAnswer: 4",
    "count-bookkeeper": "Letters in order: b o o k k e e p e r\nAnswer: 2",
    "count-dreadnought": "Letters in order: d r e a d n o u g h t\nAnswer: 2",
    "count-refrigerator": "Letters in order: r e f r i g e r a t o r\nAnswer: 4",
}


def selftest():
    """No model needed: every task must accept its known-good answer and reject a junk one."""
    bad = [t.id for t in TASKS if not t.final(GOLDEN[t.id])]
    for t in TASKS:
        if t.id in bad:
            print(f"  FAIL {t.id} rejects its own golden answer")
    print(f"verifiers: {len(TASKS) - len(bad)}/{len(TASKS)} accept their golden answer"
          + (f" -> {bad}" if bad else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=TEMPLATE.split(), help="model names on the server")
    ap.add_argument("--steps", nargs="+", default=methods.METHODS, choices=methods.METHODS)
    ap.add_argument("--kinds", nargs="+", default=["math", "program", "writing"])
    ap.add_argument("--n", type=int, default=5, help="tasks per family")
    ap.add_argument("--iters", type=int, default=4, help="refine: feedback/refine rounds")
    ap.add_argument("--candidates", type=int, default=3, help="retry: independent attempts")
    ap.add_argument("--depth", type=int, default=0, help="tree: expansion levels (0 = task default)")
    ap.add_argument("--expand", type=int, default=2, help="tree: children per node")
    ap.add_argument("--beam", type=int, default=2, help="tree: partials kept per level")
    ap.add_argument("--max-calls", type=int, default=60, help="hard cap of model calls per task")
    ap.add_argument("--jobs", type=int, default=1,
                    help="runs in parallel; raise it on a big GPU, keep 1 on a laptop")
    ap.add_argument("--show", action="store_true", help="print each answer")
    ap.add_argument("--answers", default="", help="also dump every answer to this file")
    ap.add_argument("--selftest", action="store_true", help="check all verifiers offline, no model")
    ap.add_argument("--summary", metavar="RESULTS.json",
                    help="re-print the table from a saved run; pass the same --steps/--models as "
                         "that run to control the table layout")
    ap.add_argument("--out", default="results.json")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.summary:
        return report(json.load(open(a.summary)), a.steps, a.models)

    tasks = []
    for kind in a.kinds:
        tasks += [t for t in TASKS if t.kind == kind][: a.n]

    kwargs = {"iters": a.iters, "n": a.candidates, "expand": a.expand, "beam": a.beam}
    if a.depth:
        kwargs["depth"] = a.depth
    work = [(m, s, t) for m in a.models for s in a.steps for t in tasks]

    print(f"{len(a.models)} models x {len(a.steps)} methods x {len(tasks)} tasks"
          f" = {len(work)} runs, {a.jobs} at a time\n")
    rows, t_start = [], time.time()
    done = 0

    def one(item):
        model, step, t = item
        out, cost = methods.solve(step, t, model, a.max_calls, **kwargs)
        return dict(model=model, method=step, task=t.id, kind=t.kind,
                    solved=t.final(out), answer=out.strip(), **cost)

    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for r in pool.map(one, work):
            rows.append(r)
            done += 1
            tail = (r["answer"].strip().splitlines() or [""])[-1][:56]
            print(f"[{done:3}/{len(work)}] {r['model']:22} {r['method']:9} {r['task']:26} "
                  f"{'PASS' if r['solved'] else 'fail':4} {r['calls']:2} calls "
                  f"{r['gen_tokens']:5} gen-tok {r['seconds']:6.1f}s  {tail}")
            if a.show:
                print("\n".join("      | " + l for l in r["answer"].splitlines()[:14]))

    with open(a.out, "w") as f:
        json.dump(rows, f, indent=1)
    if a.answers:
        with open(a.answers, "w") as f:
            for r in rows:
                f.write(f"### {r['model']} | {r['method']} | {r['task']} | "
                        f"{'PASS' if r['solved'] else 'fail'} | {r['gen_tokens']} gen-tokens\n"
                        f"{r['answer']}\n\n")
    report(rows, a.steps, a.models)
    print(f"\nwall clock {time.time() - t_start:.0f}s -> {a.out}")


def report(rows, steps, models):
    print("\n=== solve rate (pass / total) ===")
    head = "method    " + "".join(f"{m.split(':')[0][:14]:>16}" for m in models) + "     overall"
    print(head)
    for s in steps:
        cells = ""
        for m in models:
            rs = [r for r in rows if r["method"] == s and r["model"] == m]
            cells += f"{sum(r['solved'] for r in rs)}/{len(rs):<14}"
        rs = [r for r in rows if r["method"] == s]
        print(f"{s:10}" + cells + f"  {sum(r['solved'] for r in rs)}/{len(rs)}")

    print("\n=== cost per solved task (generated tokens, all runs) ===")
    print(f"{'method':10}{'solved':>8}{'gen-tok/run':>13}{'gen-tok/solved':>16}{'sec/run':>10}{'calls/run':>11}")
    for s in steps:
        rs = [r for r in rows if r["method"] == s]
        ok = sum(r["solved"] for r in rs)
        gen = sum(r["gen_tokens"] for r in rs)
        print(f"{s:10}{ok:>8}{gen / len(rs):>13.0f}{(gen / ok if ok else float('inf')):>16.0f}"
              f"{sum(r['seconds'] for r in rs) / len(rs):>10.1f}"
              f"{sum(r['calls'] for r in rs) / len(rs):>11.1f}")

    print("\n=== by task family ===")
    fam = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        c = fam[(r["method"], r["kind"])]
        c[0] += r["solved"]
        c[1] += 1
        c[2] += r["gen_tokens"]
        c[3] += r["seconds"]
    for (s, k), (ok, tot, gen, sec) in sorted(fam.items()):
        print(f"  {s:10}{k:9}{ok}/{tot:<5}tokens/run {gen / tot:6.0f}   sec/run {sec / tot:5.1f}")

    print("\n=== mean generated tokens, split by outcome ===")
    for s in steps:
        rs = [r for r in rows if r["method"] == s]
        win = [r["gen_tokens"] for r in rs if r["solved"]]
        lose = [r["gen_tokens"] for r in rs if not r["solved"]]
        f = lambda v: f"{sum(v) / len(v):.0f}" if v else "-"      # noqa: E731
        print(f"  {s:10} solved {f(win):>7}   unsolved {f(lose):>7}")


if __name__ == "__main__":
    main()

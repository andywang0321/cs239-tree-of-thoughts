"""Plot the comparison one task at a time, because the aggregate numbers hide which task is which.

    uv run plot.py                                   # data/results.json -> visuals/*.png
    uv run plot.py --results data/results-full.json --tables visuals/TABLES.md
    uv run plot.py --results data/results-full.json --no-figure    # tables only

Figures written (all keep every datapoint separated by task):
    visuals/per-task-matrix.png   who solved which task, for every method and model
    visuals/per-task-cost.png     generated tokens spent on each task, pass or fail
    visuals/cost-quality.png      aggregate: solve rate against tokens per solved task
"""
import argparse
import json
import os

# Keep matplotlib's and fontconfig's caches inside the project: on headless boxes $HOME is often not
# writable, which otherwise fails with "Fontconfig error: No writable cache directories".
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("MPLCONFIGDIR", os.path.join(_HERE, ".mplcache"))
os.environ.setdefault("XDG_CACHE_HOME", os.path.join(_HERE, ".mplcache"))
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

METHODS = ["baseline", "refine", "retry", "tree"]
# NAMES is the single source of truth for display names; run.py imports it for its tables.
NAMES = {"baseline": "Baseline (IO)", "refine": "Self-Refine",
         "retry": "Agentic-Program-Repair", "tree": "Tree-of-Thought"}
SHORT = NAMES
# short forms for dense figures, full names for one-per-slide figures and all tables
TINY = {"baseline": "Baseline", "refine": "Self-Refine", "retry": "Agentic-PR", "tree": "Tree-of-Th"}
MARKER = {"baseline": "o", "refine": "s", "retry": "^", "tree": "D"}
PALETTE = {"baseline": "#555555", "refine": "#D55E00", "retry": "#009E73", "tree": "#0072B2"}
MODELS = {"llama2:7b-chat": "Llama-2 7B", "mistral:7b-instruct": "Mistral 7B"}
FAMILY = {"math": "Game of 24", "program": "Python + tests", "writing": "Letter counting"}
NICE = {"g24": "Game of 24", "prog": "code", "count": "count"}


def label(task_id):
    """g24-2 -> both a readable name and its family, for axes and tables."""
    if task_id.startswith("g24"):
        return f"Game of 24 #{task_id.split('-')[1]}", "math"
    if task_id.startswith("prog-"):
        return task_id[5:].replace("_", " "), "program"
    return task_id[6:].lower(), "writing"


def load(path):
    df = pd.DataFrame(json.load(open(path)))
    df["solved"] = df["solved"].astype(bool)
    df["task_name"] = df["task"].map(lambda t: label(t)[0])
    df["kind_label"] = df["task"].map(lambda t: FAMILY[label(t)[1]])
    df["name"] = df["method"].map(SHORT)
    return df


def task_order(df):
    """Group by family, hardest family first, then by how many of the 8 runs solved each task."""
    counts = df.groupby("task")["solved"].sum()
    rows = sorted(counts.index, key=lambda t: (["math", "program", "writing"].index(label(t)[1]),
                                               counts[t], label(t)[0]))
    return [(t, label(t)[0], FAMILY[label(t)[1]]) for t in rows]


def summary(df):
    g = df.groupby(["method", "model"], as_index=False).agg(
        runs=("solved", "size"), solved=("solved", "sum"),
        gen_tokens=("gen_tokens", "sum"), seconds=("seconds", "sum"), calls=("calls", "sum"))
    g["rate"] = g["solved"] / g["runs"]
    g["tok_per_solve"] = [t / s if s else float("nan")
                          for t, s in zip(g["gen_tokens"], g["solved"])]
    g["name"] = g["method"].map(SHORT)
    return g


def pooled(df):
    p = df.groupby("method").agg(ok=("solved", "sum"), runs=("solved", "size"),
                                 tok=("gen_tokens", "sum"), secs=("seconds", "sum"),
                                 calls=("calls", "sum"))
    p["rate"] = p["ok"] / p["runs"]
    p["tok_per_solve"] = p["tok"] / p["ok"]
    p["name"] = p.index.map(SHORT)
    return p.sort_values("rate", ascending=False)


def _save(fig, outdir, name):
    path = os.path.join(outdir, name)
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")
    return path


# ------------------------------------------------------------------ figures
def fig_matrix(df, outdir, path="per-task-matrix.png"):
    """One cell per task x method x model. This is the figure the whole story hangs on:
    it shows the 6 tasks nobody solved, and that each method owns different tasks."""
    order = task_order(df)
    cols = [(m, mod) for m in METHODS for mod in sorted(df["model"].unique())]
    fig, ax = plt.subplots(figsize=(11.5, 7.4))
    for i, (tid, _, _) in enumerate(order):
        for j, (m, mod) in enumerate(cols):
            row = df[(df.task == tid) & (df.method == m) & (df.model == mod)]
            ok = bool(row["solved"].iloc[0])
            ax.plot(j, i, marker="o", markersize=13,
                    color=PALETTE[m] if ok else "#E4E4E4",
                    markeredgecolor="white" if ok else "#CCCCCC", markeredgewidth=1.2, zorder=3)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([MODELS[mod].replace(" 7B", "") + "\n" + TINY[m] for m, mod in cols],
                       fontsize=9.5)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([n for _, n, _ in order], fontsize=10)
    for i, (_, _, fam) in enumerate(order):
        if i and fam != order[i - 1][2]:
            ax.axhline(i - .5, color="#999999", lw=1.2, zorder=1)
    for k in (2, 4, 6):
        ax.axvline(k - .5, color="#BBBBBB", lw=.8, ls=":", zorder=1)
    ax.set_xlim(-.6, len(cols) - .4)
    ax.set_ylim(len(order) - .5, -.5)
    ax.grid(False)
    ax.set_title("Which tasks each method solved\nfilled dot = solved, grey dot = failed "
                 "(each dot is one run)", fontsize=13)
    handles = [Line2D([], [], marker="o", ls="", color=PALETTE[m], markersize=11,
                      label=SHORT[m]) for m in METHODS]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, -.07), ncol=4,
              frameon=False, fontsize=10)
    return _save(fig, outdir, path)


def fig_per_task_cost(df, outdir, path="per-task-cost.png"):
    """Tokens spent per task, every task on its own row: shows that failure is expensive."""
    order = task_order(df)
    fig, ax = plt.subplots(figsize=(11.5, 7.4))
    for i, (tid, _, _) in enumerate(order):
        sub = df[df.task == tid]
        for _, r in sub.iterrows():
            ax.plot(r["gen_tokens"], i + {"baseline": -.22, "refine": -.07,
                                          "retry": .08, "tree": .22}[r["method"]],
                    marker=MARKER[r["method"]], markersize=8,
                    color=PALETTE[r["method"]] if r["solved"] else "none",
                    markeredgecolor=PALETTE[r["method"]], markeredgewidth=1.2, alpha=.95, zorder=3)
    for i, (_, _, fam) in enumerate(order):
        if i and fam != order[i - 1][2]:
            ax.axhline(i - .5, color="#999999", lw=1.2, zorder=1)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([n for _, n, _ in order], fontsize=10)
    ax.set_ylim(len(order) - .5, -.5)
    ax.set_xscale("log")
    ax.set_xlabel("generated tokens on that task (log scale)")
    ax.set_title("What each task cost\nfilled marker = solved, hollow = failed "
                 "(2 models per method)", fontsize=13)
    handles = [Line2D([], [], marker=MARKER[m], ls="", color=PALETTE[m], markersize=9,
                      label=SHORT[m]) for m in METHODS]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, -.07), ncol=4,
              frameon=False, fontsize=10)
    return _save(fig, outdir, path)


def fig_cost_quality(g, outdir, path="cost-quality.png"):
    """Aggregate trade-off. Kept for the summary slide, with the caveat that it pools all tasks."""
    fig, ax = plt.subplots(figsize=(9, 6))
    plot = g.dropna(subset=["tok_per_solve"])
    for m in METHODS:
        sub = plot[plot.method == m]
        if len(sub):
            ax.plot(sub["tok_per_solve"], sub["rate"], marker=MARKER[m], ls="",
                    color=PALETTE[m], markersize=15, markeredgecolor="black",
                    markeredgewidth=.7, label=SHORT[m], zorder=3)
    ok = plot.sort_values("tok_per_solve")
    front = [r for _, r in ok.iterrows() if not (
        (ok["tok_per_solve"] <= r["tok_per_solve"]) & (ok["rate"] >= r["rate"]) &
        ((ok["tok_per_solve"] < r["tok_per_solve"]) | (ok["rate"] > r["rate"]))).any()]
    if len(front) > 1:
        f = pd.DataFrame(front).sort_values("tok_per_solve")
        ax.plot(f["tok_per_solve"], f["rate"], "k--", lw=1.4, alpha=.7, zorder=2,
                label="Pareto frontier")
    for _, r in plot.iterrows():
        ax.annotate(MODELS[r["model"]].replace(" 7B", ""), (r["tok_per_solve"], r["rate"]),
                    xytext=(0, 13), textcoords="offset points", ha="center",
                    fontsize=8.5, color="#444")
    ax.set(xscale="log", xlabel="generated tokens per solved task (log scale)",
           ylabel="share of all 17 tasks solved", ylim=(-.06, 1.0))
    ax.set_title("Quality against cost, all tasks pooled\n(the per-task figures above show "
                 "why this pooling is misleading)", fontsize=12)
    ax.legend(fontsize=9.5, loc="upper left", frameon=True)
    return _save(fig, outdir, path)


# ------------------------------------------------------------------- tables
def table(df, g):
    print("\n=== solve rate ===")
    per = g.pivot_table(index="name", columns="model", values="rate")
    per["overall"] = df.groupby("method")["solved"].mean().rename(SHORT)
    per = per.reindex([SHORT[m] for m in METHODS])
    print(per.map(lambda v: f"{v:.0%}" if pd.notna(v) else "-").to_string())

    print("\n=== cost per solved task (generated tokens) ===")
    cost = g.pivot_table(index="name", columns="model", values="tok_per_solve")
    cost = cost.reindex([SHORT[m] for m in METHODS])
    p = pooled(df).set_index("name").reindex(cost.index)
    cost["overall"] = p["tok_per_solve"]
    out = pd.concat([cost.round(0),
                     pd.DataFrame({"calls/run": (p["calls"] / p["runs"]).round(1),
                                   "sec/run": (p["secs"] / p["runs"]).round(1)})], axis=1)
    print(out.to_string(na_rep="not solved"))

    print("\n=== solve rate by task family ===")
    fam = df.pivot_table(index="task_name", columns="kind_label", values="solved", aggfunc="mean")
    fam["family"] = [label(t)[1] for t in
                     df.drop_duplicates("task_name").set_index("task_name").loc[fam.index, "task"]]
    fam["n_tasks"] = df.drop_duplicates("task_name").groupby("task_name")["task"].size().reindex(fam.index)
    print(fam.to_string())


def markdown(df, g, path, results):
    order = [SHORT[m] for m in METHODS if SHORT[m] in set(g["name"])]
    models = sorted(df["model"].unique())
    out = [f"<!-- generated by: uv run plot.py --results {results} --tables {path} -->", ""]

    out += ["### Solve rate", "", "| Method | " + " | ".join(MODELS[m] for m in models)
            + " | Overall |", "|---|" + "---|" * (len(models) + 1)]
    for n in order:
        row = [f"{g[(g.name == n) & (g.model == m)]['rate'].mean():.0%}" for m in models]
        sub = df[df.name == n]
        out.append(f"| {n} | " + " | ".join(row) + f" | {sub['solved'].mean():.0%} |")

    out += ["", "### Cost per solved task (generated tokens)", "",
            "| Method | " + " | ".join(MODELS[m] for m in models)
            + " | Overall | Calls/run | Sec/run |", "|---|" + "---|" * (len(models) + 3)]
    p = pooled(df).set_index("name")
    for n in order:
        cells = []
        for m in models:
            v = g[(g.name == n) & (g.model == m)]["tok_per_solve"].iloc[0]
            cells.append("not solved" if pd.isna(v) else f"{v:,.0f}")
        out.append(f"| {n} | " + " | ".join(cells)
                   + f" | {p.loc[n, 'tok_per_solve']:,.0f} "
                   + f"| {p.loc[n, 'calls'] / p.loc[n, 'runs']:.1f} "
                   + f"| {p.loc[n, 'secs'] / p.loc[n, 'runs']:.1f} |")

    out += ["", "### Per task: how many of the 8 runs solved it", "",
            "| Task | Family | Solved | Methods that solved it |", "|---|---|---|---|"]
    for tid, name, fam in task_order(df):
        sub = df[df.task == tid]
        solvers = sorted({SHORT[m] for m in sub[sub.solved]["method"]})
        out.append(f"| {name} | {fam} | {sub['solved'].sum()}/8 | "
                   + (", ".join(solvers) if solvers else "**none**") + " |")

    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"wrote {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="data/results.json", help="run output to read")
    ap.add_argument("--outdir", default="visuals", help="where the figures go")
    ap.add_argument("--tables", metavar="TABLES.md", help="also write the tables as markdown")
    ap.add_argument("--no-figure", action="store_true", help="tables only")
    a = ap.parse_args()
    sns.set_theme(style="whitegrid", context="talk", font_scale=0.9)
    df = load(a.results)
    g = summary(df)
    p = pooled(df)
    print(f"{a.results}: {len(df)} runs, {df['solved'].sum()} solved across "
          f"{df['task'].nunique()} tasks\nleader: {p.index[0]} at {p['rate'].iloc[0]:.0%}")
    if not a.no_figure:
        os.makedirs(a.outdir, exist_ok=True)
        fig_matrix(df, a.outdir)
        fig_per_task_cost(df, a.outdir)
        fig_cost_quality(g, a.outdir)
    table(df, g)
    if a.tables:
        markdown(df, g, a.tables, a.results)


if __name__ == "__main__":
    main()

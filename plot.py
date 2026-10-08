"""Plot the comparison.

    uv run plot.py                                   # data/results.json -> visuals/*.png
    uv run plot.py --results data/results-full.json --tables visuals/TABLES.md
    uv run plot.py --results data/results-full.json --no-figure    # tables only

Every figure breaks the result down by task family (Game of 24 / coding / letter counting) AND by
model, so no bar or box pools three very different tasks together:
    visuals/success-rate.png    solve rate: grouped by method, then model, then 3 family bars
    visuals/tokens.png          tokens per run, same grouping
    visuals/tokens-solved.png   the same, keeping only runs that solved the task
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
from matplotlib.patches import Patch  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

METHODS = ["baseline", "refine", "retry", "tree"]
# NAMES is the single source of truth for display names; run.py imports it for its tables.
NAMES = {"baseline": "Baseline (IO)", "refine": "Self-Refine",
         "retry": "Agentic-Program-Repair", "tree": "Tree-of-Thought"}
SHORT = {"baseline": "Baseline (IO)", "refine": "Self-Refine",
         "retry": "Agentic-PR", "tree": "Tree-of-Th"}
MODELS = {"llama2:7b-chat": "Llama-2 7B", "mistral:7b-instruct": "Mistral 7B"}
KINDS = ["math", "program", "writing"]
FAMILY = {"math": "Game of 24", "program": "Coding", "writing": "Letter counting"}
# one colour per model, shared by all three task families; a white edge separates the skinny bars
MCOLOR = {"llama2:7b-chat": "#4C72B0", "mistral:7b-instruct": "#DD8452"}


def load(path):
    df = pd.DataFrame(json.load(open(path)))
    df["solved"] = df["solved"].astype(bool)
    return df


def summary(df):
    """One row per method x model (the aggregate view used by the tables)."""
    g = df.groupby(["method", "model"], as_index=False).agg(
        runs=("solved", "size"), solved=("solved", "sum"),
        gen_tokens=("gen_tokens", "sum"), seconds=("seconds", "sum"), calls=("calls", "sum"))
    g["rate"] = g["solved"] / g["runs"]
    g["tok_per_solve"] = [t / s if s else float("nan")
                          for t, s in zip(g["gen_tokens"], g["solved"])]
    return g


def pooled(df):
    """One row per method, pooled over both models."""
    p = df.groupby("method").agg(ok=("solved", "sum"), runs=("solved", "size"),
                                 tok=("gen_tokens", "sum"), secs=("seconds", "sum"),
                                 calls=("calls", "sum"))
    p["rate"] = p["ok"] / p["runs"]
    p["tok_per_solve"] = p["tok"] / p["ok"]
    return p.reindex(METHODS)


def _save(fig, outdir, name):
    path = os.path.join(outdir, name)
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")
    return path


def _legend(ax, models, y=-.17, ncol=6, size=9.5):
    """Colour = family x model, so every one of the 6 bars per method is identifiable."""
    fam = [Patch(facecolor=SHADE[(k, m)], edgecolor="#666", lw=.6,
                 label=f"{FAMILY[k]} · {MODELS[m].replace(' 7B', '')}")
           for k in KINDS for m in models]
    ax.legend(handles=fam, loc="upper center", bbox_to_anchor=(.5, y), ncol=ncol,
              frameon=False, fontsize=size)


# ------------------------------------------------------------------ figures
def fig_success_rate(df, outdir, path="success-rate.png"):
    """Grouped by method, then model, then task family: every method shows 2 model bars
    (Llama-2, Mistral) and each of those is split into 3 skinny bars for {24, code, count}."""
    models = sorted(df["model"].unique())
    fig, ax = plt.subplots(figsize=(10, 5))
    bar_w, pad = 0.11, 0.035
    for mi, m in enumerate(METHODS):
        for pi, mod in enumerate(models):
            x0 = mi + (pi - .5) * (3 * bar_w + 2 * pad)
            for fi, k in enumerate(KINDS):
                sub = df[(df.method == m) & (df.kind == k) & (df.model == mod)]
                rate = sub["solved"].mean() if len(sub) else 0.0
                x = x0 + fi * (bar_w + pad)
                ax.bar(x, rate, bar_w, color=MCOLOR[mod], edgecolor="white", linewidth=1.1)
                ax.text(x, rate + .015, f"{rate:.0%}", ha="center", fontsize=7.5, color="#333")
    ax.set_xticks(range(len(METHODS)))
    ax.set_xticklabels([NAMES[m] for m in METHODS], fontsize=10)
    ax.set_ylabel("share of tasks solved")
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0, .25, .5, .75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_title("Solve rate by method, model and task family", fontsize=13)
    ax.legend(handles=[Patch(facecolor=MCOLOR[mod], edgecolor="white", label=MODELS[mod])
                       for mod in models],
              title="", loc="upper right", frameon=False, fontsize=10, ncol=2)
    ax.text(.5, -.17, "within each bar group:  Game of 24  |  coding  |  letter counting",
            transform=ax.transAxes, ha="center", fontsize=9, color="#666")
    return _save(fig, outdir, path)


def fig_tokens(df, outdir, path="tokens.png", solved_only=False):
    """Same grouping (method -> model -> family), showing the spread of generated tokens
    as a bar to the mean plus a min-max whisker."""
    models = sorted(df["model"].unique())
    fig, ax = plt.subplots(figsize=(10, 5))
    bar_w, pad = 0.11, 0.035
    for mi, m in enumerate(METHODS):
        for pi, mod in enumerate(models):
            x0 = mi + (pi - .5) * (3 * bar_w + 2 * pad)
            for fi, k in enumerate(KINDS):
                vals = df[(df.method == m) & (df.kind == k) & (df.model == mod)]["gen_tokens"]
                if solved_only:
                    vals = df[(df.method == m) & (df.kind == k) & (df.model == mod) &
                              df.solved]["gen_tokens"]
                x = x0 + fi * (bar_w + pad)
                if len(vals):
                    mean = vals.mean()
                    ax.bar(x, mean, bar_w, color=MCOLOR[mod], edgecolor="white", linewidth=1.1)
                    ax.errorbar(x, mean, yerr=[[mean - vals.min()], [vals.max() - mean]],
                                fmt="none", ecolor="#333", elinewidth=1, capsize=2)
                else:
                    ax.text(x, 25, "0", ha="center", fontsize=7.5, color="#999")
    ax.set_xticks(range(len(METHODS)))
    ax.set_xticklabels([NAMES[m] for m in METHODS], fontsize=10)
    ax.set_ylabel("generated tokens per run")
    ax.set_title("Tokens spent per run, by method, model and task family\n"
                 "(bar = mean, whisker = min to max)", fontsize=13)
    ax.legend(handles=[Patch(facecolor=MCOLOR[mod], edgecolor="white", label=MODELS[mod])
                       for mod in models],
              title="", loc="upper left", frameon=False, fontsize=10, ncol=2)
    ax.text(.5, -.17, "within each bar group:  Game of 24  |  coding  |  letter counting",
            transform=ax.transAxes, ha="center", fontsize=9, color="#666")
    return _save(fig, outdir, path)


def fig_cost_quality(g, outdir, path="cost-quality.png"):
    """Aggregate view, kept for reference: solve rate against tokens spent per solved task."""
    fig, ax = plt.subplots(figsize=(9, 6))
    plot = g.dropna(subset=["tok_per_solve"])
    for m in METHODS:
        sub = plot[plot.method == m]
        if len(sub):
            ax.plot(sub["tok_per_solve"], sub["rate"], marker="o", ls="", color="#333",
                    markersize=15, markeredgecolor="black", markeredgewidth=.7,
                    label=NAMES[m], zorder=3)
    for _, r in plot.iterrows():
        ax.annotate(f"{NAMES[r['method']].split(' ')[0]}\n{MODELS[r['model']]}",
                    (r["tok_per_solve"], r["rate"]), xytext=(0, 14),
                    textcoords="offset points", ha="center", fontsize=8, color="#444")
    ax.set(xscale="log", xlabel="generated tokens per solved task (log scale)",
           ylabel="share of all 17 tasks solved", ylim=(-.06, 1.05))
    ax.set_title("Quality against cost, all task families pooled\n"
                 "(the per-family figures are the honest view)", fontsize=12)
    ax.legend(fontsize=9.5, loc="upper left", frameon=True)
    return _save(fig, outdir, path)


# ------------------------------------------------------------------- tables
def table(df, g):
    print("\n=== solve rate ===")
    per = g.pivot_table(index="method", columns="model", values="rate").reindex(METHODS)
    per["overall"] = df.groupby("method")["solved"].mean().reindex(METHODS)
    per.index = [NAMES[m] for m in per.index]
    print(per.map(lambda v: f"{v:.0%}" if pd.notna(v) else "-").to_string())

    print("\n=== cost per solved task (generated tokens) ===")
    p = pooled(df)
    cost = g.pivot_table(index="method", columns="model", values="tok_per_solve").reindex(METHODS)
    cost["overall"] = p["tok_per_solve"]
    cost["calls/run"] = (p["calls"] / p["runs"]).round(1)
    cost["sec/run"] = (p["secs"] / p["runs"]).round(1)
    cost.index = [NAMES[m] for m in cost.index]
    print(cost.round(0).to_string(na_rep="not solved"))

    print("\n=== solve rate by task family ===")
    fam = df.pivot_table(index="method", columns="kind", values="solved", aggfunc="mean")
    fam = fam.reindex(METHODS)[KINDS]
    fam.columns = [FAMILY[k] for k in KINDS]
    fam.index = [NAMES[m] for m in fam.index]
    print(fam.map(lambda v: f"{v:.0%}").to_string())

    print("\n=== task distribution ===")
    d = df.drop_duplicates("task").groupby("kind")["task"].size().reindex(KINDS)
    print(pd.DataFrame({"family": [FAMILY[k] for k in KINDS], "tasks": d.values,
                        "runs per model per method": (d * 1).values}).to_string(index=False))


def markdown(df, g, path, results):
    models = sorted(df["model"].unique())
    out = [f"<!-- generated by: uv run plot.py --results {results} --tables {path} -->", ""]

    out += ["### Solve rate", "", "| Method | " + " | ".join(MODELS[m] for m in models)
            + " | Overall |", "|---|" + "---|" * (len(models) + 1)]
    for m in METHODS:
        row = [f"{g[(g.method == m) & (g.model == mod)]['rate'].mean():.0%}" for mod in models]
        out.append(f"| {NAMES[m]} | " + " | ".join(row)
                   + f" | {df[df.method == m]['solved'].mean():.0%} |")

    out += ["", "### Cost per solved task (generated tokens)", "",
            "| Method | " + " | ".join(MODELS[m] for m in models)
            + " | Overall | Calls/run | Sec/run |", "|---|" + "---|" * (len(models) + 3)]
    p = pooled(df)
    for m in METHODS:
        cells = []
        for mod in models:
            v = g[(g.method == m) & (g.model == mod)]["tok_per_solve"].iloc[0]
            cells.append("not solved" if pd.isna(v) else f"{v:,.0f}")
        out.append(f"| {NAMES[m]} | " + " | ".join(cells)
                   + f" | {p.loc[m, 'tok_per_solve']:,.0f} "
                   + f"| {p.loc[m, 'calls'] / p.loc[m, 'runs']:.1f} "
                   + f"| {p.loc[m, 'secs'] / p.loc[m, 'runs']:.1f} |")

    out += ["", "### Solve rate by task family", "",
            "| Method | " + " | ".join(FAMILY[k] for k in KINDS) + " |",
            "|---|" + "---|" * len(KINDS)]
    for m in METHODS:
        sub = df[df.method == m]
        out.append(f"| {NAMES[m]} | " + " | ".join(
            f"{sub[sub.kind == k]['solved'].mean():.0%}" for k in KINDS) + " |")

    out += ["", "### Task distribution", "", "| Family | Tasks |", "|---|---|"]
    for k in KINDS:
        out.append(f"| {FAMILY[k]} | {df[df.kind == k]['task'].nunique()} |")

    out += ["", "### Per task: how many of the 8 runs solved it", "",
            "| Task | Family | Solved | Solved by |", "|---|---|---|---|"]
    for tid in sorted(df["task"].unique()):
        sub = df[df.task == tid]
        solvers = sorted({NAMES[m] for m in sub[sub.solved]["method"]})
        out.append(f"| {tid} | {FAMILY[sub['kind'].iloc[0]]} | {sub['solved'].sum()}/8 | "
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
    best = p["rate"].idxmax()
    print(f"{a.results}: {len(df)} runs, {df['solved'].sum()} solved across "
          f"{df['task'].nunique()} tasks\nleader: {NAMES[best]} at {p.loc[best, 'rate']:.0%}")
    if not a.no_figure:
        os.makedirs(a.outdir, exist_ok=True)
        fig_success_rate(df, a.outdir)
        fig_tokens(df, a.outdir)
        fig_tokens(df, a.outdir, solved_only=True, path="tokens-solved.png")
    table(df, g)
    if a.tables:
        markdown(df, g, a.tables, a.results)


if __name__ == "__main__":
    main()

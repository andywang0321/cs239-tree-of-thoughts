"""Plot the comparison.

    uv run plot.py                                   # data/results.json -> visuals/*.png
    uv run plot.py --results data/results-full.json --tables visuals/TABLES.md
    uv run plot.py --results data/results-full.json --no-figure    # tables only

Every figure breaks the result down by task family (Game of 24 / coding / letter counting) AND by
model, so no bar or box pools three very different tasks together:
    visuals/success-rate.png             solve rate, one bar per method per model per family
    visuals/success-rate-<model>.png     the same, one model per figure (used in the deck)
    visuals/tokens-<model>.png           tokens per *solved* run, one box per method per family
    visuals/tokens-all.png               both models side by side, successes and failures
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
# one colour per model per family, so position + shade identifies every bar and box
SHADE = {("math", "llama2:7b-chat"): "#08519c", ("math", "mistral:7b-instruct"): "#9ecae1",
         ("program", "llama2:7b-chat"): "#a63603", ("program", "mistral:7b-instruct"): "#fdbf6f",
         ("writing", "llama2:7b-chat"): "#006d2c", ("writing", "mistral:7b-instruct"): "#a1d99b"}


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
def fig_success_rate(df, outdir, path="success-rate.png", only_model=None):
    """3 bars per method: one per task family. With only_model, a single model's figure."""
    if only_model:
        df = df[df.model == only_model]
    models = sorted(df["model"].unique())
    n = len(KINDS) * len(models)
    fig, ax = plt.subplots(figsize=(11, 4.6))
    width = 1 / (n + 1)
    for mi, m in enumerate(METHODS):
        for fi, k in enumerate(KINDS):
            for pi, mod in enumerate(models):
                sub = df[(df.method == m) & (df.kind == k) & (df.model == mod)]
                rate = sub["solved"].mean() if len(sub) else 0.0
                x = mi + (fi * len(models) + pi - (n - 1) / 2) * width
                ax.bar(x, rate, width * .9, color=SHADE[(k, mod)], edgecolor="white", lw=.7)
                ax.text(x, rate + .012, f"{rate:.0%}" if rate else "0", ha="center",
                        fontsize=7.5, color="#333")
    ax.set_xticks(range(len(METHODS)))
    ax.set_xticklabels([SHORT[m].replace(" ", "\n", 1) for m in METHODS], fontsize=11)
    ax.set_ylabel("share of that family's tasks solved", fontsize=12)
    ax.set_ylim(0, .72)
    fam_n = {k: df[df.kind == k]["task"].nunique() for k in KINDS}
    ax.set_title(f"Solve rate - {MODELS[models[0]] if len(models) == 1 else 'both models'}, "
                 f"one bar per task family\n"
                 + " · ".join(f"{FAMILY[k]}: {fam_n[k]} tasks" for k in KINDS), fontsize=12.5)
    if len(models) == 1:
        ax.legend(handles=[Patch(facecolor=SHADE[(k, models[0])], edgecolor="#666", label=FAMILY[k])
                           for k in KINDS], loc="upper center", bbox_to_anchor=(.5, -.13),
                  ncol=3, frameon=False, fontsize=10)
    else:
        _legend(ax, models)
    return _save(fig, outdir, path)


def fig_tokens(df, outdir, solved_only=True, path="tokens.png", only_model=None):
    """Boxes of tokens per run, grouped by family within each method, one panel per model.
    With only_model, a single-panel figure for that model alone."""
    models = [only_model] if only_model else sorted(df["model"].unique())
    fig, axes = plt.subplots(1, len(models), figsize=(8.2 * len(models), 4.1), sharey=True,
                             squeeze=False)
    for ax, mod in zip(axes[0], models):
        sub = df[(df.model == mod) & (df.solved == solved_only) & (df.gen_tokens > 0)]
        for mi, m in enumerate(METHODS):
            for fi, k in enumerate(KINDS):
                vals = sub[(sub.method == m) & (sub.kind == k)]["gen_tokens"]
                x = mi + (fi - 1) * .23
                if len(vals):
                    bp = ax.boxplot([vals], positions=[x], widths=.18, patch_artist=True,
                                    showfliers=False, medianprops=dict(color="black", lw=1.4))
                    for b in bp["boxes"]:
                        b.set(facecolor=SHADE[(k, mod)], alpha=.95, edgecolor="#444", lw=.7)
                    ax.scatter([x] * len(vals), vals, s=11, color="#222", alpha=.6, zorder=3)
                else:
                    ax.text(x, 22, "never\nsolved", ha="center", va="bottom", fontsize=7.5,
                            color="#999", style="italic")
        ax.set_xticks(range(len(METHODS)))
        ax.set_xticklabels([SHORT[m].replace(" ", "\n", 1) for m in METHODS], fontsize=10)
        ax.set_title(MODELS[mod], fontsize=12.5)
        ax.set_yscale("log")
        ax.set_ylim(15, 4000)
    axes[0][0].set_ylabel("generated tokens per run (log scale)", fontsize=12)
    what = "on the runs that solved the task" if solved_only else "on every run, solved or failed"
    fig.suptitle(f"Tokens spent {what}\nboxes grouped by task family within each method",
                 fontsize=13)
    fam = [Patch(facecolor=SHADE[(k, models[0])], edgecolor="#666", lw=.6, label=FAMILY[k])
           for k in KINDS]
    fig.legend(handles=fam, loc="lower center", ncol=3, frameon=False, fontsize=10,
               bbox_to_anchor=(.5, -.01))
    fig.tight_layout(rect=(0, .05, 1, .93))
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
        for mod in sorted(df["model"].unique()):
            tag = MODELS[mod].replace(" ", "-").replace(" 7B", "").lower()
            fig_success_rate(df, a.outdir, path=f"success-rate-{tag}.png", only_model=mod)
            fig_tokens(df, a.outdir, path=f"tokens-{tag}.png", only_model=mod)
        fig_tokens(df, a.outdir, solved_only=False, path="tokens-all.png")
    table(df, g)
    if a.tables:
        markdown(df, g, a.tables, a.results)


if __name__ == "__main__":
    main()

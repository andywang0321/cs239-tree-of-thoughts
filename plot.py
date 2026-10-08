"""Plot the comparison. One figure per panel, sized to be readable on its own, into visuals/.

    uv run plot.py                                  # data/results.json -> visuals/*.png
    uv run plot.py --results data/results-full.json --tables visuals/TABLES.md
    uv run plot.py --results data/results-full.json --no-figure   # tables only
"""
import argparse
import json
import os
import warnings

# Keep matplotlib's and fontconfig's caches inside the project: on headless boxes $HOME is often not
# writable, which otherwise fails with "Fontconfig error: No writable cache directories".
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("MPLCONFIGDIR", os.path.join(_HERE, ".mplcache"))
os.environ.setdefault("XDG_CACHE_HOME", os.path.join(_HERE, ".mplcache"))
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

METHODS = ["baseline", "refine", "retry", "tree"]
# Display names used on every axis, label, and table in this project.
NAMES = {"baseline": "Baseline (IO)", "refine": "Self-Refine",
         "retry": "Agentic-Program-Repair", "tree": "Tree-of-Thought"}
PALETTE = {"baseline": "#7f7f7f", "refine": "#D55E00", "retry": "#009E73", "tree": "#0072B2"}
COST = {"tokens": ("gen_tokens_per_solve", "generated tokens"),
        "seconds": ("seconds_per_solve", "wall-clock seconds")}
FAMILY = [("math", "Game of 24"), ("program", "Python + tests"), ("writing", "letter counting")]
SUBTITLE = "Same models, same prompts, same tasks - only the shape of the reasoning loop changes"


def load(path):
    df = pd.DataFrame(json.load(open(path)))
    df["solved"] = df["solved"].astype(bool)
    df["label"] = df["method"].map(NAMES)
    return df


def summary(df):
    """One row per method x model, with cost expressed per *solved* task (the honest axis)."""
    g = df.groupby(["method", "model"], as_index=False).agg(
        runs=("solved", "size"), solved=("solved", "sum"),
        gen_tokens=("gen_tokens", "sum"), seconds=("seconds", "sum"), calls=("calls", "sum"))
    g["rate"] = g["solved"] / g["runs"]
    for col in ("gen_tokens", "seconds"):
        g[f"{col}_per_solve"] = [t / s if s else float("nan")
                                 for t, s in zip(g[col], g["solved"])]
    g["label"] = g["method"].map(NAMES)
    return g


def pareto(g, xcol):
    """Runs nothing else beats on both cost and quality: the efficiency frontier."""
    ok = g.dropna(subset=[xcol])
    keep = [r for _, r in ok.iterrows() if not (
        (ok[xcol] <= r[xcol]) & (ok["rate"] >= r["rate"]) &
        ((ok[xcol] < r[xcol]) | (ok["rate"] > r["rate"]))).any()]
    return pd.DataFrame(keep).sort_values(xcol)


def pooled(g):
    p = g.groupby("label").agg(ok=("solved", "sum"), runs=("runs", "sum"),
                               tok=("gen_tokens", "sum"), secs=("seconds", "sum"),
                               calls=("calls", "sum"))
    p["rate"] = p["ok"] / p["runs"]
    p["tok_per_solve"] = p["tok"] / p["ok"]
    return p.sort_values("rate", ascending=False)


def headline(g):
    """Say what the data actually shows. Compares methods on their pooled runs across models,
    not the single best cell, so a method that wins one column cannot claim the headline."""
    p = pooled(g)
    best, runner = p.index[0], p.index[1]
    b, r = p.loc[best], p.loc[runner]
    lead = "leads" if b["rate"] > r["rate"] else "ties"
    return f"{best} {lead} on the full task set ({b['rate']:.0%} vs {r['rate']:.0%} for {runner})"


# --------------------------------------------------------------------- figures
def _save(fig, outdir, name):
    fig.tight_layout()
    path = os.path.join(outdir, name)
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")
    return path


def fig_solve_rate(df, g, outdir):
    """Who solves more, by method and model."""
    fig, ax = plt.subplots(figsize=(11, 5.5))
    sns.barplot(g, x="rate", y="label", hue="model", ax=ax,
                order=[NAMES[m] for m in METHODS], palette="Blues", errorbar=None)
    for c in ax.containers:
        ax.bar_label(c, fmt=lambda v: f"{v:.0%}", padding=4, fontsize=11)
    ax.set(xlabel="share of tasks solved", ylabel="", xlim=(0, 1.14),
           title=f"Solve rate by method\n{SUBTITLE}")
    ax.legend(title="", loc="lower right", fontsize=9)
    return _save(fig, outdir, "solve-rate.png")


def fig_cost_quality(g, outdir, metric="tokens"):
    """The trade: quality bought with compute. The frontier line is the punchline."""
    xcol, xlabel = COST[metric]
    fig, ax = plt.subplots(figsize=(10, 7))
    plot = g.dropna(subset=[xcol])
    for m in METHODS:
        sub = plot[plot["method"] == m]
        if len(sub):
            ax.plot(sub[xcol], sub["rate"], "o", color=PALETTE[m], markersize=15, zorder=3,
                    markeredgecolor="black", markeredgewidth=.7, label=NAMES[m])
    front = pareto(g, xcol)
    if len(front) > 1:
        ax.plot(front[xcol], front["rate"], "k--", lw=1.6, alpha=.75, zorder=2)
        ax.plot([], [], "k--", lw=1.6, label="Pareto frontier")
    for _, r in plot.iterrows():
        ax.annotate(r["model"].split(":")[0], (r[xcol], r["rate"]), xytext=(0, 13),
                    textcoords="offset points", ha="center", fontsize=8.5, color="#444")
    ax.set(xscale="log", xlabel=f"{xlabel} per solved task (log scale)", ylabel="share of tasks solved",
           ylim=(-.06, 1.0), title=f"Quality against cost\n{SUBTITLE}")
    ax.legend(fontsize=10, loc="upper left", frameon=True)
    if len(g) - len(plot):
        ax.text(.98, .04, f"{len(g) - len(plot)} run(s) solved nothing and cannot be placed",
                transform=ax.transAxes, ha="right", fontsize=9, style="italic", color="#555")
    return _save(fig, outdir, f"cost-quality-{metric}.png")


def fig_by_family(df, outdir):
    """Where each method stands per task family - the per-task breakdown."""
    order = [k for k, _ in FAMILY if k in set(df["kind"])]
    fam = df.pivot_table(index="label", columns="kind", values="solved", aggfunc="mean")
    fam = fam.reindex([n for n in (NAMES[m] for m in METHODS) if n in fam.index])[order]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    sns.heatmap(fam, annot=True, fmt=".0%", cmap="RdYlGn", vmin=0, vmax=1, ax=ax,
                cbar=False, linewidths=1.5, linecolor="white", annot_kws={"fontsize": 15})
    ax.set_xticklabels([dict(FAMILY)[k] for k in order], rotation=0)
    ax.set(xlabel="", ylabel="", title=f"Solve rate by task family\n{SUBTITLE}")
    return _save(fig, outdir, "by-family.png")


def fig_tokens(df, outdir):
    """Do the extra tokens land on solves, or on longer failures?"""
    box = df[df["gen_tokens"] > 0].copy()
    box["outcome"] = box["solved"].map({True: "solved", False: "gave up"})
    labels = [NAMES[m] for m in METHODS]
    fig, ax = plt.subplots(figsize=(11, 6))
    with warnings.catch_warnings():  # seaborn sets a non-positive xlim on log axes; harmless
        warnings.simplefilter("ignore")
        sns.boxplot(box, x="label", y="gen_tokens", hue="outcome", order=labels, ax=ax,
                    hue_order=["solved", "gave up"],
                    palette={"solved": "#009E73", "gave up": "#B0B0B0"},
                    width=.62, fliersize=0, linewidth=1)
        sns.stripplot(box, x="label", y="gen_tokens", hue="outcome", order=labels, ax=ax,
                      hue_order=["solved", "gave up"],
                      palette={"solved": "#00543C", "gave up": "#777777"},
                      dodge=True, size=5, alpha=.85, legend=False, edgecolor="white", linewidth=.6)
        ax.set_yscale("log")
    ax.set(xlabel="", ylabel="generated tokens per task (log scale)",
           title=f"Where the tokens go\n{SUBTITLE}")
    ax.tick_params(axis="x", labelrotation=12)
    handles = [h for h in ax.get_legend().legend_handles] if ax.get_legend() else []
    ax.legend(handles[:2], ["solved", "gave up"], title="", fontsize=10, loc="upper left")
    return _save(fig, outdir, "tokens-per-task.png")


# ---------------------------------------------------------------------- tables
def table(df, g):
    """Print the two tables that carry the argument: solve rate, then cost per solve."""
    per = g.pivot_table(index="label", columns="model", values="rate", aggfunc="sum")
    per = per.reindex([n for n in (NAMES[m] for m in METHODS) if n in per.index])
    per["overall"] = df.groupby("label")["solved"].mean().reindex(per.index)
    print("\n=== solve rate ===")
    print(per.map(lambda v: f"{v:.0%}" if pd.notna(v) else "-").to_string())

    print("\n=== cost per solved task (generated tokens) ===")
    cost = g.pivot_table(index="label", columns="model", values="gen_tokens_per_solve")
    cost = cost.reindex([n for n in (NAMES[m] for m in METHODS) if n in cost.index])
    tot = g.groupby("label").agg(tok=("gen_tokens", "sum"), ok=("solved", "sum"),
                                 sec=("seconds", "sum"), runs=("runs", "sum"))
    cost["overall"] = tot["tok"] / tot["ok"]
    out = pd.concat([cost.round(0),
                     pd.DataFrame({"calls/run": (g.groupby("label")["calls"].sum() / tot["runs"]).round(1),
                                   "sec/run": (tot["sec"] / tot["runs"]).round(1)})], axis=1)
    print(out.to_string(na_rep="not solved"))


def markdown(df, g, path):
    """Write the two headline tables as markdown, for slides, the README, or the demo notes."""
    order = [NAMES[m] for m in METHODS if NAMES[m] in set(g["label"])]
    models = sorted(df["model"].unique())
    lines = [f"<!-- generated by: uv run plot.py --results {path.replace('visuals/', 'data/')} -->", ""]

    lines += ["### Solve rate", "", "| Method | " + " | ".join(models)
              + " | Overall |", "|---|" + "---|" * (len(models) + 1)]
    for name in order:
        row = [f"{g[(g.label == name) & (g.model == m)]['rate'].mean():.0%}" for m in models]
        lines.append(f"| {name} | " + " | ".join(row)
                     + f" | {df[df.label == name]['solved'].mean():.0%} |")

    lines += ["", "### Cost per solved task (generated tokens)", "",
              "| Method | " + " | ".join(models)
              + " | Overall | Calls/run | Sec/run |", "|---|" + "---|" * (len(models) + 3)]
    for name in order:
        cells = []
        for m in models:
            v = g[(g.label == name) & (g.model == m)]["gen_tokens_per_solve"].iloc[0]
            cells.append("not solved" if pd.isna(v) else f"{v:,.0f}")
        sub = df[df.label == name]
        ok = sub["solved"].sum()
        lines.append(f"| {name} | " + " | ".join(cells)
                     + f" | {(sub['gen_tokens'].sum() / ok if ok else float('nan')):,.0f} "
                     + f"| {sub['calls'].mean():.1f} | {sub['seconds'].mean():.1f} |")

    lines += ["", "### Solve rate by task family", "",
              "| Method | " + " | ".join(n for _, n in FAMILY) + " |",
              "|---|" + "---|" * len(FAMILY)]
    for name in order:
        sub = df[df.label == name]
        lines.append(f"| {name} | " + " | ".join(
            f"{sub[sub.kind == k]['solved'].mean():.0%}" for k, _ in FAMILY) + " |")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
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
    print(f"{a.results}: {len(df)} runs, {df['solved'].sum()} solved\nheadline: {headline(g)}")
    if not a.no_figure:
        os.makedirs(a.outdir, exist_ok=True)
        fig_solve_rate(df, g, a.outdir)
        fig_cost_quality(g, a.outdir, "tokens")
        fig_cost_quality(g, a.outdir, "seconds")
        fig_by_family(df, a.outdir)
        fig_tokens(df, a.outdir)
    table(df, g)
    if a.tables:
        markdown(df, g, a.tables)


if __name__ == "__main__":
    main()

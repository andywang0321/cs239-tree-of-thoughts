"""Plot the comparison. One figure, four panels, one story.

    uv run plot.py                                   # reads results.json
    uv run plot.py --results results-full.json
    uv run plot.py --metric seconds --out cost.png   # swap the cost axis
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


def headline(g):
    """Say what the data actually shows. Compares methods on their pooled runs across models,
    not the single best cell, so a method that wins one column cannot claim the headline."""
    pooled = g.groupby("label").agg(ok=("solved", "sum"), runs=("runs", "sum"),
                                    tok=("gen_tokens", "sum"))
    pooled["rate"] = pooled["ok"] / pooled["runs"]
    pooled = pooled.sort_values(["rate", "tok"], ascending=[False, True])
    best, runner = pooled.index[0], pooled.index[1]
    b, r = pooled.loc[best], pooled.loc[runner]
    lead = "leads" if b["rate"] > r["rate"] else "ties"
    return (f"{best} {lead} on the full task set "
            f"({b['rate']:.0%} vs {r['rate']:.0%} for {runner})")


def panels(df, g, metric, out):
    sns.set_theme(style="whitegrid", context="talk", font_scale=0.82)
    fig, ax = plt.subplots(2, 2, figsize=(16.5, 11))
    xcol, xlabel = COST[metric]
    plot = g.dropna(subset=[xcol])
    labels = [NAMES[m] for m in METHODS]

    # (a) headline: who solves more
    a = ax[0, 0]
    sns.barplot(g, x="rate", y="label", hue="model", order=labels, ax=a,
                palette="Blues", errorbar=None)
    for c in a.containers:
        a.bar_label(c, fmt=lambda v: f"{v:.0%}", padding=4, fontsize=11)
    a.set(xlabel="share of tasks solved", ylabel="", xlim=(0, 1.14), title="(a) Solve rate")
    a.legend(title="", loc="lower right", fontsize=9)

    # (b) the trade: quality bought with compute
    b = ax[0, 1]
    for m in METHODS:
        sub = plot[plot["method"] == m]
        if not len(sub):
            continue
        b.plot(sub[xcol], sub["rate"], "o", color=PALETTE[m], markersize=14, zorder=3,
               markeredgecolor="black", markeredgewidth=.7, label=NAMES[m])
    front = pareto(g, xcol)
    if len(front) > 1:
        b.plot(front[xcol], front["rate"], "k--", lw=1.5, alpha=.75, zorder=2)
        b.plot([], [], "k--", lw=1.5, label="Pareto frontier")
    b.legend(fontsize=9, loc="lower right", frameon=True, title="", title_fontsize=9)
    dropped = len(g) - len(plot)
    b.set(xscale="log", xlabel=f"{xlabel} per solved task (log scale)", ylabel="share solved",
          ylim=(-.09, 1.15), title="(b) What a solve costs")
    if dropped:
        b.text(.98, .04, f"{dropped} run(s) solved nothing and cannot be placed",
               transform=b.transAxes, ha="right", fontsize=9, style="italic", color="#555")

    # (c) where each method stands per task family
    c = ax[1, 0]
    order = [k for k, _ in FAMILY if k in set(df["kind"])]
    fam = df.pivot_table(index="label", columns="kind", values="solved", aggfunc="mean")
    fam = fam.reindex([n for n in labels if n in fam.index])[order]
    sns.heatmap(fam, annot=True, fmt=".0%", cmap="RdYlGn", vmin=0, vmax=1, ax=c,
                cbar=False, linewidths=1.5, linecolor="white", annot_kws={"fontsize": 14})
    c.set_xticklabels([dict(FAMILY)[k] for k in order], rotation=0)
    c.set(xlabel="", ylabel="", title="(c) Solve rate by task family")

    # (d) do the extra tokens land on solves or on dead ends?
    d = ax[1, 1]
    box = df[df["gen_tokens"] > 0].copy()
    box["outcome"] = box["solved"].map({True: "solved", False: "gave up"})
    with warnings.catch_warnings():  # seaborn sets a non-positive xlim on log axes; harmless
        warnings.simplefilter("ignore")
        sns.boxplot(box, x="label", y="gen_tokens", hue="outcome", order=labels, ax=d,
                    hue_order=["solved", "gave up"],
                    palette={"solved": "#009E73", "gave up": "#B0B0B0"},
                    width=.62, fliersize=0, linewidth=1)
        sns.stripplot(box, x="label", y="gen_tokens", hue="outcome", order=labels, ax=d,
                      hue_order=["solved", "gave up"],
                      palette={"solved": "#00543C", "gave up": "#777777"},
                      dodge=True, size=5, alpha=.85, legend=False, edgecolor="white", linewidth=.6)
        d.set_yscale("log")
    d.set(xlabel="", ylabel="generated tokens per task (log scale)",
          title="(d) Where the tokens go")
    d.tick_params(axis="x", labelrotation=15)
    handles = [h for h in d.get_legend().legend_handles] if d.get_legend() else []
    d.legend(handles[:2], ["solved", "gave up"], title="", fontsize=10, loc="upper left")

    fig.suptitle(headline(g) + "\nSame models, same prompts, same tasks - only the shape of the "
                 "reasoning loop changes", fontsize=16.5, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out, dpi=170, bbox_inches="tight")
    print(f"wrote {out}")
    return plot


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
    lines = ["<!-- generated by: uv run plot.py --results results-full.json --tables TABLES.md -->", ""]

    lines += ["### Solve rate", "", "| Method | " + " | ".join(sorted(df["model"].unique()))
              + " | Overall |", "|---|" + "---|" * (df["model"].nunique() + 1)]
    for name in order:
        row = [f"{g[(g.label == name) & (g.model == m)]['rate'].mean():.0%}"
               for m in sorted(df["model"].unique())]
        lines.append(f"| {name} | " + " | ".join(row)
                     + f" | {df[df.label == name]['solved'].mean():.0%} |")

    lines += ["", "### Cost per solved task (generated tokens)", "",
              "| Method | " + " | ".join(sorted(df["model"].unique()))
              + " | Overall | Calls/run | Sec/run |", "|---|" + "---|" * (df["model"].nunique() + 3)]
    for name in order:
        cells = []
        for m in sorted(df["model"].unique()):
            r = g[(g.label == name) & (g.model == m)]
            v = r["gen_tokens_per_solve"].iloc[0]
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
    print(f"\nwrote {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.json")
    ap.add_argument("--metric", default="tokens", choices=list(COST))
    ap.add_argument("--out", default="comparison.png")
    ap.add_argument("--tables", metavar="TABLES.md", help="also write the tables as markdown")
    ap.add_argument("--no-figure", action="store_true", help="tables only")
    a = ap.parse_args()
    df = load(a.results)
    g = summary(df)
    if not a.no_figure:
        panels(df, g, a.metric, a.out)
    else:
        print(f"\n=== solve rate ===")
    table(df, g)
    if a.tables:
        markdown(df, g, a.tables)


if __name__ == "__main__":
    main()

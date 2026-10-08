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
PALETTE = {"baseline": "#7f7f7f", "refine": "#D55E00", "retry": "#009E73", "tree": "#0072B2"}
COST = {"tokens": ("gen_tokens_per_solve", "generated tokens"),
        "seconds": ("seconds_per_solve", "wall-clock seconds")}
FAMILY = [("math", "Game of 24"), ("program", "Python + tests"), ("writing", "letter counting")]


def load(path):
    df = pd.DataFrame(json.load(open(path)))
    df["solved"] = df["solved"].astype(bool)
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
    return g


def pareto(g, xcol):
    """Runs nothing else beats on both cost and quality: the efficiency frontier."""
    ok = g.dropna(subset=[xcol])
    keep = [r for _, r in ok.iterrows() if not (
        (ok[xcol] <= r[xcol]) & (ok["rate"] >= r["rate"]) &
        ((ok[xcol] < r[xcol]) | (ok["rate"] > r["rate"]))).any()]
    return pd.DataFrame(keep).sort_values(xcol)


def headline(g):
    """Say what the data actually shows rather than asserting a conclusion up front."""
    best = g.sort_values(["rate", "gen_tokens_per_solve"], ascending=[False, True]).iloc[0]
    rate, tok = best["rate"], best["gen_tokens_per_solve"]
    if pd.isna(tok):
        return f"{best['method']} solves the most tasks, but nothing was solved cheaply"
    return (f"{best['method']} solves the most tasks ({rate:.0%}) "
            f"at {tok:,.0f} generated tokens per solve")


def panels(df, g, metric, out):
    sns.set_theme(style="whitegrid", context="talk", font_scale=0.82)
    fig, ax = plt.subplots(2, 2, figsize=(15.5, 11))
    xcol, xlabel = COST[metric]
    plot = g.dropna(subset=[xcol])

    # (a) headline: who solves more
    a = ax[0, 0]
    sns.barplot(g, x="rate", y="method", hue="model", order=METHODS, ax=a,
                palette="Blues", errorbar=None)
    for c in a.containers:
        a.bar_label(c, fmt=lambda v: f"{v:.0%}", padding=4, fontsize=11)
    a.set(xlabel="share of tasks solved", ylabel="", xlim=(0, 1.12), title="(a) Solve rate")
    a.legend(title="", loc="lower right", fontsize=9)

    # (b) the trade: quality bought with compute
    b = ax[0, 1]
    sns.scatterplot(plot, x=xcol, y="rate", hue="method", style="model", s=280, ax=b,
                    palette=PALETTE, hue_order=METHODS, legend=False,
                    edgecolor="black", linewidth=.7, zorder=3)
    front = pareto(g, xcol)
    if len(front) > 1:
        b.plot(front[xcol], front["rate"], "k--", lw=1.5, alpha=.75, zorder=2,
               label="Pareto frontier")
        b.legend(fontsize=10, loc="lower right", frameon=True)
    for _, r in plot.iterrows():
        b.annotate(r["method"], (r[xcol], r["rate"]), xytext=(0, 11), textcoords="offset points",
                   ha="center", fontsize=9.5, fontweight="bold", color=PALETTE[r["method"]])
    dropped = len(g) - len(plot)
    b.set(xscale="log", xlabel=f"{xlabel} per solved task (log scale)", ylabel="share solved",
          ylim=(-.09, 1.15), title="(b) What a solve costs")
    if dropped:
        b.text(.98, .04, f"{dropped} run(s) solved nothing and cannot be placed",
               transform=b.transAxes, ha="right", fontsize=9, style="italic", color="#555")

    # (c) where each method stands per task family
    c = ax[1, 0]
    order = [k for k, _ in FAMILY if k in set(df["kind"])]
    fam = df.pivot_table(index="method", columns="kind", values="solved", aggfunc="mean")
    fam = fam.reindex([m for m in METHODS if m in fam.index])[order]
    sns.heatmap(fam, annot=True, fmt=".0%", cmap="RdYlGn", vmin=0, vmax=1, ax=c,
                cbar=False, linewidths=1.5, linecolor="white", annot_kws={"fontsize": 14})
    c.set_xticklabels([dict(FAMILY)[k] for k in order], rotation=0)
    c.set(xlabel="", ylabel="", title="(c) Solve rate by task family")

    # (d) do the extra tokens land on solves or on dead ends?
    d = ax[1, 1]
    box = df[df["gen_tokens"] > 0].copy()
    box["solved_"] = box["solved"].map({True: "solved", False: "gave up"})
    with warnings.catch_warnings():  # seaborn sets a non-positive xlim on log axes; harmless
        warnings.simplefilter("ignore")
        sns.boxplot(box, x="method", y="gen_tokens", hue="solved_", order=METHODS, ax=d,
                    hue_order=["solved", "gave up"], palette={"solved": "#009E73", "gave up": "#B0B0B0"},
                    width=.62, fliersize=0, linewidth=1)
        sns.stripplot(box, x="method", y="gen_tokens", hue="solved_", order=METHODS, ax=d,
                      hue_order=["solved", "gave up"], palette={"solved": "#00543C", "gave up": "#777777"},
                      dodge=True, size=5, alpha=.85, legend=False, edgecolor="white", linewidth=.6)
        d.set_yscale("log")
    d.set(xlabel="", ylabel="generated tokens per task (log scale)", title="(d) Where the tokens go")
    handles = [h for h in d.get_legend().legend_handles] if d.get_legend() else []
    d.legend(handles[:2], ["solved", "gave up"], title="", fontsize=10, loc="upper left")

    fig.suptitle(headline(g) + "\nSame models, same prompts, same tasks - only the shape of the "
                 "reasoning loop changes", fontsize=16.5, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out, dpi=170, bbox_inches="tight")
    print(f"wrote {out}")
    return plot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.json")
    ap.add_argument("--metric", default="tokens", choices=list(COST))
    ap.add_argument("--out", default="comparison.png")
    a = ap.parse_args()
    df = load(a.results)
    g = summary(df)
    panels(df, g, a.metric, a.out)
    cols = ["method", "model", "runs", "solved", "rate", "gen_tokens", "gen_tokens_per_solve",
            "seconds", "calls"]
    print(g[cols].to_string(index=False, float_format=lambda v: f"{v:,.1f}"))


if __name__ == "__main__":
    main()

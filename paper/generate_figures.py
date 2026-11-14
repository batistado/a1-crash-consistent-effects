#!/usr/bin/env python3
"""Generate all 6 vector PDF figures for the ClaimFence Elsevier FGCS manuscript
directly from measured hardware and simulation telemetry JSONs."""

from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIG_DIR = Path(__file__).resolve().parent / "figures"

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 9,
        "axes.titlesize": 9.5,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 7.5,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

COLORS = {
    "baseline": "#8c8c8c",
    "content_hash": "#d95f02",
    "deterministic_pos": "#e6ab02",
    "ckpt_ledger": "#7570b3",
    "det_canonical": "#386cb0",
    "claimfence": "#1b9e77",
}

LABELS = {
    "baseline": "Trajectory Ckpt",
    "content_hash": "Content-Hash",
    "deterministic_pos": "Positional Key",
    "ckpt_ledger": "Ckpt-Ledger (REMIT)",
    "det_canonical": "Canonical Key",
    "claimfence": "ClaimFence (Ours)",
}


def make_fig1_architecture() -> None:
    """Two-part vector diagram: (a) Crash-window taxonomy; (b) ClaimFence distributed architecture."""
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(10.4, 5.0), gridspec_kw={"height_ratios": [1.0, 1.55]}
    )

    # --- Top Panel: Event Timeline & Crash Windows ---
    ax_top.set_xlim(0, 106)
    ax_top.set_ylim(0, 11.0)
    ax_top.axis("off")
    ax_top.text(
        0.5,
        10.1,
        "(a) Step Execution Timeline and Fault-Window Taxonomy",
        fontsize=9.3,
        fontweight="bold",
    )

    # Main timeline arrow
    ax_top.annotate(
        "",
        xy=(103, 6.2),
        xytext=(2, 6.2),
        arrowprops=dict(arrowstyle="->", lw=1.6, color="#222222"),
    )

    events = [
        (9, "$t_{\\mathrm{claim}}$\nCLAIM fsync'd", "#1b9e77"),
        (26, "$t_{\\mathrm{call}}$\nRPC sent", "#333333"),
        (49, "$t_{\\mathrm{commit}}$\nService commits", "#d95f02"),
        (73, "$t_{\\mathrm{mark}}$\nCOMMIT + payload", "#1b9e77"),
        (95, "$t_{\\mathrm{ckpt}}$\nLog-fenced ckpt", "#386cb0"),
    ]
    for x, label, col in events:
        ax_top.plot([x, x], [5.55, 6.85], lw=2.0, color=col)
        ax_top.text(x, 7.15, label, ha="center", va="bottom", fontsize=7.3, color=col)

    # Dashed drop guides
    for gx, gc in [(26, "#d95f02"), (49, "#c51b7d"), (95, "#c51b7d")]:
        ax_top.plot([gx, gx], [4.3, 5.5], lw=0.8, ls=":", color=gc)

    # Service-boundary window (Limbo)
    rect_srv = mpatches.FancyBboxPatch(
        (26.5, 1.1),
        21.8,
        2.9,
        boxstyle="round,pad=0.18",
        facecolor="#fee0b6",
        edgecolor="#d95f02",
        lw=1.0,
    )
    ax_top.add_patch(rect_srv)
    ax_top.text(
        37.4,
        2.55,
        "Service window [22]\n(commit uncertain)",
        ha="center",
        va="center",
        fontsize=6.9,
        color="#7f3b08",
    )

    # Harness-side crash window W(s) (This paper)
    rect_ws = mpatches.FancyBboxPatch(
        (49.6, 1.1),
        45.0,
        2.9,
        boxstyle="round,pad=0.18",
        facecolor="#fde0dd",
        edgecolor="#c51b7d",
        lw=1.3,
    )
    ax_top.add_patch(rect_ws)
    ax_top.text(
        72.1,
        2.55,
        "Harness crash window $W(s) = (t_{\\mathrm{commit}}, t_{\\mathrm{ckpt}})$\n"
        "Committed side effect + lost payload; Ckpt-Ledger unwritten",
        ha="center",
        va="center",
        fontsize=6.95,
        color="#7a0177",
        fontweight="bold",
    )

    # --- Bottom Panel: ClaimFence Distributed Protocol Architecture ---
    ax_bot.set_xlim(0, 108)
    ax_bot.set_ylim(0, 13.4)
    ax_bot.axis("off")
    ax_bot.text(
        0.5,
        12.4,
        "(b) ClaimFence Distributed Execution, Atomic CAS Fencing, and Payload-Preserving Reconciliation",
        fontsize=9.3,
        fontweight="bold",
    )

    def draw_box(ax, x, y, w, h, title, subtitle, fc, ec, title_y=0.68, sub_y=0.30):
        b = mpatches.FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.22",
            facecolor=fc,
            edgecolor=ec,
            lw=1.3,
        )
        ax.add_patch(b)
        ax.text(x + w / 2, y + h * title_y, title, ha="center", va="center", fontsize=8.0, fontweight="bold")
        ax.text(x + w / 2, y + h * sub_y, subtitle, ha="center", va="center", fontsize=6.6, color="#333333")

    draw_box(
        ax_bot,
        1.2,
        4.2,
        22.5,
        5.5,
        "Agent Workers $H_1..H_K$",
        "Crash-prone LLM planners\n(non-deterministic replan)",
        "#eef7ff",
        "#386cb0",
    )
    draw_box(
        ax_bot,
        39.0,
        7.3,
        27.5,
        3.7,
        "Durable ClaimStore $L$",
        "flock / SQLite-WAL O(1) index\n(action, target, occ) -> key, result",
        "#e6f5d0",
        "#1b9e77",
    )
    draw_box(
        ax_bot,
        39.0,
        0.6,
        27.5,
        3.3,
        "Log-Fenced Ckpt $C$",
        "Advances iff COMMIT(s) in $L$\nFrontier per parallel branch",
        "#f7f7f7",
        "#666666",
    )
    draw_box(
        ax_bot,
        82.0,
        3.5,
        24.8,
        6.5,
        "External Service $T$",
        "1. Atomic CAS_inc(epoch, holder)\n2. Seen-key -> saved payload\n3. Rejects stale zombies (409)",
        "#fff5eb",
        "#d95f02",
        title_y=0.74,
        sub_y=0.33,
    )

    # 1. Pre-invocation create_or_reuse arrow in clean left gap (23.7..39.0)
    ax_bot.annotate(
        "",
        xy=(38.6, 8.8),
        xytext=(24.1, 8.8),
        arrowprops=dict(arrowstyle="->", lw=1.3, color="#1b9e77"),
    )
    ax_bot.text(
        31.35,
        9.25,
        "1. create_or_reuse\n(before RPC)",
        ha="center",
        va="bottom",
        fontsize=6.6,
        color="#116649",
        fontweight="bold",
    )

    # 2. RPC call through clean central corridor y=5.55 (between Ckpt C top=3.9 and ClaimStore L bottom=7.3)
    ax_bot.annotate(
        "",
        xy=(81.6, 5.55),
        xytext=(24.1, 5.55),
        arrowprops=dict(arrowstyle="<->", lw=1.3, color="#d95f02"),
    )
    ax_bot.text(
        50.5,
        5.9,
        "2. call(key, epoch, holder) <-> (status, saved_payload)",
        ha="center",
        va="bottom",
        fontsize=6.65,
        color="#a63603",
        bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor="none", alpha=0.92),
    )

    # 3. Log-fenced checkpoint arrow on right side of L -> C (x=64.2)
    ax_bot.annotate(
        "",
        xy=(64.2, 4.15),
        xytext=(64.2, 7.05),
        arrowprops=dict(arrowstyle="->", lw=1.15, ls="--", color="#555555"),
    )
    ax_bot.text(
        65.2,
        4.65,
        "3. fence $C$",
        ha="left",
        va="center",
        fontsize=6.6,
        color="#444444",
    )

    # 4. Recovery arrow in clean right gap (66.5..82.0)
    ax_bot.annotate(
        "",
        xy=(81.6, 9.1),
        xytext=(66.9, 9.1),
        arrowprops=dict(arrowstyle="<->", lw=1.3, ls="--", color="#c51b7d"),
    )
    ax_bot.text(
        74.25,
        9.6,
        "4. Recovery:\nCAS fence + replay\nkey & payload",
        ha="center",
        va="bottom",
        fontsize=6.55,
        color="#c51b7d",
        fontweight="bold",
    )

    fig.tight_layout(pad=0.45)
    fig.savefig(FIG_DIR / "fig1_architecture.pdf", bbox_inches="tight")
    plt.close(fig)


def make_fig2_chaos_and_horizon() -> None:
    chaos = json.loads((ROOT / "results" / "chaos_6way_results.json").read_text())
    m6 = chaos["main_6way"]
    sweep = chaos["multi_crash_sweep"]

    archs = [
        "baseline",
        "content_hash",
        "deterministic_pos",
        "ckpt_ledger",
        "det_canonical",
        "claimfence",
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 2.75))

    x = np.arange(len(archs))
    w = 0.27
    eo = [m6[a]["exactly_once_rate"] * 100 for a in archs]
    pay = [m6[a]["payload_continuity_rate"] * 100 for a in archs]
    strict = [m6[a]["strict_e2e_correct_rate"] * 100 for a in archs]

    ax1.bar(x - w, eo, w, label="Exactly-Once Effects (%)", color="#6baed6", edgecolor="black", lw=0.5)
    ax1.bar(x, pay, w, label="Payload Continuity (%)", color="#fd8d3c", edgecolor="black", lw=0.5)
    ax1.bar(x + w, strict, w, label="Strict E2E Correct (%)", color="#1b9e77", edgecolor="black", lw=0.5)

    ax1.set_xticks(x)
    ax1.set_xticklabels([LABELS[a] for a in archs], rotation=28, ha="right", fontsize=7.3)
    ax1.set_ylabel("Success Rate (%)")
    ax1.set_ylim(0, 112)
    ax1.set_title("(a) 6-Architecture Chaos Suite (1,500 eps/cond)")
    ax1.grid(axis="y", ls=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=6.7)

    ks = [1, 2, 3, 4]
    markers = {
        "baseline": "o",
        "content_hash": "s",
        "deterministic_pos": "^",
        "ckpt_ledger": "v",
        "det_canonical": "D",
        "claimfence": "*",
    }
    for a in archs:
        ys = [sweep[a][str(k)]["strict_e2e_correct_rate"] * 100 for k in ks]
        lw = 2.2 if a == "claimfence" else 1.3
        ls = "--" if a == "ckpt_ledger" else "-"
        ms = 8 if a == "claimfence" else 5
        ax2.plot(ks, ys, marker=markers[a], lw=lw, ls=ls, markersize=ms, color=COLORS[a], label=LABELS[a])

    ax2.set_xticks(ks)
    ax2.set_xlabel("Crashes per Workflow ($k$)")
    ax2.set_ylabel("Strict E2E Correctness (%)")
    ax2.set_ylim(-3, 108)
    ax2.set_title("(b) Multi-Crash Horizon Survival (1,000 eps/pt)")
    ax2.grid(True, ls=":", alpha=0.6)
    ax2.legend(loc="center right", frameon=True, fontsize=6.7)

    fig.tight_layout(pad=0.6)
    fig.savefig(FIG_DIR / "fig2_chaos_and_horizon.pdf", bbox_inches="tight")
    plt.close(fig)


def make_fig3_multimodel_sigkill() -> None:
    mm = json.loads((ROOT / "results" / "multimodel_sigkill_results.json").read_text())
    models = mm["models"]
    archs = [
        "baseline",
        "content_hash",
        "deterministic_pos",
        "ckpt_ledger",
        "det_canonical",
        "claimfence",
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 2.75))
    x = np.arange(len(models))
    total_w = 0.82
    w = total_w / len(archs)

    for idx, a in enumerate(archs):
        offset = (idx - (len(archs) - 1) / 2.0) * w
        dups = [m["architectures"][a]["duplicate_ep_rate"] * 100 for m in models]
        stricts = [m["architectures"][a]["strict_e2e_rate"] * 100 for m in models]
        ax1.bar(x + offset, dups, w, color=COLORS[a], edgecolor="black", lw=0.45, label=LABELS[a])
        ax2.bar(x + offset, stricts, w, color=COLORS[a], edgecolor="black", lw=0.45, label=LABELS[a])

    short_names = [m["model_id"].split("/")[-1].replace("-Instruct", "") for m in models]
    ax1.set_xticks(x)
    ax1.set_xticklabels(short_names, fontsize=7.6)
    ax1.set_ylabel("Duplicate-Effect Episode Rate (%)")
    ax1.set_ylim(0, 112)
    ax1.set_title("(a) Duplicate Rate Under Real OS SIGKILL")
    ax1.grid(axis="y", ls=":", alpha=0.6)

    ax2.set_xticks(x)
    ax2.set_xticklabels(short_names, fontsize=7.6)
    ax2.set_ylabel("Strict E2E Completion Rate (%)")
    ax2.set_ylim(0, 112)
    ax2.set_title("(b) Chained Workflow Completion Under SIGKILL")
    ax2.grid(axis="y", ls=":", alpha=0.6)
    ax2.legend(loc="upper left", ncol=2, frameon=True, fontsize=6.3)

    fig.tight_layout(pad=0.6)
    fig.savefig(FIG_DIR / "fig3_multimodel_sigkill.pdf", bbox_inches="tight")
    plt.close(fig)


def make_fig4_langgraph_and_ablation() -> None:
    abl = json.loads((ROOT / "component_ablation_results.json").read_text())["conditions"]
    e2a = json.loads((ROOT / "langgraph_port" / "results_e2a_shift.json").read_text())["conditions"]
    e2b = json.loads((ROOT / "langgraph_port" / "results_e2b_content.json").read_text())["conditions"]
    lgv2 = json.loads((ROOT / "langgraph_port" / "results_langgraph_v2.json").read_text())["conditions"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 2.65))

    # Panel (a): LangGraph v2 + Identity-Shift Boundary
    cats = ["Stable\n(Pos. Key)", "E2a Shift\n(Pos. Key)", "E2b Reword\n(Hash Key)", "All Regimes\n(ClaimFence)"]
    eo_vals = [
        lgv2["deterministic"]["exactly_once_rate"] * 100,
        e2a["det_shift"]["exactly_once_rate"] * 100,
        e2b["det_content"]["exactly_once_rate"] * 100,
        e2a["wal"]["exactly_once_rate"] * 100,
    ]
    dup_vals = [
        lgv2["deterministic"]["duplicate_effect_rate"] * 100,
        e2a["det_shift"]["duplicate_effect_rate"] * 100,
        e2b["det_content"]["duplicate_effect_rate"] * 100,
        e2a["wal"]["duplicate_effect_rate"] * 100,
    ]
    x1 = np.arange(len(cats))
    ax1.bar(x1 - 0.18, dup_vals, 0.35, color="#e41a1c", alpha=0.85, edgecolor="black", lw=0.5, label="Duplicate Rate (%)")
    ax1.bar(x1 + 0.18, eo_vals, 0.35, color="#1b9e77", edgecolor="black", lw=0.5, label="Exactly-Once (%)")
    ax1.set_xticks(x1)
    ax1.set_xticklabels(cats, fontsize=7.0)
    ax1.set_ylim(0, 112)
    ax1.set_ylabel("Episode Rate (%)")
    ax1.set_title("(a) LangGraph v2 Key-Stability Boundary (n=60)")
    ax1.grid(axis="y", ls=":", alpha=0.6)
    ax1.legend(loc="center right", fontsize=6.8)

    # Panel (b): Component Ablation (1,500 eps/cond)
    aconds = ["full", "no_fencing", "no_log", "neither"]
    alabels = ["Full Protocol", "No Epoch\nFencing", "No Claim\nLog", "Neither\n(Baseline)"]
    adup = [abl[c]["duplicate_effect_rate"] * 100 for c in aconds]
    aeo = [abl[c]["exactly_once_rate"] * 100 for c in aconds]
    x2 = np.arange(len(aconds))
    ax2.bar(x2 - 0.18, adup, 0.35, color="#d95f02", edgecolor="black", lw=0.5, label="Duplicate Rate (%)")
    ax2.bar(x2 + 0.18, aeo, 0.35, color="#386cb0", edgecolor="black", lw=0.5, label="Exactly-Once (%)")
    ax2.set_xticks(x2)
    ax2.set_xticklabels(alabels, fontsize=7.2)
    ax2.set_ylim(0, 112)
    ax2.set_ylabel("Episode Rate (%)")
    ax2.set_title("(b) Orthogonal Component Ablation (n=1,500)")
    ax2.grid(axis="y", ls=":", alpha=0.6)
    ax2.legend(loc="upper center", fontsize=6.8)

    fig.tight_layout(pad=0.6)
    fig.savefig(FIG_DIR / "fig4_langgraph_and_ablation.pdf", bbox_inches="tight")
    plt.close(fig)


def make_fig5_storage_scaling() -> None:
    st = json.loads((ROOT / "results" / "storage_and_concurrency_results.json").read_text())
    rows = st["lookup_scaling"]
    step_lat = st["step_latency_breakdown"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 2.65))

    ns = [r["n_claims"] for r in rows]
    leg = [r["legacy_unindexed_find_p50_ms"] for r in rows]
    idx = [r["claimfence_indexed_find_p50_ms"] for r in rows]
    sql = [r["claimfence_sqlite_find_p50_ms"] for r in rows]

    ax1.plot(ns, leg, "o-", color="#d95f02", lw=1.6, label="Unindexed JSONL $O(n)$")
    ax1.plot(ns, sql, "s--", color="#386cb0", lw=1.5, label="ClaimFence SQLite-WAL")
    ax1.plot(ns, idx, "*-", color="#1b9e77", lw=2.0, markersize=8, label="ClaimFence Hash-Index $O(1)$")
    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlabel("Durable Claims in Log ($N$)")
    ax1.set_ylabel("Identity Lookup p50 Latency (ms)")
    ax1.set_title("(a) Lookup Scaling (12,987x Speedup at $10^4$)")
    ax1.grid(True, which="both", ls=":", alpha=0.6)
    ax1.legend(loc="center left", fontsize=6.8)

    modes = ["jsonl_fsync", "sqlite_wal", "jsonl_fullfsync"]
    mlabels = ["JSONL\n(os.fsync)", "SQLite-WAL\n(sync=FULL)", "JSONL\n(F_FULLFSYNC)"]
    c_ms = [step_lat[m]["claim_ms"]["p50"] for m in modes]
    m_ms = [step_lat[m]["commit_ms"]["p50"] for m in modes]
    k_ms = [step_lat[m]["ckpt_ms"]["p50"] for m in modes]

    x2 = np.arange(len(modes))
    ax2.bar(x2, c_ms, 0.48, label="CLAIM write", color="#66c2a5", edgecolor="black", lw=0.5)
    ax2.bar(x2, m_ms, 0.48, bottom=c_ms, label="COMMIT + payload", color="#fc8d62", edgecolor="black", lw=0.5)
    ax2.bar(
        x2,
        k_ms,
        0.48,
        bottom=[a + b for a, b in zip(c_ms, m_ms)],
        label="Checkpoint rename",
        color="#8da0cb",
        edgecolor="black",
        lw=0.5,
    )
    ax2.set_xticks(x2)
    ax2.set_xticklabels(mlabels, fontsize=7.4)
    ax2.set_ylabel("Per-Step Write Path p50 (ms)")
    ax2.set_title("(b) APFS NVMe Durability Cost Breakdown")
    ax2.grid(axis="y", ls=":", alpha=0.6)
    ax2.legend(loc="upper left", fontsize=6.8)

    fig.tight_layout(pad=0.6)
    fig.savefig(FIG_DIR / "fig5_storage_scaling.pdf", bbox_inches="tight")
    plt.close(fig)


def make_fig6_concurrency_throughput() -> None:
    st = json.loads((ROOT / "results" / "storage_and_concurrency_results.json").read_text())
    http_rows = st["http_concurrency"]
    # Also load legacy v1.0 E3c concurrency numbers (K=1, 4, 16) for head-to-head comparison
    leg_k = [1, 4, 16]
    leg_tput = [
        json.loads((ROOT / "langgraph_port" / f"results_e3c_k{k}.json").read_text())["throughput_ops"]
        for k in leg_k
    ]
    leg_p99 = [
        json.loads((ROOT / "langgraph_port" / f"results_e3c_k{k}.json").read_text())["lat_p99_ms"]
        for k in leg_k
    ]

    ks = [r["concurrency_k"] for r in http_rows]
    cf_tput = [r["throughput_ops_s"] for r in http_rows]
    cf_p50 = [r["lat_p50_ms"] for r in http_rows]
    cf_p99 = [r["lat_p99_ms"] for r in http_rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 2.6))

    ax1.plot(ks, cf_tput, "*-", color="#1b9e77", lw=2.0, markersize=8, label="ClaimFence Fine-Grained Lock")
    ax1.plot(leg_k, leg_tput, "o--", color="#d95f02", lw=1.5, label="Global-Lock Receiver (Baseline)")
    ax1.set_xlabel("Concurrent Workflows ($K$)")
    ax1.set_ylabel("Commit Throughput (ops/s)")
    ax1.set_title("(a) Receiver Throughput Scaling")
    ax1.grid(True, ls=":", alpha=0.6)
    ax1.legend(loc="lower right", fontsize=6.8)

    ax2.plot(ks, cf_p50, "s-", color="#386cb0", lw=1.5, label="ClaimFence p50")
    ax2.plot(ks, cf_p99, "*-", color="#1b9e77", lw=1.8, markersize=7, label="ClaimFence p99")
    ax2.plot(leg_k, leg_p99, "o--", color="#d95f02", lw=1.5, label="Global-Lock p99")
    ax2.set_yscale("log")
    ax2.set_xlabel("Concurrent Workflows ($K$)")
    ax2.set_ylabel("RPC Latency (ms, log scale)")
    ax2.set_title("(b) Tail Latency Under Contention")
    ax2.grid(True, which="both", ls=":", alpha=0.6)
    ax2.legend(loc="upper left", fontsize=6.8)

    fig.tight_layout(pad=0.6)
    fig.savefig(FIG_DIR / "fig6_concurrency_throughput.pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    os.makedirs(FIG_DIR, exist_ok=True)
    make_fig1_architecture()
    make_fig2_chaos_and_horizon()
    make_fig3_multimodel_sigkill()
    make_fig4_langgraph_and_ablation()
    make_fig5_storage_scaling()
    make_fig6_concurrency_throughput()
    print(f"Generated 6 vector PDF figures in {FIG_DIR}")


if __name__ == "__main__":
    main()

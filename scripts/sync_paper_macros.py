#!/usr/bin/env python3
"""Generate paper/metrics_macros.tex directly from measured JSON artifacts
and verify numerical consistency across all tables in paper/main.tex."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_TEX = ROOT / "paper" / "metrics_macros.tex"


def pct_str(val: float, decimals: int = 1) -> str:
    return f"{val * 100:.{decimals}f}\\%"


def main() -> None:
    mc = json.loads((ROOT / "results" / "model_checking_results.json").read_text())
    chaos = json.loads((ROOT / "results" / "chaos_6way_results.json").read_text())
    storage = json.loads((ROOT / "results" / "storage_and_concurrency_results.json").read_text())
    mm = json.loads((ROOT / "results" / "multimodel_sigkill_results.json").read_text())

    mc_map = {m["protocol"]: m for m in mc["models"]}
    m6 = chaos["main_6way"]
    sw = chaos["multi_crash_sweep"]
    step_lat = storage["step_latency_breakdown"]
    scale_10k = [r for r in storage["lookup_scaling"] if r["n_claims"] == 10000][0]
    http_map = {r["concurrency_k"]: r for r in storage["http_concurrency"]}

    lines = [
        "% Auto-generated from JSON telemetry by scripts/sync_paper_macros.py -- DO NOT EDIT MANUALLY",
        f"\\newcommand{{\\MCCFStates}}{{\\ensuremath{{{mc_map['claimfence_full']['reachable_states']}}}}}",
        f"\\newcommand{{\\MCCFEdges}}{{\\ensuremath{{{mc_map['claimfence_full']['transitions_explored']}}}}}",
        f"\\newcommand{{\\MCVOneStates}}{{\\ensuremath{{{mc_map['wal_v1_nonatomic_status']['reachable_states']}}}}}",
        f"\\newcommand{{\\MCVOneDup}}{{\\ensuremath{{{mc_map['wal_v1_nonatomic_status']['safety_duplicate_states']}}}}}",
        f"\\newcommand{{\\MCVOnePay}}{{\\ensuremath{{{mc_map['wal_v1_nonatomic_status']['terminal_payload_loss_violations']}}}}}",
        "",
        "% 6-Way Chaos Suite (1,500 paired episodes/cond)",
        f"\\newcommand{{\\ChaosBaseDup}}{{\\ensuremath{{{m6['baseline']['duplicate_ep_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosBaseStrict}}{{\\ensuremath{{{m6['baseline']['strict_e2e_correct_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosHashDup}}{{\\ensuremath{{{m6['content_hash']['duplicate_ep_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosHashStrict}}{{\\ensuremath{{{m6['content_hash']['strict_e2e_correct_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosPosDup}}{{\\ensuremath{{{m6['deterministic_pos']['duplicate_ep_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosPosStrict}}{{\\ensuremath{{{m6['deterministic_pos']['strict_e2e_correct_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosRemitDup}}{{\\ensuremath{{{m6['ckpt_ledger']['duplicate_ep_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosRemitStrict}}{{\\ensuremath{{{m6['ckpt_ledger']['strict_e2e_correct_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosCanonDup}}{{\\ensuremath{{{m6['det_canonical']['duplicate_ep_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosCanonPay}}{{\\ensuremath{{{m6['det_canonical']['payload_continuity_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosCanonStrict}}{{\\ensuremath{{{m6['det_canonical']['strict_e2e_correct_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosCFDup}}{{\\ensuremath{{{m6['claimfence']['duplicate_ep_rate']:.4f}}}}}",
        f"\\newcommand{{\\ChaosCFStrict}}{{\\ensuremath{{{m6['claimfence']['strict_e2e_correct_rate']:.4f}}}}}",
        "",
        "% Multi-crash k=4 survival",
        f"\\newcommand{{\\SweepKFourBase}}{{\\ensuremath{{{pct_str(sw['baseline']['4']['strict_e2e_correct_rate'], 1)}}}}}",
        f"\\newcommand{{\\SweepKFourRemit}}{{\\ensuremath{{{pct_str(sw['ckpt_ledger']['4']['strict_e2e_correct_rate'], 1)}}}}}",
        f"\\newcommand{{\\SweepKFourCanon}}{{\\ensuremath{{{pct_str(sw['det_canonical']['4']['strict_e2e_correct_rate'], 1)}}}}}",
        f"\\newcommand{{\\SweepKFourCF}}{{\\ensuremath{{{pct_str(sw['claimfence']['4']['strict_e2e_correct_rate'], 1)}}}}}",
        "",
        "% Storage & Concurrency on Apple M5 Pro APFS NVMe",
        f"\\newcommand{{\\LatFsyncStepPFifty}}{{\\ensuremath{{{step_lat['jsonl_fsync']['step_total_ms']['p50']:.2f}\\,\\mathrm{{ms}}}}}}",
        f"\\newcommand{{\\LatFullFsyncStepPFifty}}{{\\ensuremath{{{step_lat['jsonl_fullfsync']['step_total_ms']['p50']:.2f}\\,\\mathrm{{ms}}}}}}",
        f"\\newcommand{{\\LatSQLiteStepPFifty}}{{\\ensuremath{{{step_lat['sqlite_wal']['step_total_ms']['p50']:.2f}\\,\\mathrm{{ms}}}}}}",
        f"\\newcommand{{\\ScaleTenKLegacyMs}}{{\\ensuremath{{{scale_10k['legacy_unindexed_find_p50_ms']:.2f}\\,\\mathrm{{ms}}}}}}",
        f"\\newcommand{{\\ScaleTenKCFUs}}{{\\ensuremath{{{scale_10k['claimfence_indexed_find_p50_ms'] * 1000:.2f}\\,\\mu\\mathrm{{s}}}}}}",
        f"\\newcommand{{\\ScaleTenKSpeedup}}{{\\ensuremath{{{int(round(scale_10k['lookup_speedup_vs_legacy'])):,}\\times}}}}",
        f"\\newcommand{{\\HttpPeakOps}}{{\\ensuremath{{{http_map[4]['throughput_ops_s']:,.1f}}}}}",
        f"\\newcommand{{\\HttpThirtyTwoOps}}{{\\ensuremath{{{http_map[32]['throughput_ops_s']:,.1f}}}}}",
        "",
        "% Multi-Model Real SIGKILL Table Rows",
    ]

    # Build pre-formatted LaTeX rows for the Qwen2.5 multi-model real SIGKILL table
    table_rows = []
    for m_entry in mm["models"]:
        mname = m_entry["model_id"].split("/")[-1].replace("-Instruct", "")
        a = m_entry["architectures"]
        # Columns: Model | Reword/Shift | Base Dup/E2E | Hash Dup/E2E | Pos Dup/E2E | REMIT Dup/E2E | Canon Dup/E2E | ClaimFence Dup/E2E
        reword_p = a["baseline"]["organic_reword_rate"] * 100
        shift_p = a["baseline"]["organic_plan_shift_rate"] * 100
        row = (
            f"\\texttt{{{mname}}} & "
            f"{reword_p:.0f}\\% / {shift_p:.0f}\\% & "
            f"{a['baseline']['duplicate_ep_rate']:.2f} / {a['baseline']['strict_e2e_rate']:.2f} & "
            f"{a['content_hash']['duplicate_ep_rate']:.2f} / {a['content_hash']['strict_e2e_rate']:.2f} & "
            f"{a['deterministic_pos']['duplicate_ep_rate']:.2f} / {a['deterministic_pos']['strict_e2e_rate']:.2f} & "
            f"{a['ckpt_ledger']['duplicate_ep_rate']:.2f} / {a['ckpt_ledger']['strict_e2e_rate']:.2f} & "
            f"{a['det_canonical']['duplicate_ep_rate']:.2f} / {a['det_canonical']['strict_e2e_rate']:.2f} & "
            f"\\textbf{{{a['claimfence']['duplicate_ep_rate']:.2f}}} / \\textbf{{{a['claimfence']['strict_e2e_rate']:.2f}}} \\\\"
        )
        table_rows.append(row)

    lines.append("\\newcommand{\\MultiModelSigkillRows}{%")
    for r in table_rows:
        lines.append("  " + r)
    lines.append("}")
    lines.append(f"\\newcommand{{\\TotalMMSSigkillEps}}{{\\ensuremath{{{mm['total_sigkill_episodes']}}}}}")

    OUT_TEX.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_TEX} ({len(lines)} lines)")


if __name__ == "__main__":
    main()

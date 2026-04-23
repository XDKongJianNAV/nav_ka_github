# -*- coding: utf-8 -*-
"""
nb_ka_multifreq_wkb_spectrum.py
===============================

泛 Ka 频点 WKB 与接收机频谱分析。

频率轴：
    19.0, 19.5, ..., 31.0 GHz

输出：
    - 多频 WKB 幅度/衰减/相位/群时延结果
    - 每个频点一套接收机频谱诊断
    - summary.json / csv / png
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from nav_ka import SCRATCH_RESULTS_ROOT
from nav_ka.core.plasma_wkb_core import run_wkb_frequency_sweep, summarize_wkb_frequency_sweep
from nav_ka.legacy import ka_multifreq_receiver_common as KA_COMMON


ROOT = Path(__file__).resolve().parents[3]


RESULTS_DIR = SCRATCH_RESULTS_ROOT / "results_ka_multifreq_wkb_spectrum"
SPECTRUM_DIR = RESULTS_DIR / "receiver_spectra"
TRUTH_FREE_RUNTIME = False

FREQUENCIES_HZ = np.arange(19.0e9, 31.0e9 + 0.25e9, 0.5e9)
NU_EN_HZ = KA_COMMON.DEFAULT_NU_EN_HZ


def freq_label(fc_hz: float) -> str:
    return f"{fc_hz / 1e9:.1f}".replace(".", "p") + "GHz"


def find_input_files() -> tuple[Path, Path]:
    large_candidates = [
        ROOT / "Large_Scale_Ne_Smooth.csv",
        ROOT / "data" / "raw" / "Large_Scale_Ne_Smooth.csv",
        ROOT / "data" / "Large_Scale_Ne_Smooth.csv",
        ROOT / "notebooks" / "Large_Scale_Ne_Smooth.csv",
    ]
    aoa_candidates = [
        ROOT / "RAMC_AOA_Sim_Input.csv",
        ROOT / "data" / "raw" / "RAMC_AOA_Sim_Input.csv",
        ROOT / "data" / "RAMC_AOA_Sim_Input.csv",
        ROOT / "notebooks" / "RAMC_AOA_Sim_Input.csv",
    ]
    large_csv = next((p for p in large_candidates if p.exists()), None)
    aoa_csv = next((p for p in aoa_candidates if p.exists()), None)
    if large_csv is None:
        raise FileNotFoundError("找不到 Large_Scale_Ne_Smooth.csv")
    if aoa_csv is None:
        raise FileNotFoundError("找不到 RAMC_AOA_Sim_Input.csv")
    return large_csv, aoa_csv


def build_field_context() -> dict[str, np.ndarray]:
    large_csv, aoa_csv = find_input_files()
    print(f"[文件] large_csv = {large_csv}")
    print(f"[文件] aoa_csv   = {aoa_csv}")
    return KA_COMMON.build_default_field_context()


def save_overview_plots(
    t_eval_rel: np.ndarray,
    sweep_result: dict,
) -> None:
    freqs_ghz = np.asarray(sweep_result["frequencies_hz"], dtype=float) / 1e9

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), dpi=160)
    heatmaps = [
        ("amplitude", "Amplitude", axes[0, 0]),
        ("attenuation_dB", "Attenuation (dB)", axes[0, 1]),
        ("phase_shift_rad", "Phase Shift (rad)", axes[1, 0]),
        ("group_delay_s", "Group Delay (ns)", axes[1, 1]),
    ]

    for key, title, ax in heatmaps:
        data = np.asarray(sweep_result[key], dtype=float)
        if key == "group_delay_s":
            data = data * 1e9
        mesh = ax.imshow(
            data,
            aspect="auto",
            origin="lower",
            extent=[t_eval_rel[0], t_eval_rel[-1], freqs_ghz[0], freqs_ghz[-1]],
        )
        ax.set_title(title)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Frequency (GHz)")
        fig.colorbar(mesh, ax=ax, shrink=0.88)

    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "wkb_multifreq_overview.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), dpi=160)
    summary = summarize_wkb_frequency_sweep(
        frequencies_hz=sweep_result["frequencies_hz"],
        amplitude=sweep_result["amplitude"],
        attenuation_dB=sweep_result["attenuation_dB"],
        phase_shift_rad=sweep_result["phase_shift_rad"],
        group_delay_s=sweep_result["group_delay_s"],
    )

    axes[0].plot(freqs_ghz, summary["attenuation_dB"]["median"], marker="o")
    axes[0].set_title("Median Attenuation vs Frequency")
    axes[0].set_ylabel("dB")
    axes[0].grid(True, ls=":", alpha=0.5)

    axes[1].plot(freqs_ghz, summary["phase_shift_rad"]["median"], marker="o")
    axes[1].set_title("Median Phase Shift vs Frequency")
    axes[1].set_ylabel("rad")
    axes[1].grid(True, ls=":", alpha=0.5)

    axes[2].plot(freqs_ghz, np.asarray(summary["group_delay_s"]["median"]) * 1e9, marker="o")
    axes[2].set_title("Median Group Delay vs Frequency")
    axes[2].set_xlabel("Frequency (GHz)")
    axes[2].set_ylabel("ns")
    axes[2].grid(True, ls=":", alpha=0.5)

    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "wkb_multifreq_frequency_summary.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_summary_csv(summary_rows: list[dict[str, float]]) -> None:
    fieldnames = [
        "frequency_hz",
        "amplitude_median",
        "attenuation_db_median",
        "phase_rad_median",
        "group_delay_ns_median",
        "receiver_tau_rmse_ns",
        "receiver_fd_rmse_hz",
        "peak_to_second_db",
        "post_corr_snr_median_db",
        "carrier_lock_metric_median",
        "loss_fraction",
    ]
    with (RESULTS_DIR / "frequency_summary.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)


def save_receiver_spectrum_plot(
    fc_hz: float,
    acq_result: dict,
    trk_diag: dict,
    fs_hz: float,
) -> None:
    label = freq_label(fc_hz)
    freq_raw, spec_raw = KA_COMMON.compute_spectrum_db(np.asarray(acq_result["rx_block"]), fs_hz)
    freq_bb, spec_bb = KA_COMMON.compute_spectrum_db(np.asarray(acq_result["best_mixed"]), fs_hz)

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), dpi=160)
    axes[0].plot(freq_raw / 1e3, spec_raw, lw=1.1)
    axes[0].set_title(f"{label} Acquisition Block Spectrum")
    axes[0].set_xlabel("Frequency (kHz)")
    axes[0].set_ylabel("dB")
    axes[0].grid(True, ls=":", alpha=0.5)

    axes[1].plot(freq_bb / 1e3, spec_bb, lw=1.1, color="tab:orange")
    axes[1].set_title(f"{label} Acquisition Baseband Spectrum")
    axes[1].set_xlabel("Frequency (kHz)")
    axes[1].set_ylabel("dB")
    axes[1].grid(True, ls=":", alpha=0.5)

    loss_frac = float(np.mean(np.asarray(trk_diag["sustained_loss"], dtype=float)))
    fig.suptitle(f"{label} receiver spectra | loss fraction = {loss_frac:.3f}")
    fig.tight_layout()
    fig.savefig(SPECTRUM_DIR / f"{label}_receiver_spectrum.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    np.random.seed(2026)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    SPECTRUM_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("泛 Ka 多频 WKB 与接收机频谱分析")
    print("=" * 100)

    field_result = build_field_context()
    t_eval = np.asarray(field_result["t_eval"], dtype=float)
    t_eval_rel = t_eval - t_eval[0]
    z_eval = np.asarray(field_result["z_eval"], dtype=float)
    ne_combined = np.asarray(field_result["ne_combined"], dtype=float)

    sweep_result = run_wkb_frequency_sweep(
        frequencies_hz=FREQUENCIES_HZ,
        z_grid=z_eval,
        Ne_matrix=ne_combined,
        nu_en=NU_EN_HZ,
        collision_input_unit="Hz",
        amplitude_floor=1e-20,
        fix_physics=True,
        verbose=True,
    )
    sweep_result["wkb_time_s"] = t_eval_rel

    save_overview_plots(t_eval_rel, sweep_result)
    sweep_summary = summarize_wkb_frequency_sweep(
        frequencies_hz=sweep_result["frequencies_hz"],
        amplitude=sweep_result["amplitude"],
        attenuation_dB=sweep_result["attenuation_dB"],
        phase_shift_rad=sweep_result["phase_shift_rad"],
        group_delay_s=sweep_result["group_delay_s"],
    )

    summary_rows: list[dict[str, float]] = []
    receiver_runs: list[dict[str, float | str]] = []
    details_dir = RESULTS_DIR / "frequency_details"
    details_dir.mkdir(parents=True, exist_ok=True)

    for idx, fc_hz in enumerate(FREQUENCIES_HZ):
        label = freq_label(float(fc_hz))
        print(f"\n[接收机频谱] {idx + 1}/{len(FREQUENCIES_HZ)} -> {label}")

        run_result = KA_COMMON.run_single_channel_for_frequency(
            float(fc_hz),
            field_result=field_result,
            nu_en_hz=NU_EN_HZ,
            delta_f_hz=KA_COMMON.DEFAULT_DELTA_F_HZ,
            rng_seed=2026 + idx,
            truth_free_runtime=TRUTH_FREE_RUNTIME,
        )
        wkb_result = run_result["wkb_result"]
        receiver_outputs = run_result["receiver_outputs"]
        cfg_sig = run_result["cfg_sig"]
        acq_result = receiver_outputs.acq_result
        acq_diag = receiver_outputs.acq_diag
        trk_result = receiver_outputs.trk_result
        trk_diag = receiver_outputs.trk_diag
        metrics = run_result["metrics"]

        save_receiver_spectrum_plot(float(fc_hz), acq_result, trk_diag, cfg_sig.fs_hz)

        summary_rows.append(
            {
                "frequency_hz": float(fc_hz),
                "amplitude_median": float(np.median(np.asarray(wkb_result["A_t"], dtype=float))),
                "attenuation_db_median": float(np.median(20.0 * np.log10(np.asarray(wkb_result["A_t"], dtype=float) + 1e-30))),
                "phase_rad_median": float(np.median(np.asarray(wkb_result["phi_t"], dtype=float))),
                "group_delay_ns_median": float(np.median(np.asarray(wkb_result["tau_g_t"], dtype=float)) * 1e9),
                "receiver_tau_rmse_ns": float(metrics["tau_rmse_ns"]),
                "receiver_fd_rmse_hz": float(metrics["fd_rmse_hz"]),
                "peak_to_second_db": float(metrics["peak_to_second_db"]),
                "post_corr_snr_median_db": float(metrics["post_corr_snr_median_db"]),
                "carrier_lock_metric_median": float(metrics["carrier_lock_metric_median"]),
                "loss_fraction": float(metrics["loss_fraction"]),
            }
        )
        receiver_runs.append(
            {
                "label": label,
                "frequency_hz": float(fc_hz),
                "tau_rmse_ns": float(metrics["tau_rmse_ns"]),
                "fd_rmse_hz": float(metrics["fd_rmse_hz"]),
                "peak_to_second_db": float(metrics["peak_to_second_db"]),
                "loss_fraction": float(metrics["loss_fraction"]),
                "spectrum_png": str((SPECTRUM_DIR / f"{label}_receiver_spectrum.png").resolve()),
            }
        )

        per_freq_detail = {
            "label": label,
            "frequency_hz": float(fc_hz),
            "metrics": metrics,
            "wkb": {
                "amplitude_median": float(np.median(np.asarray(wkb_result["A_t"], dtype=float))),
                "attenuation_db_median": float(np.median(20.0 * np.log10(np.asarray(wkb_result["A_t"], dtype=float) + 1e-30))),
                "phase_rad_median": float(np.median(np.asarray(wkb_result["phi_t"], dtype=float))),
                "group_delay_ns_median": float(np.median(np.asarray(wkb_result["tau_g_t"], dtype=float)) * 1e9),
            },
            "samples": {
                "pseudorange": int(len(np.asarray(trk_result["pseudorange_m"]))),
                "carrier_phase": int(len(np.asarray(trk_result["carrier_phase_cycles"]))),
                "doppler": int(len(np.asarray(trk_result["doppler_hz"]))),
            },
            "spectrum_png": str((SPECTRUM_DIR / f"{label}_receiver_spectrum.png").resolve()),
        }
        (details_dir / f"{label}.json").write_text(
            json.dumps(per_freq_detail, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    write_summary_csv(summary_rows)

    summary_json = {
        "title": "泛 Ka 多频 WKB 与接收机频谱分析",
        "frequencies_hz": [float(v) for v in FREQUENCIES_HZ],
        "frequency_labels": [freq_label(float(v)) for v in FREQUENCIES_HZ],
        "wkb_time_range_s": [float(t_eval_rel[0]), float(t_eval_rel[-1])],
        "collision_frequency_hz": NU_EN_HZ,
        "receiver_config": {
            "fs_hz": KA_COMMON.DEFAULT_FS_HZ,
            "chip_rate_hz": KA_COMMON.DEFAULT_CHIP_RATE_HZ,
            "coherent_integration_s": KA_COMMON.DEFAULT_COHERENT_INTEGRATION_S,
            "code_length": KA_COMMON.DEFAULT_CODE_LENGTH,
            "cn0_dbhz": KA_COMMON.DEFAULT_CN0_DBHZ,
            "truth_free_runtime": bool(TRUTH_FREE_RUNTIME),
        },
        "wkb_summary": sweep_summary,
        "receiver_runs": receiver_runs,
        "outputs": {
            "results_dir": str(RESULTS_DIR.resolve()),
            "summary_csv": str((RESULTS_DIR / "frequency_summary.csv").resolve()),
            "overview_png": str((RESULTS_DIR / "wkb_multifreq_overview.png").resolve()),
            "frequency_summary_png": str((RESULTS_DIR / "wkb_multifreq_frequency_summary.png").resolve()),
            "spectrum_dir": str(SPECTRUM_DIR.resolve()),
            "frequency_detail_dir": str(details_dir.resolve()),
        },
    }
    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(summary_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

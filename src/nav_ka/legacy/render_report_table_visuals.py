from __future__ import annotations

import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def configure_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = [
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 160
    plt.rcParams["savefig.dpi"] = 160
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.25


def load_rows(csv_path: Path) -> list[dict[str, float]]:
    with csv_path.open() as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            parsed = {key: float(value) for key, value in row.items()}
            parsed["frequency_ghz"] = parsed["frequency_hz"] / 1e9
            rows.append(parsed)
    return rows


def band_rows(rows: list[dict[str, float]], lo: float, hi: float) -> list[dict[str, float]]:
    return [row for row in rows if lo <= row["frequency_ghz"] <= hi]


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def representative_rows(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    targets = {19.0, 22.5, 31.0}
    selected = [row for row in rows if row["frequency_ghz"] in targets]
    selected.sort(key=lambda row: row["frequency_ghz"])
    return selected


def add_representative_markers(ax: plt.Axes) -> None:
    for freq in (19.0, 22.5, 31.0):
        ax.axvline(freq, color="0.6", linestyle="--", linewidth=0.9, alpha=0.7)


def save_overview_key_metrics(rows: list[dict[str, float]], output_dir: Path) -> None:
    metrics = [
        ("single_group_delay_ns_median", "Group Delay Median", "ns"),
        ("single_receiver_tau_rmse_ns", "Receiver Tau RMSE", "ns"),
        ("single_post_corr_snr_median_db", "Post-Corr SNR Median", "dB"),
        ("single_loss_fraction", "Loss Fraction", "ratio"),
        ("wls_case_b_wls_position_error_3d_m", "Case B WLS 3D Error", "m"),
        ("wls_monte_carlo_wls_p90_m", "MC WLS P90 Error", "m"),
        ("ekf_pr_doppler_mean_position_error_3d_m", "EKF PR+D 3D Pos Error", "m"),
        ("ekf_pr_doppler_mean_velocity_error_3d_mps", "EKF PR+D 3D Vel Error", "m/s"),
    ]

    freqs = [row["frequency_ghz"] for row in rows]
    fig, axes = plt.subplots(2, 4, figsize=(18, 8), constrained_layout=True)
    axes = axes.flatten()

    for ax, (key, title, unit) in zip(axes, metrics):
        values = [row[key] for row in rows]
        ax.plot(freqs, values, color="#1f77b4", marker="o", markersize=3.5, linewidth=1.6)
        add_representative_markers(ax)
        ylabel = unit if unit else "ratio"
        ax.set_title(title)
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(ylabel)

    fig.suptitle("Full-Band Key Metric Overview", fontsize=16)
    fig.savefig(output_dir / "overview_key_metrics.png", bbox_inches="tight")
    plt.close(fig)


def save_band_summary(rows: list[dict[str, float]], output_dir: Path) -> None:
    bands = [
        ("Low", 19.0, 22.0),
        ("Mid", 22.5, 25.5),
        ("High", 26.0, 31.0),
    ]
    metrics = [
        ("single_receiver_tau_rmse_ns", "Mean Receiver Tau RMSE", "ns"),
        ("single_post_corr_snr_median_db", "Mean Post-Corr SNR Median", "dB"),
        ("wls_case_b_wls_position_error_3d_m", "Mean Case B WLS 3D Error", "m"),
        ("ekf_pr_doppler_mean_position_error_3d_m", "Mean EKF PR+D 3D Pos Error", "m"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    axes = axes.flatten()
    colors = ["#d95f02", "#7570b3", "#1b9e77"]

    for ax, (key, title, unit) in zip(axes, metrics):
        labels = []
        values = []
        for label, lo, hi in bands:
            subset = band_rows(rows, lo, hi)
            labels.append(label)
            values.append(mean([row[key] for row in subset]))
        bars = ax.bar(labels, values, color=colors)
        ax.set_title(title)
        ax.set_ylabel(unit)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{value:.3f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    fig.suptitle("Band Summary Metrics", fontsize=16)
    fig.savefig(output_dir / "band_summary_metrics.png", bbox_inches="tight")
    plt.close(fig)


def save_representative_metrics(
    rows: list[dict[str, float]],
    output_dir: Path,
    filename: str,
    title: str,
    metrics: list[tuple[str, str, str]],
) -> None:
    selected = representative_rows(rows)
    labels = [f'{row["frequency_ghz"]:.1f}' for row in selected]

    fig, axes = plt.subplots(2, 3, figsize=(16, 8), constrained_layout=True)
    axes = axes.flatten()

    for ax, (key, metric_title, unit) in zip(axes, metrics):
        values = [row[key] for row in selected]
        bars = ax.bar(labels, values, color=["#c44e52", "#dd8452", "#55a868"])
        ax.set_title(metric_title)
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(unit)
        for bar, value in zip(bars, values):
            fmt = f"{value:.3f}" if abs(value) < 1000 else f"{value:.1f}"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                fmt,
                ha="center",
                va="bottom",
                fontsize=9,
            )

    for ax in axes[len(metrics) :]:
        ax.axis("off")

    fig.suptitle(title, fontsize=16)
    fig.savefig(output_dir / filename, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    configure_matplotlib()
    repo_root = Path(__file__).resolve().parents[3]
    results_root = repo_root / "archive" / "results" / "canonical" / "results_ka_multifreq"
    output_dir = results_root / "report_visuals"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(results_root / "cross_frequency" / "combined_metrics.csv")

    save_overview_key_metrics(rows, output_dir)
    save_band_summary(rows, output_dir)
    save_representative_metrics(
        rows,
        output_dir,
        "representative_single_channel_metrics.png",
        "Representative Single-Channel Metrics",
        [
            ("single_receiver_tau_rmse_ns", "Receiver Tau RMSE", "ns"),
            ("single_receiver_fd_rmse_hz", "Receiver Freq RMSE", "Hz"),
            ("single_post_corr_snr_median_db", "Post-Corr SNR Median", "dB"),
            ("single_carrier_lock_metric_median", "Carrier Lock Median", "ratio"),
            ("single_loss_fraction", "Loss Fraction", "ratio"),
        ],
    )
    save_representative_metrics(
        rows,
        output_dir,
        "representative_wls_metrics.png",
        "Representative WLS Metrics",
        [
            ("wls_effective_pseudorange_sigma_1s_m", "1 s PR Sigma", "m"),
            ("wls_case_a_wls_position_error_3d_m", "Case A WLS 3D Error", "m"),
            ("wls_case_b_wls_position_error_3d_m", "Case B WLS 3D Error", "m"),
            ("wls_monte_carlo_wls_mean_m", "MC WLS Mean Error", "m"),
            ("wls_monte_carlo_wls_p90_m", "MC WLS P90 Error", "m"),
        ],
    )
    save_representative_metrics(
        rows,
        output_dir,
        "representative_dynamic_metrics.png",
        "Representative Dynamic Metrics",
        [
            ("ekf_epoch_wls_mean_position_error_3d_m", "Epoch WLS Mean 3D Error", "m"),
            ("ekf_pr_only_mean_position_error_3d_m", "EKF PR Mean 3D Error", "m"),
            ("ekf_pr_doppler_mean_position_error_3d_m", "EKF PR+D Mean 3D Error", "m"),
            ("ekf_pr_doppler_mean_velocity_error_3d_mps", "EKF PR+D Mean 3D Vel Error", "m/s"),
            ("ekf_pr_doppler_mean_innovation_pr_m", "EKF PR+D Mean PR Innovation", "m"),
            ("ekf_pr_doppler_prediction_only_epochs", "Prediction-Only Epochs", "epochs"),
        ],
    )


if __name__ == "__main__":
    main()

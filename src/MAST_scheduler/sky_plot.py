from __future__ import annotations

import io
import math

import astropy.units as u
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time

matplotlib.use("Agg")

_BG = "#0f172a"
_GRID = "#334155"
_ACCENT = "#38bdf8"
_SELECTED_COLOR = "#f472b6"
_MOON_COLOR = "#fbbf24"
_BELOW_COLOR = "#475569"
_TEXT = "#e5e7eb"


def generate_sky_plot(
    targets: list[tuple[str, float, float, str | None]],  # (label, ra_deg, dec_deg, plan_id|None)
    site: EarthLocation,
    time: Time,
    moon_alt_deg: float | None,
    moon_az_deg: float | None,
    moon_illumination_pct: float | None,
    *,
    selected_plan_ids: set[str] | None = None,
    size_px: int = 1200,
) -> bytes:
    dpi = 100
    fig_size = size_px / dpi

    fig = plt.figure(figsize=(fig_size, fig_size), facecolor=_BG)
    ax = fig.add_subplot(111, projection="polar", facecolor=_BG)

    # Azimuth: 0=N at top, clockwise. Matplotlib polar has 0 at right, counter-clockwise.
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    # Altitude mapped to radius: alt=90° → r=0 (centre), alt=0° → r=1 (edge).
    ax.set_ylim(0, 1)
    ax.set_yticks([0, 1 / 3, 2 / 3, 1])
    ax.set_yticklabels(["90°", "60°", "30°", "0°"], color=_TEXT, fontsize=9)
    ax.yaxis.set_tick_params(labelcolor=_TEXT)

    # Grid circles at 30° and 60° altitude
    for alt_deg, ls in ((60, "--"), (30, "--")):
        r = 1 - alt_deg / 90.0
        theta = np.linspace(0, 2 * math.pi, 200)
        ax.plot(theta, np.full_like(theta, r), color=_GRID, linewidth=0.6, linestyle=ls)

    # Horizon ring
    theta = np.linspace(0, 2 * math.pi, 200)
    ax.plot(theta, np.ones_like(theta), color=_GRID, linewidth=1.0)

    # Cardinal labels
    for label, az in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
        ax.text(
            math.radians(az),
            1.08,
            label,
            ha="center",
            va="center",
            color=_TEXT,
            fontsize=11,
            fontweight="bold",
        )

    # Remove default grid and spines
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    ax.set_xticklabels([])

    selected = selected_plan_ids or set()

    def _plot_target(name: str, az_rad: float, r: float, color: str, is_selected: bool) -> None:
        marker = "*" if is_selected else "o"
        size = 160 if is_selected else 80
        zorder = 7 if is_selected else 5
        ax.scatter(az_rad, r, color=color, s=size, marker=marker, zorder=zorder)
        ax.text(
            az_rad,
            r - 0.06,
            name,
            ha="center",
            va="top",
            color=color,
            fontsize=11,
            fontweight="bold",
            zorder=zorder,
            bbox={"boxstyle": "round,pad=0.2", "facecolor": _BG, "edgecolor": "none", "alpha": 0.7},
        )

    # Resolve all target positions then draw non-selected first, selected on top.
    frame = AltAz(obstime=time, location=site)
    resolved: list[tuple[str, float, float, str, bool]] = []  # name, az_rad, r, color, is_selected
    for name, ra_deg, dec_deg, plan_id in targets:
        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
        altaz = coord.transform_to(frame)
        alt = float(altaz.alt.deg)
        az = float(altaz.az.deg)
        is_selected = plan_id is not None and plan_id in selected
        if alt >= 0:
            r = 1 - alt / 90.0
            color = _SELECTED_COLOR if is_selected else _ACCENT
        else:
            r = 1.0
            color = _BELOW_COLOR
        resolved.append((name, math.radians(az), r, color, is_selected))

    for name, az_rad, r, color, is_selected in resolved:
        if not is_selected:
            _plot_target(name, az_rad, r, color, is_selected)
    for name, az_rad, r, color, is_selected in resolved:
        if is_selected:
            _plot_target(name, az_rad, r, color, is_selected)

    # Legend
    legend_items = [
        (plt.scatter([], [], color=_SELECTED_COLOR, s=100, marker="*"), "Scheduled target"),
        (plt.scatter([], [], color=_ACCENT, s=60, marker="o"), "Candidate (above horizon)"),
        (plt.scatter([], [], color=_BELOW_COLOR, s=60, marker="o"), "Below horizon"),
        (
            plt.scatter(
                [], [], s=120, facecolors="none", edgecolors=_MOON_COLOR, linewidths=1.5, marker="o"
            ),
            "Moon",
        ),
    ]
    handles, labels = zip(*legend_items, strict=True)
    ax.legend(
        handles,
        labels,
        loc="lower left",
        bbox_to_anchor=(-0.12, -0.12),
        framealpha=0.6,
        facecolor=_BG,
        edgecolor=_GRID,
        labelcolor=_TEXT,
        fontsize=9,
        scatterpoints=1,
        handletextpad=0.4,
    )

    # Moon
    if moon_alt_deg is not None and moon_az_deg is not None:
        moon_r = 1 - moon_alt_deg / 90.0
        moon_r = max(0.0, min(1.0, moon_r))
        ax.scatter(
            math.radians(moon_az_deg),
            moon_r,
            marker="o",
            s=400,
            facecolors="none",
            edgecolors=_MOON_COLOR,
            linewidths=2.0,
            zorder=5,
        )
        illum_label = (
            f"{moon_illumination_pct:.0f}%" if moon_illumination_pct is not None else "Moon"
        )
        ax.text(
            math.radians(moon_az_deg),
            moon_r - 0.07,
            illum_label,
            ha="center",
            va="top",
            color=_MOON_COLOR,
            fontsize=11,
            fontweight="bold",
            bbox={"boxstyle": "round,pad=0.2", "facecolor": _BG, "edgecolor": "none", "alpha": 0.7},
        )
    elif moon_illumination_pct is not None:
        ax.text(
            0.98,
            0.02,
            f"Moon {moon_illumination_pct:.0f}%",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            color=_MOON_COLOR,
            fontsize=11,
            fontweight="bold",
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=_BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()

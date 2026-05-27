"""Flat-top 阶段最小物理维持模型。

本文件刻意保持学生作业级复杂度：不用自由边界平衡和输运求解，只保留
平台期最关键的真实约束链：等离子体电路、CS 互感维持、PF 响应矩阵、
Div 打击点等效响应，以及 q95/li/VS 裕度诊断。
"""

from __future__ import annotations

import math
from typing import Any

MU0 = 4.0 * math.pi * 1.0e-7
CS_COILS = ("CS1", "CS2", "CS3")
PF_COILS = ("PF1", "PF2", "PF3", "PF4")
DIV_COILS = ("Div1", "Div2")
AUX_COILS = DIV_COILS + ("VS",)
ALL_COILS = CS_COILS + PF_COILS + AUX_COILS
SHAPE_FIELDS = ("major_radius_m", "minor_radius_m", "elongation", "triangularity", "vertical_position_m")

DEFAULT_CS_MUTUAL_INDUCTANCE_H = {"CS1": 1.2e-3, "CS2": 1.5e-3, "CS3": 1.2e-3}
DEFAULT_CS_SHARE = {"CS1": 0.30, "CS2": 0.40, "CS3": 0.30}
DEFAULT_PF_RESPONSE_MATRIX = {
    "rows": ["Bv", "Br", "G_kappa", "G_delta", "G_Z", "G_X"],
    "columns": ["PF1", "PF2", "PF3", "PF4"],
    "values": [
        [0.002, 0.004, 0.010, 0.018],
        [0.001, -0.001, 0.004, 0.000],
        [0.020, 0.030, 0.006, 0.002],
        [0.004, 0.018, 0.010, 0.002],
        [0.001, -0.001, 0.006, 0.001],
        [0.002, 0.005, 0.008, 0.003],
    ],
}
DEFAULT_DIV_RESPONSE_MATRIX = {
    "rows": ["strike_R", "strike_Z"],
    "columns": ["Div1", "Div2"],
    "values": [[0.020, -0.015], [0.010, 0.010]],
}


def make_time_axis(t_start_s: float, t_end_s: float, dt_s: float) -> list[float]:
    if dt_s <= 0:
        raise ValueError("waveform_strategy.time_grid.step_s must be greater than 0")
    if t_end_s <= t_start_s:
        raise ValueError("targets.end_time_s must be greater than handoff_from_stage_2.time_s")
    times: list[float] = []
    t = t_start_s
    eps = dt_s * 1e-9
    while t < t_end_s - eps:
        times.append(round(t, 10))
        t += dt_s
    times.append(round(t_end_s, 10))
    return times


def smooth_fraction(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def interpolate(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction


def sinusoid(time_s: float, amplitude: float, period_s: float, phase_deg: float = 0.0) -> float:
    if period_s <= 0:
        return 0.0
    return amplitude * math.sin(2.0 * math.pi * time_s / period_s + math.radians(phase_deg))


def differentiate(times: list[float], values: list[float]) -> list[float]:
    if len(values) < 2:
        return [0.0 for _ in values]
    deriv: list[float] = []
    for i in range(len(values)):
        if i == 0:
            dt = times[1] - times[0]
            deriv.append((values[1] - values[0]) / dt)
        elif i == len(values) - 1:
            dt = times[-1] - times[-2]
            deriv.append((values[-1] - values[-2]) / dt)
        else:
            dt = times[i + 1] - times[i - 1]
            deriv.append((values[i + 1] - values[i - 1]) / dt)
    return deriv


def integrate_trapezoid(times: list[float], values: list[float], initial: float = 0.0) -> list[float]:
    out = [float(initial)]
    for i in range(1, len(times)):
        out.append(out[-1] + 0.5 * (values[i] + values[i - 1]) * (times[i] - times[i - 1]))
    return out


def generate_ip_hold_profile(times: list[float], start_ip_ma: float, target_ip_ma: float, max_deviation_ma: float, smoothing_time_s: float) -> list[float]:
    if not times:
        return []
    t0 = times[0]
    duration = max(times[-1] - t0, 1e-9)
    values: list[float] = []
    for time_s in times:
        settle = smooth_fraction(min((time_s - t0) / max(smoothing_time_s, 1e-9), 1.0))
        baseline = interpolate(start_ip_ma, target_ip_ma, settle)
        ripple = 0.10 * max_deviation_ma * math.sin(2.0 * math.pi * (time_s - t0) / duration)
        values.append(max(target_ip_ma - max_deviation_ma, min(target_ip_ma + max_deviation_ma, baseline + ripple)))
    return values


def generate_shape_hold_profile(times: list[float], start_shape: dict[str, Any], target_shape: dict[str, Any], shape_tolerance_m: float) -> dict[str, list[float]]:
    result = {field: [] for field in SHAPE_FIELDS}
    if not times:
        return result
    t0 = times[0]
    duration = max(times[-1] - t0, 1e-9)
    settle_time = min(duration, 0.5)
    for field in SHAPE_FIELDS:
        start = float(start_shape.get(field, target_shape.get(field, 0.0)))
        end = float(target_shape.get(field, start))
        amplitude = 0.15 * shape_tolerance_m if field in {"major_radius_m", "minor_radius_m", "vertical_position_m"} else 0.0
        for time_s in times:
            settle = smooth_fraction((time_s - t0) / max(settle_time, 1e-9))
            result[field].append(interpolate(start, end, settle) + amplitude * math.sin(2.0 * math.pi * (time_s - t0) / duration))
    return result


def generate_internal_inductance_profile(times: list[float], physics: dict[str, Any]) -> list[float]:
    cfg = physics.get("internal_inductance", {})
    base = float(cfg.get("flat", cfg.get("end", 0.78)))
    amp = float(cfg.get("ripple_amplitude", 0.01))
    duration = max(times[-1] - times[0], 1e-9) if times else 1.0
    return [base + amp * math.sin(2.0 * math.pi * (t - times[0]) / duration) for t in times]


def generate_temperature_profile(times: list[float], physics: dict[str, Any]) -> list[float]:
    cfg = physics.get("plasma_resistance", {})
    te = float(cfg.get("Te_flat_eV", 3000.0))
    variation = float(cfg.get("temperature_variation_fraction", 0.03))
    duration = max(times[-1] - times[0], 1e-9) if times else 1.0
    return [te * (1.0 + variation * math.sin(2.0 * math.pi * (t - times[0]) / duration + math.pi / 4.0)) for t in times]


def generate_plasma_resistance_profile(times: list[float], physics: dict[str, Any], te_profile: list[float]) -> list[float]:
    cfg = physics.get("plasma_resistance", {})
    r_flat = float(cfg.get("R_flat_ohm", 1.0e-6))
    te_flat = float(cfg.get("Te_flat_eV", 3000.0))
    variation = float(cfg.get("variation_fraction", 0.10))
    if cfg.get("mode") == "temperature_power_law":
        return [r_flat * (te_flat / max(te, 1.0)) ** 1.5 for te in te_profile]
    duration = max(times[-1] - times[0], 1e-9) if times else 1.0
    return [r_flat * (1.0 + variation * math.sin(2.0 * math.pi * (t - times[0]) / duration)) for t in times]


def compute_plasma_inductance_profile(shape_profile: dict[str, list[float]], li_profile: list[float]) -> list[float]:
    out: list[float] = []
    for r, a, li in zip(shape_profile["major_radius_m"], shape_profile["minor_radius_m"], li_profile):
        a_safe = max(float(a), 1.0e-3)
        out.append(MU0 * float(r) * (math.log(8.0 * float(r) / a_safe) - 2.0 + 0.5 * float(li)))
    return out


def split_loop_voltage_terms(times: list[float], ip_profile_ma: list[float], lp_profile_h: list[float], rp_profile_ohm: list[float]) -> dict[str, list[float]]:
    ip_a = [v * 1.0e6 for v in ip_profile_ma]
    d_ip_dt = differentiate(times, ip_a)
    d_lp_dt = differentiate(times, lp_profile_h)
    inductive = [lp * dip + ip * dlp for lp, dip, ip, dlp in zip(lp_profile_h, d_ip_dt, ip_a, d_lp_dt)]
    resistive = [rp * ip for rp, ip in zip(rp_profile_ohm, ip_a)]
    required = [max(0.0, ind + res) for ind, res in zip(inductive, resistive)]
    return {"required": required, "inductive": inductive, "resistive": resistive}


def compute_loop_voltage_required(times: list[float], ip_profile_ma: list[float], lp_profile_h: list[float], rp_profile_ohm: list[float]) -> list[float]:
    return split_loop_voltage_terms(times, ip_profile_ma, lp_profile_h, rp_profile_ohm)["required"]


def generate_cs_waveforms_from_mutual_inductance(times: list[float], initial_currents_ka: dict[str, float], loop_voltage_required: list[float], mutual_inductance: dict[str, Any] | None, share: dict[str, Any] | None) -> dict[str, Any]:
    share = {name: float((share or DEFAULT_CS_SHARE).get(name, DEFAULT_CS_SHARE[name])) for name in CS_COILS}
    total_share = sum(share.values()) or 1.0
    share = {name: value / total_share for name, value in share.items()}
    mutual = {name: float((mutual_inductance or DEFAULT_CS_MUTUAL_INDUCTANCE_H).get(name, DEFAULT_CS_MUTUAL_INDUCTANCE_H[name])) for name in CS_COILS}
    m_eff = sum(mutual[name] * share[name] for name in CS_COILS)
    m_eff = m_eff if abs(m_eff) > 1.0e-12 else 1.0e-12

    currents = {name: [float(initial_currents_ka[name])] for name in CS_COILS}
    slew = {name: [0.0] for name in CS_COILS}
    for i in range(1, len(times)):
        dt = times[i] - times[i - 1]
        v_avg = 0.5 * (loop_voltage_required[i] + loop_voltage_required[i - 1])
        for name in CS_COILS:
            di_dt_a_s = -share[name] * v_avg / m_eff
            di_ka = di_dt_a_s * dt / 1000.0
            currents[name].append(currents[name][-1] + di_ka)
            slew[name].append(di_ka / dt)
    loop_voltage_cs = []
    for i in range(len(times)):
        value = -sum(mutual[name] * (slew[name][i] * 1000.0) for name in CS_COILS)
        loop_voltage_cs.append(value)
    residual = [loop_voltage_cs[i] - loop_voltage_required[i] for i in range(len(times))]
    return {"waveforms": currents, "loop_voltage_cs_V": loop_voltage_cs, "cs_slew_rates_kA_per_s": slew, "cs_maintenance_residual_V": residual, "effective_mutual_inductance_H": m_eff}


def compute_poloidal_beta_profile(times: list[float], physics: dict[str, Any]) -> list[float]:
    cfg = physics.get("poloidal_beta", {})
    base = float(cfg.get("flat", 0.35))
    amp = float(cfg.get("ripple_amplitude", 0.02))
    duration = max(times[-1] - times[0], 1e-9) if times else 1.0
    return [base + amp * math.sin(2.0 * math.pi * (t - times[0]) / duration + math.pi / 3.0) for t in times]


def compute_required_vertical_field(ip_profile_ma: list[float], shape_profile: dict[str, list[float]], li_profile: list[float], beta_p_profile: list[float]) -> list[float]:
    out: list[float] = []
    for ip_ma, r, a, li, beta in zip(ip_profile_ma, shape_profile["major_radius_m"], shape_profile["minor_radius_m"], li_profile, beta_p_profile):
        ip_a = ip_ma * 1.0e6
        term = math.log(8.0 * r / max(a, 1.0e-3)) + beta + 0.5 * li - 1.5
        out.append(MU0 * ip_a * term / (4.0 * math.pi * r))
    return out


def solve_regularized_least_squares(matrix: list[list[float]], target: list[float], previous: list[float], regularization: float, weights: list[float]) -> tuple[list[float], float]:
    # 4 个未知量，使用正规方程 + 高斯消元，避免引入 numpy 依赖。
    n = len(previous)
    ata = [[0.0 for _ in range(n)] for _ in range(n)]
    atb = [0.0 for _ in range(n)]
    for row, y, w in zip(matrix, target, weights):
        for i in range(n):
            atb[i] += w * w * row[i] * y
            for j in range(n):
                ata[i][j] += w * w * row[i] * row[j]
    for i in range(n):
        ata[i][i] += regularization
        atb[i] += regularization * previous[i]
    solution = _solve_linear_system(ata, atb)
    residual = math.sqrt(sum((sum(row[i] * solution[i] for i in range(n)) - y) ** 2 for row, y in zip(matrix, target)))
    return solution, residual


def _solve_linear_system(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    mat = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(mat[r][col]))
        mat[col], mat[pivot] = mat[pivot], mat[col]
        if abs(mat[col][col]) < 1.0e-12:
            mat[col][col] = 1.0e-12
        div = mat[col][col]
        mat[col] = [v / div for v in mat[col]]
        for row in range(n):
            if row == col:
                continue
            factor = mat[row][col]
            mat[row] = [v - factor * mat[col][i] for i, v in enumerate(mat[row])]
    return [mat[i][-1] for i in range(n)]


def generate_pf_waveforms_from_response_matrix(times: list[float], initial_currents_ka: dict[str, float], target_shape: dict[str, Any], shape_profile: dict[str, list[float]], bv_required: list[float], physics: dict[str, Any]) -> dict[str, Any]:
    matrix_cfg = physics.get("pf_response_matrix", DEFAULT_PF_RESPONSE_MATRIX)
    matrix = [[float(v) for v in row] for row in matrix_cfg.get("values", DEFAULT_PF_RESPONSE_MATRIX["values"])]
    rows = matrix_cfg.get("rows", DEFAULT_PF_RESPONSE_MATRIX["rows"])
    solver = physics.get("solver", {})
    reg = float(solver.get("pf_regularization", 0.01))
    weight_map = solver.get("weights", {})
    weights = [float(weight_map.get(name, 1.0)) for name in rows]
    gains = physics.get("pf_shape_gains", {"kappa": 0.02, "triangularity": 0.015, "vertical_position": 0.02, "x_point": 0.02})
    target_kappa = float(target_shape.get("elongation", 1.75))
    target_delta = float(target_shape.get("triangularity", 0.35))
    target_z = float(target_shape.get("vertical_position_m", 0.0))
    initial = [float(initial_currents_ka[name]) for name in PF_COILS]
    target_solution = initial[:]
    target_residual = 0.0
    out = {name: [] for name in PF_COILS}
    residuals: list[float] = []
    for i in range(len(times)):
        y = []
        for row_name in rows:
            if row_name == "Bv":
                y.append(bv_required[i])
            elif row_name == "Br":
                y.append(0.0)
            elif row_name == "G_kappa":
                y.append(float(gains.get("kappa", 0.02)) * (shape_profile["elongation"][i] - target_kappa))
            elif row_name == "G_delta":
                y.append(float(gains.get("triangularity", 0.015)) * (shape_profile["triangularity"][i] - target_delta))
            elif row_name == "G_Z":
                y.append(float(gains.get("vertical_position", 0.02)) * (shape_profile["vertical_position_m"][i] - target_z))
            else:
                y.append(0.0)
        if i == len(times) - 1:
            target_solution, target_residual = solve_regularized_least_squares(matrix, y, initial, reg, weights)
        fraction = smooth_fraction(i / max(len(times) - 1, 1))
        sol = [initial[j] + fraction * (target_solution[j] - initial[j]) for j in range(len(PF_COILS))]
        residual = target_residual if i == len(times) - 1 else target_residual * fraction
        residuals.append(residual)
        for name, value in zip(PF_COILS, sol):
            out[name].append(value)
    return {"waveforms": out, "pf_balance_residual": residuals}


def generate_x_point_profile(times: list[float], target_shape: dict[str, Any], tolerance_m: float) -> dict[str, list[float]]:
    lower = target_shape.get("x_point", {}).get("lower_x_point", {})
    r_target = float(lower.get("R_m", 1.55))
    z_target = float(lower.get("Z_m", -1.05))
    duration = max(times[-1] - times[0], 1e-9) if times else 1.0
    amp = 0.15 * tolerance_m
    return {
        "lower_x_point_R_m": [r_target + amp * math.sin(2.0 * math.pi * (t - times[0]) / duration) for t in times],
        "lower_x_point_Z_m": [z_target + amp * math.cos(2.0 * math.pi * (t - times[0]) / duration) for t in times],
    }


def generate_strike_point_profile(times: list[float], divertor_targets: dict[str, Any]) -> dict[str, list[float]]:
    outer = divertor_targets.get("strike_point_lower_outer", {})
    inner = divertor_targets.get("strike_point_lower_inner", {})
    amp = float(divertor_targets.get("sweep_amplitude_m", 0.0)) if divertor_targets.get("allow_sweep", False) else 0.0
    period = float(divertor_targets.get("sweep_period_s", 1.0))
    outer_r0, outer_z0 = float(outer.get("R_m", 1.72)), float(outer.get("Z_m", -1.18))
    inner_r0, inner_z0 = float(inner.get("R_m", 1.22)), float(inner.get("Z_m", -1.10))
    return {
        "lower_outer_R_m": [outer_r0 + sinusoid(t - times[0], amp, period) for t in times],
        "lower_outer_Z_m": [outer_z0 for _ in times],
        "lower_inner_R_m": [inner_r0 + sinusoid(t - times[0], amp, period, 180.0) for t in times],
        "lower_inner_Z_m": [inner_z0 for _ in times],
    }


def generate_div_waveforms_from_response_matrix(times: list[float], initial_currents_ka: dict[str, float], strike_point_profile: dict[str, list[float]], divertor_targets: dict[str, Any], divertor_control: dict[str, Any], physics: dict[str, Any]) -> dict[str, Any]:
    # 首版只求解外打击点 R/Z 的小偏移，体现 Div 的物理职责，避免复杂化。
    matrix_cfg = physics.get("div_response_matrix", DEFAULT_DIV_RESPONSE_MATRIX)
    matrix = [[float(v) for v in row] for row in matrix_cfg.get("values", DEFAULT_DIV_RESPONSE_MATRIX["values"])]
    reg = float(physics.get("solver", {}).get("div_regularization", 0.01))
    base = divertor_control.get("base_currents_kA", {})
    prev = [float(base.get("Div1", initial_currents_ka.get("Div1", 0.0))), float(base.get("Div2", initial_currents_ka.get("Div2", 0.0)))]
    outer = divertor_targets.get("strike_point_lower_outer", {})
    r0, z0 = float(outer.get("R_m", 1.72)), float(outer.get("Z_m", -1.18))
    out = {"Div1": [], "Div2": []}
    residuals: list[float] = []
    for i in range(len(times)):
        y = [strike_point_profile["lower_outer_R_m"][i] - r0, strike_point_profile["lower_outer_Z_m"][i] - z0]
        delta, residual = solve_regularized_least_squares(matrix, y, [0.0, 0.0], reg, [1.0, 1.0])
        sol = [prev[0] + delta[0], prev[1] + delta[1]]
        residuals.append(residual)
        out["Div1"].append(sol[0])
        out["Div2"].append(sol[1])
    return {"waveforms": out, "strike_point_residual": residuals}


def estimate_q95_profile_from_geometry(ip_profile_ma: list[float], shape_profile: dict[str, list[float]], b0_t: float, target_q95: float) -> list[float]:
    raw: list[float] = []
    for ip, r, a, kappa, delta in zip(ip_profile_ma, shape_profile["major_radius_m"], shape_profile["minor_radius_m"], shape_profile["elongation"], shape_profile["triangularity"]):
        f_shape = 0.5 * (1.0 + kappa * kappa) * (1.0 + 0.5 * delta * delta)
        raw.append((a * a * b0_t / max(r * ip, 1.0e-9)) * f_shape)
    scale = target_q95 / raw[-1] if raw and abs(raw[-1]) > 1.0e-12 else 1.0
    return [v * scale for v in raw]


def estimate_vertical_stability_margin(shape_profile: dict[str, list[float]], x_point_profile: dict[str, list[float]] | None = None, target_shape: dict[str, Any] | None = None) -> list[float]:
    lower = (target_shape or {}).get("x_point", {}).get("lower_x_point", {})
    r_tar = float(lower.get("R_m", 1.55))
    margins: list[float] = []
    for i, (kappa, z) in enumerate(zip(shape_profile["elongation"], shape_profile["vertical_position_m"])):
        x_penalty = 0.0
        if x_point_profile:
            x_penalty = 0.08 * abs(float(x_point_profile["lower_x_point_R_m"][i]) - r_tar)
        margin = 0.42 - 0.08 * max(0.0, float(kappa) - 1.0) - 0.10 * abs(float(z)) - x_penalty
        margins.append(max(0.03, margin))
    return margins


def estimate_flux_consumption(times: list[float], loop_voltage: list[float], already_consumed_wb: float) -> list[float]:
    return integrate_trapezoid(times, loop_voltage, already_consumed_wb)


def estimate_flux_margin_fraction(flux_consumed: list[float], total_available_wb: float) -> list[float]:
    if total_available_wb <= 0:
        return [0.0 for _ in flux_consumed]
    return [max(0.0, (total_available_wb - value) / total_available_wb) for value in flux_consumed]


def generate_vs_bias(times: list[float], baseline_current_ka: float) -> list[float]:
    return [baseline_current_ka for _ in times]


def build_waveform_rows(times: list[float], ip_profile: list[float], loop_voltage: list[float], flux_consumed: list[float], flux_margin_fraction: list[float], shape_profile: dict[str, list[float]], x_point_profile: dict[str, list[float]], strike_point_profile: dict[str, list[float]], q95_profile: list[float], internal_inductance: list[float], vertical_margin: list[float], cs_waveforms: dict[str, list[float]], pf_waveforms: dict[str, list[float]], div_waveforms: dict[str, list[float]], vs_bias: list[float], total_available_flux_wb: float, diagnostics: dict[str, list[float]] | None = None) -> list[dict[str, Any]]:
    diagnostics = diagnostics or {}
    rows: list[dict[str, Any]] = []
    total_available = max(float(total_available_flux_wb), 1e-9)
    for i, time_s in enumerate(times):
        rows.append({
            "time_s": time_s,
            "stage": "flattop",
            "Ip_MA": ip_profile[i],
            "loop_voltage_V": loop_voltage[i],
            "loop_voltage_required_V": diagnostics.get("loop_voltage_required_V", loop_voltage)[i],
            "loop_voltage_cs_V": diagnostics.get("loop_voltage_cs_V", loop_voltage)[i],
            "loop_voltage_inductive_V": diagnostics.get("loop_voltage_inductive_V", [0.0] * len(times))[i],
            "loop_voltage_resistive_V": diagnostics.get("loop_voltage_resistive_V", [0.0] * len(times))[i],
            "plasma_inductance_H": diagnostics.get("plasma_inductance_H", [0.0] * len(times))[i],
            "plasma_resistance_ohm": diagnostics.get("plasma_resistance_ohm", [0.0] * len(times))[i],
            "electron_temperature_eV": diagnostics.get("electron_temperature_eV", [0.0] * len(times))[i],
            "flux_consumed_Wb": flux_consumed[i],
            "stage_3_flux_used_Wb": diagnostics.get("stage_3_flux_used_Wb", [0.0] * len(times))[i],
            "flux_remaining_Wb": max(0.0, total_available - flux_consumed[i]),
            "flux_margin_fraction": flux_margin_fraction[i],
            "q95": q95_profile[i],
            "internal_inductance": internal_inductance[i],
            "poloidal_beta": diagnostics.get("poloidal_beta", [0.0] * len(times))[i],
            "Bv_required_T": diagnostics.get("Bv_required_T", [0.0] * len(times))[i],
            "pf_balance_residual": diagnostics.get("pf_balance_residual", [0.0] * len(times))[i],
            "x_point_residual": diagnostics.get("x_point_residual", [0.0] * len(times))[i],
            "strike_point_residual": diagnostics.get("strike_point_residual", [0.0] * len(times))[i],
            "vertical_stability_margin": vertical_margin[i],
            "vs_reserved_fraction": diagnostics.get("vs_reserved_fraction", [0.0] * len(times))[i],
            "major_radius_m": shape_profile["major_radius_m"][i],
            "minor_radius_m": shape_profile["minor_radius_m"][i],
            "elongation": shape_profile["elongation"][i],
            "triangularity": shape_profile["triangularity"][i],
            "vertical_position_m": shape_profile["vertical_position_m"][i],
            "lower_x_point_R_m": x_point_profile["lower_x_point_R_m"][i],
            "lower_x_point_Z_m": x_point_profile["lower_x_point_Z_m"][i],
            "strike_point_lower_outer_R_m": strike_point_profile["lower_outer_R_m"][i],
            "strike_point_lower_outer_Z_m": strike_point_profile["lower_outer_Z_m"][i],
            "strike_point_lower_inner_R_m": strike_point_profile["lower_inner_R_m"][i],
            "strike_point_lower_inner_Z_m": strike_point_profile["lower_inner_Z_m"][i],
            "I_CS1_kA": cs_waveforms["CS1"][i], "I_CS2_kA": cs_waveforms["CS2"][i], "I_CS3_kA": cs_waveforms["CS3"][i],
            "I_PF1_kA": pf_waveforms["PF1"][i], "I_PF2_kA": pf_waveforms["PF2"][i], "I_PF3_kA": pf_waveforms["PF3"][i], "I_PF4_kA": pf_waveforms["PF4"][i],
            "I_Div1_kA": div_waveforms["Div1"][i], "I_Div2_kA": div_waveforms["Div2"][i], "I_VS_bias_kA": vs_bias[i],
            "note": "flattop_start_from_rampup" if i == 0 else ("flattop_end_final_state" if i == len(times) - 1 else "flattop_minimum_physics_hold"),
        })
    return rows


def extract_end_state(rows: list[dict[str, Any]]) -> dict[str, float]:
    last = rows[-1]
    return {"CS1": float(last["I_CS1_kA"]), "CS2": float(last["I_CS2_kA"]), "CS3": float(last["I_CS3_kA"]), "PF1": float(last["I_PF1_kA"]), "PF2": float(last["I_PF2_kA"]), "PF3": float(last["I_PF3_kA"]), "PF4": float(last["I_PF4_kA"]), "Div1": float(last["I_Div1_kA"]), "Div2": float(last["I_Div2_kA"]), "VS": float(last["I_VS_bias_kA"])}


def extract_shape_state(rows: list[dict[str, Any]]) -> dict[str, Any]:
    last = rows[-1]
    return {"major_radius_m": float(last["major_radius_m"]), "minor_radius_m": float(last["minor_radius_m"]), "elongation": float(last["elongation"]), "triangularity": float(last["triangularity"]), "vertical_position_m": float(last["vertical_position_m"]), "x_point": {"enabled": True, "lower_x_point": {"R_m": float(last["lower_x_point_R_m"]), "Z_m": float(last["lower_x_point_Z_m"])}}}


def extract_divertor_state(rows: list[dict[str, Any]]) -> dict[str, Any]:
    last = rows[-1]
    return {"strike_point_lower_outer": {"R_m": float(last["strike_point_lower_outer_R_m"]), "Z_m": float(last["strike_point_lower_outer_Z_m"])}, "strike_point_lower_inner": {"R_m": float(last["strike_point_lower_inner_R_m"]), "Z_m": float(last["strike_point_lower_inner_Z_m"])}, "coil_currents_kA": {"Div1": float(last["I_Div1_kA"]), "Div2": float(last["I_Div2_kA"])}}


def build_vs_reserved_range(vs_limit: dict[str, Any], reserve_fraction: float, baseline_current_ka: float) -> dict[str, float]:
    low = float(vs_limit["min_kA"])
    high = float(vs_limit["max_kA"])
    reserve_fraction = max(0.0, min(1.0, reserve_fraction))
    return {"baseline_kA": baseline_current_ka, "reserved_min_kA": baseline_current_ka + reserve_fraction * (low - baseline_current_ka), "reserved_max_kA": baseline_current_ka + reserve_fraction * (high - baseline_current_ka), "reserved_fraction": reserve_fraction}

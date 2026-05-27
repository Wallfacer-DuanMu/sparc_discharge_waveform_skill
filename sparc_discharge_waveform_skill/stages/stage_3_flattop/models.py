"""Flat-top 阶段简化模型。

本文件只负责可复用计算，不负责读取文件和最终验证。
学生作业口径保持简洁：
- Ip 在目标平台附近保持，仅允许小偏差；
- CS 以低环电压慢速消耗伏秒，重点保留剩余磁通裕度；
- PF1/PF2 维持边界、拉长比和三角形变；
- PF3/PF4 维持主半径、整体平衡和 X 点；
- Div 做平顶打击点固定设定或小幅扫描；
- VS 只输出基准值和预留控制范围，不做高频反馈。
"""

from __future__ import annotations

import math
from typing import Any


CS_COILS = ("CS1", "CS2", "CS3")
PF_COILS = ("PF1", "PF2", "PF3", "PF4")
DIV_COILS = ("Div1", "Div2")
AUX_COILS = DIV_COILS + ("VS",)
ALL_COILS = CS_COILS + PF_COILS + AUX_COILS
SHAPE_FIELDS = ("major_radius_m", "minor_radius_m", "elongation", "triangularity", "vertical_position_m")


def make_time_axis(t_start_s: float, t_end_s: float, dt_s: float) -> list[float]:
    """生成包含起点和终点的 Flat-top 时间轴。"""

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
    if not times or abs(times[-1] - t_end_s) > eps:
        times.append(round(t_end_s, 10))
    return times


def smooth_fraction(x: float) -> float:
    """三次 smoothstep，用于平滑端点。"""

    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def interpolate(start: float, end: float, fraction: float) -> float:
    """线性插值。"""

    return start + (end - start) * fraction


def sinusoid(time_s: float, amplitude: float, period_s: float, phase_deg: float = 0.0) -> float:
    """生成正弦微调量。"""

    if period_s <= 0:
        return 0.0
    phase_rad = math.radians(phase_deg)
    return amplitude * math.sin(2.0 * math.pi * time_s / period_s + phase_rad)


def generate_ip_hold_profile(
    times: list[float],
    start_ip_ma: float,
    target_ip_ma: float,
    max_deviation_ma: float,
    smoothing_time_s: float,
) -> list[float]:
    """生成接近平顶恒定保持的 Ip(t)。

    若 Stage 2 末态与目标存在小偏差，则在一个短平滑窗口内收敛到平台值，
    之后只保留极小幅度的慢变化，表达维持而非再升流。
    """

    if not times:
        return []

    t0 = times[0]
    duration = max(times[-1] - t0, 1e-9)
    smoothing_duration = max(smoothing_time_s, 1e-9)
    values: list[float] = []
    for time_s in times:
        settle_fraction = smooth_fraction(min((time_s - t0) / smoothing_duration, 1.0))
        baseline = interpolate(start_ip_ma, target_ip_ma, settle_fraction)
        ripple_fraction = (time_s - t0) / duration
        ripple = 0.20 * max_deviation_ma * math.sin(2.0 * math.pi * ripple_fraction)
        value = baseline + ripple
        values.append(max(target_ip_ma - max_deviation_ma, min(target_ip_ma + max_deviation_ma, value)))
    return values


def generate_loop_voltage_profile(times: list[float], profile: dict[str, Any]) -> list[float]:
    """生成从入口电压平滑过渡到低维持电压的平台曲线。"""

    initial = float(profile["initial_voltage_V"])
    target = float(profile["target_voltage_V"])
    v_min = float(profile.get("min_voltage_V", min(initial, target)))
    v_max = float(profile.get("max_voltage_V", max(initial, target)))

    if not times:
        return []

    t0 = times[0]
    duration = max(times[-1] - t0, 1e-9)
    values: list[float] = []
    for time_s in times:
        fraction = smooth_fraction((time_s - t0) / duration)
        value = interpolate(initial, target, fraction)
        values.append(max(v_min, min(v_max, value)))
    return values


def estimate_flux_consumption(times: list[float], loop_voltage: list[float], already_consumed_wb: float) -> list[float]:
    """用环电压时间积分估算累计磁通消耗。"""

    flux = [float(already_consumed_wb)]
    for index in range(1, len(times)):
        dt = times[index] - times[index - 1]
        average_voltage = 0.5 * (loop_voltage[index] + loop_voltage[index - 1])
        flux.append(flux[-1] + average_voltage * dt)
    return flux


def generate_shape_hold_profile(
    times: list[float],
    start_shape: dict[str, Any],
    target_shape: dict[str, Any],
    shape_tolerance_m: float,
) -> dict[str, list[float]]:
    """生成平顶位形保持曲线。"""

    if not times:
        return {field: [] for field in SHAPE_FIELDS}

    t0 = times[0]
    duration = max(times[-1] - t0, 1e-9)
    result: dict[str, list[float]] = {field: [] for field in SHAPE_FIELDS}
    for field in SHAPE_FIELDS:
        start = float(start_shape.get(field, target_shape.get(field, 0.0)))
        end = float(target_shape.get(field, start))
        amplitude = 0.30 * shape_tolerance_m if field in {"major_radius_m", "minor_radius_m", "vertical_position_m"} else 0.0
        for time_s in times:
            settle = smooth_fraction((time_s - t0) / min(duration, 0.5 if duration > 0.5 else duration)) if duration > 0 else 1.0
            baseline = interpolate(start, end, settle)
            ripple = amplitude * math.sin(2.0 * math.pi * (time_s - t0) / duration) if duration > 0 else 0.0
            result[field].append(baseline + ripple)
    return result


def generate_x_point_profile(times: list[float], target_shape: dict[str, Any], tolerance_m: float) -> dict[str, list[float]]:
    """生成简化 X 点位置保持曲线。"""

    x_point = target_shape.get("x_point", {})
    lower = x_point.get("lower_x_point", {})
    r_target = float(lower.get("R_m", 1.55))
    z_target = float(lower.get("Z_m", -1.05))
    amplitude = 0.25 * tolerance_m

    r_values: list[float] = []
    z_values: list[float] = []
    duration = max(times[-1] - times[0], 1e-9) if times else 1.0
    for time_s in times:
        phase = 2.0 * math.pi * (time_s - times[0]) / duration if times else 0.0
        r_values.append(r_target + amplitude * math.sin(phase))
        z_values.append(z_target + amplitude * math.cos(phase))
    return {"lower_x_point_R_m": r_values, "lower_x_point_Z_m": z_values}


def generate_strike_point_profile(times: list[float], divertor_targets: dict[str, Any]) -> dict[str, list[float]]:
    """生成简化打击点位置曲线。"""

    lower_outer = divertor_targets.get("strike_point_lower_outer", {})
    lower_inner = divertor_targets.get("strike_point_lower_inner", {})
    allow_sweep = bool(divertor_targets.get("allow_sweep", False))
    amplitude = float(divertor_targets.get("sweep_amplitude_m", 0.0)) if allow_sweep else 0.0
    period = float(divertor_targets.get("sweep_period_s", 1.0))

    outer_r0 = float(lower_outer.get("R_m", 1.72))
    outer_z0 = float(lower_outer.get("Z_m", -1.18))
    inner_r0 = float(lower_inner.get("R_m", 1.22))
    inner_z0 = float(lower_inner.get("Z_m", -1.10))

    outer_r: list[float] = []
    outer_z: list[float] = []
    inner_r: list[float] = []
    inner_z: list[float] = []
    for time_s in times:
        sweep = sinusoid(time_s - times[0], amplitude, period, phase_deg=0.0)
        anti_sweep = sinusoid(time_s - times[0], amplitude, period, phase_deg=180.0)
        outer_r.append(outer_r0 + sweep)
        outer_z.append(outer_z0)
        inner_r.append(inner_r0 + anti_sweep)
        inner_z.append(inner_z0)
    return {
        "lower_outer_R_m": outer_r,
        "lower_outer_Z_m": outer_z,
        "lower_inner_R_m": inner_r,
        "lower_inner_Z_m": inner_z,
    }


def estimate_q95_profile(times: list[float], start_q95: float, target_q95: float) -> list[float]:
    """估算 Flat-top 中 q95 的保持趋势。"""

    if not times:
        return []
    duration = max(times[-1] - times[0], 1e-9)
    values: list[float] = []
    for time_s in times:
        fraction = smooth_fraction((time_s - times[0]) / duration)
        baseline = interpolate(start_q95, target_q95, fraction)
        ripple = 0.02 * math.sin(2.0 * math.pi * (time_s - times[0]) / duration)
        values.append(baseline + ripple)
    return values


def estimate_internal_inductance_profile(times: list[float]) -> list[float]:
    """给出内电感的平顶缓慢保持估计。"""

    if not times:
        return []
    duration = max(times[-1] - times[0], 1e-9)
    return [0.78 + 0.01 * math.sin(2.0 * math.pi * (time_s - times[0]) / duration) for time_s in times]


def estimate_vertical_stability_margin(shape_profile: dict[str, list[float]]) -> list[float]:
    """用拉长比与竖直位移估算垂直稳定裕度。"""

    margins: list[float] = []
    for elongation, vertical_position in zip(shape_profile["elongation"], shape_profile["vertical_position_m"]):
        margin = 0.32 - 0.08 * max(0.0, float(elongation) - 1.0) - 0.10 * abs(float(vertical_position))
        margins.append(max(0.05, margin))
    return margins


def generate_cs_waveforms(
    times: list[float],
    initial_currents_ka: dict[str, float],
    loop_voltage: list[float],
    share: dict[str, float] | None = None,
) -> dict[str, list[float]]:
    """根据低环电压维持需求生成 CS 慢速摆动。"""

    share = share or {"CS1": 0.30, "CS2": 0.40, "CS3": 0.30}
    total_share = sum(share.get(name, 0.0) for name in CS_COILS)
    if total_share <= 0:
        raise ValueError("CS share must be positive")

    flux_from_stage_start = estimate_flux_consumption(times, loop_voltage, 0.0)
    total_swing_ka = [0.08 * value for value in flux_from_stage_start]
    result: dict[str, list[float]] = {}
    for name in CS_COILS:
        i0 = float(initial_currents_ka[name])
        normalized_share = share.get(name, 0.0) / total_share
        result[name] = [i0 - swing * normalized_share for swing in total_swing_ka]
    return result


def generate_pf_waveforms(
    times: list[float],
    initial_currents_ka: dict[str, float],
    target_shape: dict[str, Any],
    shape_profile: dict[str, list[float]],
    correction_gain: dict[str, Any],
    allowed_relative_adjustment: float,
) -> dict[str, list[float]]:
    """生成 PF1-4 平顶形状保持与小幅修正波形。"""

    if not times:
        return {name: [] for name in PF_COILS}

    target_elongation = float(target_shape.get("elongation", 1.75))
    target_triangularity = float(target_shape.get("triangularity", 0.35))
    target_radius = float(target_shape.get("major_radius_m", 1.85))
    target_vertical = float(target_shape.get("vertical_position_m", 0.0))
    duration = max(times[-1] - times[0], 1e-9)

    result = {name: [] for name in PF_COILS}
    for index, time_s in enumerate(times):
        elongation_error = shape_profile["elongation"][index] - target_elongation
        triangularity_error = shape_profile["triangularity"][index] - target_triangularity
        radius_error = shape_profile["major_radius_m"][index] - target_radius
        vertical_error = shape_profile["vertical_position_m"][index] - target_vertical
        micro_adjustment = 0.10 * math.sin(2.0 * math.pi * (time_s - times[0]) / duration)

        raw_targets = {
            "PF1": float(initial_currents_ka["PF1"]) - float(correction_gain.get("PF1", 0.20)) * (2.5 * elongation_error + triangularity_error) + micro_adjustment,
            "PF2": float(initial_currents_ka["PF2"]) - float(correction_gain.get("PF2", 0.25)) * (3.0 * elongation_error + 2.0 * triangularity_error),
            "PF3": float(initial_currents_ka["PF3"]) - float(correction_gain.get("PF3", 0.25)) * (2.0 * radius_error + 1.5 * vertical_error) - micro_adjustment,
            "PF4": float(initial_currents_ka["PF4"]) - float(correction_gain.get("PF4", 0.30)) * (2.5 * radius_error - 1.0 * vertical_error),
        }

        for name in PF_COILS:
            base = float(initial_currents_ka[name])
            limit = abs(base) * allowed_relative_adjustment
            if limit < 0.20:
                limit = 0.20
            value = raw_targets[name]
            value = max(base - limit, min(base + limit, value))
            result[name].append(value)
    return result


def generate_div_waveforms(
    times: list[float],
    initial_currents_ka: dict[str, float],
    divertor_control: dict[str, Any],
) -> dict[str, list[float]]:
    """生成 Div 平顶固定工作点或小幅扫描。"""

    base = divertor_control.get("base_currents_kA", {})
    sweep = divertor_control.get("sweep_currents_kA", {})

    div1_base = float(base.get("Div1", initial_currents_ka.get("Div1", 0.0)))
    div2_base = float(base.get("Div2", initial_currents_ka.get("Div2", 0.0)))
    div1_amp = float(sweep.get("Div1_amplitude", 0.0))
    div2_amp = float(sweep.get("Div2_amplitude", 0.0))
    period = float(sweep.get("period_s", 1.0))
    phase_deg = float(sweep.get("phase_difference_deg", 180.0))

    result = {"Div1": [], "Div2": []}
    for time_s in times:
        local_time = time_s - times[0]
        result["Div1"].append(div1_base + sinusoid(local_time, div1_amp, period, phase_deg=0.0))
        result["Div2"].append(div2_base + sinusoid(local_time, div2_amp, period, phase_deg=phase_deg))
    return result


def generate_vs_bias(times: list[float], baseline_current_ka: float) -> list[float]:
    """VS 只保持离线基准值。"""

    return [baseline_current_ka for _ in times]


def estimate_flux_margin_fraction(flux_consumed: list[float], total_available_wb: float) -> list[float]:
    """估算各时刻剩余伏秒占总预算的比例。"""

    if total_available_wb <= 0:
        return [0.0 for _ in flux_consumed]
    return [max(0.0, (total_available_wb - value) / total_available_wb) for value in flux_consumed]


def build_waveform_rows(
    times: list[float],
    ip_profile: list[float],
    loop_voltage: list[float],
    flux_consumed: list[float],
    flux_margin_fraction: list[float],
    shape_profile: dict[str, list[float]],
    x_point_profile: dict[str, list[float]],
    strike_point_profile: dict[str, list[float]],
    q95_profile: list[float],
    internal_inductance: list[float],
    vertical_margin: list[float],
    cs_waveforms: dict[str, list[float]],
    pf_waveforms: dict[str, list[float]],
    div_waveforms: dict[str, list[float]],
    vs_bias: list[float],
    total_available_flux_wb: float,
) -> list[dict[str, Any]]:
    """合并所有 Flat-top 波形为逐时刻表格。"""

    rows: list[dict[str, Any]] = []
    last_index = len(times) - 1
    total_available = max(float(total_available_flux_wb), 1e-9)
    for index, time_s in enumerate(times):
        flux_remaining = max(0.0, total_available - flux_consumed[index])
        if index == 0:
            note = "flattop_start_from_rampup"
        elif index == last_index:
            note = "flattop_end_final_state"
        else:
            note = "flattop_hold_and_trim"

        rows.append(
            {
                "time_s": time_s,
                "stage": "flattop",
                "Ip_MA": ip_profile[index],
                "loop_voltage_V": loop_voltage[index],
                "flux_consumed_Wb": flux_consumed[index],
                "flux_remaining_Wb": flux_remaining,
                "flux_margin_fraction": flux_margin_fraction[index],
                "q95": q95_profile[index],
                "internal_inductance": internal_inductance[index],
                "vertical_stability_margin": vertical_margin[index],
                "major_radius_m": shape_profile["major_radius_m"][index],
                "minor_radius_m": shape_profile["minor_radius_m"][index],
                "elongation": shape_profile["elongation"][index],
                "triangularity": shape_profile["triangularity"][index],
                "vertical_position_m": shape_profile["vertical_position_m"][index],
                "lower_x_point_R_m": x_point_profile["lower_x_point_R_m"][index],
                "lower_x_point_Z_m": x_point_profile["lower_x_point_Z_m"][index],
                "strike_point_lower_outer_R_m": strike_point_profile["lower_outer_R_m"][index],
                "strike_point_lower_outer_Z_m": strike_point_profile["lower_outer_Z_m"][index],
                "strike_point_lower_inner_R_m": strike_point_profile["lower_inner_R_m"][index],
                "strike_point_lower_inner_Z_m": strike_point_profile["lower_inner_Z_m"][index],
                "I_CS1_kA": cs_waveforms["CS1"][index],
                "I_CS2_kA": cs_waveforms["CS2"][index],
                "I_CS3_kA": cs_waveforms["CS3"][index],
                "I_PF1_kA": pf_waveforms["PF1"][index],
                "I_PF2_kA": pf_waveforms["PF2"][index],
                "I_PF3_kA": pf_waveforms["PF3"][index],
                "I_PF4_kA": pf_waveforms["PF4"][index],
                "I_Div1_kA": div_waveforms["Div1"][index],
                "I_Div2_kA": div_waveforms["Div2"][index],
                "I_VS_bias_kA": vs_bias[index],
                "note": note,
            }
        )
    return rows


def extract_end_state(rows: list[dict[str, Any]]) -> dict[str, float]:
    """提取 Flat-top 末态线圈电流。"""

    last = rows[-1]
    return {
        "CS1": float(last["I_CS1_kA"]),
        "CS2": float(last["I_CS2_kA"]),
        "CS3": float(last["I_CS3_kA"]),
        "PF1": float(last["I_PF1_kA"]),
        "PF2": float(last["I_PF2_kA"]),
        "PF3": float(last["I_PF3_kA"]),
        "PF4": float(last["I_PF4_kA"]),
        "Div1": float(last["I_Div1_kA"]),
        "Div2": float(last["I_Div2_kA"]),
        "VS": float(last["I_VS_bias_kA"]),
    }


def extract_shape_state(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """提取 Flat-top 末端位形。"""

    last = rows[-1]
    return {
        "major_radius_m": float(last["major_radius_m"]),
        "minor_radius_m": float(last["minor_radius_m"]),
        "elongation": float(last["elongation"]),
        "triangularity": float(last["triangularity"]),
        "vertical_position_m": float(last["vertical_position_m"]),
        "x_point": {
            "enabled": True,
            "lower_x_point": {
                "R_m": float(last["lower_x_point_R_m"]),
                "Z_m": float(last["lower_x_point_Z_m"]),
            },
        },
    }


def extract_divertor_state(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """提取 Flat-top 末端偏滤器设定。"""

    last = rows[-1]
    return {
        "strike_point_lower_outer": {
            "R_m": float(last["strike_point_lower_outer_R_m"]),
            "Z_m": float(last["strike_point_lower_outer_Z_m"]),
        },
        "strike_point_lower_inner": {
            "R_m": float(last["strike_point_lower_inner_R_m"]),
            "Z_m": float(last["strike_point_lower_inner_Z_m"]),
        },
        "coil_currents_kA": {
            "Div1": float(last["I_Div1_kA"]),
            "Div2": float(last["I_Div2_kA"]),
        },
    }


def build_vs_reserved_range(vs_limit: dict[str, Any], reserve_fraction: float, baseline_current_ka: float) -> dict[str, float]:
    """计算 VS 预留控制范围。"""

    low = float(vs_limit["min_kA"])
    high = float(vs_limit["max_kA"])
    reserve_fraction = max(0.0, min(1.0, reserve_fraction))
    reserve_low = baseline_current_ka + reserve_fraction * (low - baseline_current_ka)
    reserve_high = baseline_current_ka + reserve_fraction * (high - baseline_current_ka)
    return {
        "baseline_kA": baseline_current_ka,
        "reserved_min_kA": reserve_low,
        "reserved_max_kA": reserve_high,
    }

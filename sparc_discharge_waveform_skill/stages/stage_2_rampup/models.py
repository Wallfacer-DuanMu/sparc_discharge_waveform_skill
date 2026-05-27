"""Ramp-up 阶段简化模型。

本文件只负责可复用计算，不负责读取文件和最终验证。
学生作业口径保持简洁：
- Ip 从 Breakdown 末端种子电流爬升到目标平顶电流；
- CS 按 loop voltage 需求持续释放磁通；
- PF1/PF2 负责成形，PF3/PF4 负责平衡和位置；
- Div 只在 ramp-up 后段缓慢进入平顶前设定；
- VS 只输出基准值，不做快速反馈。
"""

from __future__ import annotations

from typing import Any


CS_COILS = ("CS1", "CS2", "CS3")
PF_COILS = ("PF1", "PF2", "PF3", "PF4")
DIV_COILS = ("Div1", "Div2")
AUX_COILS = DIV_COILS + ("VS",)
ALL_COILS = CS_COILS + PF_COILS + AUX_COILS
SHAPE_FIELDS = ("major_radius_m", "minor_radius_m", "elongation", "triangularity", "vertical_position_m")


def make_time_axis(t_start_s: float, t_end_s: float, dt_s: float) -> list[float]:
    """生成包含起点和终点的 Ramp-up 时间轴。"""

    if dt_s <= 0:
        raise ValueError("waveform_strategy.time_grid.step_s must be greater than 0")
    if t_end_s <= t_start_s:
        raise ValueError("targets.end_time_s must be greater than handoff_from_stage_1.time_s")

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
    """三次 smoothstep，用于平滑波形端点。"""

    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def interpolate(start: float, end: float, fraction: float) -> float:
    """线性插值。"""

    return start + (end - start) * fraction


def generate_ip_profile(times: list[float], breakpoints: list[dict[str, Any]]) -> list[float]:
    """根据分段点生成 Ip(t)。

    Ip 爬升采用分段线性，便于直接控制最大爬升率；PF 和电压曲线再用平滑函数过渡。
    """

    points = sorted(
        [(float(point["time_s"]), float(point["plasma_current_MA"])) for point in breakpoints],
        key=lambda item: item[0],
    )
    if len(points) < 2:
        raise ValueError("waveform_strategy.current_ramp.breakpoints must contain at least two points")

    result: list[float] = []
    for time_s in times:
        if time_s <= points[0][0]:
            result.append(points[0][1])
            continue
        if time_s >= points[-1][0]:
            result.append(points[-1][1])
            continue

        for (t0, ip0), (t1, ip1) in zip(points, points[1:]):
            if t0 <= time_s <= t1:
                fraction = (time_s - t0) / (t1 - t0)
                result.append(interpolate(ip0, ip1, fraction))
                break
    return result


def generate_loop_voltage_profile(times: list[float], profile: dict[str, Any]) -> list[float]:
    """生成从初始环电压平滑衰减到末端环电压的简化曲线。"""

    initial = float(profile["initial_voltage_V"])
    final = float(profile["final_voltage_V"])
    v_min = float(profile.get("min_voltage_V", min(initial, final)))
    v_max = float(profile.get("max_voltage_V", max(initial, final)))

    t0 = times[0]
    duration = times[-1] - t0
    values: list[float] = []
    for time_s in times:
        fraction = smooth_fraction((time_s - t0) / duration) if duration > 0 else 1.0
        value = interpolate(initial, final, fraction)
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


def generate_shape_profile(
    times: list[float],
    initial_shape: dict[str, Any],
    target_shape: dict[str, Any],
) -> dict[str, list[float]]:
    """生成主半径、小半径、拉长比和三角形变的平滑演化。"""

    t0 = times[0]
    duration = times[-1] - t0
    shape: dict[str, list[float]] = {}
    for field in SHAPE_FIELDS:
        start = float(initial_shape.get(field, target_shape.get(field, 0.0)))
        end = float(target_shape.get(field, start))
        shape[field] = []
        for time_s in times:
            fraction = smooth_fraction((time_s - t0) / duration) if duration > 0 else 1.0
            shape[field].append(interpolate(start, end, fraction))
    return shape


def generate_density_profile(times: list[float], density_ramp: dict[str, Any]) -> list[float]:
    """生成线平均密度的简化爬升曲线。"""

    start = float(density_ramp["start_line_average_density_1e19_m3"])
    end = float(density_ramp["end_line_average_density_1e19_m3"])
    t0 = times[0]
    duration = times[-1] - t0
    return [interpolate(start, end, smooth_fraction((t - t0) / duration)) for t in times]


def estimate_q95_profile(ip_profile: list[float], shape_profile: dict[str, list[float]], target_q95: float) -> list[float]:
    """估算 q95 趋势。

    该指标不是平衡求解，只表达 ramp-up 中 q95 从较高值逐步接近目标值。
    """

    start_q = max(float(target_q95) + 1.0, 4.0)
    end_q = float(target_q95)
    count = max(len(ip_profile) - 1, 1)
    return [interpolate(start_q, end_q, smooth_fraction(index / count)) for index, _ in enumerate(ip_profile)]


def estimate_internal_inductance_profile(times: list[float]) -> list[float]:
    """给出内电感的温和平滑演化估计。"""

    count = max(len(times) - 1, 1)
    return [interpolate(0.95, 0.75, smooth_fraction(index / count)) for index, _ in enumerate(times)]


def estimate_vertical_stability_margin(shape_profile: dict[str, list[float]]) -> list[float]:
    """用拉长比估算垂直稳定裕度，拉长越高裕度越低。"""

    margins: list[float] = []
    for elongation in shape_profile["elongation"]:
        margins.append(max(0.05, 0.35 - 0.10 * max(0.0, float(elongation) - 1.0)))
    return margins


def generate_cs_waveforms(
    times: list[float],
    initial_currents_ka: dict[str, float],
    loop_voltage: list[float],
    share: dict[str, float] | None = None,
) -> dict[str, list[float]]:
    """根据 loop voltage 生成 CS 电流 swing。

    简化比例：环电压积分每 100 Vs 对应约 10 kA 总 CS swing。
    """

    share = share or {"CS1": 0.30, "CS2": 0.40, "CS3": 0.30}
    total_share = sum(share.get(name, 0.0) for name in CS_COILS)
    if total_share <= 0:
        raise ValueError("CS share must be positive")

    flux_from_stage_start = estimate_flux_consumption(times, loop_voltage, 0.0)
    total_swing_ka = [0.10 * value for value in flux_from_stage_start]
    result: dict[str, list[float]] = {}
    for name in CS_COILS:
        i0 = float(initial_currents_ka[name])
        normalized_share = share.get(name, 0.0) / total_share
        result[name] = [i0 - swing * normalized_share for swing in total_swing_ka]
    return result


def generate_pf_waveforms(
    times: list[float],
    initial_currents_ka: dict[str, float],
    ip_profile: list[float],
    shape_profile: dict[str, list[float]],
) -> dict[str, list[float]]:
    """生成 PF1-4 简化成形和平衡波形。"""

    ip_start = max(ip_profile[0], 1e-9)
    ip_end = max(ip_profile[-1], ip_start)
    result = {name: [] for name in PF_COILS}

    for index, ip in enumerate(ip_profile):
        current_fraction = (ip - ip_start) / max(ip_end - ip_start, 1e-9)
        kappa = shape_profile["elongation"][index]
        delta = shape_profile["triangularity"][index]
        minor_radius = shape_profile["minor_radius_m"][index]
        vertical_position = shape_profile["vertical_position_m"][index]

        targets = {
            "PF1": initial_currents_ka["PF1"] + 3.0 * (kappa - 1.1) + 1.0 * delta,
            "PF2": initial_currents_ka["PF2"] + 4.0 * (kappa - 1.1) + 2.5 * delta,
            "PF3": initial_currents_ka["PF3"] + 2.0 * current_fraction + 1.5 * delta - 1.0 * vertical_position,
            "PF4": initial_currents_ka["PF4"] + 3.5 * current_fraction + 1.0 * (minor_radius - 0.35),
        }
        for name in PF_COILS:
            result[name].append(float(targets[name]))
    return result


def generate_div_waveforms(times: list[float], initial_currents_ka: dict[str, float]) -> dict[str, list[float]]:
    """Div 在 ramp-up 后 30% 时间内缓慢进入小偏置。"""

    t0 = times[0]
    duration = times[-1] - t0
    result: dict[str, list[float]] = {"Div1": [], "Div2": []}
    for time_s in times:
        raw_fraction = (time_s - (t0 + 0.70 * duration)) / max(0.30 * duration, 1e-9)
        fraction = smooth_fraction(raw_fraction)
        result["Div1"].append(interpolate(float(initial_currents_ka.get("Div1", 0.0)), 1.5, fraction))
        result["Div2"].append(interpolate(float(initial_currents_ka.get("Div2", 0.0)), -1.5, fraction))
    return result


def generate_vs_bias(times: list[float], initial_currents_ka: dict[str, float]) -> list[float]:
    """VS 只保持基准偏置。"""

    return [float(initial_currents_ka.get("VS", 0.0)) for _ in times]


def build_waveform_rows(
    times: list[float],
    ip_profile: list[float],
    loop_voltage: list[float],
    flux_consumed: list[float],
    shape_profile: dict[str, list[float]],
    density_profile: list[float],
    q95_profile: list[float],
    internal_inductance: list[float],
    vertical_margin: list[float],
    cs_waveforms: dict[str, list[float]],
    pf_waveforms: dict[str, list[float]],
    div_waveforms: dict[str, list[float]],
    vs_bias: list[float],
) -> list[dict[str, Any]]:
    """合并所有 Ramp-up 波形为逐时刻表格。"""

    rows: list[dict[str, Any]] = []
    last_index = len(times) - 1
    for index, time_s in enumerate(times):
        if index == 0:
            note = "rampup_start_from_breakdown"
        elif index == last_index:
            note = "rampup_end_to_flattop"
        else:
            note = "rampup_current_and_shape_evolution"

        rows.append(
            {
                "time_s": time_s,
                "stage": "rampup",
                "Ip_MA": ip_profile[index],
                "loop_voltage_V": loop_voltage[index],
                "flux_consumed_Wb": flux_consumed[index],
                "q95": q95_profile[index],
                "internal_inductance": internal_inductance[index],
                "vertical_stability_margin": vertical_margin[index],
                "line_average_density_1e19_m3": density_profile[index],
                "major_radius_m": shape_profile["major_radius_m"][index],
                "minor_radius_m": shape_profile["minor_radius_m"][index],
                "elongation": shape_profile["elongation"][index],
                "triangularity": shape_profile["triangularity"][index],
                "vertical_position_m": shape_profile["vertical_position_m"][index],
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
    """提取 Flat-top 所需的 Ramp-up 末态。"""

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


def extract_shape_state(rows: list[dict[str, Any]]) -> dict[str, float]:
    """提取 Ramp-up 末端位形。"""

    last = rows[-1]
    return {field: float(last[field]) for field in SHAPE_FIELDS}

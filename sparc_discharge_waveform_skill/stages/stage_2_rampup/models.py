"""Ramp-up 阶段最小物理模型。

本文件只负责可复用计算，不负责读取文件和最终验证。升级后的口径是：
- Ip 轨迹仍由配置 breakpoints 给出；
- 用 Lp(t)、Rp(t) 和 V=d(Lp Ip)/dt+Rp Ip 计算环电压需求；
- 用 CS 互感方程反推 CS 电流；
- 用 Shafranov 型垂直场需求与 PF 响应矩阵生成 PF 电流；
- Div 后段缓慢进入预偏置，VS 只保留基准与裕度。

单位约定：
- 输入/输出线圈电流沿用 Stage 2 现有 kA；
- 等离子体电流为 MA；
- 物理公式内部将电流转换为 A；
- 磁通 Wb 与 Vs 在本离线模型中等价。
"""

from __future__ import annotations

import math
from typing import Any

MU0 = 4.0e-7 * math.pi

CS_COILS = ("CS1", "CS2", "CS3")
PF_COILS = ("PF1", "PF2", "PF3", "PF4")
DIV_COILS = ("Div1", "Div2")
AUX_COILS = DIV_COILS + ("VS",)
ALL_COILS = CS_COILS + PF_COILS + AUX_COILS
SHAPE_FIELDS = ("major_radius_m", "minor_radius_m", "elongation", "triangularity", "vertical_position_m")
PF_RESPONSE_ROWS = ("Bv", "Br", "G_kappa", "G_delta", "G_Z")

DEFAULT_CS_MUTUAL_INDUCTANCE_H = {"CS1": 1.2e-6, "CS2": 1.5e-6, "CS3": 1.2e-6}
DEFAULT_CS_SHARE = {"CS1": 0.30, "CS2": 0.40, "CS3": 0.30}
DEFAULT_PF_RESPONSE_MATRIX = [
    [0.002, 0.004, 0.010, 0.018],
    [0.001, -0.001, 0.004, 0.000],
    [0.020, 0.030, 0.006, 0.002],
    [0.004, 0.018, 0.010, 0.002],
    [0.001, -0.001, 0.006, 0.001],
]
DEFAULT_PF_SHAPE_GAINS = {"kappa": 0.02, "triangularity": 0.015, "vertical_position": 0.02}
DEFAULT_PF_WEIGHTS = {"Bv": 1.0, "Br": 0.5, "G_kappa": 0.8, "G_delta": 0.8, "G_Z": 0.5}


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
    """根据分段点生成平滑 Ip(t)。"""

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
                result.append(interpolate(ip0, ip1, smooth_fraction((time_s - t0) / (t1 - t0))))
                break
    return result


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
        shape[field] = [interpolate(start, end, smooth_fraction((t - t0) / duration)) for t in times]
    return shape


def generate_density_profile(times: list[float], density_ramp: dict[str, Any]) -> list[float]:
    """生成线平均密度的简化爬升曲线。"""

    start = float(density_ramp["start_line_average_density_1e19_m3"])
    end = float(density_ramp["end_line_average_density_1e19_m3"])
    t0 = times[0]
    duration = times[-1] - t0
    return [interpolate(start, end, smooth_fraction((t - t0) / duration)) for t in times]


def generate_endpoint_profile(times: list[float], start: float, end: float) -> list[float]:
    """按阶段起止值生成 smoothstep 曲线。"""

    t0 = times[0]
    duration = max(times[-1] - t0, 1e-12)
    return [interpolate(start, end, smooth_fraction((t - t0) / duration)) for t in times]


def generate_internal_inductance_profile(times: list[float], physics: dict[str, Any] | None = None) -> list[float]:
    """生成内电感 li(t)。"""

    config = (physics or {}).get("internal_inductance", {})
    return generate_endpoint_profile(times, float(config.get("start", 0.95)), float(config.get("end", 0.75)))


def generate_temperature_profile(times: list[float], physics: dict[str, Any] | None = None) -> list[float]:
    """生成电子温度 Te(t)，单位 eV。"""

    config = (physics or {}).get("plasma_resistance", {})
    return generate_endpoint_profile(times, float(config.get("Te_start_eV", 80.0)), float(config.get("Te_end_eV", 2000.0)))


def generate_plasma_resistance_profile(times: list[float], physics: dict[str, Any] | None = None) -> list[float]:
    """生成等离子体电阻 Rp(t)，单位 ohm。"""

    config = (physics or {}).get("plasma_resistance", {})
    r_start = float(config.get("R_start_ohm", 1.0e-4))
    r_end = float(config.get("R_end_ohm", 1.0e-6))
    return generate_endpoint_profile(times, r_start, r_end)


def generate_poloidal_beta_profile(times: list[float], physics: dict[str, Any] | None = None) -> list[float]:
    """生成低阶 poloidal beta 估计。"""

    config = (physics or {}).get("poloidal_beta", {})
    return generate_endpoint_profile(times, float(config.get("start", 0.05)), float(config.get("end", 0.25)))


def compute_plasma_inductance_profile(shape_profile: dict[str, list[float]], li_profile: list[float]) -> list[float]:
    """用 Lp=mu0*R*(ln(8R/a)-2+li/2) 计算等离子体电感。"""

    result: list[float] = []
    for index, li in enumerate(li_profile):
        r0 = max(float(shape_profile["major_radius_m"][index]), 1e-6)
        minor_radius = max(float(shape_profile["minor_radius_m"][index]), 1e-6)
        result.append(MU0 * r0 * (math.log(8.0 * r0 / minor_radius) - 2.0 + 0.5 * float(li)))
    return result


def differentiate(times: list[float], values: list[float]) -> list[float]:
    """中心差分。"""

    if len(times) != len(values):
        raise ValueError("times and values must have the same length")
    if len(times) < 2:
        return [0.0 for _ in values]

    result: list[float] = []
    for index, value in enumerate(values):
        if index == 0:
            dt = times[1] - times[0]
            derivative = (values[1] - value) / dt
        elif index == len(times) - 1:
            dt = times[-1] - times[-2]
            derivative = (value - values[-2]) / dt
        else:
            dt = times[index + 1] - times[index - 1]
            derivative = (values[index + 1] - values[index - 1]) / dt
        if dt <= 0:
            raise ValueError("time axis must be strictly increasing")
        result.append(derivative)
    return result


def compute_loop_voltage_terms(
    times: list[float],
    ip_profile_ma: list[float],
    lp_profile_h: list[float],
    rp_profile_ohm: list[float],
) -> dict[str, list[float]]:
    """计算 V=d(Lp Ip)/dt+Rp Ip，并拆分感应/电阻项。"""

    ip_a = [value * 1.0e6 for value in ip_profile_ma]
    lp_ip = [lp * ip for lp, ip in zip(lp_profile_h, ip_a)]
    inductive = differentiate(times, lp_ip)
    resistive = [rp * ip for rp, ip in zip(rp_profile_ohm, ip_a)]
    required = [max(0.0, ind + res) for ind, res in zip(inductive, resistive)]
    return {
        "loop_voltage_required_V": required,
        "loop_voltage_inductive_V": inductive,
        "loop_voltage_resistive_V": resistive,
    }


def estimate_flux_consumption(times: list[float], loop_voltage: list[float], already_consumed_wb: float) -> list[float]:
    """用环电压时间积分估算累计磁通消耗。"""

    flux = [float(already_consumed_wb)]
    for index in range(1, len(times)):
        dt = times[index] - times[index - 1]
        average_voltage = 0.5 * (loop_voltage[index] + loop_voltage[index - 1])
        flux.append(flux[-1] + average_voltage * dt)
    return flux


def get_cs_mutual_inductance_h(physics: dict[str, Any] | None = None) -> dict[str, float]:
    """读取 CS 互感，缺省使用等效常数。"""

    configured = (physics or {}).get("cs_mutual_inductance_H", {})
    result = dict(DEFAULT_CS_MUTUAL_INDUCTANCE_H)
    if isinstance(configured, dict):
        for name, value in configured.items():
            if name in CS_COILS:
                result[name] = float(value)
    if any(value <= 0 for value in result.values()):
        raise ValueError("CS mutual inductance values must be positive")
    return result


def get_cs_share(physics: dict[str, Any] | None = None) -> dict[str, float]:
    """读取 CS swing 分担。"""

    configured = (physics or {}).get("cs_swing_share", {})
    result = dict(DEFAULT_CS_SHARE)
    if isinstance(configured, dict):
        for name, value in configured.items():
            if name in CS_COILS:
                result[name] = max(0.0, float(value))
    total = sum(result.values())
    if total <= 0:
        raise ValueError("CS share must contain at least one positive value")
    return {name: value / total for name, value in result.items()}


def generate_cs_waveforms_from_mutual_inductance(
    times: list[float],
    initial_currents_ka: dict[str, float],
    loop_voltage_required: list[float],
    physics: dict[str, Any] | None = None,
) -> tuple[dict[str, list[float]], list[float]]:
    """用 V=-sum(M dI/dt) 由环电压反推 CS 电流。"""

    mutual = get_cs_mutual_inductance_h(physics)
    share = get_cs_share(physics)
    effective_m = sum(mutual[name] * share[name] for name in CS_COILS)
    if effective_m <= 0:
        raise ValueError("effective CS mutual inductance must be positive")

    derivatives_ka_per_s = {name: [] for name in CS_COILS}
    for voltage in loop_voltage_required:
        total_derivative_a_per_s = -float(voltage) / effective_m
        for name in CS_COILS:
            derivatives_ka_per_s[name].append(total_derivative_a_per_s * share[name] / 1000.0)

    result: dict[str, list[float]] = {name: [float(initial_currents_ka[name])] for name in CS_COILS}
    for index in range(1, len(times)):
        dt = times[index] - times[index - 1]
        for name in CS_COILS:
            average_derivative = 0.5 * (derivatives_ka_per_s[name][index] + derivatives_ka_per_s[name][index - 1])
            result[name].append(result[name][-1] + average_derivative * dt)

    loop_voltage_cs = compute_cs_drive_voltage(times, result, mutual)
    return result, loop_voltage_cs


def compute_cs_drive_voltage(
    times: list[float],
    cs_waveforms_ka: dict[str, list[float]],
    mutual_inductance_h: dict[str, float],
) -> list[float]:
    """由 CS 电流变化反算环电压。"""

    voltage = [0.0 for _ in times]
    for name in CS_COILS:
        derivatives_ka_per_s = differentiate(times, cs_waveforms_ka[name])
        for index, derivative in enumerate(derivatives_ka_per_s):
            voltage[index] += -mutual_inductance_h[name] * derivative * 1000.0
    return voltage


def compute_required_vertical_field(
    ip_profile_ma: list[float],
    shape_profile: dict[str, list[float]],
    li_profile: list[float],
    beta_p_profile: list[float],
) -> list[float]:
    """用低阶 Shafranov 近似估算平衡所需垂直场。"""

    result: list[float] = []
    for index, ip_ma in enumerate(ip_profile_ma):
        ip_a = max(float(ip_ma), 0.0) * 1.0e6
        major_radius = max(float(shape_profile["major_radius_m"][index]), 1e-6)
        minor_radius = max(float(shape_profile["minor_radius_m"][index]), 1e-6)
        bracket = math.log(8.0 * major_radius / minor_radius) + beta_p_profile[index] + 0.5 * li_profile[index] - 1.5
        result.append(MU0 * ip_a / (4.0 * math.pi * major_radius) * bracket)
    return result


def get_pf_response_matrix(physics: dict[str, Any] | None = None) -> list[list[float]]:
    """读取 PF 响应矩阵。"""

    configured = (physics or {}).get("pf_response_matrix", {})
    values = configured.get("values") if isinstance(configured, dict) else None
    if isinstance(values, list) and len(values) == len(PF_RESPONSE_ROWS):
        matrix = [[float(value) for value in row] for row in values]
        if all(len(row) == len(PF_COILS) for row in matrix):
            return matrix
    return [list(row) for row in DEFAULT_PF_RESPONSE_MATRIX]


def get_pf_shape_gains(physics: dict[str, Any] | None = None) -> dict[str, float]:
    """读取形状目标增益。"""

    gains = dict(DEFAULT_PF_SHAPE_GAINS)
    configured = (physics or {}).get("pf_shape_gains", {})
    if isinstance(configured, dict):
        for key in gains:
            if key in configured:
                gains[key] = float(configured[key])
    return gains


def get_pf_solver_settings(physics: dict[str, Any] | None = None) -> tuple[float, dict[str, float]]:
    """读取 PF 求解器正则和权重。"""

    solver = (physics or {}).get("solver", {})
    regularization = float(solver.get("pf_regularization", 0.01)) if isinstance(solver, dict) else 0.01
    weights = dict(DEFAULT_PF_WEIGHTS)
    configured_weights = solver.get("weights", {}) if isinstance(solver, dict) else {}
    if isinstance(configured_weights, dict):
        for key in weights:
            if key in configured_weights:
                weights[key] = float(configured_weights[key])
    return regularization, weights


def generate_pf_waveforms_from_response_matrix(
    times: list[float],
    initial_currents_ka: dict[str, float],
    shape_profile: dict[str, list[float]],
    bv_required_t: list[float],
    physics: dict[str, Any] | None = None,
) -> tuple[dict[str, list[float]], list[float]]:
    """用 PF 响应矩阵和正则化最小二乘生成 PF 电流。"""

    matrix = get_pf_response_matrix(physics)
    gains = get_pf_shape_gains(physics)
    regularization, weights = get_pf_solver_settings(physics)
    weight_list = [weights[row] for row in PF_RESPONSE_ROWS]
    initial_vector = [float(initial_currents_ka[name]) for name in PF_COILS]
    previous = list(initial_vector)
    initial_kappa = shape_profile["elongation"][0]
    initial_delta = shape_profile["triangularity"][0]
    initial_z = shape_profile["vertical_position_m"][0]

    result = {name: [] for name in PF_COILS}
    residuals: list[float] = []
    for index, bv_required in enumerate(bv_required_t):
        target = [
            float(bv_required),
            0.0,
            gains["kappa"] * (shape_profile["elongation"][index] - initial_kappa),
            gains["triangularity"] * (shape_profile["triangularity"][index] - initial_delta),
            gains["vertical_position"] * (shape_profile["vertical_position_m"][index] - initial_z),
        ]
        solution = solve_regularized_least_squares(matrix, target, weight_list, regularization, previous)
        previous = solution
        for name, value in zip(PF_COILS, solution):
            result[name].append(value)
        residuals.append(compute_weighted_residual(matrix, solution, target, weight_list))
    return result, residuals


def solve_regularized_least_squares(
    matrix: list[list[float]],
    target: list[float],
    weights: list[float],
    regularization: float,
    previous: list[float],
) -> list[float]:
    """解 (C^T W^2 C + lambda I)x=C^T W^2 y + lambda previous。"""

    n_cols = len(matrix[0])
    lhs = [[0.0 for _ in range(n_cols)] for _ in range(n_cols)]
    rhs = [0.0 for _ in range(n_cols)]
    for row_index, row in enumerate(matrix):
        weight2 = weights[row_index] * weights[row_index]
        for col_i in range(n_cols):
            rhs[col_i] += row[col_i] * weight2 * target[row_index]
            for col_j in range(n_cols):
                lhs[col_i][col_j] += row[col_i] * weight2 * row[col_j]
    lam = max(float(regularization), 0.0)
    for index in range(n_cols):
        lhs[index][index] += lam
        rhs[index] += lam * previous[index]
    return solve_linear_system(lhs, rhs)


def solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """小矩阵高斯消元，避免新增 numpy 依赖。"""

    size = len(rhs)
    a = [row[:] + [rhs[index]] for index, row in enumerate(matrix)]
    for pivot in range(size):
        best = max(range(pivot, size), key=lambda row: abs(a[row][pivot]))
        if abs(a[best][pivot]) < 1e-12:
            return [0.0 for _ in rhs]
        a[pivot], a[best] = a[best], a[pivot]
        divisor = a[pivot][pivot]
        for col in range(pivot, size + 1):
            a[pivot][col] /= divisor
        for row in range(size):
            if row == pivot:
                continue
            factor = a[row][pivot]
            for col in range(pivot, size + 1):
                a[row][col] -= factor * a[pivot][col]
    return [a[row][size] for row in range(size)]


def compute_weighted_residual(matrix: list[list[float]], solution: list[float], target: list[float], weights: list[float]) -> float:
    """计算加权残差范数。"""

    total = 0.0
    for row_index, row in enumerate(matrix):
        predicted = sum(coef * value for coef, value in zip(row, solution))
        total += (weights[row_index] * (predicted - target[row_index])) ** 2
    return math.sqrt(total)


def estimate_q95_profile_from_geometry(
    ip_profile: list[float],
    shape_profile: dict[str, list[float]],
    b0_t: float,
    target_q95: float,
) -> list[float]:
    """由几何、电流和 B_T 估算 q95，并按末端目标校准系数。"""

    raw: list[float] = []
    for index, ip in enumerate(ip_profile):
        major_radius = max(shape_profile["major_radius_m"][index], 1e-6)
        minor_radius = max(shape_profile["minor_radius_m"][index], 1e-6)
        kappa = shape_profile["elongation"][index]
        delta = shape_profile["triangularity"][index]
        shape_factor = 0.5 * (1.0 + kappa * kappa) * (1.0 + 0.5 * delta * delta)
        raw.append((minor_radius * minor_radius * float(b0_t) * shape_factor) / (major_radius * max(ip, 1e-6)))
    calibration = float(target_q95) / max(raw[-1], 1e-9)
    return [calibration * value for value in raw]


def estimate_vertical_stability_margin(shape_profile: dict[str, list[float]]) -> list[float]:
    """用拉长比和垂直位移估算垂直稳定裕度。"""

    margins: list[float] = []
    for elongation, z_pos in zip(shape_profile["elongation"], shape_profile["vertical_position_m"]):
        margins.append(max(0.05, 0.35 - 0.10 * max(0.0, float(elongation) - 1.0) - 0.20 * abs(float(z_pos))))
    return margins


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
    physics_diagnostics: dict[str, list[float]] | None = None,
) -> list[dict[str, Any]]:
    """合并所有 Ramp-up 波形为逐时刻表格。"""

    physics_diagnostics = physics_diagnostics or {}
    rows: list[dict[str, Any]] = []
    last_index = len(times) - 1
    for index, time_s in enumerate(times):
        if index == 0:
            note = "rampup_start_from_breakdown"
        elif index == last_index:
            note = "rampup_end_to_flattop"
        else:
            note = "rampup_physics_current_and_shape_evolution"

        row = {
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
        for key, values in physics_diagnostics.items():
            row[key] = values[index]
        rows.append(row)
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

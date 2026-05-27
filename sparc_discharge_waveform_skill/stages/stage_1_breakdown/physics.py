"""Breakdown 阶段最小物理约束模型。

本模块不做完整 Biot-Savart 或自由边界平衡求解，只提供第一阶段需要的
低阶物理关系：
- 真空环电感 L0；
- 等效击穿电路 V_loop = Lp dIp/dt + Rp Ip；
- CS 互感驱动 V_loop = -sum(M_i dI_i/dt)；
- PF 影响系数矩阵估算击穿点 Br/Bz。

单位约定：外部配置电流为 MA；内部物理公式使用 SI 单位 A、H、V、T。
"""

from __future__ import annotations

import math
from typing import Any

MU0 = 4.0e-7 * math.pi

DEFAULT_CS_MUTUAL_INDUCTANCE_H = {
    "CS1": 1.2e-6,
    "CS2": 1.5e-6,
    "CS3": 1.2e-6,
}

# 影响系数单位：T / MA。它们是最小物理约束模型中的等效系数，
# 用于替代旧版经验加权和，不代表真实 SPARC 工程线圈几何。
DEFAULT_PF_FIELD_COEFFICIENTS_T_PER_MA = {
    "PF1": {"Br": 0.0010, "Bz": 0.0015},
    "PF2": {"Br": -0.0010, "Bz": 0.0015},
    "PF3": {"Br": 0.0030, "Bz": 0.0120},
    "PF4": {"Br": 0.0000, "Bz": -0.0100},
}


class PhysicsConfigError(ValueError):
    """物理配置不合法。"""


def vacuum_loop_inductance_h(device: dict[str, Any]) -> float:
    """用真空环近似估算等离子体电感 L0。"""

    r0 = float(device.get("R0_m", 0.0))
    minor_radius = float(device.get("a_m", 0.0))
    if r0 <= 0 or minor_radius <= 0:
        raise PhysicsConfigError("device.R0_m and device.a_m must be positive for vacuum inductance")
    return MU0 * r0 * (math.log(8.0 * r0 / minor_radius) - 2.0)


def get_plasma_resistance_ohm(config: dict[str, Any]) -> float:
    """读取极简等效击穿电阻，默认取很小值以避免主导击穿电压。"""

    physics = config.get("physics", {})
    value = float(physics.get("plasma_resistance_ohm", 1.0e-5))
    if value < 0:
        raise PhysicsConfigError("physics.plasma_resistance_ohm must be non-negative")
    return value


def get_cs_mutual_inductance_h(config: dict[str, Any]) -> dict[str, float]:
    """读取 CS 互感常数。"""

    physics = config.get("physics", {})
    configured = physics.get("cs_mutual_inductance_H", {})
    result = dict(DEFAULT_CS_MUTUAL_INDUCTANCE_H)
    if isinstance(configured, dict):
        for name, value in configured.items():
            result[name] = float(value)
    for name, value in result.items():
        if value <= 0:
            raise PhysicsConfigError(f"physics.cs_mutual_inductance_H.{name} must be positive")
    return result


def get_pf_field_coefficients(config: dict[str, Any]) -> dict[str, dict[str, float]]:
    """读取 PF 击穿点场影响系数。"""

    physics = config.get("physics", {})
    configured = physics.get("pf_field_coefficients_T_per_MA", {})
    result = {name: dict(values) for name, values in DEFAULT_PF_FIELD_COEFFICIENTS_T_PER_MA.items()}
    if isinstance(configured, dict):
        for name, values in configured.items():
            if isinstance(values, dict):
                result[name] = {
                    "Br": float(values.get("Br", result.get(name, {}).get("Br", 0.0))),
                    "Bz": float(values.get("Bz", result.get(name, {}).get("Bz", 0.0))),
                }
    return result


def compute_plasma_circuit_voltage(
    times: list[float],
    ip_profile_ma: list[float],
    plasma_inductance_h: float,
    plasma_resistance_ohm: float,
) -> list[float]:
    """根据 V = L dIp/dt + R Ip 计算目标 Ip 轨迹需要的环电压。"""

    if len(times) != len(ip_profile_ma):
        raise ValueError("times and ip_profile_ma must have the same length")
    if len(times) < 2:
        return [0.0 for _ in times]

    voltages: list[float] = []
    for idx, ip_ma in enumerate(ip_profile_ma):
        if idx == 0:
            dt = times[1] - times[0]
            derivative_ma_per_s = (ip_profile_ma[1] - ip_profile_ma[0]) / dt
        elif idx == len(times) - 1:
            dt = times[-1] - times[-2]
            derivative_ma_per_s = (ip_profile_ma[-1] - ip_profile_ma[-2]) / dt
        else:
            dt = times[idx + 1] - times[idx - 1]
            derivative_ma_per_s = (ip_profile_ma[idx + 1] - ip_profile_ma[idx - 1]) / dt
        if dt <= 0:
            raise ValueError("time axis must be strictly increasing")

        ip_a = ip_ma * 1.0e6
        derivative_a_per_s = derivative_ma_per_s * 1.0e6
        voltages.append(plasma_inductance_h * derivative_a_per_s + plasma_resistance_ohm * ip_a)
    return voltages


def compute_cs_drive_voltage(
    times: list[float],
    cs_waveforms_ma: dict[str, list[float]],
    mutual_inductance_h: dict[str, float],
) -> list[float]:
    """由 CS 电流变化反算其提供的环电压。"""

    if len(times) < 2:
        return [0.0 for _ in times]
    voltages: list[float] = []
    for idx in range(len(times)):
        total = 0.0
        for name, values in cs_waveforms_ma.items():
            if idx == 0:
                dt = times[1] - times[0]
                derivative_ma_per_s = (values[1] - values[0]) / dt
            elif idx == len(times) - 1:
                dt = times[-1] - times[-2]
                derivative_ma_per_s = (values[-1] - values[-2]) / dt
            else:
                dt = times[idx + 1] - times[idx - 1]
                derivative_ma_per_s = (values[idx + 1] - values[idx - 1]) / dt
            total += -mutual_inductance_h.get(name, 0.0) * derivative_ma_per_s * 1.0e6
        voltages.append(total)
    return voltages


def integrate_voltage_to_cs_waveforms(
    times: list[float],
    coils: dict[str, dict[str, float]],
    share: dict[str, float],
    target_loop_voltage_v: float,
    mutual_inductance_h: dict[str, float],
) -> dict[str, list[float]]:
    """用 CS 互感方程从目标环电压反推 CS 电流波形。"""

    total_share = sum(max(0.0, float(share.get(name, 0.0))) for name in ("CS1", "CS2", "CS3"))
    if total_share <= 0:
        raise ValueError("CS shares must contain at least one positive value")

    effective_m = sum(
        mutual_inductance_h[name] * max(0.0, float(share.get(name, 0.0))) / total_share
        for name in ("CS1", "CS2", "CS3")
    )
    if effective_m <= 0:
        raise PhysicsConfigError("effective CS mutual inductance must be positive")

    result: dict[str, list[float]] = {}
    for name in ("CS1", "CS2", "CS3"):
        i0 = float(coils[name]["I0_MA"])
        normalized_share = max(0.0, float(share.get(name, 0.0))) / total_share
        derivative_total_ma_per_s = -target_loop_voltage_v / effective_m / 1.0e6
        derivative_ma_per_s = derivative_total_ma_per_s * normalized_share
        result[name] = [i0 + derivative_ma_per_s * (time_s - times[0]) for time_s in times]
    return result


def solve_pf_null_targets(
    coils: dict[str, dict[str, float]],
    coefficients: dict[str, dict[str, float]],
    zero_field_tolerance_t: float | None = None,
) -> dict[str, float]:
    """用 PF3/PF4 解最小零场目标，PF1/PF2 保持小修正。"""

    targets = {
        "PF1": float(coils["PF1"]["I0_MA"]),
        "PF2": float(coils["PF2"]["I0_MA"]),
        "PF3": float(coils["PF3"]["I0_MA"]),
        "PF4": float(coils["PF4"]["I0_MA"]),
    }

    base_br, base_bz = compute_breakdown_field_t(targets, coefficients)
    if zero_field_tolerance_t is not None and field_magnitude_t(base_br, base_bz) <= zero_field_tolerance_t:
        return targets
    a11 = coefficients["PF3"].get("Br", 0.0)
    a12 = coefficients["PF4"].get("Br", 0.0)
    a21 = coefficients["PF3"].get("Bz", 0.0)
    a22 = coefficients["PF4"].get("Bz", 0.0)
    determinant = a11 * a22 - a12 * a21
    if abs(determinant) < 1.0e-12:
        return targets

    delta_i3 = (-base_br * a22 - a12 * -base_bz) / determinant
    delta_i4 = (a11 * -base_bz - -base_br * a21) / determinant
    targets["PF3"] = _clamp_to_limits(targets["PF3"] + delta_i3, coils["PF3"])
    targets["PF4"] = _clamp_to_limits(targets["PF4"] + delta_i4, coils["PF4"])
    return targets


def compute_breakdown_field_t(
    pf_currents_ma: dict[str, float],
    coefficients: dict[str, dict[str, float]],
) -> tuple[float, float]:
    """用 PF 影响系数矩阵计算击穿点 Br/Bz。"""

    br = 0.0
    bz = 0.0
    for name, current_ma in pf_currents_ma.items():
        coeff = coefficients.get(name, {})
        br += float(coeff.get("Br", 0.0)) * float(current_ma)
        bz += float(coeff.get("Bz", 0.0)) * float(current_ma)
    return br, bz


def field_magnitude_t(br_t: float, bz_t: float) -> float:
    """返回极向场模。"""

    return math.hypot(br_t, bz_t)


def _clamp_to_limits(value: float, coil: dict[str, float]) -> float:
    return max(float(coil["I_min_MA"]), min(float(coil["I_max_MA"]), value))

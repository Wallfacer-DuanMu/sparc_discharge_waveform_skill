"""Breakdown 阶段简化模型。

本文件只放置可复用的计算模型，不负责读取文件，也不负责最终验证。
口径保持简单：
- Ip 从 0 连续上升到种子电流；
- CS1/CS2/CS3 按比例做击穿 swing；
- PF3/PF4 做零场预置，PF1/PF2 做小修正；
- Div 和 VS 在 Breakdown 中保持初始值。
"""

from __future__ import annotations

from typing import Any


CS_COILS = ("CS1", "CS2", "CS3")
PF_COILS = ("PF1", "PF2", "PF3", "PF4")
AUX_COILS = ("Div1", "Div2", "VS")
ALL_COILS = CS_COILS + PF_COILS + AUX_COILS


def make_time_axis(t_start_s: float, t_end_s: float, dt_s: float) -> list[float]:
    """生成包含起点和终点的 Breakdown 时间轴。"""

    if dt_s <= 0:
        raise ValueError("timeline.dt_s must be greater than 0")
    if t_end_s <= t_start_s:
        raise ValueError("timeline.breakdown_end_s must be greater than t_start_s")

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
    """三次 smoothstep，用于避免起点和终点出现尖锐折角。"""

    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def interpolate(start: float, end: float, fraction: float) -> float:
    """按给定比例在两个数值之间插值。"""

    return start + (end - start) * fraction


def generate_ip_seed_profile(times: list[float], ip_seed_ma: float) -> list[float]:
    """生成从 0 平滑上升到 Ip_seed_MA 的简化种子电流轨迹。"""

    if ip_seed_ma < 0:
        raise ValueError("target.Ip_seed_MA must be non-negative")

    t0 = times[0]
    duration = times[-1] - t0
    if duration <= 0:
        return [ip_seed_ma for _ in times]

    return [interpolate(0.0, ip_seed_ma, smooth_fraction((t - t0) / duration)) for t in times]


def estimate_cs_flux_used(loop_voltage_v: float, t_start_s: float, t_end_s: float) -> float:
    """用 V_loop * duration 估算 Breakdown 消耗的 CS 伏秒。"""

    if loop_voltage_v <= 0:
        raise ValueError("constraints.breakdown_loop_voltage_V must be greater than 0")
    return loop_voltage_v * (t_end_s - t_start_s)


def generate_cs_swing(
    times: list[float],
    coils: dict[str, dict[str, float]],
    share: dict[str, float],
    loop_voltage_v: float,
) -> dict[str, list[float]]:
    """生成 CS 击穿 swing 波形。

    这里不用真实互感矩阵，而用一个教学化规则：击穿电压越高，CS 在阶段内释放的
    电流越多；三组 CS 按 share 分担。方向取负，表示从预充磁状态释放磁通。
    """

    duration = times[-1] - times[0]
    if duration <= 0:
        raise ValueError("breakdown duration must be greater than 0")

    total_share = sum(share.get(name, 0.0) for name in CS_COILS)
    if total_share <= 0:
        raise ValueError("options.cs_swing_share must contain positive CS shares")

    result: dict[str, list[float]] = {}
    # 简化比例：20 V、0.08 s 约对应 0.8 MA 总 swing，便于学生作业量级演示。
    total_delta_ma = 0.5 * loop_voltage_v * duration

    for name in CS_COILS:
        coil = coils[name]
        i0 = float(coil["I0_MA"])
        normalized_share = share.get(name, 0.0) / total_share
        target = i0 - total_delta_ma * normalized_share
        result[name] = _smooth_series(times, i0, target)

    return result


def generate_pf_null_preset(
    times: list[float],
    coils: dict[str, dict[str, float]],
    targets: dict[str, float],
) -> dict[str, list[float]]:
    """生成 PF 零场预置波形。"""

    result: dict[str, list[float]] = {}
    for name in PF_COILS:
        i0 = float(coils[name]["I0_MA"])
        target = float(targets.get(name, i0))
        result[name] = _smooth_series(times, i0, target)
    return result


def generate_hold_waveforms(times: list[float], coils: dict[str, dict[str, float]]) -> dict[str, list[float]]:
    """生成 Breakdown 中保持初始值的 Div/VS 波形。"""

    result: dict[str, list[float]] = {}
    for name in AUX_COILS:
        i0 = float(coils[name]["I0_MA"])
        result[name] = [i0 for _ in times]
    return result


def estimate_zero_field_error(pf_end_state: dict[str, float]) -> float:
    """估算击穿区零场误差。

    这是简化指标，不是真实磁场求解。权重体现 PF4/PF3 是主力，PF1/PF2 是小修正。
    目标为 weighted_sum 接近 0。
    """

    weighted_sum = (
        0.01 * pf_end_state.get("PF1", 0.0)
        + 0.02 * pf_end_state.get("PF2", 0.0)
        + 0.04 * pf_end_state.get("PF3", 0.0)
        - 0.03 * pf_end_state.get("PF4", 0.0)
    )
    return abs(weighted_sum)


def build_waveform_rows(
    times: list[float],
    ip_profile: list[float],
    cs_waveforms: dict[str, list[float]],
    pf_waveforms: dict[str, list[float]],
    aux_waveforms: dict[str, list[float]],
    b0_t: float,
) -> list[dict[str, Any]]:
    """合并所有 Breakdown 波形为逐时刻表格。"""

    rows: list[dict[str, Any]] = []
    last_index = len(times) - 1
    for idx, time_s in enumerate(times):
        if idx == 0:
            note = "breakdown_start"
        elif idx == last_index:
            note = "breakdown_end"
        else:
            note = "breakdown_swing"

        rows.append(
            {
                "time_s": time_s,
                "stage": "breakdown",
                "Ip_MA": ip_profile[idx],
                "I_CS1_MA": cs_waveforms["CS1"][idx],
                "I_CS2_MA": cs_waveforms["CS2"][idx],
                "I_CS3_MA": cs_waveforms["CS3"][idx],
                "I_PF1_MA": pf_waveforms["PF1"][idx],
                "I_PF2_MA": pf_waveforms["PF2"][idx],
                "I_PF3_MA": pf_waveforms["PF3"][idx],
                "I_PF4_MA": pf_waveforms["PF4"][idx],
                "I_Div1_MA": aux_waveforms["Div1"][idx],
                "I_Div2_MA": aux_waveforms["Div2"][idx],
                "I_VS_bias_MA": aux_waveforms["VS"][idx],
                "B0_T": b0_t,
                "note": note,
            }
        )
    return rows


def extract_end_state(rows: list[dict[str, Any]]) -> dict[str, float]:
    """从最后一行波形中提取 Ramp-up 所需的线圈末态。"""

    last = rows[-1]
    return {
        "CS1": float(last["I_CS1_MA"]),
        "CS2": float(last["I_CS2_MA"]),
        "CS3": float(last["I_CS3_MA"]),
        "PF1": float(last["I_PF1_MA"]),
        "PF2": float(last["I_PF2_MA"]),
        "PF3": float(last["I_PF3_MA"]),
        "PF4": float(last["I_PF4_MA"]),
        "Div1": float(last["I_Div1_MA"]),
        "Div2": float(last["I_Div2_MA"]),
        "VS": float(last["I_VS_bias_MA"]),
    }


def _smooth_series(times: list[float], start: float, end: float) -> list[float]:
    t0 = times[0]
    duration = times[-1] - t0
    if duration <= 0:
        return [end for _ in times]
    return [interpolate(start, end, smooth_fraction((t - t0) / duration)) for t in times]

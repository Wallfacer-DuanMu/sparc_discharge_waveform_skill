"""SPARC 三阶段放电波形设计 Pipeline 最小闭环。

用法示例：
    python sparc_discharge_waveform_skill/pipeline/run_pipeline.py
    python sparc_discharge_waveform_skill/pipeline/run_pipeline.py --config sparc_discharge_waveform_skill/config/input_template.yaml
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ROOT_DIR.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from sparc_discharge_waveform_skill.common.io import ensure_dir, read_yaml, write_json, write_text
from sparc_discharge_waveform_skill.common.state import (
    make_empty_process_state,
    make_final_result,
    make_stage_1_result,
    make_stage_2_result,
    make_stage_3_result,
)
from sparc_discharge_waveform_skill.common.validation import validate_config


def run_pipeline(config_path: str | Path, use_stage_generators: bool = False) -> dict[str, Any]:
    """执行三阶段 Pipeline，并返回过程状态。"""
    config = read_yaml(config_path)
    if use_stage_generators:
        config.setdefault("options", {})["stage_execution_mode"] = "stage_generators"
    validation = validate_config(config)
    case_name = config.get("case_name", "unnamed_case")
    output_root = config.get("options", {}).get("output_root", "outputs")
    output_dir = ensure_dir(ROOT_DIR / output_root / case_name)

    process_state = make_empty_process_state(config)
    process_state["status"] = "running"
    process_state["input_validation"] = validation

    if not validation["passed"]:
        process_state["status"] = "failed"
        process_state["final_result"] = {
            "passed": False,
            "failed_stage": "input_validation",
            "issues": validation["issues"],
            "process_state_file": str(output_dir / "process_state.json"),
        }
        write_json(output_dir / "process_state.json", process_state)
        return process_state

    stage_1_result = make_stage_1_result(config)
    process_state["stage_1_result"] = stage_1_result

    stage_2_result = make_stage_2_result(config, stage_1_result)
    process_state["stage_2_result"] = stage_2_result

    stage_3_result = make_stage_3_result(config, stage_2_result)
    process_state["stage_3_result"] = stage_3_result

    final_result = make_final_result(
        config=config,
        stage_1_result=stage_1_result,
        stage_2_result=stage_2_result,
        stage_3_result=stage_3_result,
        output_dir=str(output_dir),
    )
    process_state["final_result"] = final_result
    process_state["status"] = "passed" if final_result["passed"] else "failed"

    write_minimal_waveforms(output_dir / "waveforms.csv", config, process_state)
    write_text(output_dir / "stage_summary.md", build_stage_summary(process_state))
    write_text(output_dir / "validation_report.md", build_validation_report(process_state))
    write_text(output_dir / "revision_suggestions.md", build_revision_suggestions(process_state))
    write_json(output_dir / "process_state.json", process_state)

    return process_state


def write_minimal_waveforms(path: str | Path, config: dict[str, Any], process_state: dict[str, Any]) -> None:
    """写出最小波形表，只记录三阶段边界点。"""
    timeline = config["timeline"]
    device = config["device"]
    stage_1 = process_state["stage_1_result"]
    stage_2 = process_state["stage_2_result"]
    stage_3 = process_state["stage_3_result"]

    rows = []
    if stage_2.get("waveform_rows") or stage_3.get("waveform_rows"):
        rows.extend(_convert_stage_rows_to_pipeline(stage_2.get("waveform_rows", []), device))
        rows.extend(_convert_stage_rows_to_pipeline(stage_3.get("waveform_rows", []), device))
    if not rows:
        rows = [
            _waveform_row(float(timeline["t_start_s"]), "start", 0.0, stage_1["coil_state_at_breakdown_end"], device),
            _waveform_row(float(timeline["breakdown_end_s"]), "breakdown_end", float(stage_1["Ip_at_breakdown_end_MA"]), stage_1["coil_state_at_breakdown_end"], device),
            _waveform_row(float(timeline["rampup_end_s"]), "rampup_end", float(stage_2["Ip_at_rampup_end_MA"]), stage_2["coil_state_at_rampup_end"], device),
            _waveform_row(float(timeline["flattop_end_s"]), "flattop_end", float(stage_3["Ip_at_flattop_end_MA"]), stage_3["coil_state_at_flattop_end"], device),
        ]

    with Path(path).open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _convert_stage_rows_to_pipeline(rows: list[dict[str, Any]], device: dict[str, Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for row in rows:
        converted.append(
            {
                "time_s": row.get("time_s", 0.0),
                "stage": row.get("stage", "unknown"),
                "Ip_MA": row.get("Ip_MA", row.get("plasma_current_MA", 0.0)),
                "I_CS1_MA": float(row.get("I_CS1_kA", 0.0)) / 1000.0,
                "I_CS2_MA": float(row.get("I_CS2_kA", 0.0)) / 1000.0,
                "I_CS3_MA": float(row.get("I_CS3_kA", 0.0)) / 1000.0,
                "I_PF1_MA": float(row.get("I_PF1_kA", 0.0)) / 1000.0,
                "I_PF2_MA": float(row.get("I_PF2_kA", 0.0)) / 1000.0,
                "I_PF3_MA": float(row.get("I_PF3_kA", 0.0)) / 1000.0,
                "I_PF4_MA": float(row.get("I_PF4_kA", 0.0)) / 1000.0,
                "I_Div1_MA": float(row.get("I_Div1_kA", 0.0)) / 1000.0,
                "I_Div2_MA": float(row.get("I_Div2_kA", 0.0)) / 1000.0,
                "I_VS_bias_MA": float(row.get("I_VS_bias_kA", 0.0)) / 1000.0,
                "B0_T": device.get("B0_T", 0.0),
                "loop_voltage_V": row.get("loop_voltage_V", row.get("loop_voltage_required_V", "")),
                "flux_consumed_Wb": row.get("flux_consumed_Wb", ""),
                "q95": row.get("q95", ""),
                "pf_balance_residual": row.get("pf_balance_residual", ""),
                "strike_point_residual": row.get("strike_point_residual", ""),
            }
        )
    return converted


def _waveform_row(
    time_s: float,
    stage: str,
    ip_ma: float,
    coil_state: dict[str, float],
    device: dict[str, Any],
) -> dict[str, Any]:
    return {
        "time_s": time_s,
        "stage": stage,
        "Ip_MA": ip_ma,
        "I_CS1_MA": coil_state.get("CS1", 0.0),
        "I_CS2_MA": coil_state.get("CS2", 0.0),
        "I_CS3_MA": coil_state.get("CS3", 0.0),
        "I_PF1_MA": coil_state.get("PF1", 0.0),
        "I_PF2_MA": coil_state.get("PF2", 0.0),
        "I_PF3_MA": coil_state.get("PF3", 0.0),
        "I_PF4_MA": coil_state.get("PF4", 0.0),
        "I_Div1_MA": coil_state.get("Div1", 0.0),
        "I_Div2_MA": coil_state.get("Div2", 0.0),
        "I_VS_bias_MA": coil_state.get("VS", 0.0),
        "B0_T": device.get("B0_T", 0.0),
    }


def build_stage_summary(process_state: dict[str, Any]) -> str:
    """生成阶段摘要。"""
    final_result = process_state["final_result"]
    metrics = final_result.get("key_metrics", {})
    stage_1 = process_state.get("stage_1_result", {})
    diagnostics = stage_1.get("physics_diagnostics", {})
    field = diagnostics.get("breakdown_field", {})
    return "\n".join(
        [
            "# Stage Summary",
            "",
            f"- case_name: `{process_state['case_name']}`",
            f"- pipeline_status: `{process_state['status']}`",
            f"- Ip_seed_MA: `{metrics.get('Ip_seed_MA')}`",
            f"- Ip_flat_MA: `{metrics.get('Ip_flat_MA')}`",
            f"- cs_flux_used_total_Vs: `{metrics.get('cs_flux_used_total_Vs')}`",
            f"- cs_flux_remaining_Vs: `{metrics.get('cs_flux_remaining_Vs')}`",
            f"- cs_flux_margin_fraction: `{metrics.get('cs_flux_margin_fraction')}`",
            f"- stage_2_execution_mode: `{process_state.get('stage_2_result', {}).get('execution_mode', 'not_reported')}`",
            f"- stage_2_model: `{process_state.get('stage_2_result', {}).get('physics_diagnostics', {}).get('model', 'not_reported')}`",
            f"- stage_3_execution_mode: `{process_state.get('stage_3_result', {}).get('execution_mode', 'not_reported')}`",
            f"- stage_3_model: `{process_state.get('stage_3_result', {}).get('physics_diagnostics', {}).get('model', 'not_reported')}`",
            f"- stage_3_max_loop_voltage_required_V: `{process_state.get('stage_3_result', {}).get('raw_stage_result_summary', {}).get('max_loop_voltage_required_V')}`",
            f"- stage_3_min_q95: `{process_state.get('stage_3_result', {}).get('raw_stage_result_summary', {}).get('min_q95')}`",
            f"- stage_3_max_pf_balance_residual: `{process_state.get('stage_3_result', {}).get('raw_stage_result_summary', {}).get('max_pf_balance_residual')}`",
            f"- stage_3_max_strike_point_residual: `{process_state.get('stage_3_result', {}).get('raw_stage_result_summary', {}).get('max_strike_point_residual')}`",
            f"- breakdown_model: `{diagnostics.get('model', 'not_reported')}`",
            f"- breakdown_average_cs_drive_voltage_V: `{diagnostics.get('average_cs_drive_voltage_V')}`",
            f"- breakdown_average_plasma_circuit_voltage_V: `{diagnostics.get('average_plasma_circuit_voltage_V')}`",
            f"- breakdown_Br_T: `{field.get('Br_T')}`",
            f"- breakdown_Bz_T: `{field.get('Bz_T')}`",
            "",
        ]
    )


def build_validation_report(process_state: dict[str, Any]) -> str:
    """生成验证报告。"""
    lines = ["# Validation Report", ""]
    lines.append(f"- input_validation: `{process_state['input_validation']['passed']}`")
    for key in ("stage_1_result", "stage_2_result", "stage_3_result"):
        result = process_state[key]
        validation_key = next(name for name in result if name.endswith("_validation"))
        lines.append(f"- {result['stage_name']}: `{result[validation_key]['passed']}`")
    lines.append("")
    return "\n".join(lines)


def build_revision_suggestions(process_state: dict[str, Any]) -> str:
    """生成修正建议。"""
    suggestions = process_state["final_result"].get("next_revision_suggestions", [])
    lines = ["# Revision Suggestions", ""]
    if not suggestions:
        lines.append("- 当前最小闭环未发现阻断性问题；后续应替换占位阶段模型为真实阶段计算。")
    else:
        lines.extend(f"- {item}" for item in suggestions)
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 SPARC 三阶段放电波形设计最小 Pipeline。")
    parser.add_argument(
        "--config",
        default=str(ROOT_DIR / "config" / "input_template.yaml"),
        help="输入 YAML 配置路径。",
    )
    parser.add_argument(
        "--use-stage-generators",
        action="store_true",
        help="调用已接入的真实阶段生成器；当前会启用真实 Stage 2 Ramp-up 与 Stage 3 Flat-top。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    process_state = run_pipeline(args.config, use_stage_generators=args.use_stage_generators)
    print(f"Pipeline finished: {process_state['status']}")
    print(process_state["final_result"].get("process_state_file", ""))


if __name__ == "__main__":
    main()

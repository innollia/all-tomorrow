from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from all_tomorrow.contracts import ContractError, PipelineSpec, PipelineStep


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ContractError(f"{path} must be a mapping")
    return value


def parse_pipeline(data: Any) -> PipelineSpec:
    root = _mapping(data, "pipeline")
    raw_steps = root.get("steps")
    if not isinstance(raw_steps, list):
        raise ContractError("pipeline.steps must be a list")

    steps: list[PipelineStep] = []
    for index, raw in enumerate(raw_steps):
        item = _mapping(raw, f"pipeline.steps[{index}]")
        retry = _mapping(item.get("retry"), f"pipeline.steps[{index}].retry")
        steps.append(
            PipelineStep(
                id=item.get("id", ""),
                type=item.get("type", ""),
                config=_mapping(item.get("config"), f"pipeline.steps[{index}].config"),
                inputs=_mapping(item.get("inputs"), f"pipeline.steps[{index}].inputs"),
                when=item.get("when"),
                next_step=item.get("next"),
                on_status=_mapping(item.get("on_status"), f"pipeline.steps[{index}].on_status"),
                max_retries=retry.get("max_attempts", 1) - 1,
            )
        )

    return PipelineSpec(
        pipeline_id=root.get("id", ""),
        version=root.get("version", 0),
        status=root.get("status", "draft"),
        parent_version=root.get("parent_version"),
        change_reason=root.get("change_reason"),
        trigger=_mapping(root.get("trigger"), "pipeline.trigger"),
        steps=tuple(steps),
    )


def load_pipeline(path: str | Path) -> PipelineSpec:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        data = json.loads(text)
    elif source.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        raise ContractError(f"unsupported pipeline format: {source.suffix}")
    return parse_pipeline(data)


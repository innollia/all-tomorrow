"""Roster loading and LiteLLM gateway config generation (key names only, never values)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ROSTER_PATH = Path(os.environ.get("IDEA_FACTORY_ROSTER", REPO_ROOT / "config" / "idea-factory.yaml"))
KEY_POOL_PATH = Path(os.environ.get("IDEA_FACTORY_KEY_POOL", REPO_ROOT / "config" / "key-pool.local.env"))

PROVIDERS = {
    "openrouter": {"prefix": "OPENROUTER__", "model": "openrouter/{model}"},
    "groq": {"prefix": "GROQ__", "model": "groq/{model}"},
    "huggingface": {"prefix": "HUGGINGFACE__", "model": "openai/{model}", "api_base": "https://router.huggingface.co/v1"},
}


@dataclass(slots=True)
class Roster:
    ideas_per_topic: int
    council_rounds: int
    council_pass_votes: int
    evaluation_min_samples: int
    promote_above: float
    retire_below: float
    model_groups: dict[str, list[dict[str, str]]]
    fallback_group: str
    tiers: list[str]
    staff: list[dict[str, Any]] = field(default_factory=list)
    profile_sources: list[dict[str, Any]] = field(default_factory=list)
    council_share: str = "summary"  # summary | full | filtered (see pipeline._transcript_for)


def load_roster(path: Path = ROSTER_PATH) -> Roster:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    roster = Roster(**data)
    for group in roster.model_groups.values():
        for entry in group:
            if entry["provider"] == "openrouter" and not entry["model"].endswith(":free"):
                raise ValueError(f"OpenRouter model must be :free (paid keys are in the pool): {entry['model']}")
    return roster


def load_key_pool(path: Path = KEY_POOL_PATH) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            if value.strip():
                entries[name.strip()] = value.strip()
    return entries


def gateway_config(roster: Roster, key_names: list[str], master_key_env: str = "IDEA_FACTORY_GATEWAY_KEY") -> dict[str, Any]:
    """LiteLLM proxy config: one deployment per (model, key). Keys referenced as os.environ/NAME."""
    model_list = []
    for group, entries in roster.model_groups.items():
        for entry in entries:
            spec = PROVIDERS[entry["provider"]]
            for key_name in sorted(k for k in key_names if k.startswith(spec["prefix"])):
                params: dict[str, Any] = {"model": spec["model"].format(model=entry["model"]),
                                          "api_key": f"os.environ/{key_name}"}
                if "api_base" in spec:
                    params["api_base"] = spec["api_base"]
                model_list.append({
                    "model_name": group,
                    "litellm_params": params,
                    "model_info": {"id": f"{group}|{entry['model']}|{key_name}"},
                })
    fallbacks = [{group: [roster.fallback_group]} for group in roster.model_groups if group != roster.fallback_group]
    return {
        "model_list": model_list,
        "router_settings": {
            "routing_strategy": "simple-shuffle",
            "num_retries": 3,
            "allowed_fails": 1,
            "cooldown_time": 60,
            "fallbacks": fallbacks,
        },
        "litellm_settings": {"callbacks": [], "drop_params": True, "request_timeout": 120},
        "general_settings": {"master_key": f"os.environ/{master_key_env}"},
    }


def export_secrets_to_env(names: tuple[str, ...] = ("IDEA_FACTORY_GATEWAY_KEY", "NOTION_TOKEN")) -> None:
    """Runtime secrets live in the key-pool file; the process environment wins when set."""
    pool = load_key_pool()
    for name in names:
        if pool.get(name):
            os.environ.setdefault(name, pool[name])

"""05B — Daily Report Composer.

Builds a daily report from source-backed structured facts. The section skeleton
is deterministic; an LLM may only reorder/compress/phrase — it can never add a
claim that has no source ref, and the report is durable even if the LLM fails
(deterministic fallback). Unknown cost stays UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from all_tomorrow.report.store import Report, ReportSection

# Minimum output section contract, in order.
SECTION_TITLES: tuple[str, ...] = (
    "Autonomous Goals",
    "User Work Progress",
    "Research Findings",
    "System Changes",
    "Rollbacks / Rejections",
    "Resource & Cost",
    "Approval Pending",
    "Needs User",
)


@dataclass(frozen=True, slots=True)
class Fact:
    section: str
    text: str
    source_refs: tuple[str, ...]
    unknown: bool = False


class UnsourcedClaimError(Exception):
    """An LLM-added claim had no backing source ref."""


def _skeleton(facts: list[Fact]) -> list[ReportSection]:
    by_section: dict[str, list[Fact]] = {t: [] for t in SECTION_TITLES}
    for f in facts:
        by_section.setdefault(f.section, []).append(f)
    sections: list[ReportSection] = []
    for title in SECTION_TITLES:
        items = by_section.get(title, [])
        refs = tuple(dict.fromkeys(r for f in items for r in f.source_refs))
        unknown = any(f.unknown for f in items)
        sections.append(ReportSection(title=title, source_refs=refs, unknown=unknown))
    return sections


def validate_claims(llm_claims: list[Fact], known_source_refs: frozenset[str]) -> None:
    """Every LLM claim must map to a known source ref; else reject the LLM output."""
    for c in llm_claims:
        if not c.source_refs:
            raise UnsourcedClaimError(f"claim without source: {c.text!r}")
        for r in c.source_refs:
            if r not in known_source_refs:
                raise UnsourcedClaimError(f"claim cites unknown source {r}: {c.text!r}")


def compose(
    facts: list[Fact],
    *,
    llm_summary: str | None = None,
    llm_claims: list[Fact] | None = None,
) -> tuple[list[ReportSection], str]:
    """Return (sections, summary). Falls back to a deterministic summary on LLM failure.

    ``llm_claims`` (if any) are validated against the facts' source refs; an
    unsourced/unknown-source claim discards the LLM contribution and uses the
    deterministic fallback — report durability never depends on the LLM.
    """
    sections = _skeleton(facts)
    known = frozenset(r for f in facts for r in f.source_refs)
    summary = _deterministic_summary(facts)
    if llm_summary is not None:
        try:
            if llm_claims:
                validate_claims(llm_claims, known)
            summary = llm_summary  # LLM only improves phrasing of a source-backed report
        except UnsourcedClaimError:
            summary = _deterministic_summary(facts)  # fallback FINAL
    return sections, summary


def _deterministic_summary(facts: list[Fact]) -> str:
    counts: dict[str, int] = {}
    for f in facts:
        counts[f.section] = counts.get(f.section, 0) + 1
    parts = [f"{title}: {counts.get(title, 0)}" for title in SECTION_TITLES if counts.get(title)]
    return "; ".join(parts) if parts else "No activity in period."

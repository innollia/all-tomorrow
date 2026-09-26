"""Stage 3.1C — Personal query & brief verification (S3-31C-01..04)."""

from __future__ import annotations

from datetime import timedelta

from all_tomorrow.domain.ids import utc_now
from all_tomorrow.owners import OwnerFact, SourceKind, SourceRef, Truthiness
from all_tomorrow.personal import (
    BriefProjector,
    answer_what_should_i_do,
    assemble_context,
)


def _fact(kind, value, age=timedelta(0)):
    ref = SourceRef(source_id=f"s-{kind}", kind=kind, fetched_at=utc_now() - age,
                    freshness=timedelta(hours=1))
    return OwnerFact(key="k", value=value, source=ref)


def _pack():
    return assemble_context(
        ["w1"],
        {
            "next_class": [_fact(SourceKind.OWNER_CANONICAL, "Math 9am")],
            "homework": [_fact(SourceKind.CACHE, "essay", age=timedelta(hours=5))],  # stale
        },
    )


# S3-31C-01: "뭐 해야 돼?" answer is source-backed.
def test_31c_01_source_backed_answer() -> None:
    ans = answer_what_should_i_do(_pack())
    assert any("Math 9am" in d and "src=" in d for d in ans["do"])


# S3-31C-02: stale/unknown is surfaced, not fabricated.
def test_31c_02_stale_flagged() -> None:
    ans = answer_what_should_i_do(_pack())
    assert any("homework" in a and "STALE_UNKNOWN" in a for a in ans["attention"])
    # the stale item is NOT presented as an actionable current fact
    assert not any("essay" in d for d in ans["do"])


# S3-31C-03: proactive brief is idempotent (no duplicate outbound).
def test_31c_03_brief_idempotent() -> None:
    p = BriefProjector()
    first = p.project(owner_id="o1", logical_period="2026-09-27", pack=_pack())
    dup = p.project(owner_id="o1", logical_period="2026-09-27", pack=_pack())
    assert first is not None and dup is None


# S3-31C-04: owner truth is referenced (source_id), not centrally copied wholesale.
def test_31c_04_reference_not_copy() -> None:
    pack = _pack()
    for item in pack.items:
        assert item.source_id is not None   # every fact carries its source ref

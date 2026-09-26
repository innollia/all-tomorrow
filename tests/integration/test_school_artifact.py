"""Stage 3.1B — School artifact pipeline verification (S3-31B-01..03)."""

from __future__ import annotations

from all_tomorrow.personal.school import (
    ExtractedField,
    FieldState,
    SchoolArtifactPipeline,
)


def _field(name, value, conf, page=1, span=(0, 10), ver="v1"):
    return ExtractedField(name=name, value=value, confidence=conf, page=page,
                          span=span, extraction_version=ver)


# S3-31B-01: original → extraction → Work lineage with provenance.
def test_31b_01_lineage_and_provenance() -> None:
    p = SchoolArtifactPipeline()
    res = p.process(upload_artifact_id="u1", content_hash="h1",
                    fields=[_field("due_date", "2026-10-01", 0.95)])
    assert res.upload_artifact_id == "u1"
    assert res.extraction_artifact_id and res.extraction_artifact_id != "u1"
    assert res.work_id is not None                     # confident field → Work
    f = res.fields[0]
    assert f.page == 1 and f.span == (0, 10) and f.extraction_version == "v1"


# S3-31B-02: low-confidence region is not turned into a fact.
def test_31b_02_low_confidence_not_fabricated() -> None:
    p = SchoolArtifactPipeline()
    res = p.process(upload_artifact_id="u2", content_hash="h2",
                    fields=[_field("teacher", "maybe-smith", 0.30),
                            _field("unreadable", None, 0.0)])
    assert SchoolArtifactPipeline.facts(res) == []              # nothing confident
    assert len(SchoolArtifactPipeline.unknown_regions(res)) == 2
    assert res.work_id is None                                   # no fabricated Work
    assert all(f.state == FieldState.UNKNOWN for f in res.fields)


# duplicate artifact hash is deduped.
def test_31b_dedup_by_hash() -> None:
    p = SchoolArtifactPipeline()
    first = p.process(upload_artifact_id="u3", content_hash="dup",
                      fields=[_field("due_date", "2026-10-02", 0.9)])
    second = p.process(upload_artifact_id="u3-again", content_hash="dup",
                       fields=[_field("due_date", "2026-10-02", 0.9)])
    assert first.deduped is False and second.deduped is True
    assert second.extraction_artifact_id == first.extraction_artifact_id


# S3-31B-03: central result holds extraction refs, not replicated raw telemetry.
def test_31b_03_no_raw_telemetry_copy() -> None:
    p = SchoolArtifactPipeline()
    res = p.process(upload_artifact_id="u4", content_hash="h4",
                    fields=[_field("due_date", "2026-10-03", 0.9)])
    # result carries hashes/refs/fields — not the raw document bytes
    assert not hasattr(res, "raw_bytes")
    assert res.content_hash == "h4"

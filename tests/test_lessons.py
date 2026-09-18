from all_tomorrow.lessons import Lesson, LessonCatalog, LessonStatus


def test_bootstrap_only_selects_accepted_cross_project_lessons() -> None:
    catalog = LessonCatalog()
    catalog.add(
        Lesson(
            project_id="project:eve",
            title="Keep source-owned state modular",
            body="Do not duplicate canonical state in prompts.",
            tags=frozenset({"memory", "architecture"}),
            evidence_refs=("event:1",),
            status=LessonStatus.ACCEPTED,
        )
    )
    catalog.add(
        Lesson(
            project_id="project:game",
            title="Unverified idea",
            body="Not accepted yet.",
            tags=frozenset({"architecture"}),
            evidence_refs=("event:2",),
        )
    )
    bootstrap = catalog.bootstrap("project:new", frozenset({"architecture", "python"}))
    assert len(bootstrap.lesson_candidates) == 1
    assert bootstrap.lesson_candidates[0].lesson.title == "Keep source-owned state modular"
    assert bootstrap.lesson_candidates[0].matched_tags == frozenset({"architecture"})


def test_bootstrap_does_not_feed_project_its_own_lesson() -> None:
    catalog = LessonCatalog()
    catalog.add(
        Lesson(
            project_id="project:eve",
            title="Eve lesson",
            body="Evidence-backed.",
            tags=frozenset({"memory"}),
            evidence_refs=("event:1",),
            status=LessonStatus.ACCEPTED,
        )
    )
    assert catalog.bootstrap("project:eve", frozenset({"memory"})).lesson_candidates == ()


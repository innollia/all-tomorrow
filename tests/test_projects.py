from all_tomorrow.projects import load_projects


def test_eve_persona_name_resolves_to_maintainer_project() -> None:
    registry = load_projects("projects/catalog.yaml")
    resolution = registry.resolve("이브")
    assert resolution.project.project_id == "project:eve"
    assert "repo_edit" in resolution.project.maintainer_capabilities


def test_unknown_project_requires_user_instead_of_guessing() -> None:
    registry = load_projects("projects/catalog.yaml")
    resolution = registry.resolve(None)
    assert resolution.project is None
    assert resolution.question is not None
    assert resolution.question.required_fields == ("project_id",)


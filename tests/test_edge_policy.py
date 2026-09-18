from all_tomorrow.edge import EdgeAction, EdgeAnalysis, load_edge_policy


def test_casual_discord_message_stays_local() -> None:
    policy = load_edge_policy("edge/discord/default.yaml")
    decision = policy.decide(EdgeAnalysis(intent="casual_chat"))
    assert decision.action is EdgeAction.LOCAL_REPLY


def test_project_state_escalates_to_central_query() -> None:
    policy = load_edge_policy("edge/discord/default.yaml")
    decision = policy.decide(EdgeAnalysis(intent="task_query", needs_project_state=True))
    assert decision.action is EdgeAction.CENTRAL_QUERY


def test_canonical_mutation_beats_general_project_query() -> None:
    policy = load_edge_policy("edge/discord/default.yaml")
    decision = policy.decide(
        EdgeAnalysis(
            intent="fix_eve",
            needs_project_state=True,
            needs_canonical_mutation=True,
        )
    )
    assert decision.action is EdgeAction.PROJECT_ACTION


def test_unclassified_message_asks_instead_of_guessing() -> None:
    policy = load_edge_policy("edge/discord/default.yaml")
    decision = policy.decide(EdgeAnalysis(intent="unknown"))
    assert decision.action is EdgeAction.USER_CLARIFICATION


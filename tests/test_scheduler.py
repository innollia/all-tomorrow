from all_tomorrow.scheduler import BackgroundTaskClass, Priority, ScheduledWork, WorkQueue


def test_interactive_work_preempts_idle_work_at_claim_boundary() -> None:
    queue = WorkQueue()
    queue.enqueue(ScheduledWork(BackgroundTaskClass.RESEARCH, Priority.P6_IDLE, {}))
    queue.enqueue(ScheduledWork(BackgroundTaskClass.PROJECT_BACKGROUND, Priority.P0_USER_INTERACTIVE, {}))
    assert queue.claim().priority is Priority.P0_USER_INTERACTIVE


def test_running_low_priority_work_is_told_to_yield() -> None:
    queue = WorkQueue()
    queue.enqueue(ScheduledWork(BackgroundTaskClass.REPORT_GENERATION, Priority.P1_URGENT, {}))
    assert queue.should_yield(Priority.P5_EXPERIMENT)
    assert not queue.should_yield(Priority.P0_USER_INTERACTIVE)


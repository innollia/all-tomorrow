from all_tomorrow.overseer.runtime import trim_log


def test_trim_log_keeps_whole_tail_lines(tmp_path):
    log = tmp_path / "collect.log"
    log.write_bytes(b"".join(b"line %05d\n" % i for i in range(1000)))
    trim_log(log, max_bytes=5000, keep_bytes=1000)
    data = log.read_bytes()
    assert len(data) <= 1000
    assert data.startswith(b"line ")
    assert data.endswith(b"line 00999\n")


def test_trim_log_leaves_small_or_missing_files(tmp_path):
    log = tmp_path / "api.log"
    log.write_bytes(b"short\n")
    trim_log(log, max_bytes=5000, keep_bytes=1000)
    assert log.read_bytes() == b"short\n"
    trim_log(tmp_path / "missing.log")

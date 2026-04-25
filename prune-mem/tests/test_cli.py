from prune_mem.cli import normalize_global_root_arg


def test_normalize_global_root_arg_keeps_front_position():
    assert normalize_global_root_arg(["--root", ".tmp/demo", "report", "--emit"]) == [
        "--root",
        ".tmp/demo",
        "report",
        "--emit",
    ]


def test_normalize_global_root_arg_moves_root_before_command():
    assert normalize_global_root_arg(["report", "--root", ".tmp/demo", "--emit"]) == [
        "--root",
        ".tmp/demo",
        "report",
        "--emit",
    ]


def test_normalize_global_root_arg_is_noop_without_root():
    assert normalize_global_root_arg(["report", "--emit"]) == ["report", "--emit"]

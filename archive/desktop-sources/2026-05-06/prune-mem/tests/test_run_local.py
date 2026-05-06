from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_run_local_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_local.py"
    spec = spec_from_file_location("run_local_module", script_path)
    module = module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_args_inserts_default_root():
    module = load_run_local_module()
    args = module.build_args(["report", "--emit"])
    assert args[0] == "prune-mem"
    assert args[1] == "--root"
    assert args[3:] == ["report", "--emit"]


def test_build_args_normalizes_root_after_command():
    module = load_run_local_module()
    args = module.build_args(["report", "--root", ".tmp/demo", "--emit"])
    assert args == ["prune-mem", "--root", ".tmp/demo", "report", "--emit"]


def test_build_args_keeps_root_before_command():
    module = load_run_local_module()
    args = module.build_args(["--root", ".tmp/demo", "report", "--emit"])
    assert args == ["prune-mem", "--root", ".tmp/demo", "report", "--emit"]

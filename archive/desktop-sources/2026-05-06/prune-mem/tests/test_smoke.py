from prune_mem.smoke import run_smoke


def test_smoke_is_self_contained(tmp_path):
    assert run_smoke(str(tmp_path / "smoke")) == 0

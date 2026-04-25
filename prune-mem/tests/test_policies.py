from prune_mem.models import MemoryRecord, SourceLevel
from prune_mem.policies import PolicyConfig, admission_decision


def make_memory(*, value: str, category: str = "constraint", slot_key: str | None = None) -> MemoryRecord:
    return MemoryRecord(
        summary=value,
        value=value,
        category=category,
        source_level=SourceLevel.EXPLICIT,
        importance=0.85,
        confidence=0.92,
        stability=0.88,
        slot_key=slot_key,
        tags=["constraint"],
        turn_ids=["t1"],
    )


def test_rejects_question_like_constraint():
    decision = admission_decision(make_memory(value="图例，你看参考文献里的图有图例吗？"), PolicyConfig())
    assert decision.action == "reject"


def test_rejects_short_low_information_memory():
    decision = admission_decision(make_memory(value="扭"), PolicyConfig())
    assert decision.action == "reject"


def test_rejects_command_like_constraint():
    decision = admission_decision(make_memory(value="看看 codex-cli，我用 /resume 也没有记录"), PolicyConfig())
    assert decision.action == "reject"


def test_accepts_durable_constraint_wording():
    decision = admission_decision(make_memory(value="不要写太长的解释。"), PolicyConfig())
    assert decision.action == "accept"


def test_rejects_task_scoped_constraint():
    decision = admission_decision(
        make_memory(value="不要提前合并到主分支，也不要开始阶段2（m_sweep 和 fixed-cardinality）。"),
        PolicyConfig(),
    )
    assert decision.action == "reject"


def test_rejects_ui_task_constraint():
    decision = admission_decision(
        make_memory(value="不要把示例放到对话框里，历史记录单独做页面，增加登录注册窗口。"),
        PolicyConfig(),
    )
    assert decision.action == "reject"


def test_rejects_pasted_analysis_as_constraint():
    decision = admission_decision(
        make_memory(value="别人的分析吧：您的代码整体结构清晰、功能完整，但仍有不少优化空间。"),
        PolicyConfig(),
    )
    assert decision.action == "reject"


def test_rejects_vague_short_constraint():
    decision = admission_decision(make_memory(value="不要一起配上。"), PolicyConfig())
    assert decision.action == "reject"
    assert "vague" in decision.reason


def test_rejects_fragment_constraint():
    decision = admission_decision(make_memory(value="别是你提出的 **回流机制** 和 **晋升/降级**。"), PolicyConfig())
    assert decision.action == "reject"
    assert "fragment-like" in decision.reason


def test_accepts_general_problem_solving_preference():
    decision = admission_decision(make_memory(value="不要这么保守，要以解决问题优先。"), PolicyConfig())
    assert decision.action == "accept"


def test_rejects_followup_workflow_constraint():
    decision = admission_decision(
        make_memory(value="不要动，都不要删。整理完之后核对一下，然后开始下一步工作。"),
        PolicyConfig(),
    )
    assert decision.action == "reject"


def test_rejects_future_run_parameter_note():
    decision = admission_decision(make_memory(value="别的代码吧，后面我可能要跑100000参数"), PolicyConfig())
    assert decision.action == "reject"
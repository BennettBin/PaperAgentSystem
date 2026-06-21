import pytest
from agent_runtime.state_machine import (
    AgentState,
    AgentContext,
    StateMachine,
    StateTransition,
    VALID_TRANSITIONS,
)
from agent_runtime.nodes import (
    RequirementCheckNode,
    ClarificationNode,
    SkillSelectorNode,
    PlannerNode,
    ExecutorNode,
    VerifierNode,
    ReplannerNode,
    NodeFactory,
)
from agent_runtime.orchestrator import AgentOrchestrator
from core.domain.ids import TaskId, WorkspaceId, UserId


class TestStateMachine:
    """Test Agent state machine"""

    def test_initial_state(self):
        """Test state machine starts in INITIAL state"""
        sm = StateMachine()
        assert sm.current_state == AgentState.INITIAL
        assert len(sm.get_history()) == 1

    def test_valid_transition(self):
        """Test valid state transition"""
        sm = StateMachine()
        assert sm.transition(AgentState.REQUIREMENT_CHECK)
        assert sm.current_state == AgentState.REQUIREMENT_CHECK

    def test_invalid_transition(self):
        """Test invalid state transition"""
        sm = StateMachine()
        assert not sm.transition(AgentState.COMPLETED)
        assert sm.current_state == AgentState.INITIAL

    def test_transition_history(self):
        """Test state transition history"""
        sm = StateMachine()
        sm.transition(AgentState.REQUIREMENT_CHECK)
        sm.transition(AgentState.SKILL_SELECTING)
        history = sm.get_history()
        assert len(history) == 3
        assert history[0] == AgentState.INITIAL
        assert history[1] == AgentState.REQUIREMENT_CHECK
        assert history[2] == AgentState.SKILL_SELECTING

    def test_can_transition_check(self):
        """Test can_transition validation"""
        sm = StateMachine()
        assert sm.can_transition(AgentState.REQUIREMENT_CHECK)
        assert not sm.can_transition(AgentState.COMPLETED)

    def test_valid_transitions_defined(self):
        """Test that valid transitions are properly defined"""
        assert len(VALID_TRANSITIONS) > 0
        assert any(
            t.from_state == AgentState.INITIAL and t.to_state == AgentState.REQUIREMENT_CHECK
            for t in VALID_TRANSITIONS
        )


class TestAgentContext:
    """Test Agent context"""

    def test_context_creation(self):
        """Test context initialization"""
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze the paper",
        )
        assert context.task_id == "task-1"
        assert context.clarifications == {}
        assert context.selected_skills == []
        assert context.traces == []

    def test_context_updates(self):
        """Test context updates"""
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze the paper",
        )
        context.selected_skills = ["paper_reader"]
        context.clarifications = {"q1": "a1"}
        assert "paper_reader" in context.selected_skills
        assert "q1" in context.clarifications


@pytest.mark.asyncio
class TestNodes:
    """Test agent runtime nodes"""

    async def test_requirement_check_node(self):
        """Test RequirementCheckNode execution"""
        node = RequirementCheckNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze this paper",
        )
        result = await node.execute(context)
        assert len(result.traces) > 0
        assert result.traces[0]["node"] == "requirement_check"

    async def test_clarification_node(self):
        """Test ClarificationNode execution"""
        node = ClarificationNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze",
        )
        result = await node.execute(context)
        assert len(result.traces) > 0
        assert result.traces[0]["node"] == "clarification"

    async def test_skill_selector_node(self):
        """Test SkillSelectorNode execution"""
        node = SkillSelectorNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze the paper",
        )
        result = await node.execute(context)
        assert len(result.selected_skills) > 0

    async def test_planner_node(self):
        """Test PlannerNode execution"""
        node = PlannerNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze the paper",
            selected_skills=["paper_reader"],
        )
        result = await node.execute(context)
        assert result.plan != {}
        assert "steps" in result.plan

    async def test_executor_node(self):
        """Test ExecutorNode execution"""
        node = ExecutorNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze the paper",
            plan={"steps": [{"step": 1, "action": "parse"}]},
        )
        result = await node.execute(context)
        assert result.execution_result.get("status") == "success"

    async def test_verifier_node(self):
        """Test VerifierNode execution"""
        node = VerifierNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze the paper",
            execution_result={"status": "success"},
        )
        result = await node.execute(context)
        assert len(result.traces) > 0

    async def test_replanner_node(self):
        """Test ReplannerNode execution"""
        node = ReplannerNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Analyze the paper",
        )
        result = await node.execute(context)
        assert len(result.traces) > 0


class TestNodeFactory:
    """Test node factory"""

    def test_get_requirement_check_node(self):
        """Test getting requirement check node"""
        node = NodeFactory.get_node(AgentState.REQUIREMENT_CHECK)
        assert isinstance(node, RequirementCheckNode)

    def test_get_planner_node(self):
        """Test getting planner node"""
        node = NodeFactory.get_node(AgentState.PLANNING)
        assert isinstance(node, PlannerNode)

    def test_get_none_for_terminal_state(self):
        """Test getting node for terminal state"""
        node = NodeFactory.get_node(AgentState.COMPLETED)
        assert node is None


@pytest.mark.asyncio
class TestAgentOrchestrator:
    """Test Agent orchestrator"""

    async def test_orchestrator_initialization(self):
        """Test orchestrator initialization"""
        orchestrator = AgentOrchestrator()
        context = await orchestrator.initialize(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            requirement="Analyze the paper",
        )
        assert context.task_id == "task-1"
        assert context.user_requirement == "Analyze the paper"

    async def test_orchestrator_state_transitions(self):
        """Test orchestrator state transitions"""
        orchestrator = AgentOrchestrator()
        await orchestrator.initialize(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            requirement="Analyze this paper for key findings",
        )
        assert orchestrator.get_current_state() == AgentState.INITIAL

    async def test_orchestrator_full_run(self):
        """Test orchestrator full run"""
        orchestrator = AgentOrchestrator()
        await orchestrator.initialize(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            requirement="Analyze this paper for key findings",
        )
        result = await orchestrator.run()
        assert result["state"] in [AgentState.COMPLETED.value, AgentState.FAILED.value]
        assert result["iterations"] > 0
        assert result["context"] is not None

    async def test_orchestrator_context_preservation(self):
        """Test that context is preserved through execution"""
        orchestrator = AgentOrchestrator()
        await orchestrator.initialize(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            requirement="Analyze the paper",
        )
        context = orchestrator.get_context()
        assert context is not None
        assert context.user_requirement == "Analyze the paper"
        assert len(context.traces) == 0

    async def test_node_next_state_logic(self):
        """Test node transition logic"""
        node = RequirementCheckNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Long enough requirement to not need clarification",
        )
        next_state = node.get_next_state(context)
        assert next_state == AgentState.SKILL_SELECTING

    async def test_node_short_requirement_needs_clarification(self):
        """Test that short requirement triggers clarification"""
        node = RequirementCheckNode()
        context = AgentContext(
            task_id="task-1",
            workspace_id="ws-1",
            user_id="user-1",
            user_requirement="Short",
        )
        next_state = node.get_next_state(context)
        assert next_state == AgentState.CLARIFYING

"""
Agent runtime state machine definition
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class AgentState(Enum):
    """Agent execution states"""
    INITIAL = "initial"
    REQUIREMENT_CHECK = "requirement_check"
    CLARIFYING = "clarifying"
    SKILL_SELECTING = "skill_selecting"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentContext:
    """Context for agent execution"""
    task_id: str
    workspace_id: str
    user_id: str
    user_requirement: str
    clarifications: dict = field(default_factory=dict)
    selected_skills: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    execution_result: dict = field(default_factory=dict)
    traces: list = field(default_factory=list)


@dataclass
class StateTransition:
    """State transition definition"""
    from_state: AgentState
    to_state: AgentState
    condition: Optional[str] = None
    action: Optional[str] = None


# Valid state transitions
VALID_TRANSITIONS = [
    StateTransition(AgentState.INITIAL, AgentState.REQUIREMENT_CHECK),
    StateTransition(AgentState.REQUIREMENT_CHECK, AgentState.CLARIFYING, condition="needs_clarification"),
    StateTransition(AgentState.REQUIREMENT_CHECK, AgentState.SKILL_SELECTING, condition="requirement_complete"),
    StateTransition(AgentState.CLARIFYING, AgentState.SKILL_SELECTING),
    StateTransition(AgentState.SKILL_SELECTING, AgentState.PLANNING),
    StateTransition(AgentState.PLANNING, AgentState.EXECUTING),
    StateTransition(AgentState.EXECUTING, AgentState.VERIFYING),
    StateTransition(AgentState.VERIFYING, AgentState.REPLANNING, condition="verification_failed"),
    StateTransition(AgentState.VERIFYING, AgentState.COMPLETED, condition="verification_passed"),
    StateTransition(AgentState.REPLANNING, AgentState.PLANNING),
    StateTransition(AgentState.INITIAL, AgentState.CANCELLED),
    StateTransition(AgentState.REQUIREMENT_CHECK, AgentState.CANCELLED),
    StateTransition(AgentState.EXECUTING, AgentState.FAILED),
    StateTransition(AgentState.PLANNING, AgentState.FAILED),
]


class StateMachine:
    """Agent state machine"""
    
    def __init__(self, initial_state: AgentState = AgentState.INITIAL):
        self.current_state = initial_state
        self.state_history = [initial_state]
    
    def can_transition(self, to_state: AgentState) -> bool:
        """Check if transition is valid"""
        for transition in VALID_TRANSITIONS:
            if transition.from_state == self.current_state and transition.to_state == to_state:
                return True
        return False
    
    def transition(self, to_state: AgentState) -> bool:
        """Transition to new state"""
        if not self.can_transition(to_state):
            return False
        self.current_state = to_state
        self.state_history.append(to_state)
        return True
    
    def get_history(self) -> list:
        """Get state history"""
        return self.state_history

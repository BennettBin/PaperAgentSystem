"""
Agent runtime orchestrator
"""

from typing import Optional
from agent_runtime.state_machine import StateMachine, AgentState, AgentContext
from agent_runtime.nodes import NodeFactory


class AgentOrchestrator:
    """Main orchestrator for agent execution"""
    
    def __init__(self):
        self.state_machine = StateMachine()
        self.context: Optional[AgentContext] = None
    
    async def initialize(
        self,
        task_id: str,
        workspace_id: str,
        user_id: str,
        requirement: str,
    ) -> AgentContext:
        """Initialize agent with task"""
        self.context = AgentContext(
            task_id=task_id,
            workspace_id=workspace_id,
            user_id=user_id,
            user_requirement=requirement,
        )
        return self.context
    
    async def execute_state(self) -> bool:
        """Execute current state node"""
        if self.context is None:
            return False
        
        current_state = self.state_machine.current_state
        
        # Skip terminal states
        if current_state in [AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED]:
            return False
        
        # Get node for current state
        node = NodeFactory.get_node(current_state)
        if node is None:
            return False
        
        # Execute node
        self.context = await node.execute(self.context)
        
        # Transition to next state
        next_state = node.get_next_state(self.context)
        if not self.state_machine.transition(next_state):
            return False
        
        return True
    
    async def run(self, max_iterations: int = 20) -> dict:
        """Run agent to completion"""
        iterations = 0
        
        while iterations < max_iterations:
            # Start from initial state
            if self.state_machine.current_state == AgentState.INITIAL:
                self.state_machine.transition(AgentState.REQUIREMENT_CHECK)
            
            # Execute current state
            success = await self.execute_state()
            if not success:
                break
            
            iterations += 1
        
        return {
            "state": self.state_machine.current_state.value,
            "iterations": iterations,
            "context": self.context,
        }
    
    def get_current_state(self) -> AgentState:
        """Get current state"""
        return self.state_machine.current_state
    
    def get_context(self) -> Optional[AgentContext]:
        """Get current context"""
        return self.context

from pydantic import BaseModel, EmailStr, Field, AliasChoices
from typing import Optional, List, Dict, Any

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    
class ChatResponse(BaseModel):
    action: str="INITIATE_CHAT"
    payload: str
    meta: Dict[str, Any] = {}

class UserAuth(BaseModel):
    email: str
    password: str

class PlanRequest(BaseModel):
    task: str
    time_budget: int #In seconds
    mode: str="fast" #Fast is default mode, otherwise deep
    conversation_id: Optional[int] = None

class StatusUpdate(BaseModel):
    status: str

class MemoryCreate(BaseModel):
    fact_key: str
    fact_value: str
    importance: Optional[int] = 1   
    category: Optional[str] = "general"

class TaskStep(BaseModel):
    step: str
    time_allocated: int
    tool_required: str #Options: "web_search" and "code_execution" for testing 
    logic_reasoning: str #xAI turns black box AI to understandable AI

class AgentStatePlan(BaseModel):
    objective: str
    total_budget: int
    steps: List[TaskStep]
    strategy_recommendation: str

class StepApprovalRequest(BaseModel):
    step_id: str
    status: str = "approved"
    description: Optional[str] = None
    #tool_required: Optional[str] = None # Optional: if you want to allow switching tools too for future updates
    
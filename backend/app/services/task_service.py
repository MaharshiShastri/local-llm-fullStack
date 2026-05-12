import re
import json
import uuid
from sqlalchemy.orm import Session
from app.models import models


def clean_and_parse_plan(raw_text: str):
    try:
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if match:
            clean_json = match.group(0).replace("}{", "},{")
            return json.loads(clean_json)
        
        # Fallback for individual objects
        found_objects = re.findall(r'\{[^{}]*\}', raw_text, re.DOTALL)
        return [json.loads(obj) for obj in found_objects]
    except Exception:
        return []

def create_mission_and_steps(db: Session, user_id: int, task_title: str, budget: int, raw_steps: list):
    mission = models.Tasks(user_id=user_id, title=task_title[:50], total_time=budget, status="pending")
    db.add(mission)
    db.commit()
    db.refresh(mission)

    enriched_steps = []
    step_instances = []
    for idx, s in enumerate(raw_steps):
        if isinstance(s, str):
            data = {"step": s, "time_allocated": budget//6}
        elif isinstance(s, list) and len(s) > 0:
            data = s[0] if isinstance(s[0], dict) else {"step": str(s[0]), "time_allocated": 60}
        elif isinstance(s, dict):
            data = s
        else:
            data = {"step": "Unknown Step", "time_allocated": 60}
        
        b_id = f"STP-{uuid.uuid4().hex[:6].upper()}"
        desc = data.get("step") or data.get("description") or "Step details missing"
        time_val = data.get("time_allocated") or 60
        tool = data.get("tool_required", "")
        logic = data.get("logic_reasoning", "Global Common Sense")

        step_entry = models.TaskStep(
            task_id=mission.id,
            backend_step_id=b_id,
            description=desc,
            time_allocated=time_val,
            order=idx,
            status="pending",
            tool_required=tool,
            logic_reasoning=logic
        )
        step_instances.append(step_entry)
        
        enriched_steps.append({
            "backend_step_id": b_id,
            "description": desc,
            "time_allocated": time_val,
            "status": "pending",
            "tool_required": tool,
            "logic_reasoning": logic
        })
    
    db.add_all(step_instances)
    db.commit()
    return mission.id, enriched_steps

def trigger_mission_execution(db: Session, mission_id: int, budget: int, enriched_steps: list):
    from .tasks import execute_mission_task
    task = execute_mission_task.delay(mission_id, budget, enriched_steps)

    mission = db.query(models.Tasks).filter(models.Tasks.id == mission_id).first()
    if mission:
        mission.status = "queued"
        # If you add a task_id column to your Tasks model:
        # mission.celery_task_id = task.id 
        db.commit()

    return task.id
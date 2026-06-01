import asyncio
import json
import psutil
import logging
import json

from database import SessionLocal
from .celery_app import celery, r_client
from .executor import MissionExecutor
from app.services.optimizer import TimeOptimizer
from app.services.ai_service import generate_stream
from app.services import chat_service
from app.models import models
from app.services.memory_service import get_memories

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def validate_and_correct_steps(steps, total_budget):
    """Guardrail: Ensures the plan is neither too long nor too short and stays in budget."""
    if len(steps) < 5:
        while len(steps) < 5:
            steps.append({
                "step": "Additional validation and project review", 
                "time_allocated": 0,
                "tool_required": "logic"
            })
    elif len(steps) > 7:
        steps = steps[:7]
    
    for s in steps:
        if s.get("time_allocated", 0) <= 0:
            s["time_allocated"] = total_budget // len(steps)

    actual_sum = sum(step.get("time_allocated", 0) for step in steps)

    if actual_sum > total_budget:
        ratio = total_budget / actual_sum
        for s in steps:
            # max(10, ...) ensures no step is less than 10 mins
            s["time_allocated"] = max(10, int(s["time_allocated"] * ratio))

    return steps

@celery.task(name="mission.process_chat")
def process_chat_task(conversation_id, user_id, raw_message):
    db = SessionLocal()
    try:
        doc_context = ""
        try:
            from app.rag.retriever import rag_retriever

            cpu_load = psutil.cpu_percent()
            result, metrics = rag_retriever.retrieve_context(raw_message, db, load=cpu_load, total_time=50000)
       
            if result:
                metrics["system_cpu"] = cpu_load
                with open("retrieval_metricss.log", "a") as log_file:
                    log_file.write(json.dumps(metrics)+"\n")
                doc_context = f"\n--- RELEVANT DOCUMENTS ---\n" + "\n".join(result)

        except Exception as rag_err:
            logger.error(f"Celery RAG Execution Failure: {rag_err}")
        
        mission_context = ""
        active_mission = db.query(models.Tasks).filter(
            models.Tasks.user_id == user_id,
            models.Tasks.status == "pending"
        ).first()

        if active_mission:
            mission_context = f"\n[SYSTEM ALERT: The user has an active mission: '{active_mission.title}']\n"
        
        memories = get_memories(db, user_id)
        memory_context = ""
        if memories:
            memory_context = "USER FACTS:\n" + "\n".join([f"-[{m.catergory}] {m.fact_key}: {m.fact_value}" for m in memories if m.importance >= 3])
        
        history = chat_service.build_chat_history(db, conversation_id)

        final_prompt = f"{mission_context}\n{memory_context}\n{doc_context}\n{history}\nUser: {raw_message}\nAssistant:"

        redis_channel = f"chat_stream_{conversation_id}"

        for token in generate_stream(final_prompt):
            if token:
                r_client.publish(redis_channel, token)

        r_client.publish(redis_channel, "[DONE]")
    
    except Exception as task_err:
        logger.error(f"Critical Error Processing chat tasak in celery: {task_err}")
        r_client.publish(f"chat_stream_{conversation_id}", f"[ERROR] {str(task_err)}")
        r_client.publish(f"chat_stream_{conversation_id}", "[DONE]")
    
    finally:
        db.close()

    
@celery.task(name="mission.process_plan")
def process_plan_task(task_description, budget, mode, user_id):
    from app.services.ai_service import generate_plan
    from app.services.task_service import create_mission_and_steps # Local import
    from app.rag.ingestor import ingest_text, get_grounded_context
    

    try:
        context = ''
        with SessionLocal() as db:
            print("Getting context....")
            context = get_grounded_context(task_description, db, user_id)
        raw_steps = list(generate_plan(task_description, budget, mode, context))
        steps = validate_and_correct_steps(raw_steps, budget)
        with SessionLocal() as db:
            user = db.query(models.User).filter(models.User.id == user_id).first()
            if not user:
                return {"status": "error", "message": "User not found"}
            mission_id, enriched = create_mission_and_steps(db, user_id, task_description, budget, steps)
            ingest_text(db, title=f"Task {mission_id}", raw_text=task_description, user_id=user_id, source_type="task")
            result_channel = f"plan_result_{user_id}"
            payload = {
                "status": "complete",
                "mission_id": mission_id,
                "enriched_steps": enriched
            }
            print(f"Mission {mission_id} created with {len(enriched)} enriched steps.")
            print(f"Publishing plan result to Redis Channel: {result_channel}")
            r_client.publish(result_channel, json.dumps(payload))
            
        return {"status": "success", "mission_id": mission_id}
    except Exception as e:
        error_payload = {"status":"error", "message": str(e)}       
        
        r_client.publish(f"plan_result_{user_id}", json.dumps(error_payload))
        return error_payload

@celery.task(bind=True, name="mission.execute_lifecycle")
def execute_mission_task(self, mission_id, total_budget, manifest):
    """
    The background process that runs the MissionExecutor loop.
    """
    # Initialize the stateful executor
    executor = MissionExecutor(mission_id, total_budget)
    
    # Run the async loop inside the synchronous Celery worker
    return asyncio.run(run_mission_loop(self, executor, manifest, total_budget))

async def run_mission_loop(task, executor, manifest, total_budget):
    start_time = asyncio.get_event_loop().time()
    
    for i, step in enumerate(manifest):
        # 1. Update status to 'PROGRESS' for frontend polling
        task.update_state(state='PROGRESS', meta={
            'event': 'STEP_STARTED',
            'index': i,
            'step_id': step['backend_step_id']
        })

        # 2. Check Strategy (NORMAL vs EMERGENCY)[cite: 27]
        elapsed = asyncio.get_event_loop().time() - start_time
        strategy = TimeOptimizer.get_execution_strategy(float(total_budget), float(elapsed))

        # 3. Validation & Pub/Sub Handshake
        val = await executor.validate_input(step)
        if val['status'] == "AMBIGUOUS" and strategy != "EMERGENCY":
            # Signal the UI to show an interrupt[cite: 26]
            task.update_state(state='PROGRESS', meta={
                'event': 'STRATEGIC_INTERRUPT',
                'step_id': step['backend_step_id'],
                'reason': val['reason']
            })
            # PAUSE: Wait for Redis Pub/Sub signal from router_logic.py
            await executor.wait_for_approval(step['backend_step_id'])

        # 4. Execution with Retries[cite: 24]
        result = await executor.run_step_with_retries(step, strategy)
        if result == "FAILED_BUT_CONTINUING":
            task.update_state(state='PROGRESS', meta={
                'event': 'STEP_FAILED',
                'index': i,
                'step_id': step['backend_step_id']
            })
        # 5. Success/Telemetry Pulse[cite: 25]
        task.update_state(state='PROGRESS', meta={
            'event': 'STEP_COMPLETED',
            'index': i,
            'latency': asyncio.get_event_loop().time() - start_time
        })

    return {"status": "SUCCESS", "mission_id": executor.mission_id}
import asyncio
import json

from database import SessionLocal
from .celery_app import celery, r_client
from .executor import MissionExecutor
from app.services.optimizer import TimeOptimizer
from app.services.ai_service import generate_stream
from app.services.chat_service import save_message

@celery.task(name="mission.process_chat")
def process_chat_task(conversation_id, prompt):
    full_response = ""
    token_channel = f"chat_stream_{conversation_id}"
    print(f"Streaming on Redis channel: {token_channel}")
    try:
        for token in generate_stream(prompt):
            full_response += token
            #Publish the token to redis
            r_client.publish(token_channel, token)
        #Done signal            
        r_client.publish(token_channel, "[DONE]")
        
        with SessionLocal() as db:
            save_message(db, conversation_id, "AI", full_response)
        
        return full_response
    except Exception as e:
        print(f"Error in tasks.py: {str(e)}")
        return {"status": "error", "message": str(e)}
    
@celery.task(name="mission.process_plan")
def process_plan_task(task_description, budget, mode, user_id, context):
    from app.services.ai_service import generate_plan
    from app.services.task_service import create_mission_and_steps # Local import
    from app.rag.ingestor import ingest_text
    from app.models import models
    try:
        raw_steps = generate_plan(task_description, budget, mode, context)
        
        with SessionLocal() as db:
            user = db.query(models.User).filter(models.User.id == user_id).first()
            if not user:
                return {"status": "error", "message": "User not found"}
            mission_id, enriched = create_mission_and_steps(db, user_id, task_description, budget, raw_steps)
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
        
        # 5. Success/Telemetry Pulse[cite: 25]
        task.update_state(state='PROGRESS', meta={
            'event': 'STEP_COMPLETED',
            'index': i,
            'latency': asyncio.get_event_loop().time() - start_time
        })

    return {"status": "SUCCESS", "mission_id": executor.mission_id}
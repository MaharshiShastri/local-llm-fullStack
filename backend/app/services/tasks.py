import asyncio
from .celery_app import celery
from .executor import MissionExecutor
from app.services.optimizer import TimeOptimizer

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
import asyncio
import time
import logging
from app.services.browser_agent import browser_agent
from app.services.code_executor import executor
import redis
import os
import json

logger = logging.getLogger(__name__)

class MissionExecutor:
    def __init__(self, mission_id, total_budget):
        self.mission_id = mission_id
        self.total_budget = total_budget
        self.step_context = {}
        self.metrics = {"interrupts": 0, "retries": 0}
        self.redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    async def validate_input(self, step):
        tool = step.get('tool_required')
        desc = step.get('description', '')

        if tool == 'web_search' and len(desc) < 10:
            return {"status": "AMBIGUOUS", "reason": "Search query too short"}
        
        return {"status": "CLEAR"}
    
    async def wait_for_approval(self, step_id):
        pubsub = self.redis_client.pubsub()
        channel = f"mission_control_{self.mission_id}"
        pubsub.subscribe(channel)
        
        logger.info(f"Step {step_id} suspended. Waiting for signal on {channel}...")
        
        while True:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message['data'].decode('utf-8') == "RESUME":
                logger.info(f"Resume signal received for mission {self.mission_id}")
                break
            await asyncio.sleep(1)
        pubsub.unsubscribe(channel)
        
    async def perform_task(self, tool, step_data):
        try:
            if tool == "web_search":
                tool_output = await browser_agent.search_and_summarize(step_data)
            elif tool == "code_execution":
                tool_output = await executor.execute_python(step_data)
            else:
                tool_output = "Unidentifiable tool"
            
        except Exception as e:
            tool_output = f"Tool Error ({tool}): {str(e)}"

        finally:
            return tool_output

    async def run_step_with_retries(self, step, strategy, max_retries=2):
        step_id = step['backend_step_id']
        tool = step.get('tool_required', 'logic')
        start_time = time.time()
        
        for attempt in range(max_retries + 1):
            try:
                payload = {"instruction": step["description"], "context": self.step_context}
                result = await self.perform_task(tool, payload)
                
                # Check for tool-specific errors to trigger a retry
                if "Error" in str(result) or "Timeout" in str(result):
                    raise Exception(f"Tool {tool} returned an error signal.")

                # Success Telemetry: You could log success latency here if needed
                self.step_context[step_id] = result
                return result

            except Exception as e:
                self.metrics["retries"] += 1
                
                # Log the failure to your existing failure.log via classify_failure
                failure_entry = {
                    "error": {
                        "code": "ERR_OLLAMA_TIMEOUT", 
                        "severity": "HIGH", 
                        "retry": True
                    } if "Timeout" in str(e) else {
                        "code": "ERR_SYS_EXHAUSTED", 
                        "severity": "CRITICAL", 
                        "retry": True
                    },
                    "detail": f"Step {step_id} - Attempt {attempt+1}: {str(e)}",
                    "timestamp": time.time()
                }

                try:
                    with open("failure.log", "a") as f:
                        f.write(json.dumps(failure_entry) + "\n")
                
                except Exception as log_err:
                    logger.error(f"Failed to write to failure.log: {log_err}")
                
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(f"Retrying {step_id} in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    # Final Fallback: Mark as partial failure and move on
                    logger.error(f"Step {step_id} failed after {max_retries} retries.")
                    self.step_context[step_id] = "EXHAUSTED_RETRIES_PARTIAL_DATA"
                    return "FAILED_BUT_CONTINUING"
        
        # Graceful Degradation (Task 3)
        self.step_context[step_id] = "Partial success: Step failed after retries."
        return "FAILED_BUT_CONTINUING"

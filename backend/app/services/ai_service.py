import requests
import json
import subprocess
import time
import os
import logging
import re
import traceback

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.2:1b"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def ollama_running():
    try:
        requests.get("http://localhost:11434/", timeout=2)
    except requests.exceptions.ConnectionError:
        print("Ollama is not running. Starting server...")
        try:
            print("Starting Ollama with GPU Discovery...")
            subprocess.Popen(["ollama",  "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(5)
        
        except FileNotFoundError:
            print("Error: 'ollama' command not found. Please install ollama")

ollama_running() #To initialize ollama server on its own

def verify_grounding(output: str, context: str) -> float:
    if not context: return 1.0

    out_words = set(re.findall(r'\w+', output.lower()))
    ctx_words = set(re.findall(r'\w+', context.lower()))

    overlap = out_words.intersection(ctx_words)

    return len(overlap) / max(len(out_words), 1)


def get_strategy_time(total_time):
    if total_time < 300:
        return "COMPRESSED_MODE: Combine tasks, skip deep verification, prioritize speed."
    elif total_time > 3600:
        return "DEEP_REASONING: Add validation sub-steps, perform exhaustive search, prioritize accuracy."
    return "BALANCED_MODE: Output a clear plan with some validation, but keep it concise and actionable."

def generate_response(prompt):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False
            },
            timeout=180
        )
        
        
        if response.status_code == 200:
            result = response.json()
            return {
                "success": True,
                "data": result.get("response", ""),
                "error": None
            }
        
        return {"success": False, "data": None, "error": f"API_STATUS_{response.status_code}"}

    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {e}")
        return {"success": False, "data": None, "error": "REQUEST_TIMEOUT"}

def generate_plan(task: str, total_time: int, mode: str, context: str=""):
    # Prompt optimized to force a clear, repeatable structure
    prompt = f"""[INST] <<SYS>>
You are the CHRONOS_ARCHITECT. Your goal is to decompose a MISSION_OBJECTIVE into a sequence of 5-7 actionable steps while assigning the most efficient tool for each.
AVAILABLE TOOLS:
- "web_search": Use for current data, market trends, or external facts.
- "code_execution": Use for math, data analysis, or complex logic.
TIME CONSTRAINTS:
- Current Budget: {total_time}s.
- Strategy Window: {get_strategy_time(total_time)}.
- If Time < 10% of budget: Force immediate "complete".
STRICT JSON OUTPUT ONLY:
{{
  "objective": "{task}",
  "total_budget": {total_time},
  "steps": [
    {{
      "step": "Detailed description of action",
      "time_allocated": integer,
      "tool_required": "web_search|code_execution|rag_retrieval|chat",
      "logic_reasoning": "Explanation for tool choice"
    }}
  ],
  "strategy_recommendation": "Summary of execution approach"
}}
Sum of time_allocated must be {total_time}s only. No prose.
<</SYS>>
MISSION_OBJECTIVE: "{task}"
TOTAL_TEMPORAL_BUDGET: {total_time}
MODE: {mode}
GENERATE_SEQUENCE_NOW: [/INST]"""

    try:
        start_request = time.perf_counter()
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "format": "json", 
                "stream": False 
            },
            timeout=1800
        )
        if(time.perf_counter() - start_request) > 60:
            logger.warning("LLM response exceeded SLA performance window.")
                    

        result = response.json()
        content = result.get("response", "")
        print(f"--- [DEBUG] FULL RAW CONTENT ---\n{content}\n---")

        # 1. PRIMARY STRATEGY: REGEX EXTRACTION
        # This prevents the "overwriting keys" bug by finding every {} block individually
        # It looks for anything that looks like a step object.
        step_pattern = r'\{[^{}]*"step":\s*".*?"[^{}]*"time_allocated":\s*\d+[^{}]*\}'
        matches = re.findall(step_pattern, content, re.DOTALL)

        if matches:
            valid_steps = []
            print(f"--- [DEBUG] REGEX FOUND {len(matches)} STEPS ---")
            for m in matches:
                try:
                    step_obj = json.loads(m)
                    if context:
                        overlap_check = set(step_obj['step'].lower().split()) & set(context.lower().split())
                        if len(overlap_check) < 2:
                            yield {
                                "step" : step_obj['step'],
                                "time_allocated" : step_obj['time_allocated'],
                                "warning" : "LOW_GROUNDING",
                                "reason" : "Step details not found in provided documents."
                            }
                            continue
                        
                    valid_steps.append(step_obj)
                    yield step_obj
                except json.JSONDecodeError:
                    traceback.print_exc()
                    continue
            total_allocated = sum(s.get("time_allocated", 0) for s in valid_steps)
            if abs(total_allocated - total_time) > (total_time * 0.1):
                print(f"BUDGET_ALARM: Total {total_allocated} vs Expected {total_time}")
                {"code": "ERR_TEMPORAL_MISMATCH", "severity": "LOW"}
            return # Exit if regex successfully handled it

        # 2. SECONDARY STRATEGY: STANDARD JSON LOAD
        # (Fallback if the AI actually followed the "steps": [] format perfectly)
        try:
            data = json.loads(content)
            print(f"--- [DEBUG] RAW JSON DATA: {data} ---")
            
            # If it's a dict, try to find the list inside
            if isinstance(data, dict):
                steps_list = data.get("steps") or next((v for v in data.values() if isinstance(v, list)), None)
                if steps_list:
                    for s in steps_list:
                        yield s
                    return
                else:
                    # If it's just a single dict and not a list
                    yield data
                    return
            
            # If it's a direct list
            if isinstance(data, list):
                for s in data:
                    yield s
                return

        except json.JSONDecodeError as je:
            traceback.print_exc()
            print(f"--- [DEBUG] JSON PARSE FAILED: {je} ---")
            yield {"error": "Failed to parse plan structure"}

    except Exception as e:
        traceback.print_exc()
        print(f"--- [DEBUG] CRITICAL ERROR: {str(e)} ---")
        yield {"error": str(e)}

def generate_stream(prompt: str):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": True
            },
            timeout=1800,
            stream=True
        )
        # Check for HTTP errors immediately
        response.raise_for_status()

        for line in response.iter_lines(decode_unicode=True):
            if line:
                try:
                    data = json.loads(line)
                    token = data.get("response", "")
                    
                    # ONLY yield if there is actual content
                    if token:
                        #print(repr(token)) # Debugging
                        yield token

                    if data.get("done"):
                        return

                except json.JSONDecodeError:
                    print(f"Skipping malformed line: {line}")
                    continue
                    
    except Exception as e:
        print("STREAM ERROR:", str(e))
        yield f"[ERROR: {str(e)}]"
import os
import json
import logging
import re
import traceback
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY = "insert_key_here_as_string"
MODEL_NAME = "llama-3.1-8b-instant"
client = Groq(api_key=GROQ_API_KEY)



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
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, # Lower for more consistent responses
            stream=False
        )
        return {
            "success": True,
            "data": completion.choices[0].message.content,
            "error": None
        }
    except Exception as e:
        logger.error(f"Groq Request failed: {e}")
        return {"success": False, "data": None, "error": str(e)}

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
        # Groq supports JSON mode for structured output like your plan
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2 # Very low for structural reliability
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        
        # Generator for steps to maintain your existing logic
        steps = data.get("steps", [])
        for s in steps:
            yield s

    except Exception as e:
        logger.error(f"Plan Generation Failed: {e}")
        yield {"error": str(e)}

def generate_stream(prompt: str):
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )

        for chunk in completion:
            token = chunk.choices[0].delta.content
            if token:
                yield token
                    
    except Exception as e:
        logger.error(f"STREAM ERROR: {e}")
        yield f"[ERROR: {str(e)}]"
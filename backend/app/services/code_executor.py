import sys
import io
import contextlib
import logging

logger = logging.getLogger(__name__)

class CodeExecutor:
    def execute_python(self, code: str):
        # 1. Restricted Global Environment
        safe_locals = {}
        safe_globals = {
            "__builtins__": {
                "print": print, "range": range, "len": len, "int": int, "float": float,
                "list": list, "dict": dict, "sum": sum, "max": max, "min": min
            }
        }
        
        stdout = io.StringIO()
        try:
            # 2. Timeout protection would ideally happen via multiprocessing, 
            # but for now, we use restricted builtins
            with contextlib.redirect_stdout(stdout):
                exec(code, safe_globals, safe_locals)
            return stdout.getvalue()
        except Exception as e:
            return f"Runtime Error: {str(e)}"
        
executor = CodeExecutor()
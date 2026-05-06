class TimeOptimizer:
    @staticmethod
    def get_execution_strategy(total_budget: float, elapsed_time: float) -> str:
        if total_budget <= 0: return "EMERGENCY"
        percent_used = (elapsed_time / total_budget) if total_budget > 0 else 1.0

        if percent_used > 0.9:  return 'EMERGENCY'
        if percent_used > 0.7:  return 'CRITICAL'
        return "NORMAL"
    
    @staticmethod
    def rebalance_manifest(manifest: list, current_index: int, total_budget: float, elapsed_time: float):
        remaining_budget = total_budget - elapsed_time
        remaining_steps = manifest[current_index+1:]

        if not remaining_budget:
            return manifest
        
        current_planned_remaining = sum(s['time_allocated'] for s in remaining_steps)

        if remaining_budget < current_planned_remaining:
            ratio = max(0.1, remaining_budget / current_planned_remaining)

            for step in remaining_steps:
                step['time_allocated'] = max(5, int(step['time_allocated'] * ratio))

        return manifest
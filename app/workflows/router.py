from __future__ import annotations
from typing import Dict, List

"""
Router 骨架：当前仅返回固定多源流程计划（兜底）。
后续将加入：意图分类、步骤门控、预算控制与降级策略。
保持与现有前端/SSE 兼容，不改业务调用。
"""

FIXED_PLAN_STEPS: List[str] = [
    "generate_queries",
    "search",
    "analyze_papers",
    "analyze_trials",
    "generate_final",
]

def make_plan(user_query: str, context: Dict | None = None) -> Dict:
    """返回执行计划（当前固定计划）。

    Returns:
        {
          "steps": ["generate_queries", ...],
          "why": ["fallback_fixed"],
          "fallback": "fixed_multi_source"
        }
    """
    return {
        "steps": FIXED_PLAN_STEPS.copy(),
        "why": ["fallback_fixed"],
        "fallback": "fixed_multi_source",
    }

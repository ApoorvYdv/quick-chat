"""Structured case lookup by case number (re-export; the query lives with retrieval)."""

from quick_chat_api.modules.embedding.retrieval import get_cases_by_number

__all__ = ["get_cases_by_number"]

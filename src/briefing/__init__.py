"""PR briefing generation with senior-engineer-voice prompts and structured output."""
from src.briefing.generator import Briefing, generate_briefing
from src.briefing.prompt_templates import SYSTEM_PROMPT

__all__ = ["Briefing", "generate_briefing", "SYSTEM_PROMPT"]

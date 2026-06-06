"""NLP module for NutriAdvisor."""

from .cache import IntentCache
from .intent_engine import IntentEngine, load_default_training_examples
from .prompts import GEMINI_SYSTEM_PROMPT, build_user_prompt, VALID_INTENTS
from .schemas import NLPResult, ProfileUpdates, ReplacementTarget, TrainingExample

__all__ = [
    "IntentCache",
    "IntentEngine",
    "load_default_training_examples",
    "GEMINI_SYSTEM_PROMPT",
    "build_user_prompt",
    "VALID_INTENTS",
    "NLPResult",
    "ProfileUpdates",
    "ReplacementTarget",
    "TrainingExample",
]

"""The pinned model ids every eval stage uses, in one place.

The exact id or snapshot behind ``JUDGE_MODEL`` and ``PHRASER_MODEL`` is pinned from the
provider's reported ``response.model`` at run time and recorded in the manifest, so a
silent provider-side change shows up as a difference there rather than going unnoticed.
"""

from app.services.decisions.openrouter import JEV_MODEL
from app.services.retrieval.rerank.cohere import COHERE_MODEL as COHERE_RERANK_MODEL

GENERATOR_MODEL = "deepseek-flash"
JUDGE_MODEL = "anthropic/claude-haiku-5.5"
PHRASER_MODEL = JUDGE_MODEL

__all__ = [
    "COHERE_RERANK_MODEL",
    "GENERATOR_MODEL",
    "JEV_MODEL",
    "JUDGE_MODEL",
    "PHRASER_MODEL",
]

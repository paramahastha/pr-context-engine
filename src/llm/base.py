"""Abstract LLM provider contract — the single interface all providers implement."""
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Provider-agnostic LLM interface. One method; no provider types leak out."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Return the model's text completion for the given prompt."""
        ...

"""One small client for any OpenAI-compatible server (Ollama, vLLM, ...)."""
import os
import time
from dataclasses import dataclass, field

from openai import OpenAI

BASE_URL = os.environ.get("BASE_URL", "http://localhost:11434/v1")
API_KEY = os.environ.get("API_KEY", "ollama")


@dataclass
class Budget:
    """Hard cap on model calls per task, so a runaway search cannot burn the demo."""
    max_calls: int = 60
    calls: int = 0
    gen_tokens: int = 0
    prompt_tokens: int = 0
    seconds: float = 0.0
    log: list = field(default_factory=list)

    @property
    def left(self) -> int:
        return self.max_calls - self.calls

    def spend(self, seconds: float, gen: float, prompt: float) -> None:
        self.calls += 1
        self.seconds += seconds
        self.gen_tokens += gen
        self.prompt_tokens += prompt


class LLM:
    def __init__(self, model: str, budget: Budget):
        self.model = model
        self.budget = budget
        self.client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=180)

    def __call__(self, prompt: str, system: str = "", temperature: float = 0.7,
                 max_tokens: int = 400, stop: tuple = ()) -> str:
        if self.budget.left <= 0:
            raise RuntimeError("call budget exhausted")
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        t0 = time.time()
        r = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, stop=list(stop) or None)
        dt = time.time() - t0
        u = r.usage
        self.budget.spend(dt, getattr(u, "completion_tokens", 0) or 0,
                          getattr(u, "prompt_tokens", 0) or 0)
        return r.choices[0].message.content or ""

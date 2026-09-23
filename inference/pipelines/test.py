import os

from dotenv import load_dotenv
from openai import OpenAI


class Test:
    """Small text-generation pipeline backed by NVIDIA NIM."""

    def __init__(self):
        load_dotenv()
        key = os.getenv("NVIDIA_API_KEY")
        if not key:
            raise RuntimeError("NVIDIA_API_KEY is missing")
        self.client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key)
        self.model = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")

    def infer(self, request):
        prompt = request.get("prompt") or request.get("input")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("request needs a non-empty 'prompt' (or 'input')")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=request.get("temperature", 0.2),
            max_tokens=request.get("max_tokens", 300),
        )
        return {"text": response.choices[0].message.content}

"""Minimal client for a local Ollama instance."""
import json

import requests


class OllamaClient:
    def __init__(self, host: str, model: str, timeout: int = 60):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate_json(self, prompt: str):
        """Call Ollama and parse a JSON object out of the response.

        Returns None if the model didn't return valid JSON after one retry.
        """
        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1},
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "").strip()
                return json.loads(raw)
            except (requests.RequestException, json.JSONDecodeError, ValueError):
                if attempt == 0:
                    continue
                return None
        return None

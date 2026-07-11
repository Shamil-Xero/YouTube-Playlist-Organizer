"""Minimal client for a local LM Studio server (OpenAI-compatible API).

Requires LM Studio's local server to be running: Developer tab -> Start
Server, or `lms server start` from the CLI. Default base URL is
http://localhost:1234.
"""
import json

import requests


class LMStudioClient:
    def __init__(self, host: str, model: str = "", timeout: int = 60, api_key: str = "lm-studio"):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self._resolved_model = model or None

    def _headers(self):
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

    def resolve_model(self) -> str:
        """Returns the configured model, or auto-detects whichever model is
        currently loaded in LM Studio if none was set in config.yaml."""
        if self._resolved_model:
            return self._resolved_model

        resp = requests.get(f"{self.host}/v1/models", headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        if not models:
            raise RuntimeError(
                "No model is loaded in LM Studio. Load one in the app (or run "
                "`lms load <model>`), or set 'model' explicitly in config.yaml."
            )
        self._resolved_model = models[0]["id"]
        return self._resolved_model

    def generate_json(self, prompt: str, schema: dict, schema_name: str = "response"):
        """Call LM Studio's chat completions endpoint with a JSON schema and
        return the parsed object. Returns None on failure after one retry."""
        model = self.resolve_model()
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{self.host}/v1/chat/completions",
                    headers=self._headers(),
                    json=body,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
                raw = msg.get("content") or msg.get("reasoning_content") or ""
                return json.loads(raw)
            except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError, ValueError):
                if attempt == 0:
                    continue
                return None
        return None

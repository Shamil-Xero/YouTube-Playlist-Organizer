"""Simple JSON-backed record of videos already processed, so re-runs don't
redo work, re-spend API quota, or duplicate playlist moves."""
import json
import os


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)

    def is_done(self, video_id: str) -> bool:
        return video_id in self.data

    def mark_done(self, video_id: str, category: str, note: str = ""):
        self.data[video_id] = {"category": category, "note": note}
        self._save()

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

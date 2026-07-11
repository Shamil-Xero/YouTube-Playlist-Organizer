"""Thin wrapper around the YouTube Data API v3 calls this tool needs."""


class YouTubeClient:
    def __init__(self, service):
        self.svc = service

    def get_playlist_items(self, playlist_id: str):
        """Return list of dicts: video_id, title, playlist_item_id."""
        items = []
        page_token = None
        while True:
            resp = self.svc.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            ).execute()
            for it in resp.get("items", []):
                items.append({
                    "video_id": it["contentDetails"]["videoId"],
                    "title": it["snippet"]["title"],
                    "playlist_item_id": it["id"],
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return items

    def get_video_details(self, video_ids: list) -> dict:
        """Batch-fetch snippet details for up to 50 IDs per call."""
        details = {}
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            resp = self.svc.videos().list(
                part="snippet,contentDetails",
                id=",".join(chunk),
            ).execute()
            for it in resp.get("items", []):
                sn = it["snippet"]
                cd = it.get("contentDetails", {})
                details[it["id"]] = {
                    "title": sn.get("title", ""),
                    "description": sn.get("description", ""),
                    "tags": sn.get("tags", []),
                    "channel": sn.get("channelTitle", ""),
                    "category_id": sn.get("categoryId", ""),
                    "duration": cd.get("duration", ""),
                }
        return details

    def find_playlist_by_name(self, name: str):
        page_token = None
        while True:
            resp = self.svc.playlists().list(
                part="snippet", mine=True, maxResults=50, pageToken=page_token
            ).execute()
            for it in resp.get("items", []):
                if it["snippet"]["title"].strip().lower() == name.strip().lower():
                    return it["id"]
            page_token = resp.get("nextPageToken")
            if not page_token:
                return None

    def create_playlist(self, name: str, description: str = ""):
        resp = self.svc.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": name, "description": description},
                "status": {"privacyStatus": "private"},
            },
        ).execute()
        return resp["id"]

    def get_or_create_playlist(self, name: str, description: str = ""):
        existing = self.find_playlist_by_name(name)
        if existing:
            return existing
        return self.create_playlist(name, description)

    def add_video_to_playlist(self, playlist_id: str, video_id: str):
        return self.svc.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()

    def remove_playlist_item(self, playlist_item_id: str):
        self.svc.playlistItems().delete(id=playlist_item_id).execute()

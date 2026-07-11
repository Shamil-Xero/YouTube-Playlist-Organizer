"""Handles OAuth2 authentication for the YouTube Data API.

First run opens a browser for you to grant access; after that, the
refresh token is cached in token_file so you won't be prompted again.
"""
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# "youtube" (not "youtube.readonly") is required because this tool
# creates playlists and adds/removes items, not just reads data.
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def get_youtube_client(client_secret_file: str, token_file: str):
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)

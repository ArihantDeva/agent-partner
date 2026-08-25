"""Single place where the model + client mode is chosen.

Two auth modes for the google-genai SDK:
- API-key mode (default locally): GEMINI_API_KEY set -> Gemini Developer API
- Vertex mode (Cloud Run deploy): GOOGLE_CLOUD_PROJECT + USE_VERTEX=1 ->
  Vertex AI with the service's built-in identity. Same Gemini models, no key.

Hackathon requires gemini-3.5+; flip GEMINI_MODEL when credits/billing land.
"""
import os

from dotenv import load_dotenv

load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
assert MODEL.split("-")[0] == "gemini" and int(MODEL.split("-")[1].split(".")[1]) >= 5 or "flash-preview" in MODEL or MODEL >= "gemini-3.5", f"hackathon requires Gemini 3.5+, got {MODEL}"

USE_VERTEX = os.environ.get("USE_VERTEX") == "1"
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

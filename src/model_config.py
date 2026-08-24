"""Single place where the model is chosen.

Hackathon requires gemini-3.5+ ; free tier on that model is 20 req/day,
so local dev defaults to 3.6-flash. Flip GEMINI_MODEL in .env when the
$150 credits + billing land, or for final demo runs.
"""
import os
from dotenv import load_dotenv

load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
assert MODEL.split("-")[0] == "gemini" and int(MODEL.split("-")[1].split(".")[1]) >= 5 or "flash-preview" in MODEL or MODEL >= "gemini-3.5", f"hackathon requires Gemini 3.5+, got {MODEL}"

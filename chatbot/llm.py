"""Gemini chat model via LangChain. Reads GEMINI_API_KEY (and optional GEMINI_MODEL) from .env."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Same default as the ad agent: Flash-Lite has the most generous free-tier limits.
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def get_llm():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("No GEMINI_API_KEY found. Copy .env.example to .env and add your Google AI Studio key.")

    from langchain_google_genai import ChatGoogleGenerativeAI
    # No temperature: Gemini 3.x models use fixed sampling defaults and ignore it.
    return ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL), google_api_key=key,
                                  max_retries=4)

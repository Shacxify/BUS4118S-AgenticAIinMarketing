"""Gemini-backed policy: the LLM proposes the split, code enforces the guardrails.

Reliability features:
  * runs with no API key: falls back to the heuristic for that day and logs why
  * retries rate-limit / server errors with exponential backoff
  * throttles calls (GEMINI_MIN_INTERVAL seconds) to stay inside free-tier limits
  * caps LLM calls per run (cost cap); after the cap, the heuristic takes over
  * caches responses on disk, so re-runs are free and reproducible
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import config
from .policies import HeuristicAgent, Proposal
from .tools import metrics_summary

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = ROOT / "prompts" / "system_prompt.md"
CACHE_PATH = ROOT / "outputs" / "gemini_cache.json"
# Flash-Lite: the free tier for gemini-3.6-flash allows only 20 requests/day, less than one
# 30-day run (~28 calls). Set GEMINI_MODEL to use a different model.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_CALLS_PER_RUN = 60

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "allocation": {
            "type": "object",
            "properties": {c: {"type": "number"} for c in config.CHANNELS},
            "required": config.CHANNELS,
        },
        "rationale": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["allocation", "rationale", "confidence"],
}


def _load_dotenv():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


class GeminiAgent:
    name = "gemini"
    guarded = True

    def __init__(self, model=None, use_cache=True, seed=0):
        _load_dotenv()
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.min_interval = float(os.getenv("GEMINI_MIN_INTERVAL", "4"))
        self.system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        self.fallback = HeuristicAgent(seed=seed)
        self.use_cache = use_cache
        self.cache = self._read_cache() if use_cache else {}
        self.calls = 0
        self.last_call = 0.0
        self.client = None
        self.init_error = None
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if key:
            try:
                from google import genai
                self.client = genai.Client(api_key=key)
            except Exception as e:  # SDK missing or misconfigured
                self.init_error = f"Gemini client unavailable ({type(e).__name__})"
        else:
            self.init_error = "no GEMINI_API_KEY set"

    # ---- policy interface -------------------------------------------------
    def decide(self, day, history, prev_alloc):
        prompt = self.build_prompt(day, history, prev_alloc)
        key = hashlib.sha256(f"{self.model}\n{self.system_prompt}\n{prompt}".encode()).hexdigest()

        if key in self.cache:
            text, source = self.cache[key], "gemini (cached)"
        else:
            if self.client is None:
                return self._fallback(day, history, prev_alloc, self.init_error)
            if self.calls >= MAX_CALLS_PER_RUN:
                return self._fallback(day, history, prev_alloc, f"LLM call cap ({MAX_CALLS_PER_RUN}) reached")
            try:
                text = self._call(prompt)
            except Exception as e:
                return self._fallback(day, history, prev_alloc, f"Gemini error: {_short(e)}")
            source = "gemini"

        try:
            data = json.loads(text)
            shares = {c: float(data["allocation"][c]) for c in config.CHANNELS}
            if any(s < 0 for s in shares.values()) or not 0.5 <= sum(shares.values()) <= 1.5:
                raise ValueError(f"shares sum to {sum(shares.values()):.2f}")
            rationale = str(data.get("rationale", ""))
            confidence = data.get("confidence")
        except Exception as e:
            return self._fallback(day, history, prev_alloc, f"unusable Gemini reply ({_short(e)})")

        if source == "gemini" and self.use_cache:
            self.cache[key] = text
            self._write_cache()
        if confidence:
            rationale = f"{rationale} (confidence: {confidence})"
        return Proposal(shares, rationale, source)

    # ---- helpers -----------------------------------------------------------
    def build_prompt(self, day, history, prev_alloc):
        date = history["date"].max()
        payload = {
            "day": day + 1,
            "of_days": config.DAYS,
            "last_observed_date": date,
            "daily_budget": config.DAILY_BUDGET,
            "yesterday_allocation_dollars": {c: round(prev_alloc[c], 2) for c in config.CHANNELS},
            f"last_{config.WINDOW}_days_by_channel": metrics_summary(history),
        }
        return ("Decide tomorrow's budget split. Performance data:\n"
                + json.dumps(payload, indent=2)
                + "\nReturn only the JSON object described in your instructions.")

    def _call(self, prompt):
        from google.genai import errors, types
        cfg = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=0.2,
            response_mime_type="application/json",
            response_json_schema=RESPONSE_SCHEMA,
        )
        self.calls += 1   # one per decision; retries of the same request don't count toward the cap
        delay = 2.0
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.monotonic()
            try:
                resp = self.client.models.generate_content(model=self.model, contents=prompt, config=cfg)
                if not resp.text:
                    raise ValueError("empty response")
                return resp.text
            except errors.APIError as e:
                if getattr(e, "code", None) == 429 and "PerDay" in str(e):
                    # Daily quota is gone: retrying won't help, so stop calling for the rest of the run.
                    self.client = None
                    self.init_error = f"daily Gemini quota exhausted for {self.model}"
                    raise RuntimeError(self.init_error) from None
                retryable = getattr(e, "code", None) in (429, 500, 502, 503, 504)
                if not retryable or attempt == 3:
                    raise
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    def _fallback(self, day, history, prev_alloc, reason):
        p = self.fallback.decide(day, history, prev_alloc)
        return Proposal(p.shares, p.rationale, f"heuristic fallback: {reason}")

    def _read_cache(self):
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_cache(self):
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")


def _short(e):
    msg = re.sub(r"(key=)[^&\s'\"]+", r"\1REDACTED", f"{type(e).__name__}: {e}")  # never log the API key
    msg = " ".join(msg.split())
    return msg if len(msg) < 120 else msg[:117] + "..."

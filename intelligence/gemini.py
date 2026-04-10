"""
intelligence/gemini.py — Gemini AI API wrapper with rate limiting and structured output
Uses REST API directly (no heavy SDK dependency).
"""
import json
import time
import logging
from typing import Optional, Dict, Any
from collections import deque

from curl_cffi import requests as curl_requests

from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT

logger = logging.getLogger("idx_bot.gemini")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    """
    Lightweight Gemini API client with:
    - Rate limiting (15 RPM free tier)
    - Automatic retry on transient errors
    - JSON response parsing
    - Token counting safety
    """

    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL):
        self.api_key = api_key
        self.model = model
        self._call_timestamps: deque = deque(maxlen=15)  # Track last 15 calls
        self._total_calls = 0
        self._total_tokens = 0
        self._errors = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def analyze(self, prompt: str, temperature: float = 0.1) -> Optional[Dict]:
        """
        Send a prompt to Gemini and parse the JSON response.
        Returns parsed dict, or None on failure.

        Args:
            prompt: The text prompt to send
            temperature: Lower = more deterministic. 0.1 for analysis, 0.7 for summaries.
        """
        if not self.is_configured:
            logger.warning("Gemini API key not configured — skipping AI analysis")
            return None

        self._enforce_rate_limit()

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "topP": 0.8,
                "topK": 40,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ],
        }

        for attempt in range(3):
            try:
                resp = curl_requests.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=GEMINI_TIMEOUT,
                )

                if resp.status_code == 200:
                    result = resp.json()
                    text = self._extract_text(result)
                    self._total_calls += 1
                    self._record_call()

                    # Try to parse as JSON
                    if text:
                        return self._parse_json_response(text)
                    return None

                elif resp.status_code == 429:
                    # Rate limited — wait and retry
                    wait = min(2 ** (attempt + 2), 30)
                    logger.warning("Gemini rate limited, waiting %ds…", wait)
                    time.sleep(wait)

                elif resp.status_code in (500, 502, 503):
                    # Transient server error
                    wait = 2 ** (attempt + 1)
                    logger.warning("Gemini server error %s, retrying in %ds…", resp.status_code, wait)
                    time.sleep(wait)

                else:
                    logger.error(
                        "Gemini API error HTTP %s: %s",
                        resp.status_code, resp.text[:200],
                    )
                    self._errors += 1
                    return None

            except Exception as e:
                logger.error("Gemini request failed (attempt %d): %s", attempt + 1, e)
                self._errors += 1
                if attempt < 2:
                    time.sleep(2 ** attempt)

        return None

    def analyze_text(self, prompt: str, temperature: float = 0.3) -> Optional[str]:
        """
        Send a prompt and return raw text response (not JSON).
        For generating summaries, explanations, etc.
        """
        if not self.is_configured:
            return None

        self._enforce_rate_limit()

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 1024,
            },
        }

        try:
            resp = curl_requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=GEMINI_TIMEOUT,
            )

            if resp.status_code == 200:
                result = resp.json()
                text = self._extract_text(result)
                self._total_calls += 1
                self._record_call()
                return text
            else:
                logger.warning("Gemini text API error HTTP %s", resp.status_code)
                return None

        except Exception as e:
            logger.error("Gemini text request failed: %s", e)
            return None

    def _extract_text(self, result: dict) -> Optional[str]:
        """Extract text from Gemini API response."""
        try:
            candidates = result.get("candidates", [])
            if not candidates:
                return None
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                return None
            return parts[0].get("text", "")
        except (IndexError, KeyError, TypeError) as e:
            logger.debug("Failed to extract text from Gemini response: %s", e)
            return None

    def _parse_json_response(self, text: str) -> Optional[Dict]:
        """Parse JSON from Gemini response, handling markdown code blocks."""
        if not text:
            return None

        # Strip markdown code block if present
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from mixed text
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            logger.debug("Failed to parse Gemini JSON response: %s", text[:200])
            return None

    def _enforce_rate_limit(self):
        """Enforce 15 RPM rate limit with sliding window."""
        now = time.time()

        # Remove timestamps older than 60 seconds
        while self._call_timestamps and (now - self._call_timestamps[0]) > 60:
            self._call_timestamps.popleft()

        if len(self._call_timestamps) >= 14:  # Leave 1 RPM buffer
            oldest = self._call_timestamps[0]
            wait = 60 - (now - oldest) + 1
            if wait > 0:
                logger.info("Rate limit approaching, waiting %.1fs…", wait)
                time.sleep(wait)

    def _record_call(self):
        """Record a successful API call for rate limiting."""
        self._call_timestamps.append(time.time())

    def get_stats(self) -> Dict[str, Any]:
        """Return usage statistics."""
        return {
            "total_calls": self._total_calls,
            "errors": self._errors,
            "calls_last_minute": len(self._call_timestamps),
            "configured": self.is_configured,
            "model": self.model,
        }

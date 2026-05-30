"""
NarrativeEngine — LLM narrative/context reasoning via Claude Haiku.
Only called when fresh news exists for a candidate symbol. Heavily cached.
Returns a structured thesis. No-op (neutral) if ANTHROPIC_API_KEY is unset.

This is the qualitative layer that rule-based engines can't cover: novel
catalysts, ambiguous headlines, second-order narrative effects. It is strictly
optional — with no API key the whole module is a transparent neutral pass-through
and the trading system runs unchanged.
"""

import os
import json
import time
import logging
import threading
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

ANTHROPIC_URL     = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_VERSION = '2023-06-01'
MODEL             = 'claude-haiku-4-5-20251001'
MAX_TOKENS        = 300
HTTP_TIMEOUT      = 8          # seconds
CACHE_TTL         = 60 * 60    # 60 minutes per symbol

NEUTRAL = {
    'score':        0.0,
    'confidence':   0.0,
    'thesis':       '',
    'event_type':   'none',
    'time_horizon': '',
    'key_risk':     '',
    'fade_signal':  False,
}


def _api_key() -> str:
    return os.getenv('ANTHROPIC_API_KEY', '') or ''


def is_enabled() -> bool:
    """True only when an Anthropic API key is configured."""
    return bool(_api_key().strip())


class NarrativeEngine:
    """Wraps a single cached Claude Haiku call per symbol/hour."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict = {}   # symbol -> {'result': {...}, 'ts': float}

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(symbol: str, data: dict, regime: str,
                      headlines: list) -> str:
        data = data or {}
        price = data.get('last_price')
        rsi   = data.get('rsi')
        trend = data.get('trend')
        news_block = '\n'.join(f'- {h}' for h in headlines[:8] if h)

        return (
            "You are a sharp, skeptical equity analyst. Read the fresh news for "
            f"{symbol} and judge its near-term trading impact.\n\n"
            f"Symbol: {symbol}\n"
            f"Last price: {price}\n"
            f"Market regime: {regime}\n"
            f"RSI: {rsi}\n"
            f"Trend: {trend}\n\n"
            f"Fresh headlines:\n{news_block}\n\n"
            "Respond with ONLY a JSON object (no prose, no markdown fences) of the form:\n"
            "{\"score\": <float -2..2, positive=bullish>, "
            "\"confidence\": <float 0..1>, "
            "\"thesis\": <one-sentence reasoning>, "
            "\"time_horizon\": <\"intraday\"|\"days\"|\"weeks\">, "
            "\"event_type\": <short label e.g. earnings, guidance, M&A, legal, macro>, "
            "\"key_risk\": <one phrase>, "
            "\"fade_signal\": <true if the move looks overdone and should be faded>}\n"
            "Be conservative: if the news is stale, vague, or already priced in, "
            "use a low confidence and a score near 0."
        )

    # ------------------------------------------------------------------
    # HTTP call
    # ------------------------------------------------------------------

    def _call_anthropic(self, prompt: str) -> str | None:
        """Raw HTTP POST to the Messages API. Returns assistant text or None."""
        key = _api_key()
        if not key:
            return None

        body = json.dumps({
            'model':      MODEL,
            'max_tokens': MAX_TOKENS,
            'messages':   [{'role': 'user', 'content': prompt}],
        }).encode('utf-8')

        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            method='POST',
            headers={
                'content-type':      'application/json',
                'x-api-key':         key,
                'anthropic-version': ANTHROPIC_VERSION,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
            blocks = payload.get('content', [])
            parts = [b.get('text', '') for b in blocks if b.get('type') == 'text']
            return ''.join(parts).strip() or None
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            log.debug('[NARR] HTTP error: %s', e)
            return None
        except Exception as e:
            log.debug('[NARR] call error: %s', e)
            return None

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Extract a JSON object from the model text, tolerating ``` fences."""
        if not text:
            return {}
        t = text.strip()
        if t.startswith('```'):
            t = t.strip('`')
            if t.lower().startswith('json'):
                t = t[4:]
            t = t.strip()
        # Slice to the outermost braces in case of stray prose.
        start, end = t.find('{'), t.rfind('}')
        if start != -1 and end != -1 and end > start:
            t = t[start:end + 1]
        try:
            return json.loads(t)
        except Exception as e:
            log.debug('[NARR] json parse failed: %s', e)
            return {}

    @staticmethod
    def _normalise(raw: dict) -> dict:
        """Coerce a parsed dict into the strict NEUTRAL-shaped result."""
        out = dict(NEUTRAL)
        try:
            score = float(raw.get('score', 0.0))
            out['score'] = round(max(-2.0, min(2.0, score)), 3)
        except Exception:
            pass
        try:
            conf = float(raw.get('confidence', 0.0))
            out['confidence'] = round(max(0.0, min(1.0, conf)), 3)
        except Exception:
            pass
        out['thesis']       = str(raw.get('thesis', '') or '')[:500]
        out['event_type']   = str(raw.get('event_type', 'none') or 'none')[:40]
        out['time_horizon'] = str(raw.get('time_horizon', '') or '')[:20]
        out['key_risk']     = str(raw.get('key_risk', '') or '')[:200]
        out['fade_signal']  = bool(raw.get('fade_signal', False))
        return out

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self, symbol: str, data: dict, regime: str,
                   news_headlines: list | None = None) -> dict:
        """
        Produce a structured narrative thesis. Returns NEUTRAL immediately when
        the API key is missing or there is no news to reason about.
        """
        try:
            if not is_enabled() or not news_headlines:
                return dict(NEUTRAL)

            sym = (symbol or '').upper()
            now = time.time()
            with self._lock:
                entry = self._cache.get(sym)
                if entry and (now - entry['ts']) < CACHE_TTL:
                    return dict(entry['result'])

            prompt = self._build_prompt(sym, data, regime, news_headlines)
            text = self._call_anthropic(prompt)
            if not text:
                return dict(NEUTRAL)

            result = self._normalise(self._parse_json(text))

            with self._lock:
                self._cache[sym] = {'result': dict(result), 'ts': now}

            log.info('[NARR] %s — score=%.2f conf=%.2f event=%s',
                     sym, result['score'], result['confidence'], result['event_type'])
            return result

        except Exception as e:
            log.debug('[NARR] get_signal(%s) error: %s', symbol, e)
            return dict(NEUTRAL)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: 'NarrativeEngine | None' = None


def get_engine() -> NarrativeEngine:
    """Return the lazily-created module-level engine singleton."""
    global _engine
    if _engine is None:
        _engine = NarrativeEngine()
    return _engine


def get_signal(symbol: str, data: dict, regime: str,
               news_headlines: list | None = None) -> dict:
    """Narrative signal dict for ``symbol`` (never raises; neutral if disabled)."""
    try:
        return get_engine().get_signal(symbol, data, regime, news_headlines)
    except Exception as e:
        log.debug('[NARR] module get_signal error: %s', e)
        return dict(NEUTRAL)


def score_contrib(symbol: str, data: dict, regime: str,
                  news_headlines: list | None = None) -> float:
    """
    Effective contribution = score × confidence (0.0 when disabled or on error).
    """
    try:
        sig = get_signal(symbol, data, regime, news_headlines)
        return float(sig.get('score', 0.0)) * float(sig.get('confidence', 0.0))
    except Exception:
        return 0.0

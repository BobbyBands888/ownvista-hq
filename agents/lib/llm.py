"""Groq free-tier LLM wrapper with JSON mode and a fallback model on rate limits."""
import json
import time
import requests
from . import config

URL = "https://api.groq.com/openai/v1/chat/completions"

def ask(system, user, json_mode=True, max_tokens=2000, temperature=0.4):
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    last_err, errs = None, []
    # Free tier limits are per model, so spread across several before giving up. Unavailable ones are skipped.
    models = [config.GROQ_MODEL, config.GROQ_FALLBACK_MODEL, "qwen/qwen3-32b", "moonshotai/kimi-k2-instruct-0905"]
    for model in dict.fromkeys(models):
        for attempt in range(3):
            body = {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"   # keep reasoning from eating the token budget
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            r = requests.post(URL, headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, json=body, timeout=90)
            if r.status_code == 429:
                last_err = "rate limited"
                errs.append(f"{model}: 429 {r.text[:90]}")
                if "per day" in r.text or "TPD" in r.text or "RPD" in r.text:
                    break                       # daily cap on this model: move to the next one now
                time.sleep(min(30, 5 * (attempt + 1)))
                continue
            if r.status_code >= 300:
                last_err = f"{r.status_code} {r.text[:200]}"
                errs.append(f"{model}: {r.status_code}")
                break
            text = r.json()["choices"][0]["message"]["content"] or ""
            if model.startswith("qwen/"):
                import re
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            if not json_mode:
                return text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                last_err = "bad JSON from model"
                continue
    raise RuntimeError(f"LLM failed: {last_err} | tried: {' ; '.join(dict.fromkeys(errs))}")

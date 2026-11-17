"""Groq free-tier LLM wrapper with JSON mode and a fallback model on rate limits."""
import json
import time
import requests
from . import config

URL = "https://api.groq.com/openai/v1/chat/completions"

# Preferred order for text work; whatever Groq actually serves today decides which are used.
PREFERRED = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile",
             "minimaxai/minimax-m2.7", "meta-models/muse-spark-open", "llama-3.1-8b-instant"]
NOT_CHAT = ("whisper", "orpheus", "guard", "safeguard", "tts", "playai", "distil")
_live = None

def text_models():
    """Chat models to try, in order: configured ones, then PREFERRED, then any other chat model Groq lists —
    filtered to what /models says exists, so a retired model never ends the chain (Maker failed on 2 dead ones)."""
    global _live
    if _live is None:
        try:
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, timeout=20)
            _live = [m["id"] for m in r.json().get("data", []) if m.get("active", True)] if r.status_code < 300 else []
        except Exception:
            _live = []
    want = list(dict.fromkeys([config.GROQ_MODEL, config.GROQ_FALLBACK_MODEL] + PREFERRED))
    if not _live:
        return want                           # couldn't list: try the known names
    extra = sorted(m for m in _live if not any(x in m.lower() for x in NOT_CHAT) and m not in want)
    return [m for m in want if m in _live] + extra

def ask(system, user, json_mode=True, max_tokens=2000, temperature=0.4):
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    last_err, errs = None, []
    # Free tier limits are per model, so spread across several before giving up. Unavailable ones are skipped.
    for model in text_models():
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
                errs.append(f"{model}: 429 {r.json().get('error',{}).get('message','')[90:330] if r.headers.get('content-type','').startswith('application/json') else r.text[:200]}")
                if "per day" in r.text or "TPD" in r.text or "RPD" in r.text:
                    break                       # daily cap on this model: move to the next one now
                time.sleep(min(30, 5 * (attempt + 1)))
                continue
            if r.status_code >= 300:
                last_err = f"{r.status_code} {r.text[:200]}"
                errs.append(f"{model}: {r.status_code}")
                if r.status_code == 400 and "response_format" in r.text and json_mode:
                    body.pop("response_format", None)
                    r = requests.post(URL, headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                                      json={**body, "messages": [{"role": "system", "content": system +
                                            "\nRespond with ONLY a valid JSON object."}, body["messages"][1]]}, timeout=90)
                    if r.status_code < 300:
                        import re
                        t = re.sub(r"<think>.*?</think>", "", r.json()["choices"][0]["message"]["content"] or "", flags=re.S)
                        m = re.search(r"\{.*\}", t, re.S)
                        if m:
                            try:
                                return json.loads(m.group(0))
                            except json.JSONDecodeError:
                                pass
                break
            text = r.json()["choices"][0]["message"]["content"] or ""
            if "<think>" in text:
                import re
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            if not json_mode:
                return text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                last_err = "bad JSON from model"
                continue
    # Last resort: Cloudflare Workers AI free daily allowance (separate from Groq's caps)
    import os
    acct, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if acct and tok:
        for cf_model in ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/meta/llama-3.1-8b-instruct"):
            try:
                sys_msg = system + ("\nRespond with ONLY a valid JSON object, no other text." if json_mode else "")
                r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{cf_model}",
                                  headers={"Authorization": f"Bearer {tok}"}, timeout=120,
                                  json={"messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}],
                                        "max_tokens": max_tokens, "temperature": temperature})
                if r.status_code >= 300:
                    errs.append(f"{cf_model}: {r.status_code} {r.text[:120]}")
                    continue
                out = r.json().get("result", {}).get("response")
                if isinstance(out, (dict, list)):
                    return out if json_mode else json.dumps(out)
                text = out or ""
                if not json_mode:
                    return text
                import re
                m = re.search(r"\{.*\}", text, re.S)
                if m:
                    return json.loads(m.group(0))
                errs.append(f"{cf_model}: no JSON")
            except Exception as e:
                errs.append(f"{cf_model}: {type(e).__name__} {str(e)[:80]}")
    if not (os.environ.get("CF_ACCOUNT_ID") and os.environ.get("CF_API_TOKEN")):
        errs.append("Cloudflare backup not configured (CF_ACCOUNT_ID / CF_API_TOKEN secrets)")
    raise RuntimeError(f"LLM failed: {last_err} | tried: {' ; '.join(dict.fromkeys(errs))}")


# ---------------- vision (what's on screen) ----------------
# Free vision models change often, so try a list. GROQ_VISION_MODEL overrides the first choice.
VISION_MODELS = ["qwen/qwen3.8-27b"]   # Llama 4 Scout/Maverick were retired on Groq (404, Nov 2026)
_dead_vision = set()


def _json_any(text):
    """First JSON object in a reply; a bare top-level list comes back as {"frames": [...]}."""
    import re
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text).strip()
    for cand in (text, (re.search(r"\{.*\}", text, re.S) or [None])[0], (re.search(r"\[.*\]", text, re.S) or [None])[0]):
        if not cand:
            continue
        try:
            v = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(v, list):
            return {"frames": v}
        if isinstance(v, dict):
            return v
    # Cut-off or chatty replies (Cloudflare's vision model): keep every complete flat {...} frame object we can read
    frames = []
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            o = json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(o, dict) and "n" in o:
            frames.append(o)
    return {"frames": frames} if frames else None


def see(prompt, jpeg, max_tokens=1500, check=None):
    """Ask a vision model about one JPEG (bytes). Returns parsed JSON. Groq first, Cloudflare Workers AI fallback.
    `check(result)` -> bool: a reply that parses but holds nothing usable counts as a failure, so the next model
    is tried instead of silently returning an empty answer."""
    import base64
    import os
    import re
    b64 = base64.b64encode(jpeg).decode()
    errs = []
    models = [m for m in dict.fromkeys([os.environ.get("GROQ_VISION_MODEL") or ""] + VISION_MODELS) if m]
    if config.GROQ_API_KEY:
        for model in models:
            if model in _dead_vision:
                continue
            for attempt in range(5):
                body = {"model": model, "max_tokens": max_tokens, "temperature": 0.1,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": prompt + "\nRespond with ONLY a JSON object."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
                try:
                    r = requests.post(URL, headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, json=body, timeout=120)
                except Exception as e:
                    errs.append(f"{model}: {type(e).__name__}")
                    break
                if r.status_code == 429:
                    if "per day" in r.text or "TPD" in r.text or "RPD" in r.text:
                        errs.append(f"{model}: daily cap")
                        _dead_vision.add(model)
                        break
                    # per-minute token cap (each image is ~2K tokens): wait as long as Groq asks
                    wait = r.headers.get("retry-after")
                    m = re.search(r"try again in ([\d.]+)(m?s)", r.text)
                    secs = float(wait) if wait and wait.replace(".", "").isdigit() else \
                        (float(m[1]) / (1000 if m and m[2] == "ms" else 1) if m else 15 * (attempt + 1))
                    errs.append(f"{model}: 429 wait {secs:.0f}s")
                    time.sleep(min(70, secs + 1))
                    continue
                if r.status_code >= 300:
                    errs.append(f"{model}: {r.status_code} {r.text[:120]}")
                    if r.status_code in (400, 404) and ("model" in r.text.lower() or "not support" in r.text.lower()):
                        _dead_vision.add(model)          # retired / not a vision model: skip it for the rest of the run
                    break
                text = r.json()["choices"][0]["message"]["content"] or ""
                v = _json_any(text)
                if v is not None and (check is None or check(v)):
                    return v
                errs.append(f"{model}: {'unusable' if v is not None else 'bad JSON'}: {text[:160]!r}")
                break
    acct, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if acct and tok and "cf" not in _dead_vision:
        cf = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/meta/llama-3.2-11b-vision-instruct"
        h = {"Authorization": f"Bearer {tok}"}
        bodies = [  # current Workers AI shape (image inside the message), then the older top-level "image" shape
            {"messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt + "\nRespond with ONLY a JSON object."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
             "max_tokens": max_tokens, "temperature": 0.1},
            {"messages": [{"role": "user", "content": prompt + "\nRespond with ONLY a JSON object."}],
             "image": f"data:image/jpeg;base64,{b64}", "max_tokens": max_tokens, "temperature": 0.1}]
        for attempt in range(3):
            try:
                r = requests.post(cf, headers=h, timeout=120, json=bodies[min(attempt, 1)])
                if r.status_code == 400 and "no user-supplied" in r.text and attempt == 0:
                    continue                                         # wrong shape for this model version: try the other
                if attempt > 0 and r.status_code == 400 and "no user-supplied" in r.text:
                    errs.append(f"cf vision: {r.status_code} {r.text[:120]}")
                    break
                if r.status_code >= 300 and "agree" in r.text.lower() and attempt == 0:
                    requests.post(cf, headers=h, json={"prompt": "agree"}, timeout=60)   # one-time Meta licence accept
                    continue
                if r.status_code >= 300:
                    errs.append(f"cf vision: {r.status_code} {r.text[:120]}")
                    break
                out = r.json().get("result", {}).get("response")
                v = out if isinstance(out, dict) else _json_any(out if isinstance(out, str) else json.dumps(out))
                if v is not None and (check is None or check(v)):
                    return v
                errs.append(f"cf vision: {'unusable' if v is not None else 'no JSON'}: {str(out)[:160]!r}")
                break
            except Exception as e:
                errs.append(f"cf vision: {type(e).__name__} {str(e)[:80]}")
                break
    raise RuntimeError("vision failed: " + " ; ".join(errs))

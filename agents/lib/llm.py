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
    models = [config.GROQ_MODEL, config.GROQ_FALLBACK_MODEL, "qwen/qwen3-32b"]
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
                errs.append(f"{model}: 429 {r.json().get('error',{}).get('message','')[90:330] if r.headers.get('content-type','').startswith('application/json') else r.text[:200]}")
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
    raise RuntimeError(f"LLM failed: {last_err} | tried: {' ; '.join(dict.fromkeys(errs))}")


# ---------------- vision (what's on screen) ----------------
# Free vision models change often, so try a list. GROQ_VISION_MODEL overrides the first choice.
VISION_MODELS = ["qwen/qwen3.8-27b", "meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]
_dead_vision = set()


def see(prompt, jpeg, max_tokens=1500):
    """Ask a vision model about one JPEG (bytes). Returns parsed JSON. Groq first, Cloudflare Workers AI fallback."""
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
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
                m = re.search(r"\{.*\}", text, re.S)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except json.JSONDecodeError:
                        pass
                errs.append(f"{model}: bad JSON")
    acct, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if acct and tok and "cf" not in _dead_vision:
        cf = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/meta/llama-3.2-11b-vision-instruct"
        h = {"Authorization": f"Bearer {tok}"}
        for attempt in range(2):
            try:
                r = requests.post(cf, headers=h, timeout=120, json={
                    "messages": [{"role": "user", "content": prompt + "\nRespond with ONLY a JSON object."}],
                    "image": f"data:image/jpeg;base64,{b64}", "max_tokens": max_tokens, "temperature": 0.1})
                if r.status_code >= 300 and "agree" in r.text.lower() and attempt == 0:
                    requests.post(cf, headers=h, json={"prompt": "agree"}, timeout=60)   # one-time Meta licence accept
                    continue
                if r.status_code >= 300:
                    errs.append(f"cf vision: {r.status_code} {r.text[:120]}")
                    break
                out = r.json().get("result", {}).get("response")
                if isinstance(out, dict):
                    return out
                m = re.search(r"\{.*\}", out or "", re.S)
                if m:
                    return json.loads(m.group(0))
                errs.append("cf vision: no JSON")
                break
            except Exception as e:
                errs.append(f"cf vision: {type(e).__name__} {str(e)[:80]}")
                break
    raise RuntimeError("vision failed: " + " ; ".join(errs))

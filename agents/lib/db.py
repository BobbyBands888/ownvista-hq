"""Tiny Supabase (PostgREST) client using the service key. No extra dependency."""
import json
import requests
from . import config

class DB:
    def __init__(self):
        if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        self.base = config.SUPABASE_URL.rstrip("/") + "/rest/v1/"
        self.h = {
            "apikey": config.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }

    def _check(self, r):
        if r.status_code >= 300:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else []

    def select(self, table, params=None):
        """params: PostgREST query dict, e.g. {"status": "eq.new", "order": "created_at.desc", "limit": 20}"""
        return self._check(requests.get(self.base + table, headers=self.h, params=params or {}, timeout=30))

    def insert(self, table, rows, upsert=False, on_conflict=None, returning=True):
        # returning=False: don't echo the written rows back (saves Supabase egress on big writes)
        h = dict(self.h, Prefer=("return=representation" if returning else "return=minimal")
                 + (",resolution=merge-duplicates" if upsert else ""))
        params = {"on_conflict": on_conflict} if on_conflict else {}
        rows = rows if isinstance(rows, list) else [rows]
        if not rows:
            return []
        return self._check(requests.post(self.base + table, headers=h, params=params,
                                         data=json.dumps(rows, default=str), timeout=30))

    def update(self, table, match, values):
        """match: PostgREST filter dict, e.g. {"id": "eq.<uuid>"}"""
        h = dict(self.h, Prefer="return=representation")
        return self._check(requests.patch(self.base + table, headers=h, params=match,
                                          data=json.dumps(values, default=str), timeout=30))

    def delete(self, table, match):
        return self._check(requests.delete(self.base + table, headers=self.h, params=match, timeout=30))

    def setting(self, key, default=None):
        rows = self.select("settings", {"key": f"eq.{key}"})
        return rows[0]["value"] if rows else default

    def alert(self, agent, message, level="info"):
        return self.insert("alerts", {"agent": agent, "message": message[:1000], "level": level})

    def alert_once(self, agent, message, level="info", key=None):
        """Alert only if no open (unresolved) alert from this agent already starts with `key` (default: the
        whole message). Stops the same problem filling 'Needs you' on every run."""
        key = (key or message)[:200]
        try:
            open_ = self.select("alerts", {"agent": f"eq.{agent}", "resolved": "is.false",
                                           "select": "message", "order": "created_at.desc", "limit": 300})
            if any((a.get("message") or "").startswith(key) for a in open_):
                return []
        except Exception:
            pass
        return self.alert(agent, message, level)

    def resolve_alerts(self, agent, contains):
        """Mark open alerts from `agent` whose text contains `contains` as done."""
        try:
            for a in self.select("alerts", {"agent": f"eq.{agent}", "resolved": "is.false",
                                            "select": "id,message", "limit": 500}):
                if contains in (a.get("message") or ""):
                    self.update("alerts", {"id": f"eq.{a['id']}"}, {"resolved": True})
        except Exception:
            pass

"""Scoped SQLite persistence. Handles are trusted host configuration, never model input."""
from contextlib import contextmanager
import hashlib
import math
import sqlite3
import threading
import time
from uuid import uuid4

from .guardrails import Action, SensitiveData, canonical, strict_json


class Storage:
    def __init__(self, path, *, scope, privacy=None, clock=time.time):
        if not isinstance(scope, str) or not scope: raise ValueError('trusted scope required')
        if sqlite3.sqlite_version_info < (3, 35, 0): raise ValueError('SQLite 3.35+ required')
        self.scope, self.privacy, self.clock = scope, privacy or SensitiveData(), clock
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        with self.transaction() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('unsupported storage migration')
            # No executescript here: it implicitly commits a pending transaction.
            statements = [
                'CREATE TABLE IF NOT EXISTS import_errors(scope TEXT, batch_id TEXT, row_number INTEGER, code TEXT)',
                'CREATE TABLE IF NOT EXISTS records(scope TEXT, id TEXT, version TEXT, data TEXT, PRIMARY KEY(scope,id,version))',
                'CREATE TABLE IF NOT EXISTS sources(scope TEXT, id TEXT, origin TEXT, fetched REAL, hash TEXT, content TEXT, PRIMARY KEY(scope,id))',
                'CREATE TABLE IF NOT EXISTS observations(scope TEXT, id TEXT, record_id TEXT, record_version TEXT, field TEXT, value TEXT, source_id TEXT, excerpt TEXT, extractor TEXT, validator TEXT, status TEXT, created REAL, PRIMARY KEY(scope,id))',
                'CREATE TABLE IF NOT EXISTS acceptances(scope TEXT, id TEXT, observation_id TEXT, policy TEXT, reviewer TEXT, created REAL, revoked REAL, PRIMARY KEY(scope,id))',
                'CREATE TABLE IF NOT EXISTS jobs(scope TEXT, id TEXT, dedup TEXT, payload TEXT, state TEXT, attempt INTEGER, max_attempts INTEGER, available REAL, lease TEXT, lease_until REAL, result TEXT, error TEXT, PRIMARY KEY(scope,id), UNIQUE(scope,dedup))',
                'CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(scope,state,available)',
                'CREATE TABLE IF NOT EXISTS approvals(scope TEXT, token_hash TEXT, fingerprint TEXT, expires REAL, PRIMARY KEY(scope,token_hash))',
                'CREATE TABLE IF NOT EXISTS intents(scope TEXT, id TEXT, fingerprint TEXT, state TEXT, provider_id TEXT, PRIMARY KEY(scope,id))',
                'CREATE TABLE IF NOT EXISTS usage(scope TEXT, run_id TEXT, payload TEXT, PRIMARY KEY(scope,run_id))',
            ]
            for sql in statements: db.execute(sql)
            db.execute('PRAGMA user_version=1')

    def close(self):
        self.db.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    @contextmanager
    def transaction(self):
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
            except BaseException:
                self.db.rollback()
                raise
            else:
                self.db.commit()

    def now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value): raise ValueError('invalid clock')
        return value

    def clean(self, value):
        return self.privacy.redact(strict_json(canonical(value)))

    def record(self, record_id, version):
        row = self.db.execute('SELECT data FROM records WHERE scope=? AND id=? AND version=?', (self.scope, record_id, version)).fetchone()
        if row is None: raise KeyError('record not found in scope')
        return strict_json(row['data'])

    def import_records(self, rows, *, identify, version, validate, chunk_size=500):
        if not isinstance(version, str) or not version or type(chunk_size) is not int or chunk_size < 1:
            raise ValueError('version and chunk size required')
        counts = dict(input=0, accepted=0, rejected=0, duplicates=0, conflicts=0)
        batch_id = uuid4().hex
        def insert(chunk):
            with self.transaction() as db:
                for record_id, text in chunk:
                    old = db.execute('SELECT data FROM records WHERE scope=? AND id=? AND version=?', (self.scope, record_id, version)).fetchone()
                    if old:
                        counts['duplicates' if old['data'] == text else 'conflicts'] += 1
                    else:
                        db.execute('INSERT INTO records VALUES(?,?,?,?)', (self.scope, record_id, version, text))
                        counts['accepted'] += 1
        chunk = []
        for row in rows:
            counts['input'] += 1
            try:
                value = strict_json(canonical(row))
                before = canonical(value)
                decision = validate(value)
                if decision is False or canonical(value) != before: raise ValueError('invalid record')
                record_id = identify(value)
                if not isinstance(record_id, str) or not record_id or self.privacy.contains(record_id): raise ValueError('invalid id')
                chunk.append((record_id, canonical(self.clean(value))))
            except (ValueError, TypeError, KeyError):
                counts['rejected'] += 1
                with self.transaction() as db:
                    db.execute('INSERT INTO import_errors VALUES(?,?,?,?)', (self.scope, batch_id, counts['input'], 'invalid_record'))
            if len(chunk) >= chunk_size: insert(chunk); chunk = []
        if chunk: insert(chunk)
        return counts

    def import_errors(self):
        return [dict(row) for row in self.db.execute("SELECT batch_id,row_number,code FROM import_errors WHERE scope=? ORDER BY rowid", (self.scope,))]


class DurableApprovals:
    """Same exact-action contract as ApprovalStore; scope is a trusted store handle."""
    def __init__(self, storage, *, intent_key=None):
        self.storage, self.intent_key = storage, intent_key

    def issue(self, action, *, seconds=300):
        if not isinstance(action, Action) or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('invalid approval')
        token = uuid4().hex + uuid4().hex
        hashed = hashlib.sha256(token.encode()).hexdigest()
        s = self.storage
        with s.transaction() as db:
            db.execute('INSERT INTO approvals VALUES(?,?,?,?)', (s.scope, hashed, action.fingerprint, s.now() + seconds))
        return token

    def consume(self, token, action):
        if not isinstance(token, str) or not isinstance(action, Action): return False
        if self.intent_key is not None:
            try:
                self.dispatch(self.intent_key(action), action, token)
                return True
            except ValueError:
                return False
        s = self.storage
        with s.transaction() as db:
            row = db.execute('DELETE FROM approvals WHERE scope=? AND token_hash=? AND fingerprint=? AND expires>? RETURNING fingerprint',
                             (s.scope, hashlib.sha256(token.encode()).hexdigest(), action.fingerprint, s.now())).fetchone()
            return row is not None

    def dispatch(self, intent_id, action, token):
        """Atomic approval consumption plus dispatch intent. No network I/O here."""
        if not isinstance(intent_id, str) or not intent_id or not isinstance(token, str) or not isinstance(action, Action):
            raise ValueError('invalid intent')
        s = self.storage
        with s.transaction() as db:
            if db.execute('SELECT 1 FROM intents WHERE scope=? AND id=?', (s.scope, intent_id)).fetchone():
                raise ValueError('intent already dispatched; reconcile outcome')
            row = db.execute('DELETE FROM approvals WHERE scope=? AND token_hash=? AND fingerprint=? AND expires>? RETURNING fingerprint',
                             (s.scope, hashlib.sha256(token.encode()).hexdigest(), action.fingerprint, s.now())).fetchone()
            if row is None: raise ValueError('approval invalid')
            db.execute('INSERT INTO intents VALUES(?,?,?,?,?)', (s.scope, intent_id, action.fingerprint, 'dispatched', None))
        return intent_id  # Pass this to the provider as its idempotency key.

    def reconcile(self, intent_id, *, state, provider_id=None):
        if state not in {'confirmed', 'failed', 'unknown'}: raise ValueError('invalid outcome')
        if provider_id is not None and not isinstance(provider_id, str): raise ValueError('invalid provider reference')
        s = self.storage
        with s.transaction() as db:
            cur = db.execute('UPDATE intents SET state=?,provider_id=? WHERE scope=? AND id=? AND state IN (\'dispatched\',\'unknown\')',
                             (state, s.clean(provider_id), s.scope, intent_id))
            if cur.rowcount != 1: raise ValueError('intent cannot transition')

    def intent(self, intent_id):
        row = self.storage.db.execute('SELECT id,state,provider_id FROM intents WHERE scope=? AND id=?', (self.storage.scope, intent_id)).fetchone()
        if row is None: raise KeyError('intent missing')
        return dict(row)


class UsageLedger:
    """Idempotent per-run totals, never recursive result aggregation."""
    def __init__(self, storage): self.storage = storage

    def record(self, run):
        keys = ('run_id', 'parent_id', 'agent_model', 'usage', 'usage_complete')
        data = {k: run[k] for k in keys}
        if not isinstance(data['run_id'], str) or not data['run_id'] or type(data['usage_complete']) is not bool:
            raise ValueError('invalid usage record')
        if not isinstance(data['usage'], dict) or any(type(v) is not int or v < 0 for v in data['usage'].values()):
            raise ValueError('invalid token counts')
        if 'usage_by_model' in run:
            by_model = run['usage_by_model']
            summed = {}
            if not isinstance(by_model, dict): raise ValueError('invalid model usage')
            for name, counts in by_model.items():
                if not isinstance(name, str) or not isinstance(counts, dict): raise ValueError('invalid model usage')
                for key, count in counts.items():
                    if type(count) is not int or count < 0: raise ValueError('invalid model token count')
                    summed[key] = summed.get(key, 0) + count
            if any(summed.get(k, 0) != data['usage'].get(k, 0) for k in summed.keys() | data['usage'].keys()):
                raise ValueError('model usage does not reconcile')
            data['usage_by_model'] = by_model
        text = canonical(self.storage.clean(data)); s = self.storage
        with s.transaction() as db:
            old = db.execute('SELECT payload FROM usage WHERE scope=? AND run_id=?', (s.scope, data['run_id'])).fetchone()
            if old and old['payload'] != text: raise ValueError('conflicting usage record')
            db.execute('INSERT OR IGNORE INTO usage VALUES(?,?,?)', (s.scope, data['run_id'], text))

    def summary(self, *, rates=None, pricing_version=None):
        rates = rates or {}
        if rates and not pricing_version: raise ValueError('pricing version required')
        totals, complete, estimate, unpriced = {}, True, 0.0, set()
        rows = self.storage.db.execute('SELECT payload FROM usage WHERE scope=?', (self.storage.scope,)).fetchall()
        for row in rows:
            run = strict_json(row['payload']); complete &= run['usage_complete']
            for name, counts in run.get('usage_by_model', {run['agent_model']: run['usage']}).items():
                for key, count in counts.items():
                    totals[key] = totals.get(key, 0) + count
                    rate = rates.get(name, {}).get(key)
                    if count and rate is None: unpriced.add(name + ':' + key)
                    elif rate is not None:
                        if type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0: raise ValueError('invalid pricing')
                        estimate += count * rate / 1000000
        return dict(runs=len(rows), tokens=totals, usage_complete=complete, estimated_token_cost=estimate,
                    pricing_version=pricing_version, unpriced=sorted(unpriced), includes_service_charges=False)

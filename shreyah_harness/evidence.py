"""Evidence attribution is enforced structurally; factual acceptance is host-owned."""
import hashlib
from uuid import uuid4
from .guardrails import canonical, strict_json


class Evidence:
    def __init__(self, storage): self.storage = storage

    def snapshot(self, origin, content, *, fetched_at=None):
        s = self.storage
        if not isinstance(origin, str) or not origin or not isinstance(content, str): raise ValueError('invalid source')
        origin, content = s.clean(origin), s.clean(content)
        fetched_at = s.now() if fetched_at is None else fetched_at
        import math
        if type(fetched_at) not in (int, float) or not math.isfinite(fetched_at): raise ValueError('invalid timestamp')
        digest = hashlib.sha256(content.encode()).hexdigest()
        source_id = hashlib.sha256(canonical([origin, fetched_at, digest]).encode()).hexdigest()
        with s.transaction() as db:
            db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?)', (s.scope, source_id, origin, fetched_at, digest, content))
        return source_id

    def source(self, source_id):
        row = self.storage.db.execute('SELECT id,origin,fetched,hash,content FROM sources WHERE scope=? AND id=?', (self.storage.scope, source_id)).fetchone()
        if row is None: raise KeyError('source missing in scope')
        data = dict(row)
        if hashlib.sha256(data['content'].encode()).hexdigest() != data['hash']: raise ValueError('source integrity failure')
        return data

    def observe(self, *, record_id, record_version, field, value, extractor, validator,
                status, source_id=None, excerpt=''):
        s = self.storage
        s.record(record_id, record_version)
        if status not in {'supported', 'unknown', 'conflicting', 'needs_review'}: raise ValueError('invalid status')
        if any(not isinstance(v, str) or not v for v in (field, extractor, validator)): raise ValueError('claim versions required')
        excerpt = s.clean(excerpt)
        if not isinstance(excerpt, str): raise ValueError('excerpt must be text')
        if source_id:
            source = self.source(source_id)
            if not excerpt or excerpt not in source['content']: raise ValueError('evidence span missing')
        elif status != 'unknown' or value is not None:
            raise ValueError('no evidence requires unknown null')
        observation_id = uuid4().hex
        with s.transaction() as db:
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (s.scope, observation_id, record_id, record_version, field, canonical(s.clean(value)),
                        source_id, excerpt, extractor, validator, status, s.now()))
        return observation_id

    def observation(self, observation_id):
        row = self.storage.db.execute('SELECT * FROM observations WHERE scope=? AND id=?', (self.storage.scope, observation_id)).fetchone()
        if row is None: raise KeyError('observation missing in scope')
        data = dict(row); data.pop('scope'); data['value'] = strict_json(data['value'])
        if data['source_id']:
            src = self.source(data['source_id'])
            if not data['excerpt'] or data['excerpt'] not in src['content']: raise ValueError('evidence integrity failure')
        return data

    def accept(self, observation_id, *, policy, reviewer, validate):
        s = self.storage; observation = self.observation(observation_id)
        if observation['status'] != 'supported' or not policy or not reviewer: raise ValueError('unsupported acceptance')
        before = canonical(observation)
        if validate(observation) is not True or canonical(observation) != before:
            raise ValueError('acceptance validator must explicitly approve unchanged evidence')
        acceptance_id = uuid4().hex
        with s.transaction() as db:
            db.execute('INSERT INTO acceptances VALUES(?,?,?,?,?,?,?)',
                       (s.scope, acceptance_id, observation_id, policy, reviewer, s.now(), None))
        return acceptance_id

    def accepted(self, acceptance_id, *, max_age):
        s = self.storage
        if type(max_age) not in (int, float) or not 0 <= max_age < float('inf'): raise ValueError('freshness bound required')
        row = s.db.execute('SELECT * FROM acceptances WHERE scope=? AND id=? AND revoked IS NULL', (s.scope, acceptance_id)).fetchone()
        if row is None: raise KeyError('active acceptance missing')
        data = self.observation(row['observation_id']); source = self.source(data['source_id'])
        if not 0 <= s.now() - source['fetched'] <= max_age: raise ValueError('evidence stale or future dated')
        return dict(acceptance_id=acceptance_id, policy=row['policy'], reviewer=row['reviewer'], observation=data)

    def revoke(self, acceptance_id):
        s = self.storage
        with s.transaction() as db:
            cur = db.execute('UPDATE acceptances SET revoked=? WHERE scope=? AND id=? AND revoked IS NULL', (s.now(), s.scope, acceptance_id))
            if cur.rowcount != 1: raise KeyError('active acceptance missing')

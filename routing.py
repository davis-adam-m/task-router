"""Durable simulated routing and guarded workflow transitions."""
import logging
import random
import threading
import time
from db import transaction

AREAS = ('finance', 'healthcare', 'data analysis', 'operations')
SCENARIOS = ('random', 'match', 'no_match', 'unresolved')


class Router:
    def __init__(self, path, clock=time.time, rng=None):
        self.path, self.clock, self.rng = path, clock, rng or random.Random()

    def event(self, c, tid, message):
        c.execute('INSERT INTO events(task_id,created,message) VALUES (?,?,?)',(tid,self.clock(),message))

    def task(self, c, tid):
        row = c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
        if row is None:
            raise ValueError('Task does not exist.')
        return row

    def create(self, title, area, priority):
        title = title.strip()
        if not title or len(title)>160 or area not in AREAS or priority not in ('Normal','High'):
            raise ValueError('Enter a title (1–160 characters), expertise, and priority.')
        with transaction(self.path) as c:
            tid = c.execute('INSERT INTO tasks(title,area,priority,created) VALUES (?,?,?,?)',(title,area,priority,self.clock())).lastrowid
            self.event(c,tid,'Task created; ready to route.')
        return tid

    def submit(self, tid, scenario='random'):
        if scenario not in SCENARIOS:
            raise ValueError('Unknown demo scenario.')
        with transaction(self.path) as c:
            task = self.task(c,tid)
            if task['state']=='accepted':
                raise ValueError('Reopen the accepted task before routing again.')
            candidates = [r[0] for r in c.execute('SELECT contributor_id FROM expertise WHERE area=?',(task['area'],))]
            candidate = self.rng.choice(candidates) if candidates else None
            unresolved = scenario=='unresolved' or (scenario=='random' and self.rng.random()<0.2)
            due = None if unresolved else self.clock()+self.rng.uniform(5,20)
            if scenario=='no_match':
                candidate = None
            rid = c.execute('INSERT INTO requests(task_id,created,due,candidate) VALUES (?,?,?,?)',(tid,self.clock(),due,candidate)).lastrowid
            c.execute("UPDATE assignments SET state='replaced' WHERE task_id=? AND state IN ('offered','accepted')",(tid,))
            c.execute("UPDATE tasks SET state='routing',current_request=? WHERE id=?",(rid,tid))
            self.event(c,tid,f'Routing request #{rid} submitted; previous request/offer superseded.' + (f' Demo control: {scenario}.' if scenario!='random' else ''))

    def assign(self, tid, cid):
        with transaction(self.path) as c:
            task = self.task(c,tid)
            if task['state']=='accepted':
                raise ValueError('Reopen the accepted task before changing its assignment.')
            if not c.execute('SELECT 1 FROM expertise WHERE contributor_id=? AND area=?',(cid,task['area'])).fetchone():
                raise ValueError('Choose a contributor with matching expertise.')
            c.execute("UPDATE assignments SET state='replaced' WHERE task_id=? AND state='offered'",(tid,))
            c.execute("INSERT INTO assignments(task_id,contributor_id,state) VALUES (?,?,'offered')",(tid,cid))
            c.execute("UPDATE tasks SET state='offered',current_request=NULL WHERE id=?",(tid,))
            self.event(c,tid,f'Operator offered assignment to contributor #{cid}; outstanding routing superseded.')

    def transition(self, tid, action, reason='', expected_assignment=None):
        if action not in ('accept','decline','fail','reopen'):
            raise ValueError('Unknown action.')
        if action in ('decline','fail','reopen') and not reason.strip():
            raise ValueError('A reason is required for this action.')
        if len(reason)>500:
            raise ValueError('Keep the reason within 500 characters.')
        with transaction(self.path) as c:
            task = self.task(c,tid)
            if expected_assignment is not None:
                active = c.execute("SELECT id FROM assignments WHERE task_id=? AND state IN ('offered','accepted')",(tid,)).fetchone()
                if active is None or active['id'] != expected_assignment:
                    raise ValueError('This offer changed since the page was loaded. Review the current assignment before responding.')
            if action=='reopen':
                if task['state']!='accepted':
                    raise ValueError('Only accepted tasks can be reopened.')
                state, target = 'reopened','ready'
            else:
                if task['state']!='offered':
                    raise ValueError('This action requires an outstanding assignment offer.')
                state = {'accept':'accepted','decline':'declined','fail':'failed'}[action]
                target = state if action=='accept' else 'ready'
            c.execute("UPDATE assignments SET state=? WHERE task_id=? AND state IN ('offered','accepted')",(state,tid))
            c.execute('UPDATE tasks SET state=?,current_request=NULL WHERE id=?',(target,tid))
            self.event(c,tid,f'Operator recorded {state}.' + (f' Reason: {reason.strip()}' if reason.strip() else ' Routing complete.'))

    def tick(self):
        with transaction(self.path) as c:
            rows = c.execute('SELECT * FROM requests WHERE processed=0 AND due IS NOT NULL AND due<=? ORDER BY id',(self.clock(),)).fetchall()
            for req in rows:
                task = self.task(c,req['task_id'])
                if task['current_request']!=req['id'] or task['state']!='routing':
                    self.event(c,task['id'],f"Ignored stale result from routing request #{req['id']}; current assignment unchanged.")
                elif req['candidate'] is None:
                    c.execute("UPDATE tasks SET state='no_match',current_request=NULL WHERE id=?",(task['id'],))
                    self.event(c,task['id'],f"Routing request #{req['id']} returned no match.")
                else:
                    c.execute("INSERT INTO assignments(task_id,contributor_id,state) VALUES (?,?,'offered')",(task['id'],req['candidate']))
                    c.execute("UPDATE tasks SET state='offered',current_request=NULL WHERE id=?",(task['id'],))
                    self.event(c,task['id'],f"Routing request #{req['id']} offered contributor #{req['candidate']}.")
                c.execute('UPDATE requests SET processed=1 WHERE id=?',(req['id'],))


def start_worker(router):
    stop = threading.Event()
    def run():
        while not stop.is_set():
            try:
                router.tick()
            except Exception:
                logging.exception('Routing worker tick failed; will retry')
            stop.wait(0.5)
    thread = threading.Thread(target=run, name='routing-worker', daemon=True)
    thread.start()
    return stop, thread

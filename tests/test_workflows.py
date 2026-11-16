import random
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from app import create_app
from db import initialize, seed, transaction
from routing import Router, start_worker


class Fixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name)/'test.sqlite3')
        initialize(self.path)
        seed(self.path,1000)
        self.now = 1000
        self.router = Router(self.path,lambda:self.now,random.Random(7))
        self.tid = self.router.create('Test task','finance','High')

    def rows(self,sql,args=()):
        with transaction(self.path) as c:
            return c.execute(sql,args).fetchall()

    def state(self):
        return self.rows('SELECT state FROM tasks WHERE id=?',(self.tid,))[0][0]

    def advance(self):
        self.now += 21
        self.router.tick()


class Workflows(Fixture, unittest.TestCase):
    def test_routine_accept_and_explicit_reopen(self):
        self.router.submit(self.tid,'match')
        self.assertEqual(self.state(),'routing')
        self.advance()
        self.assertEqual(self.state(),'offered')
        self.router.transition(self.tid,'accept')
        for operation in [lambda:self.router.submit(self.tid),lambda:self.router.assign(self.tid,1)]:
            with self.assertRaises(ValueError): operation()
        with self.assertRaises(ValueError): self.router.transition(self.tid,'reopen')
        self.router.transition(self.tid,'reopen','Scope changed')
        self.assertEqual(self.state(),'ready')
        self.assertIn('Scope changed',self.rows('SELECT message FROM events ORDER BY id DESC')[0][0])

    def test_unresolved_stays_pending(self):
        self.router.submit(self.tid,'unresolved')
        self.now += 100000
        self.router.tick()
        self.assertEqual(self.state(),'routing')
        self.router.assign(self.tid,1)
        self.assertEqual(self.state(),'offered')

    def test_stale_result_after_manual_assignment_and_acceptance(self):
        self.router.submit(self.tid,'match')
        self.router.assign(self.tid,1)
        self.router.transition(self.tid,'accept')
        self.advance()
        self.assertEqual(self.state(),'accepted')
        self.assertEqual(len(self.rows("SELECT * FROM assignments WHERE task_id=? AND state IN ('offered','accepted')",(self.tid,))),1)
        self.assertEqual(len(self.rows("SELECT * FROM events WHERE message LIKE 'Ignored stale%'")),1)
        self.router.tick()
        self.assertEqual(len(self.rows("SELECT * FROM events WHERE message LIKE 'Ignored stale%'")),1)

    def test_retry_supersedes_pending_and_offer(self):
        self.router.submit(self.tid,'match')
        self.router.submit(self.tid,'no_match')
        self.advance()
        self.assertEqual(self.state(),'no_match')
        self.assertEqual(len(self.rows('SELECT * FROM assignments WHERE task_id=?',(self.tid,))),0)
        self.router.assign(self.tid,1)
        self.router.submit(self.tid,'match')
        self.assertEqual(self.rows('SELECT state FROM assignments WHERE task_id=?',(self.tid,))[0][0],'replaced')
        self.advance()
        self.assertEqual(self.state(),'offered')

    def test_decline_and_failure_recovery(self):
        for action in ('decline','fail'):
            self.router.assign(self.tid,1)
            with self.assertRaises(ValueError): self.router.transition(self.tid,action)
            self.router.transition(self.tid,action,'Unavailable')
            self.assertEqual(self.state(),'ready')
        self.router.submit(self.tid,'match')
        self.advance()
        self.assertEqual(self.state(),'offered')

    def test_restart_preserves_outcomes_and_unresolved_requests(self):
        self.router.submit(self.tid,'match')
        other = self.router.create('Other','healthcare','Normal')
        self.router.submit(other,'unresolved')
        before = [tuple(r) for r in self.rows('SELECT * FROM requests')]
        initialize(self.path)
        seed(self.path,self.now)
        restarted = Router(self.path,lambda:1021)
        self.assertEqual(before,[tuple(r) for r in self.rows('SELECT * FROM requests')])
        restarted.tick()
        self.assertEqual(self.state(),'offered')
        self.assertEqual(self.rows('SELECT state FROM tasks WHERE id=?',(other,))[0][0],'routing')

    def test_transaction_rolls_back_assignment_if_history_write_fails(self):
        with transaction(self.path) as c:
            c.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.router.assign(self.tid,1)
        self.assertEqual(self.state(),'ready')
        self.assertEqual(self.rows('SELECT count(*) FROM assignments')[0][0],0)

    def test_database_enforces_one_active_assignment(self):
        self.router.assign(self.tid,1)
        with self.assertRaises(sqlite3.IntegrityError):
            with transaction(self.path) as c:
                c.execute("INSERT INTO assignments(task_id,contributor_id,state) VALUES (?,1,'accepted')",(self.tid,))

    def test_concurrent_routing_and_intervention(self):
        tids = [self.router.create(str(i),'finance','Normal') for i in range(8)]
        errors = []
        def submit(tid):
            try: self.router.submit(tid,'match')
            except Exception as e: errors.append(e)
        threads = [threading.Thread(target=submit,args=(tid,)) for tid in tids]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors,[])
        self.now += 21
        def intervene():
            try: self.router.assign(tids[0],1)
            except Exception as e: errors.append(e)
        threads = [threading.Thread(target=self.router.tick),threading.Thread(target=intervene)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors,[])
        self.assertEqual(self.rows("SELECT count(*) FROM assignments WHERE state='offered'")[0][0],8)

    def test_worker_progresses_without_browser(self):
        self.router.submit(self.tid,'match')
        self.now += 21
        stop,thread = start_worker(self.router)
        try:
            deadline = time.monotonic()+3
            while self.state()!='offered' and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertEqual(self.state(),'offered')
        finally:
            stop.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_validation_and_expertise(self):
        for args in [('', 'finance','Normal'),('x','unknown','Normal'),('x','finance','urgent')]:
            with self.assertRaises(ValueError): self.router.create(*args)
        with self.assertRaises(ValueError): self.router.assign(self.tid,2)
        with self.assertRaises(ValueError): self.router.transition(self.tid,'accept')
        self.assertEqual(self.state(),'ready')

    def test_outdated_offer_response_does_not_accept_replacement(self):
        self.router.assign(self.tid,1)
        old = self.rows('SELECT id FROM assignments WHERE task_id=?',(self.tid,))[0][0]
        self.router.assign(self.tid,1)
        with self.assertRaises(ValueError):
            self.router.transition(self.tid,'accept',expected_assignment=old)
        self.assertEqual(self.state(),'offered')

    def test_random_engine_probability_and_delay_contract(self):
        for _ in range(200): self.router.submit(self.tid)
        requests = self.rows('SELECT due,created FROM requests')
        never = sum(r['due'] is None for r in requests)
        self.assertTrue(20<never<65)
        self.assertTrue(all(5<=r['due']-r['created']<=20 for r in requests if r['due'] is not None))


class Web(Fixture, unittest.TestCase):
    def test_operator_routes_and_assignment_identity(self):
        client = create_app(self.path,testing=True).test_client()
        client.get('/')
        with client.session_transaction() as s: token = s['csrf']
        def post(action, **data):
            return client.post(f'/tasks/{self.tid}/{action}',data={'csrf':token,**data},follow_redirects=True)
        self.assertIn(b'Action recorded',post('assign',contributor='1').data)
        old = self.rows('SELECT id FROM assignments WHERE task_id=?',(self.tid,))[0][0]
        self.assertIn(b'Action recorded',post('assign',contributor='1').data)
        self.assertIn(b'offer changed',post('accept',assignment=old).data)
        current = self.rows("SELECT id FROM assignments WHERE task_id=? AND state='offered'",(self.tid,))[0][0]
        self.assertIn(b'Routing is complete',post('accept',assignment=current).data)
        self.assertIn(b'Reopen the accepted task',post('route').data)
        self.assertIn(b'Action recorded',post('reopen',assignment=current,reason='New scope').data)
        self.assertEqual(self.state(),'ready')

    def test_pages_forms_csrf_and_hidden_outcomes(self):
        app = create_app(self.path,testing=True)
        client = app.test_client()
        response = client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertNotIn(b'http-equiv="refresh"',response.data)
        with client.session_transaction() as s: token = s['csrf']
        self.assertEqual(client.post('/tasks',data={'title':'Bad'}).status_code,400)
        response = client.post('/tasks',data={'csrf':token,'title':'Web task','area':'finance','priority':'High'})
        self.assertEqual(response.status_code,302)
        page = client.get(response.location)
        self.assertIn(b'Routing pending',page.data)
        self.assertIn(b'Deterministic demo controls',page.data)
        self.assertNotIn(b'candidate',page.data)
        self.assertNotIn(b'name="due"',page.data)
        self.assertEqual(client.get('/tasks/99999').status_code,404)
        invalid = client.post('/tasks',data={'csrf':token,'title':'Preserved title','area':'bad','priority':'Normal'})
        self.assertEqual(invalid.status_code,400)
        self.assertIn(b'Preserved title',invalid.data)


if __name__=='__main__':
    unittest.main()

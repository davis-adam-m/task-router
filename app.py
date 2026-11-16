import secrets
import time
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from db import initialize, seed, transaction
from routing import AREAS, Router, start_worker


def create_app(database=None, testing=False):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), TESTING=testing,
                      MAX_CONTENT_LENGTH=16384, SESSION_COOKIE_SAMESITE='Strict')
    path = str(database or Path(__file__).parent / 'instance' / 'router.sqlite3')
    initialize(path)
    seed(path, time.time())
    router = Router(path)
    app.extensions['router'] = router

    @app.before_request
    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(24)
        if request.method=='POST' and not secrets.compare_digest(session['csrf'],request.form.get('csrf','')):
            abort(400, 'Invalid form token. Reload the page and try again.')

    @app.template_filter('age')
    def age(value):
        seconds = max(0,int(time.time()-value))
        if seconds<60:
            return f'{seconds}s'
        if seconds<3600:
            return f'{seconds//60}m {seconds%60}s'
        return f'{seconds//3600}h {(seconds%3600)//60}m'

    @app.template_filter('timestamp')
    def timestamp(value):
        return time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(value))

    def contributors(c):
        return c.execute("SELECT c.id,c.name,group_concat(e.area, ', ') AS areas FROM contributors c JOIN expertise e ON e.contributor_id=c.id GROUP BY c.id ORDER BY c.name").fetchall()

    @app.get('/')
    def index():
        with transaction(path) as c:
            tasks = c.execute("SELECT t.*,c.name AS assignee,r.created AS requested FROM tasks t LEFT JOIN assignments a ON a.task_id=t.id AND a.state IN ('offered','accepted') LEFT JOIN contributors c ON c.id=a.contributor_id LEFT JOIN requests r ON r.id=t.current_request ORDER BY CASE t.priority WHEN 'High' THEN 0 ELSE 1 END,t.created").fetchall()
            people = contributors(c)
        return render_template('index.html',tasks=tasks,people=people,areas=AREAS)

    @app.post('/tasks')
    def create():
        try:
            tid = router.create(request.form.get('title',''),request.form.get('area',''),request.form.get('priority',''))
            router.submit(tid)
        except ValueError as e:
            flash(str(e),'error')
            return render_template('create_error.html',areas=AREAS),400
        flash('Task created and submitted for routing.','success')
        return redirect(url_for('detail',tid=tid))

    @app.get('/tasks/<int:tid>')
    def detail(tid):
        with transaction(path) as c:
            task = c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if task is None:
                abort(404)
            offer = c.execute("SELECT a.*,c.name FROM assignments a JOIN contributors c ON c.id=a.contributor_id WHERE task_id=? AND a.state IN ('offered','accepted')",(tid,)).fetchone()
            eligible = c.execute('SELECT c.* FROM contributors c JOIN expertise e ON e.contributor_id=c.id WHERE e.area=? ORDER BY c.name',(task['area'],)).fetchall()
            events = c.execute('SELECT * FROM events WHERE task_id=? ORDER BY id DESC',(tid,)).fetchall()
            pending = c.execute('SELECT created FROM requests WHERE id=?',(task['current_request'],)).fetchone()
        return render_template('detail.html',task=task,offer=offer,eligible=eligible,events=events,pending=pending)

    @app.post('/tasks/<int:tid>/<action>')
    def act(tid,action):
        try:
            if action=='route':
                router.submit(tid,request.form.get('scenario','random'))
            elif action=='assign':
                router.assign(tid,int(request.form.get('contributor','0')))
            else:
                router.transition(tid,action,request.form.get('reason',''),
                                  expected_assignment=int(request.form.get('assignment','0')))
            flash('Action recorded.','success')
        except ValueError as e:
            flash(str(e),'error')
        return redirect(url_for('detail',tid=tid))
    return app


if __name__=='__main__':
    # This entry point owns exactly one worker. Do not launch via flask run.
    app = create_app()
    stop, worker = start_worker(app.extensions['router'])
    try:
        app.run(host='127.0.0.1',port=5000,debug=False,use_reloader=False)
    finally:
        stop.set()
        worker.join(timeout=2)

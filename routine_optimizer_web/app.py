# app.py (FULL - replace your current app.py)
import os
import json
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, send_file, flash, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO

# ---------- Config ----------
APP_SECRET = os.environ.get("ROUTINE_SECRET") or os.urandom(24)
DATA_FILE = "data.json"
DATEFMT = "%Y-%m-%d %H:%M"   # storage format for tasks' due

app = Flask(__name__)
app.secret_key = APP_SECRET


# ---------- Helpers: load/save ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({
                "users": [], "tasks": [], "notes": [], "budgets": [], "habits": [],
                "settings": {"pomodoro_minutes": 25, "break_minutes": 5}
            }, f, indent=2)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, default=str)


def current_user():
    return session.get("user_id")


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not current_user():
            flash("Please login to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrap


# ---------- Authentication ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        data = load_data()
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        if not username or not password:
            flash("Provide username and password.", "danger")
            return redirect(url_for("register"))
        if any(u["username"] == username for u in data["users"]):
            flash("Username already exists.", "danger")
            return redirect(url_for("register"))
        user = {"id": uuid.uuid4().hex, "username": username, "pw": generate_password_hash(password), "prefs": {}}
        data["users"].append(user)
        save_data(data)
        flash("Account created. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("login_register.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = load_data()
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        user = next((u for u in data["users"] if u["username"] == username), None)
        if user and check_password_hash(user["pw"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Logged in.", "success")
            nxt = request.args.get("next") or url_for("index")
            return redirect(nxt)
        flash("Invalid credentials.", "danger")
        return redirect(url_for("login"))
    return render_template("login_register.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("index"))


# ---------- Index & Dashboard ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    data = load_data()
    user = current_user()
    tasks = [t for t in data["tasks"] if t.get("user_id") == user]
    budgets = [b for b in data["budgets"] if b.get("user_id") == user]
    habits = [h for h in data["habits"] if h.get("user_id") == user]

    counts = {
        "tasks_total": len(tasks),
        "tasks_pending": len([t for t in tasks if not t.get("completed")]),
        "budgets_count": len(budgets),
        "habits_count": len(habits)
    }
    return render_template("dashboard.html", counts=counts)


# ---------- TASKS CRUD & SEARCH & collab linking ---------
@app.route("/tasks")
@login_required
def tasks():
    data = load_data()
    user = current_user()
    tasks = [t for t in data["tasks"] if t.get("user_id") == user]
    q = request.args.get("q", "").strip().lower()
    if q:
        tasks = [t for t in tasks if q in (t.get("title","").lower() + " " + t.get("description","").lower() + " " + " ".join(t.get("tags",[])))]
    def score(t):
        pr = int(t.get("priority", 3))
        dur = int(t.get("duration", 30))
        s = pr * 20
        if dur <= 20: s -= 5
        due = t.get("due")
        if due:
            try:
                dt = datetime.strptime(due, DATEFMT)
                hours = (dt - datetime.now()).total_seconds()/3600
                if hours <= 0: s -= 50
                elif hours < 24: s -= 20
                elif hours < 72: s -=5
            except:
                pass
        return s
    tasks.sort(key=score)
    user_notes = [n for n in data["notes"] if n.get("user_id") == user]
    user_budgets = [b for b in data["budgets"] if b.get("user_id") == user]
    return render_template("tasks.html", tasks=tasks, q=q, notes=user_notes, budgets=user_budgets)


@app.route("/tasks/add", methods=["GET", "POST"])
@login_required
def add_task():
    data = load_data()
    user = current_user()
    if request.method == "POST":
        t = {
            "id": uuid.uuid4().hex,
            "user_id": user,
            "title": request.form.get("title","").strip(),
            "description": request.form.get("description","").strip(),
            "priority": int(request.form.get("priority") or 3),
            "duration": int(request.form.get("duration") or 30),
            "due": request.form.get("due") or None,
            "tags": [x.strip().lower() for x in (request.form.get("tags") or "").split(",") if x.strip()],
            "completed": False,
            "created_at": datetime.now().strftime(DATEFMT),
            "linked_note": request.form.get("linked_note") or None,
            "linked_budget": request.form.get("linked_budget") or None
        }
        data["tasks"].append(t)
        save_data(data)
        flash("Task added.", "success")
        return redirect(url_for("tasks"))
    user_notes = [n for n in data["notes"] if n.get("user_id") == user]
    user_budgets = [b for b in data["budgets"] if b.get("user_id") == user]
    return render_template("add_task.html", notes=user_notes, budgets=user_budgets)


@app.route("/tasks/edit/<tid>", methods=["GET", "POST"])
@login_required
def edit_task(tid):
    data = load_data()
    user = current_user()
    task = next((x for x in data["tasks"] if x["id"] == tid and x.get("user_id")==user), None)
    if not task:
        flash("Task not found.", "danger")
        return redirect(url_for("tasks"))
    if request.method == "POST":
        task["title"] = request.form.get("title","").strip()
        task["description"] = request.form.get("description","").strip()
        task["priority"] = int(request.form.get("priority") or 3)
        task["duration"] = int(request.form.get("duration") or 30)
        task["due"] = request.form.get("due") or None
        task["tags"] = [x.strip().lower() for x in (request.form.get("tags") or "").split(",") if x.strip()]
        task["completed"] = bool(request.form.get("completed"))
        task["linked_note"] = request.form.get("linked_note") or None
        task["linked_budget"] = request.form.get("linked_budget") or None
        save_data(data)
        flash("Task updated.", "success")
        return redirect(url_for("tasks"))
    user_notes = [n for n in data["notes"] if n.get("user_id") == user]
    user_budgets = [b for b in data["budgets"] if b.get("user_id") == user]
    return render_template("edit_task.html", task=task, notes=user_notes, budgets=user_budgets)


@app.route("/tasks/delete/<tid>")
@login_required
def delete_task(tid):
    data = load_data()
    user = current_user()
    data["tasks"] = [x for x in data["tasks"] if not (x["id"]==tid and x.get("user_id")==user)]
    save_data(data)
    flash("Task deleted.", "info")
    return redirect(url_for("tasks"))


@app.route("/tasks/toggle/<tid>")
@login_required
def toggle_task(tid):
    data = load_data()
    user = current_user()
    t = next((x for x in data["tasks"] if x["id"]==tid and x.get("user_id")==user), None)
    if t:
        t["completed"] = not t.get("completed", False)
        save_data(data)
    return redirect(url_for("tasks"))


# ---------- NOTES with tags ----------
@app.route("/notes")
@login_required
def notes():
    data = load_data()
    user = current_user()
    notes = [n for n in data["notes"] if n.get("user_id")==user]
    return render_template("notes.html", notes=notes)


@app.route("/notes/add", methods=["GET","POST"])
@login_required
def add_note():
    if request.method == "POST":
        data = load_data()
        user = current_user()
        n = {
            "id": uuid.uuid4().hex,
            "user_id": user,
            "title": request.form.get("title","").strip(),
            "content": request.form.get("content","").strip(),
            "tags": [t.strip().lower() for t in (request.form.get("tags") or "").split(",") if t.strip()],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        data["notes"].append(n)
        save_data(data)
        flash("Note added.", "success")
        return redirect(url_for("notes"))
    return render_template("add_note.html")


@app.route("/notes/delete/<nid>")
@login_required
def delete_note(nid):
    data = load_data()
    user = current_user()
    data["notes"] = [n for n in data["notes"] if not (n["id"]==nid and n.get("user_id")==user)]
    save_data(data)
    flash("Note deleted.", "info")
    return redirect(url_for("notes"))


# ---------- BUDGET ----------
@app.route("/budget")
@login_required
def budget():
    data = load_data()
    user = current_user()
    budgets = sorted([b for b in data["budgets"] if b.get("user_id")==user], key=lambda x: x["timestamp"], reverse=True)
    return render_template("budget.html", budgets=budgets)


@app.route("/budget/add", methods=["GET","POST"])
@login_required
def add_budget():
    if request.method == "POST":
        data = load_data()
        user = current_user()
        b = {
            "id": uuid.uuid4().hex,
            "user_id": user,
            "category": request.form.get("category","").strip(),
            "amount": float(request.form.get("amount") or 0),
            "note": request.form.get("note","").strip(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        data["budgets"].append(b)
        save_data(data)
        flash("Budget entry added.", "success")
        return redirect(url_for("budget"))
    return render_template("add_budget.html")


@app.route("/budget/delete/<bid>")
@login_required
def delete_budget(bid):
    data = load_data()
    user = current_user()
    data["budgets"] = [b for b in data["budgets"] if not (b["id"]==bid and b.get("user_id")==user)]
    save_data(data)
    flash("Deleted budget entry.", "info")
    return redirect(url_for("budget"))


@app.route("/api/budget_summary")
@login_required
def api_budget_summary():
    data = load_data()
    user = current_user()
    now = datetime.now()
    year = now.year
    this_month = now.month
    cat_totals = {}
    month_totals = {}
    for b in data["budgets"]:
        if b.get("user_id") != user:
            continue
        try:
            dt = datetime.strptime(b["timestamp"], "%Y-%m-%d %H:%M:%S")
        except:
            try:
                dt = datetime.strptime(b["timestamp"], "%Y-%m-%d %H:%M")
            except:
                continue
        if dt.year == year and dt.month == this_month:
            cat_totals[b["category"]] = cat_totals.get(b["category"], 0) + b["amount"]
        key = dt.strftime("%Y-%m")
        month_totals[key] = month_totals.get(key, 0) + b["amount"]
    return jsonify({"categories": cat_totals, "months": month_totals})


# ---------- HABITS ----------
@app.route("/habits")
@login_required
def habits():
    data = load_data()
    user = current_user()
    habits = [h for h in data["habits"] if h.get("user_id")==user]
    report = []
    for h in habits:
        done_dates = h.get("done_dates", [])
        cnt = sum(1 for d in done_dates if d and datetime.strptime(d, "%Y-%m-%d %H:%M:%S") >= datetime.now() - timedelta(days=7))
        report.append({"habit": h, "last7": cnt})
    return render_template("habits.html", report=report, habits=habits)


@app.route("/habits/add", methods=["GET","POST"])
@login_required
def add_habit():
    if request.method == "POST":
        user = current_user()
        data = load_data()
        h = {
            "id": uuid.uuid4().hex,
            "user_id": user,
            "name": request.form.get("name","").strip(),
            "target_per_week": int(request.form.get("target") or 3),
            "streak": int(request.form.get("streak") or 0),
            "done_dates": []
        }
        data["habits"].append(h)
        save_data(data)
        flash("Habit added.", "success")
        return redirect(url_for("habits"))
    return render_template("add_habit.html")


@app.route("/habits/done/<hid>")
@login_required
def habit_done(hid):
    data = load_data()
    user = current_user()
    h = next((x for x in data["habits"] if x["id"]==hid and x.get("user_id")==user), None)
    if h:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        h.setdefault("done_dates", []).append(ts)
        h["streak"] = h.get("streak",0) + 1
        save_data(data)
        flash("Marked habit done.", "success")
    return redirect(url_for("habits"))


# ---------- EVENTS API (FullCalendar) - tasks+budgets+notes ----------
def _parse_iso(dtstr):
    if not dtstr:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(dtstr, fmt)
        except:
            pass
    return None


@app.route("/api/events", methods=["GET", "POST"])
@login_required
def api_events():
    data = load_data()
    user = current_user()
    if request.method == "GET":
        events = []
        # tasks
        for t in data["tasks"]:
            if t.get("user_id") != user or not t.get("due"):
                continue
            try:
                dt = datetime.strptime(t["due"], DATEFMT)
                start = dt.strftime("%Y-%m-%dT%H:%M:%S")
                end = (dt + timedelta(minutes=int(t.get("duration",30)))).strftime("%Y-%m-%dT%H:%M:%S")
                events.append({"id": t["id"], "title": t["title"], "start": start, "end": end, "allDay": False, "type":"task"})
            except:
                continue
        # budgets
        for b in data["budgets"]:
            if b.get("user_id") != user:
                continue
            try:
                dt = datetime.strptime(b["timestamp"], "%Y-%m-%d %H:%M:%S")
            except:
                try:
                    dt = datetime.strptime(b["timestamp"], "%Y-%m-%d %H:%M")
                except:
                    continue
            start = dt.strftime("%Y-%m-%dT%H:%M:%S")
            end = (dt + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
            events.append({"id": b["id"], "title": f"Budget: {b['category']} ({b['amount']})", "start": start, "end": end, "allDay": False, "type":"budget"})
        # notes
        for n in data["notes"]:
            if n.get("user_id") != user:
                continue
            try:
                dt = datetime.strptime(n["timestamp"], "%Y-%m-%d %H:%M:%S")
            except:
                try:
                    dt = datetime.strptime(n["timestamp"], "%Y-%m-%d %H:%M")
                except:
                    continue
            start = dt.strftime("%Y-%m-%dT%H:%M:%S")
            events.append({"id": n["id"], "title": f"Note: {n['title']}", "start": start, "end": (dt + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"), "allDay": False, "type":"note"})
        return jsonify(events)
    else:
        payload = request.get_json() or {}
        title = payload.get("title","New event")
        start = payload.get("start")
        end = payload.get("end")
        dt_start = _parse_iso(start)
        if not dt_start:
            return jsonify({"error":"invalid start"}), 400
        duration = 30
        if end:
            dt_end = _parse_iso(end)
            if dt_end:
                duration = int((dt_end - dt_start).total_seconds() / 60)
        data = load_data()
        user = current_user()
        t = {
            "id": uuid.uuid4().hex,
            "user_id": user,
            "title": title,
            "description": payload.get("description",""),
            "priority": int(payload.get("priority") or 3),
            "duration": duration,
            "due": dt_start.strftime(DATEFMT),
            "tags": payload.get("tags", []),
            "completed": False,
            "created_at": datetime.now().strftime(DATEFMT),
            "linked_note": payload.get("linked_note") or None,
            "linked_budget": payload.get("linked_budget") or None
        }
        data["tasks"].append(t)
        save_data(data)
        return jsonify({"id": t["id"], "title": t["title"], "start": dt_start.strftime("%Y-%m-%dT%H:%M:%S"), "end": (dt_start + timedelta(minutes=duration)).strftime("%Y-%m-%dT%H:%M:%S")}), 201


@app.route("/api/events/<eid>", methods=["PUT", "DELETE"])
@login_required
def api_event_modify(eid):
    data = load_data()
    user = current_user()
    t = next((x for x in data["tasks"] if x["id"]==eid and x.get("user_id")==user), None)
    if not t:
        return jsonify({"error":"not found"}), 404
    if request.method == "DELETE":
        data["tasks"] = [x for x in data["tasks"] if not (x["id"]==eid and x.get("user_id")==user)]
        save_data(data)
        return jsonify({"deleted": True})
    else:
        payload = request.get_json() or {}
        if payload.get("title") is not None:
            t["title"] = payload["title"]
        if payload.get("start"):
            dt = _parse_iso(payload["start"])
            if dt:
                t["due"] = dt.strftime(DATEFMT)
        if payload.get("end"):
            dt_end = _parse_iso(payload["end"])
            if dt_end and t.get("due"):
                dt_start = datetime.strptime(t["due"], DATEFMT)
                t["duration"] = int((dt_end - dt_start).total_seconds() / 60)
        if "completed" in payload:
            t["completed"] = bool(payload["completed"])
        if "linked_note" in payload:
            t["linked_note"] = payload.get("linked_note")
        if "linked_budget" in payload:
            t["linked_budget"] = payload.get("linked_budget")
        save_data(data)
        return jsonify({"updated": True})


# ---------- Calendar page (renders calendar.html) ----------
@app.route("/calendar")
@login_required
def calendar_view():
    return render_template("calendar.html")


# ---------- Unified search endpoint ----------
@app.route("/search")
@login_required
def unified_search():
    q = request.args.get("q","").strip().lower()
    data = load_data()
    user = current_user()
    results = {"tasks":[], "notes":[], "budgets":[]}
    if not q:
        return render_template("search.html", q="", results=results)
    for t in data["tasks"]:
        if t.get("user_id") != user: continue
        hay = (t.get("title","") + " " + t.get("description","") + " " + " ".join(t.get("tags",[]))).lower()
        if q in hay:
            results["tasks"].append(t)
    for n in data["notes"]:
        if n.get("user_id") != user: continue
        hay = (n.get("title","") + " " + n.get("content","") + " " + " ".join(n.get("tags",[]))).lower()
        if q in hay:
            results["notes"].append(n)
    for b in data["budgets"]:
        if b.get("user_id") != user: continue
        hay = (b.get("category","") + " " + b.get("note","")).lower()
        if q in hay:
            results["budgets"].append(b)
    return render_template("search.html", q=q, results=results)


# ---------- ICS export ----------
@app.route("/export_ics")
@login_required
def export_ics():
    data = load_data()
    user = current_user()
    events = []
    for t in data["tasks"]:
        if t.get("user_id") != user or not t.get("due"):
            continue
        try:
            start = datetime.strptime(t["due"], DATEFMT)
        except:
            continue
        end = start + timedelta(minutes=int(t.get("duration",30)))
        ev = ("BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{stamp}\nDTSTART:{start}\nDTEND:{end}\nSUMMARY:{title}\nDESCRIPTION:{desc}\nEND:VEVENT\n").format(
            uid=t["id"],
            stamp=datetime.now().strftime("%Y%m%dT%H%M%S"),
            start=start.strftime("%Y%m%dT%H%M%S"),
            end=end.strftime("%Y%m%dT%H%M%S"),
            title=t["title"],
            desc=t.get("description","")
        )
        events.append(ev)
    cal = "BEGIN:VCALENDAR\nVERSION:2.0\n" + "".join(events) + "END:VCALENDAR\n"
    bio = BytesIO(cal.encode("utf-8"))
    return send_file(bio, download_name="tasks_export.ics", as_attachment=True)


# ---------- Dev seed (creates sample user + sample events) ----------
@app.route("/dev/seed")
def dev_seed():
    # allow only in non-production to avoid accidental use
    if os.environ.get("FLASK_ENV") == "production":
        abort(403)
    data = load_data()
    # create test user if not exists
    test_user = next((u for u in data["users"] if u["username"] == "demo"), None)
    if not test_user:
        test_user = {"id": uuid.uuid4().hex, "username": "demo", "pw": generate_password_hash("demo"), "prefs": {}}
        data["users"].append(test_user)
    # create one note, one budget, two tasks
    uid = test_user["id"]
    now = datetime.now()
    # avoid duplicating many times: only add if no entries exist for demo
    existing_demo = any(t.get("user_id")==uid for t in data["tasks"])
    if not existing_demo:
        data["notes"].append({"id": uuid.uuid4().hex, "user_id": uid, "title":"Demo note", "content":"This is a demo note", "tags":["demo"], "timestamp": now.strftime("%Y-%m-%d %H:%M:%S")})
        data["budgets"].append({"id": uuid.uuid4().hex, "user_id": uid, "category":"Food", "amount": 350.0, "note":"Lunch", "timestamp": now.strftime("%Y-%m-%d %H:%M:%S")})
        # task due in 1 hour
        data["tasks"].append({"id": uuid.uuid4().hex, "user_id": uid, "title":"Demo task soon", "description":"Task due in 1 hour", "priority":2, "duration":30, "due": (now + timedelta(hours=1)).strftime(DATEFMT), "tags":["demo"], "completed":False, "created_at": now.strftime(DATEFMT), "linked_note": None, "linked_budget": None})
        # task due tomorrow
        data["tasks"].append({"id": uuid.uuid4().hex, "user_id": uid, "title":"Demo meeting", "description":"Meeting tomorrow", "priority":3, "duration":60, "due": (now + timedelta(days=1)).strftime(DATEFMT), "tags":["meeting"], "completed":False, "created_at": now.strftime(DATEFMT), "linked_note": None, "linked_budget": None})
        save_data(data)
    # return credentials so you can login quickly
    return jsonify({"msg":"seeded demo user and sample items", "username":"demo", "password":"demo"})


# ---------- Run ----------
if __name__ == "__main__":
    app.run(debug=True)
import os, sqlite3, functools
from flask import (Flask, request, redirect, url_for,
                   session, render_template, abort)
from flask_socketio import SocketIO, emit, join_room

# ── config ────────────────────────────────────────────────────────────────
APP_PASSWORD = os.getenv("EDIT_PASSWORD", "change-me!")
SECRET_KEY   = os.getenv("SECRET_KEY",   "dev-secret")
DB_FILE      = "pages.db"
FILENAME     = "undertale.html"

# ── init DB ───────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS pages
                    (filename TEXT PRIMARY KEY, content TEXT)""")
    cur = conn.execute("SELECT 1 FROM pages WHERE filename=?", (FILENAME,))
    if not cur.fetchone():
        conn.execute("INSERT INTO pages VALUES(?,?)",
                     (FILENAME, "<!-- start editing -->"))
        conn.commit()
    return conn

DB = init_db()

def get_content():
    return DB.execute("SELECT content FROM pages WHERE filename=?", (FILENAME,)) \
             .fetchone()[0]

def save_content(html):
    DB.execute("UPDATE pages SET content=? WHERE filename=?",
               (html, FILENAME))
    DB.commit()

# ── app & socket setup ───────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY
socketio = SocketIO(app, async_mode="eventlet")
ROOM = "all-editors"

def login_required(f):
    @functools.wraps(f)
    def wrapper(*a, **k):
        if not session.get("ok"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return wrapper

# ── routes ────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST" and request.form.get("pw") == APP_PASSWORD:
        session["ok"] = True
        return redirect(request.args.get("next", "/edit"))
    return render_template("login.html")

@app.route("/edit")
@login_required
def edit():
    return render_template("edit.html", initial=get_content())

@app.route(f"/{FILENAME}")
def view():
    html = get_content()
    return html

# ── WebSocket events ─────────────────────────────────────────────────────
@socketio.on("join")
def ws_join():
    join_room(ROOM)
    emit("init", {"content": get_content()})

@socketio.on("update")
def ws_update(data):
    html = data["content"]
    save_content(html)
    emit("update", {"content": html}, room=ROOM, include_self=False)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)

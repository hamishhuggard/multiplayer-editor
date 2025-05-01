"""
Tiny collaborative HTML editor for ONE file (undertale.html).

• GET /              → password form
• POST /             → set session + redirect to /edit
• GET /edit          → split screen: left editor (CodeMirror), right preview
• WebSocket /socket.io → live text sync across users + DB
• GET /undertale.html → read-only view of saved HTML
"""

import os, sqlite3, functools
from flask import (Flask, request, redirect, url_for,
                   session, render_template_string, abort)
from flask_socketio import SocketIO, emit, join_room

# ── config ───────────────────────────────────────────────────────────
APP_PASSWORD = os.getenv("EDIT_PASSWORD", "change-me!")    # shared password
SECRET_KEY   = os.getenv("SECRET_KEY",   "dev-secret")     # flask session
DB_FILE      = "pages.db"
FILENAME     = "undertale.html"

# ── minimal DB helper ────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS pages "
                 "(filename TEXT PRIMARY KEY, content TEXT)")
    # insert empty file if not present
    cur = conn.execute("SELECT 1 FROM pages WHERE filename=?", (FILENAME,))
    if not cur.fetchone():
        conn.execute("INSERT INTO pages VALUES (?, ?)", (FILENAME, "<!-- start editing -->"))
        conn.commit()
    return conn
DB = init_db()

def get_content():
    return DB.execute("SELECT content FROM pages WHERE filename=?", (FILENAME,)).fetchone()[0]

def save_content(html: str):
    DB.execute("UPDATE pages SET content=? WHERE filename=?", (html, FILENAME))
    DB.commit()

# ── Flask + SocketIO setup ───────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY
socketio = SocketIO(app, async_mode="eventlet")   # eventlet worker

def logged_in():
    return session.get("ok")

def login_required(fn):
    @functools.wraps(fn)
    def wrapped(*a, **kw):
        if not logged_in():
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapped

# ── routes ───────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pw") == APP_PASSWORD:
            session["ok"] = True
            return redirect(request.args.get("next", "/edit"))
    return render_template_string("""<!doctype html>
        <form style="margin:4rem auto;max-width:12rem" method="POST">
            <h3>Enter password</h3>
            <input name=pw type=password autofocus style="width:100%%"><br>
            <button style="margin-top:.5rem">Enter</button>
        </form>""")

@app.route("/edit")
@login_required
def edit():
    return render_template_string(TEMPLATE, initial=get_content())

@app.route(f"/{FILENAME}")
def view():
    html = get_content()
    return html  # raw HTML delivered

# ── WebSocket events ─────────────────────────────────────────────────
ROOM = "all-editors"      # single doc → single room

@socketio.on("join")
def ws_join():
    join_room(ROOM)
    emit("init", {"content": get_content()})  # send current state to newcomer

@socketio.on("update")
def ws_update(data):
    html = data["content"]
    save_content(html)
    emit("update", {"content": html}, room=ROOM, include_self=False)

# ── inline template ─────────────────────────────────────────────────
TEMPLATE = r"""
<!doctype html><html><head><meta charset="utf-8">
<title>undertale.html editor</title>

<link  href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.15/codemirror.min.css" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.15/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.15/mode/xml/xml.min.js"></script>
<script src="https://cdn.socket.io/4.7.4/socket.io.min.js"></script>

<style>
html, body {
  margin: 0;
  height: 100vh;
}
#wrap {
  display: flex;
  height: 100%;
}
#left, #right {
  width: 50vw;
  height: 100%;
}
#left {
  border-right: 1px solid #ccc;
}
.CodeMirror {
  height: 100% !important;
}
#preview {
  width: 100%;
  height: 100%;
  border: none;
}
</style>
</head>
<body>
<div id="wrap">
  <div id="wrap">
    <div id="left">
      <textarea id="ta">{{ initial }}</textarea>
    </div>
    <div id="right">
      <iframe id="preview"></iframe>
    </div>
  </div>
</div>

<script>
/* --- bootstrap CodeMirror --- */
const cm = CodeMirror.fromTextArea(document.getElementById("ta"),
  {mode:"text/html", lineNumbers:true});
const iframe = document.getElementById("preview");
function render(html){
  const d = iframe.contentWindow.document;
  d.open(); d.write(html); d.close();
}
render(cm.getValue());

/* --- Socket.IO setup --- */
const socket = io();
socket.emit("join");                 // join the single room

/* --- avoid feedback loop flag --- */
let fromRemote = false;

/* --- local → server --- */
cm.on("change", ()=>{
  if(fromRemote) return;             // ignore programmatic updates
  const html = cm.getValue();
  render(html);
  socket.emit("update", {content: html});
});

/* --- server → local --- */
socket.on("init", data=>{
  fromRemote = true;
  cm.setValue(data.content);
  render(data.content);
  fromRemote = false;
});
socket.on("update", data=>{
  fromRemote = true;
  cm.setValue(data.content);
  render(data.content);
  fromRemote = false;
});
</script>
</body></html>
"""

# ── run ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)

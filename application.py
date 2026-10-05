"""Student Skill Portfolio & Opportunity Matching System (Flask + optional AWS DynamoDB)."""
import os, uuid
from flask import Flask, request, session, redirect, url_for, render_template_string, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@portal.com").lower()
TABLES = ("students", "opportunities", "applications")


class Store:
    """In-memory by default; DynamoDB when USE_DYNAMODB=1 (tables SkillPortal-<name>, key 'id')."""
    def __init__(self):
        self.mem = {t: {} for t in TABLES}
        self.ddb = None
        if os.getenv("USE_DYNAMODB") == "1":
            import boto3
            self.ddb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "ap-south-1"))

    def _t(self, t): return self.ddb.Table(f"SkillPortal-{t}")
    def put(self, t, item):
        (self._t(t).put_item(Item=item) if self.ddb else self.mem[t].__setitem__(item["id"], item))
    def get(self, t, key):
        if self.ddb: return self._t(t).get_item(Key={"id": key}).get("Item")
        return self.mem[t].get(key)
    def all(self, t):
        return self._t(t).scan().get("Items", []) if self.ddb else list(self.mem[t].values())

db = Store()


def split(text):
    return [s.strip() for s in (text or "").replace("\n", ",").split(",") if s.strip()]


def match_score(student_skills, required_skills):
    """Percentage of required skills the student has (case-insensitive)."""
    req = {s.lower() for s in required_skills}
    if not req: return 0
    have = {s.lower() for s in student_skills}
    return round(100 * len(req & have) / len(req))


def me():
    return db.get("students", session["user"]) if "user" in session else None


PAGE = """<!doctype html><title>Skill Portal</title>
<style>body{font-family:system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;color:#222}
nav a{margin-right:1rem}.card{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:.7rem 0}
input,textarea,select{width:100%;padding:.4rem;margin:.2rem 0 .7rem}button{padding:.5rem 1rem}
.bar{background:#eee;border-radius:6px;height:10px}.bar i{display:block;height:10px;background:#2a9d5c;border-radius:6px}
.msg{background:#fff3cd;padding:.5rem;border-radius:6px}</style>
<nav><b>SkillPortal</b> <a href="/">Home</a>
{% if u %}<a href="/profile">Profile</a><a href="/opportunities">Opportunities</a><a href="/applications">Applications</a>
{% if u.role=='admin' %}<a href="/admin">Admin</a>{% endif %}<a href="/logout">Logout ({{u.name}})</a>
{% else %}<a href="/login">Login</a><a href="/register">Register</a>{% endif %}</nav><hr>
{% for m in get_flashed_messages() %}<p class="msg">{{m}}</p>{% endfor %}
{{ body|safe }}"""


def page(body_tpl, **ctx):
    from flask import render_template_string as r
    return r(PAGE, u=me(), body=r(body_tpl, **ctx))


@app.route("/")
def home():
    return page("<h2>Student Skill Portfolio &amp; Opportunity Matching</h2><p>Build your skill profile, get matched to internships, hackathons, workshops and projects, and apply in one click.</p>")


@app.route("/health")
def health(): return jsonify(status="ok")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        if db.get("students", email):
            flash("Email already registered."); return redirect(url_for("register"))
        db.put("students", {"id": email, "name": request.form["name"], "pw": generate_password_hash(request.form["password"]),
                            "role": "admin" if email == ADMIN_EMAIL else "student",
                            "skills": [], "projects": [], "certificates": [], "interests": []})
        session["user"] = email
        return redirect(url_for("profile"))
    return page("""<h3>Register</h3><form method=post>Name<input name=name required>Email<input name=email type=email required>
        Password<input name=password type=password required><button>Create account</button></form>""")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db.get("students", request.form["email"].strip().lower())
        if u and check_password_hash(u["pw"], request.form["password"]):
            session["user"] = u["id"]; return redirect(url_for("opportunities"))
        flash("Invalid credentials.")
    return page("""<h3>Login</h3><form method=post>Email<input name=email type=email required>
        Password<input name=password type=password required><button>Login</button></form>""")


@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    u = me()
    if not u: return redirect(url_for("login"))
    if request.method == "POST":
        for f in ("skills", "projects", "certificates", "interests"):
            u[f] = split(request.form.get(f))
        db.put("students", u); flash("Profile saved.")
    return page("""<h3>My Portfolio</h3><form method=post>
        Skills (comma separated)<input name=skills value="{{', '.join(u.skills)}}">
        Projects<textarea name=projects>{{', '.join(u.projects)}}</textarea>
        Certifications<textarea name=certificates>{{', '.join(u.certificates)}}</textarea>
        Interests<input name=interests value="{{', '.join(u.interests)}}"><button>Save</button></form>""", u=u)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    u = me()
    if not u or u["role"] != "admin": return redirect(url_for("login"))
    if request.method == "POST":
        db.put("opportunities", {"id": uuid.uuid4().hex[:8], "title": request.form["title"], "type": request.form["type"],
               "org": request.form["org"], "skills": split(request.form["skills"])})
        flash("Opportunity posted.")
    return page("""<h3>Post Opportunity</h3><form method=post>Title<input name=title required>Organization<input name=org required>
        Type<select name=type><option>Internship<option>Hackathon<option>Workshop<option>Project</select>
        Required skills (comma separated)<input name=skills required><button>Post</button></form>
        <h4>Posted</h4>{% for o in ops %}<div class=card>{{o.title}} - {{o.type}} ({{o.org}}): {{', '.join(o.skills)}}</div>{% endfor %}""",
        ops=db.all("opportunities"))


@app.route("/opportunities")
def opportunities():
    u = me()
    if not u: return redirect(url_for("login"))
    ranked = sorted(({**o, "score": match_score(u["skills"], o["skills"])} for o in db.all("opportunities")),
                    key=lambda o: -o["score"])
    applied = {a["opp"] for a in db.all("applications") if a["student"] == u["id"]}
    return page("""<h3>Recommended Opportunities</h3>{% for o in ranked %}<div class=card>
        <b>{{o.title}}</b> - {{o.type}} at {{o.org}}<br>Needs: {{', '.join(o.skills)}}
        <div class=bar><i style="width:{{o.score}}%"></i></div>Match: {{o.score}}%
        {% if o.id in applied %}<b>(Applied)</b>{% else %}<form method=post action="/apply/{{o.id}}"><button>Apply</button></form>{% endif %}
        </div>{% else %}<p>No opportunities yet.</p>{% endfor %}""", ranked=ranked, applied=applied)


@app.route("/apply/<oid>", methods=["POST"])
def apply(oid):
    u = me()
    if not u: return redirect(url_for("login"))
    if db.get("opportunities", oid):
        db.put("applications", {"id": f"{u['id']}#{oid}", "student": u["id"], "opp": oid, "status": "Submitted"})
        flash("Application submitted.")
    return redirect(url_for("applications"))


@app.route("/applications", methods=["GET", "POST"])
def applications():
    u = me()
    if not u: return redirect(url_for("login"))
    if request.method == "POST" and u["role"] == "admin":
        a = db.get("applications", request.form["id"])
        if a: a["status"] = request.form["status"]; db.put("applications", a)
    apps = db.all("applications") if u["role"] == "admin" else [a for a in db.all("applications") if a["student"] == u["id"]]
    titles = {o["id"]: o["title"] for o in db.all("opportunities")}
    return page("""<h3>Applications</h3>{% for a in apps %}<div class=card>{{titles.get(a.opp)}} {% if u.role=='admin' %}by {{a.student}}{% endif %} - <b>{{a.status}}</b>
        {% if u.role=='admin' %}<form method=post><input type=hidden name=id value="{{a.id}}"><select name=status>
        <option>Submitted<option>Shortlisted<option>Accepted<option>Rejected</select><button>Update</button></form>{% endif %}</div>
        {% else %}<p>No applications.</p>{% endfor %}""", apps=apps, titles=titles, u=u)


@app.route("/api/match")
def api_match():
    skills, req = split(request.args.get("skills")), split(request.args.get("required"))
    return jsonify(score=match_score(skills, req))


application = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

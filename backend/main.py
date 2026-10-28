from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import crud
from auth import create_token, decode_token, hash_password, verify_password
from database import Base, SessionLocal, User, engine

Base.metadata.create_all(engine)  # jo tables nahi hain woh bana do

app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    """Header 'Authorization: Bearer <token>' se pehchano ki kaun hai."""
    token = authorization.removeprefix("Bearer ").strip()
    username = decode_token(token)
    user = crud.find_user(db, username) if username else None
    if not user:
        raise HTTPException(status_code=401, detail="Pehle login karo")
    return user


def add_presence(chat):
    """Private chat mein dikhao ki samne wala abhi online hai ya nahi."""
    chat["online"] = bool(chat["other"]) and chat["other"] in manager.users
    return chat


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=6, max_length=64)


class NewChat(BaseModel):
    username: str


# ---------- Signup / Login ----------
@app.post("/api/signup", status_code=201)
def signup(data: Credentials, db: Session = Depends(get_db)):
    if crud.find_user(db, data.username):
        raise HTTPException(status_code=400, detail="Ye username pehle se liya hua hai")
    user = User(username=data.username, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    return {"token": create_token(user.username), "username": user.username}


@app.post("/api/login")
def login(data: Credentials, db: Session = Depends(get_db)):
    user = crud.find_user(db, data.username)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Username ya password galat hai")
    return {"token": create_token(user.username), "username": user.username}


# ---------- Users aur Chats ----------
@app.get("/api/users/search")
def search_users(q: str = "", me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = q.strip()
    if not q:
        return []
    rows = db.query(User).filter(User.username.ilike(f"%{q}%"), User.id != me.id).limit(10).all()
    return [u.username for u in rows]


@app.get("/api/chats")
def my_chats(me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [add_presence(c) for c in crud.list_chats(db, me)]


@app.post("/api/chats")
def start_chat(data: NewChat, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    other = crud.find_user(db, data.username)
    if not other:
        raise HTTPException(status_code=404, detail="Ye user nahi mila")
    if other.id == me.id:
        raise HTTPException(status_code=400, detail="Apne aap se chat nahi kar sakte")
    chat = crud.get_or_create_private_chat(db, me, other)
    return add_presence(crud.chat_summary(db, chat, me))


@app.get("/api/chats/{chat_id}/messages")
def chat_messages(chat_id: int, me: User = Depends(get_current_user), db: Session = Depends(get_db)):
    messages = crud.get_messages(db, chat_id, me)
    if messages is None:
        raise HTTPException(status_code=404, detail="Chat nahi mili")
    return messages


# ---------- Real-time ----------
class ConnectionManager:
    def __init__(self):
        # {"jai": {ws1, ws2}}  (ek user ke kai tabs ho sakte hain)
        self.users = {}

    async def connect(self, username, ws):
        await ws.accept()
        self.users.setdefault(username, set()).add(ws)

    def disconnect(self, username, ws):
        conns = self.users.get(username)
        if conns:
            conns.discard(ws)
            if not conns:
                del self.users[username]

    async def send_to(self, username, message, exclude=None):
        for ws in list(self.users.get(username, ())):
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


def _with_db(fn, *args):
    with SessionLocal() as db:
        return fn(db, *args)


async def run_db(fn, *args):
    """Database ka kaam alag thread mein chalao, taaki server ruke nahi."""
    return await run_in_threadpool(_with_db, fn, *args)


async def notify_presence(user, online, last_seen=None):
    """User ke contacts ko batao ki wo online aaya ya gaya."""
    names = await run_db(crud.contacts, user.id)
    payload = {"type": "presence", "user": user.username, "online": online, "last_seen": last_seen}
    for name in names:
        await manager.send_to(name, payload)


@app.get("/")
def home():
    return FileResponse("index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    username = decode_token(token)
    user = await run_db(crud.find_user, username) if username else None
    if not user:
        await ws.accept()
        await ws.close(code=4001)  # 4001 = "token galat, dobara login karo"
        return

    username = user.username
    first_tab = username not in manager.users
    await manager.connect(username, ws)
    if first_tab:
        await notify_presence(user, True)
    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            chat_id = data.get("chat_id")
            if not isinstance(chat_id, int):
                continue

            if kind == "message":
                text = str(data.get("text", "")).strip()[:500]
                if not text:
                    continue
                result = await run_db(crud.save_message, chat_id, user.id, text)
                if result is None:  # is chat ke member nahi ho
                    continue
                payload = {
                    "type": "message",
                    "chat_id": chat_id,
                    "user": username,
                    "text": text,
                    "time": result["time"],
                }
                for name in result["recipients"]:
                    await manager.send_to(name, payload)

            elif kind == "read":
                await run_db(crud.mark_read, chat_id, user.id)

            elif kind == "typing":
                members = await run_db(crud.chat_members, chat_id)
                if user.id not in [m[0] for m in members]:
                    continue
                for _, name in members:
                    if name != username:
                        await manager.send_to(name, {"type": "typing", "chat_id": chat_id, "user": username})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(username, ws)
        if username not in manager.users:  # aakhri tab band hua
            last_seen = await run_db(crud.set_last_seen, user.id)
            await notify_presence(user, False, last_seen)
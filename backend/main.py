from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import create_token, decode_token, hash_password, verify_password
from database import Base, SessionLocal, User, engine

Base.metadata.create_all(engine)  # users table nahi hai toh bana do

app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=6, max_length=64)


def find_user(db: Session, username: str):
    return db.query(User).filter(func.lower(User.username) == username.lower()).first()


@app.post("/api/signup", status_code=201)
def signup(data: Credentials, db: Session = Depends(get_db)):
    if find_user(db, data.username):
        raise HTTPException(status_code=400, detail="Ye username pehle se liya hua hai")
    user = User(username=data.username, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    return {"token": create_token(user.username), "username": user.username}


@app.post("/api/login")
def login(data: Credentials, db: Session = Depends(get_db)):
    user = find_user(db, data.username)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Username ya password galat hai")
    return {"token": create_token(user.username), "username": user.username}


class RoomManager:
    def __init__(self):
        # {"adda": {ws1: "jai", ws2: "amit"}}
        self.rooms = {}

    async def connect(self, room, ws, username):
        await ws.accept()
        self.rooms.setdefault(room, {})[ws] = username

    def disconnect(self, room, ws):
        if room in self.rooms:
            self.rooms[room].pop(ws, None)

    def is_online(self, room, username):
        return username in self.rooms.get(room, {}).values()

    def users(self, room):
        return list(dict.fromkeys(self.rooms.get(room, {}).values()))

    async def broadcast(self, room, message, exclude=None):
        for ws in list(self.rooms.get(room, {})):
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                pass


manager = RoomManager()


@app.get("/")
def home():
    return FileResponse("index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/{room}")
async def chat(ws: WebSocket, room: str, token: str = ""):
    username = decode_token(token)
    if not username:
        await ws.accept()
        await ws.close(code=4001)  # 4001 = hamara apna code: "token galat"
        return

    first_tab = not manager.is_online(room, username)
    await manager.connect(room, ws, username)
    if first_tab:
        await manager.broadcast(room, {"type": "system", "text": f"{username} joined"})
    await manager.broadcast(room, {"type": "users", "users": manager.users(room)})
    try:
        while True:
            data = await ws.receive_json()
            if data["type"] == "message":
                await manager.broadcast(
                    room, {"type": "message", "user": username, "text": data["text"]}
                )
            elif data["type"] == "typing":
                await manager.broadcast(
                    room, {"type": "typing", "user": username}, exclude=ws
                )
    except WebSocketDisconnect:
        manager.disconnect(room, ws)
        if not manager.is_online(room, username):
            await manager.broadcast(room, {"type": "system", "text": f"{username} left"})
        await manager.broadcast(room, {"type": "users", "users": manager.users(room)})
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

app = FastAPI()


class RoomManager:
    def __init__(self):
        # {"General": {ws1: "Jai", ws2: "Amit"}}
        self.rooms = {}

    async def connect(self, room, ws, username):
        await ws.accept()
        self.rooms.setdefault(room, {})[ws] = username

    def disconnect(self, room, ws):
        if room in self.rooms:
            self.rooms[room].pop(ws, None)

    def users(self, room):
        return list(self.rooms.get(room, {}).values())

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


@app.websocket("/ws/{room}/{username}")
async def chat(ws: WebSocket, room: str, username: str):
    await manager.connect(room, ws, username)
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
        await manager.broadcast(room, {"type": "system", "text": f"{username} left"})
        await manager.broadcast(room, {"type": "users", "users": manager.users(room)})
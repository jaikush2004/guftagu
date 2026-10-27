from fastapi.responses import FileResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()


class RoomManager:
    def __init__(self):
        # {"General": [ws1, ws2], "Coding": [ws3]}
        self.rooms = {}

    async def connect(self, room, ws):
        await ws.accept()
        self.rooms.setdefault(room, []).append(ws)

    def disconnect(self, room, ws):
        if room in self.rooms and ws in self.rooms[room]:
            self.rooms[room].remove(ws)

    async def broadcast(self, room, message):
        for ws in self.rooms.get(room, []):
            await ws.send_json(message)


manager = RoomManager()

@app.get("/")
def home():
    return FileResponse("index.html")

@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/{room}/{username}")
async def chat(ws: WebSocket, room: str, username: str):
    await manager.connect(room, ws)
    await manager.broadcast(room, {"user": "System", "text": f"{username} joined"})
    try:
        while True:
            text = await ws.receive_text()
            await manager.broadcast(room, {"user": username, "text": text})
    except WebSocketDisconnect:
        manager.disconnect(room, ws)
        await manager.broadcast(room, {"user": "System", "text": f"{username} left"})
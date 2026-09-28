"""
Chess multiplayer backend — a real-time move relay over WebSockets.

Two players join a room by code. The first to join plays White, the second
plays Black. Moves are relayed between them; the server enforces turn order
(so a player can't move twice) while the browsers handle full rules validation.

No database: rooms live in memory for the life of the process, which is all a
friendly "play with a friend" feature needs. Deploy as a single web service.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Chess Multiplayer")

# Allow the static frontend (any origin) to reach the REST health check.
# WebSocket connections are not subject to CORS, but this keeps REST calls open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class Player:
    ws: WebSocket
    color: str  # "w" or "b"
    name: str


@dataclass
class Room:
    code: str
    players: list[Player] = field(default_factory=list)
    move_count: int = 0  # even -> White to move, odd -> Black to move
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def opponent_of(self, player: Player) -> Player | None:
        for p in self.players:
            if p is not player:
                return p
        return None


rooms: dict[str, Room] = {}
rooms_guard = asyncio.Lock()


def _new_code() -> str:
    # Avoid ambiguous characters (0/O, 1/I) so codes are easy to share by voice.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(5))


async def _create_unique_room() -> Room:
    async with rooms_guard:
        code = _new_code()
        while code in rooms:
            code = _new_code()
        room = Room(code=code)
        rooms[code] = room
        return room


@app.get("/")
async def root():
    return {"service": "chess-multiplayer", "status": "ok", "rooms": len(rooms)}


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _safe_send(ws: WebSocket, message: dict) -> None:
    try:
        await ws.send_json(message)
    except Exception:
        pass


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    """
    Query params:
      room=CODE   join an existing room; omit or "new" to create one
      name=...    optional display name
    """
    await websocket.accept()
    params = websocket.query_params
    requested = (params.get("room") or "").strip().upper()
    name = (params.get("name") or "Player").strip()[:24] or "Player"

    room: Room | None = None
    player: Player | None = None

    try:
        # ----- join or create a room -----
        if not requested or requested == "NEW":
            room = await _create_unique_room()
        else:
            room = rooms.get(requested)
            if room is None:
                await _safe_send(websocket, {"type": "error", "message": "Room not found"})
                await websocket.close()
                return

        async with room.lock:
            if len(room.players) >= 2:
                await _safe_send(websocket, {"type": "full"})
                await websocket.close()
                return
            # first player is White, second is Black
            color = "w" if len(room.players) == 0 else "b"
            player = Player(ws=websocket, color=color, name=name)
            room.players.append(player)
            opponent = room.opponent_of(player)

        await _safe_send(
            websocket,
            {"type": "init", "room": room.code, "color": player.color, "name": name},
        )

        if opponent is not None:
            # both present — tell everyone the game can start
            await _safe_send(
                opponent.ws,
                {"type": "opponent_joined", "name": name},
            )
            for p in room.players:
                await _safe_send(p.ws, {"type": "start", "color": p.color})

        # ----- message loop -----
        while True:
            data = await websocket.receive_json()
            mtype = data.get("type")
            opponent = room.opponent_of(player)

            if mtype == "move":
                # enforce turn order: only the side to move may send a move
                expected = "w" if room.move_count % 2 == 0 else "b"
                if player.color != expected:
                    await _safe_send(
                        websocket,
                        {"type": "error", "message": "Not your turn"},
                    )
                    continue
                room.move_count += 1
                if opponent is not None:
                    await _safe_send(
                        opponent.ws,
                        {
                            "type": "move",
                            "move": data.get("move"),
                            "fen": data.get("fen"),
                        },
                    )

            elif mtype in ("resign", "draw_offer", "draw_accept", "rematch", "chat"):
                if opponent is not None:
                    payload = {"type": mtype}
                    if mtype == "chat":
                        payload["text"] = str(data.get("text", ""))[:500]
                    await _safe_send(opponent.ws, payload)
                if mtype == "rematch":
                    # reset the move counter so a new game can begin cleanly
                    room.move_count = 0

            elif mtype == "ping":
                await _safe_send(websocket, {"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # remove the player and notify the opponent
        if room is not None and player is not None:
            async with room.lock:
                if player in room.players:
                    room.players.remove(player)
                remaining = list(room.players)
            for p in remaining:
                await _safe_send(p.ws, {"type": "opponent_left"})
            # drop empty rooms
            if not remaining:
                async with rooms_guard:
                    rooms.pop(room.code, None)

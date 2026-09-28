# Chess Backend — online multiplayer

A tiny real-time move-relay server for the [Chess frontend](https://github.com/ArifRahaman/Chess-frontend).
Two players join a room by code; moves are relayed between them over a WebSocket.

- **FastAPI + WebSockets**, no database (rooms live in memory)
- First player to join a room is **White**, second is **Black**
- Server enforces turn order; the browsers validate full chess rules
- Handles join / start / move / resign / rematch / disconnect

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Health check: <http://localhost:8000/health>

## WebSocket API

Connect to `ws://<host>/ws?room=<CODE>&name=<NAME>`.
Omit `room` (or use `new`) to create a room; the server replies with its code.

**Server → client**

| type | meaning |
|------|---------|
| `init` | you joined; includes your `color` and the `room` code |
| `opponent_joined` | the second player arrived |
| `start` | both present — begin; includes your `color` |
| `move` | opponent's move (`move` object + `fen`) |
| `resign` / `draw_offer` / `draw_accept` / `rematch` | opponent control messages |
| `opponent_left` | opponent disconnected |
| `full` | room already has two players |
| `error` | `message` describes the problem |

**Client → server**

| type | payload |
|------|---------|
| `move` | `{ move: {...}, fen: "..." }` |
| `resign` / `draw_offer` / `draw_accept` / `rematch` | — |
| `chat` | `{ text: "..." }` |
| `ping` | keepalive (server replies `pong`) |

## Deploy on Render

This repo includes `render.yaml`. On [Render](https://render.com):

1. **New → Blueprint**, connect this repo — it reads `render.yaml`, or
2. **New → Web Service** manually:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Health check path: `/health`

Render supports WebSockets on all plans. After deploy you'll get a URL like
`https://chess-backend.onrender.com`; the frontend connects to `wss://chess-backend.onrender.com/ws`.

> Note: Render's free tier sleeps after inactivity, so the first connection may
> take ~30–60s to wake the service.

import os
import json
import asyncio
import hashlib
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from io import BytesIO

import chromadb
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv

from auth import identify_user, UserRole, UserIdentity

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bob-voice")

app = FastAPI(title="BOB Voice Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://voice.appalachiantoysgames.com",
        "https://appalachiantoysgames.com",
        "https://www.appalachiantoysgames.com",
        "http://192.168.1.228:8150",
        "http://localhost:8150",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

BOB_URL = os.getenv("BOB_URL", "http://localhost:8100")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # Adam voice default

eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# ChromaDB for conversation memory
CHROMADB_URL = os.getenv("CHROMADB_URL", "http://localhost:8000")
_chroma = None
_collections = {}  # cache: collection_name -> collection object
RECENT_MEMORY_COUNT = 10


def _get_chroma_client():
    global _chroma
    if _chroma is None:
        host = CHROMADB_URL.replace("http://", "").split(":")[0]
        port = int(CHROMADB_URL.split(":")[-1])
        _chroma = chromadb.HttpClient(host=host, port=port)
    return _chroma


def _get_voice_collection(collection_name: str = "voice_conversations"):
    """Get or create a voice memory collection. Per-user collections for multi-user."""
    if collection_name not in _collections:
        client = _get_chroma_client()
        _collections[collection_name] = client.get_or_create_collection(
            name=collection_name,
            metadata={"description": f"Voice conversation history — {collection_name}"}
        )
    return _collections[collection_name]


def store_voice_exchange(transcript: str, response: str, thread_id: str,
                         user: UserIdentity | None = None):
    """Store a voice Q&A exchange in ChromaDB."""
    if user and user.role == UserRole.GUEST:
        return  # Guests get no memory

    collection_name = user.memory_collection if user else "voice_conversations"
    if not collection_name:
        return

    try:
        col = _get_voice_collection(collection_name)
        now = datetime.now(timezone.utc)
        doc_id = f"voice-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        speaker = user.display_name if user else "User"
        text = f"{speaker}: {transcript}\nBOB: {response}"
        metadata = {
            "thread_id": thread_id,
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
        }
        if user and user.email:
            metadata["user_email"] = user.email
        col.add(ids=[doc_id], documents=[text], metadatas=[metadata])
        logger.info(f"Stored voice exchange: {doc_id} (user: {speaker})")
    except Exception as e:
        logger.warning(f"Failed to store voice exchange: {e}")


def recall_recent_conversations(query: str = "", n_results: int = RECENT_MEMORY_COUNT,
                                user: UserIdentity | None = None) -> str:
    """Recall recent voice conversations from ChromaDB."""
    if user and user.role == UserRole.GUEST:
        return ""  # Guests get no memory

    collection_name = user.memory_collection if user else "voice_conversations"
    if not collection_name:
        return ""

    try:
        col = _get_voice_collection(collection_name)
        if col.count() == 0:
            return ""
        if query:
            results = col.query(query_texts=[query], n_results=n_results)
        else:
            results = col.get(limit=n_results)

        docs = results.get("documents", [])
        if isinstance(docs[0], list):
            docs = docs[0]
        metas = results.get("metadatas", [])
        if isinstance(metas[0], list):
            metas = metas[0]

        if not docs:
            return ""

        exchanges = []
        for i, doc in enumerate(docs):
            meta = metas[i] if metas else {}
            ts = meta.get("timestamp", "")
            exchanges.append((ts, doc))
        exchanges.sort(key=lambda x: x[0])

        lines = [ex[1] for ex in exchanges]
        return "\n---\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to recall conversations: {e}")
        return ""


# TTS cache
_tts_cache = {}
_TTS_CACHE_MAX = 100


def _tts_cache_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _build_user_context(user: UserIdentity) -> str:
    """Build a context prefix for BOB based on who's talking."""
    if user.is_rob:
        return ""  # Rob gets default BOB — no prefix needed, "Yes Boss" mode is in system prompt

    if user.role == UserRole.MEMBER:
        return (
            f"[SYSTEM NOTE: You are speaking with {user.display_name} ({user.email}), "
            f"an authenticated user but NOT Rob. Be helpful and friendly. "
            f"Do NOT use 'Yes Boss'. Do NOT share Rob's private business details, "
            f"internal financials, or API keys. You can discuss ATG products, "
            f"Bear Creek Trail, and general information. "
            f"Address them by name: {user.display_name}.]\n\n"
        )

    # Guest
    return (
        "[SYSTEM NOTE: You are speaking with an unauthenticated guest. "
        "Be friendly but brief. Do NOT share any internal business information, "
        "credentials, infrastructure details, or private project status. "
        "You can talk about ATG products, Bear Creek Trail, and general topics. "
        "Do NOT use 'Yes Boss'. Do NOT execute any tools that modify state "
        "(create tasks, send messages, etc.). Read-only tools are OK.]\n\n"
    )


@app.get("/health")
async def health():
    from auth import status as auth_status
    return {
        "status": "ok",
        "service": "bob-voice",
        "multi_user": True,
        "auth": auth_status(),
    }


@app.get("/auth/status")
async def auth_status_endpoint():
    """Show which auth backend is active and which are configured.

    Useful for verifying the auth abstraction is set up correctly without
    actually authenticating a user.
    """
    from auth import status
    return status()


@app.get("/")
async def root():
    # Default landing — three buttons (Talk / Chat / Photo).
    return FileResponse("static/landing.html", headers={"Cache-Control": "no-cache, no-store"})


@app.get("/landing")
async def landing():
    return FileResponse("static/landing.html", headers={"Cache-Control": "no-cache, no-store"})


@app.get("/voice")
async def voice_page():
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, no-store"})


@app.get("/photos")
async def photos_page():
    return FileResponse("static/photos.html", headers={"Cache-Control": "no-cache, no-store"})


@app.post("/photos/upload")
async def photos_upload_proxy(request: Request):
    """Auth-gated proxy: validates JWT, then forwards multipart to BOB orchestrator."""
    user = await identify_user(dict(request.headers))
    if user.role == UserRole.GUEST:
        return {"error": "photo upload requires authentication"}, 401

    body = await request.body()
    headers = {
        "Content-Type": request.headers.get("content-type", "multipart/form-data"),
    }
    # Forward as-is, but inject the user identity as a form field via header hint.
    # Simpler: re-read the multipart form, add 'user' field, re-post.
    form = await request.form()
    files = {}
    data = {"user": user.email or user.display_name or "anonymous"}
    for key, value in form.multi_items():
        if hasattr(value, "filename"):
            files[key] = (value.filename, await value.read(), value.content_type)
        else:
            data[key] = value

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{BOB_URL}/photos/upload", data=data, files=files)
    return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"error": resp.text}


@app.post("/photos/remember/{photo_id}")
async def photos_remember_proxy(photo_id: str, request: Request):
    user = await identify_user(dict(request.headers))
    if user.role == UserRole.GUEST:
        return {"error": "auth required"}, 401
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BOB_URL}/photos/remember/{photo_id}",
            data={"user": user.email or user.display_name or "anonymous"},
        )
    return resp.json()


@app.get("/manifest.json")
async def manifest():
    return FileResponse("static/manifest.json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.get("/whoami")
async def whoami(request: Request):
    """Debug endpoint — shows who Cloudflare thinks you are."""
    user = await identify_user(dict(request.headers))
    return {
        "role": user.role.value,
        "email": user.email,
        "name": user.display_name,
        "memory_collection": user.memory_collection,
    }


async def transcribe_audio(audio_data: bytes) -> str:
    """Send audio to Deepgram and get transcription."""
    dg = DeepgramClient(DEEPGRAM_API_KEY)
    options = {
        "model": "nova-2",
        "smart_format": True,
        "language": "en",
    }
    source = {"buffer": audio_data, "mimetype": "audio/webm"}
    response = await asyncio.to_thread(
        lambda: dg.listen.rest.v("1").transcribe_file(source, options)
    )
    transcript = response.results.channels[0].alternatives[0].transcript
    return transcript


async def ask_bob(message: str, thread_id: str,
                  latitude: float = None, longitude: float = None) -> str:
    """Send message to BOB (non-streaming fallback)."""
    body = {"message": message, "thread_id": thread_id}
    if latitude is not None and longitude is not None:
        body["latitude"] = latitude
        body["longitude"] = longitude
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{BOB_URL}/chat",
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", data.get("message", str(data)))


def _generate_tts_full(text: str) -> bytes:
    """Generate TTS audio (blocking). Returns complete MP3 bytes."""
    audio_gen = eleven_client.text_to_speech.convert(
        text=text,
        voice_id=ELEVENLABS_VOICE_ID,
        model_id="eleven_turbo_v2_5",
        output_format="mp3_44100_128",
    )
    chunks = []
    for chunk in audio_gen:
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


async def stream_bob_and_speak(message: str, thread_id: str, ws: WebSocket,
                                stop_event: asyncio.Event,
                                latitude: float = None, longitude: float = None) -> str:
    """Stream BOB's response via SSE, generate TTS per sentence, send audio as each is ready."""
    full_text = ""
    buffer = ""
    tts_tasks = []

    async def tts_and_send(sentence: str):
        if stop_event.is_set():
            return
        cache_key = _tts_cache_key(sentence)
        if cache_key in _tts_cache:
            audio_bytes = _tts_cache[cache_key]
        else:
            audio_bytes = await asyncio.to_thread(_generate_tts_full, sentence)
            if len(_tts_cache) >= _TTS_CACHE_MAX:
                oldest_key = next(iter(_tts_cache))
                del _tts_cache[oldest_key]
            _tts_cache[cache_key] = audio_bytes
        if not stop_event.is_set():
            await ws.send_bytes(audio_bytes)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            body = {"message": message, "thread_id": thread_id}
            if latitude is not None and longitude is not None:
                body["latitude"] = latitude
                body["longitude"] = longitude
            async with client.stream(
                "POST",
                f"{BOB_URL}/chat/stream",
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if stop_event.is_set():
                        break
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])

                    if data.get("type") == "token":
                        token = data["text"]
                        full_text += token
                        buffer += token

                        parts = _SENTENCE_RE.split(buffer)
                        if len(parts) > 1:
                            for sentence in parts[:-1]:
                                sentence = sentence.strip()
                                if sentence:
                                    for t in tts_tasks:
                                        await t
                                    tts_tasks.clear()
                                    tts_tasks.append(asyncio.create_task(tts_and_send(sentence)))
                            buffer = parts[-1]

                    elif data.get("type") == "done":
                        full_text = data.get("text", full_text)
                        break

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.info("Streaming not available, falling back to /chat")
            full_text = await ask_bob(message, thread_id, latitude=latitude, longitude=longitude)
            if not stop_event.is_set():
                audio_bytes = await asyncio.to_thread(_generate_tts_full, full_text)
                cache_key = _tts_cache_key(full_text)
                if len(_tts_cache) >= _TTS_CACHE_MAX:
                    oldest_key = next(iter(_tts_cache))
                    del _tts_cache[oldest_key]
                _tts_cache[cache_key] = audio_bytes
                await ws.send_bytes(audio_bytes)
            return full_text
        raise
    except Exception:
        logger.exception("Streaming error, falling back to /chat")
        full_text = await ask_bob(message, thread_id, latitude=latitude, longitude=longitude)
        if not stop_event.is_set():
            audio_bytes = await asyncio.to_thread(_generate_tts_full, full_text)
            await ws.send_bytes(audio_bytes)
        return full_text

    for t in tts_tasks:
        await t
    if buffer.strip() and not stop_event.is_set():
        await tts_and_send(buffer.strip())

    return full_text


# Per-session rate limit: max messages per minute
WS_RATE_LIMIT = int(os.getenv("WS_RATE_LIMIT_PER_MIN", "10"))
WS_GUEST_RATE_LIMIT = int(os.getenv("WS_GUEST_RATE_LIMIT_PER_MIN", "5"))


@app.websocket("/ws/voice")
async def voice_endpoint(ws: WebSocket):
    await ws.accept()

    # Identify user from Cloudflare JWT
    headers = dict(ws.headers)
    user = await identify_user(headers)

    thread_id = f"voice-{user.role.value}-{uuid.uuid4().hex[:8]}"
    stop_event = asyncio.Event()
    msg_queue = asyncio.Queue()
    user_context = _build_user_context(user)
    user_location = {"lat": None, "lon": None}

    # Per-session rate limiting
    rate_limit = WS_RATE_LIMIT if user.role != UserRole.GUEST else WS_GUEST_RATE_LIMIT
    message_timestamps: list[float] = []

    logger.info(f"Voice session started: {thread_id} | user: {user.display_name} ({user.role.value})")

    # Track session on BOB dashboard
    async def _track_session(action: str, **kwargs):
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                await c.post(f"{BOB_URL}/dashboard/api/sessions/{action}", json=kwargs)
        except Exception as e:
            logger.debug(f"Session tracking ({action}) failed: {e}")

    client_ip = headers.get("cf-connecting-ip", headers.get("x-forwarded-for", "unknown"))
    await _track_session("open",
        session_id=thread_id,
        endpoint="voice",
        user_email=user.email or client_ip,
        user_name=user.display_name or client_ip,
        user_role=user.role.value,
        client_ip=client_ip,
    )

    # Tell the client who they are
    await ws.send_json({
        "type": "identity",
        "role": user.role.value,
        "name": user.display_name,
    })

    async def listen_for_messages():
        try:
            while True:
                data = await ws.receive()
                if "bytes" in data:
                    await msg_queue.put(data)
                elif "text" in data:
                    msg = json.loads(data["text"])
                    if msg.get("type") == "stop_audio":
                        stop_event.set()
                    elif msg.get("type") == "new_session":
                        nonlocal thread_id
                        stop_event.set()
                        thread_id = f"voice-{user.role.value}-{uuid.uuid4().hex[:8]}"
                        await ws.send_json({"type": "status", "message": "New conversation started"})
                    elif msg.get("type") == "location":
                        user_location["lat"] = msg.get("lat")
                        user_location["lon"] = msg.get("lon")
                        logger.info(f"Received geolocation for {user.display_name}: {user_location}")
                        await _track_session("update",
                            session_id=thread_id,
                            latitude=user_location["lat"],
                            longitude=user_location["lon"],
                        )
                    elif msg.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                    else:
                        await msg_queue.put(data)
        except (WebSocketDisconnect, Exception):
            await msg_queue.put(None)

    listener = asyncio.create_task(listen_for_messages())
    is_first_message = True

    try:
        while True:
            data = await msg_queue.get()
            if data is None:
                break

            if "bytes" in data:
                # Rate limiting
                now_ts = time.time()
                message_timestamps.append(now_ts)
                cutoff = now_ts - 60
                message_timestamps[:] = [t for t in message_timestamps if t > cutoff]
                if len(message_timestamps) > rate_limit:
                    await ws.send_json({
                        "type": "status",
                        "message": "Slow down — too many messages. Try again in a moment."
                    })
                    continue

                audio_data = data["bytes"]
                logger.info(f"Received {len(audio_data)} bytes of audio from {user.display_name}")

                await ws.send_json({"type": "status", "message": "Listening..."})
                transcript = await transcribe_audio(audio_data)
                logger.info(f"Transcript ({user.display_name}): {transcript}")

                if not transcript.strip():
                    await ws.send_json({"type": "status", "message": "Didn't catch that, try again"})
                    continue

                await ws.send_json({"type": "transcript", "text": transcript})

                # Build message with user context and memory
                message_to_send = transcript

                if user_context:
                    message_to_send = user_context + transcript

                # On first message, inject recent conversation memory (not for guests)
                if is_first_message and user.role != UserRole.GUEST:
                    recent = await asyncio.to_thread(
                        recall_recent_conversations, transcript, RECENT_MEMORY_COUNT, user
                    )
                    if recent:
                        memory_prefix = (
                            f"[Previous voice conversations with {user.display_name} for context — "
                            f"do not repeat these, just be aware of them]\n{recent}\n\n"
                        )
                        if user_context:
                            message_to_send = user_context + memory_prefix + f"[Current message from {user.display_name}]\n{transcript}"
                        else:
                            message_to_send = memory_prefix + f"[Current message from {user.display_name}]\n{transcript}"
                        logger.info(f"Injected conversation memory for {user.display_name}")
                    is_first_message = False

                # Inject browser geolocation if available
                if user_location["lat"] is not None and user_location["lon"] is not None:
                    location_note = f"[USER_LOCATION: lat={user_location['lat']}, lon={user_location['lon']}]\n"
                    message_to_send = location_note + message_to_send

                # Stream BOB response
                stop_event.clear()
                await ws.send_json({"type": "status", "message": "BOB is thinking..."})
                await ws.send_json({"type": "audio_start"})

                bob_response = await stream_bob_and_speak(
                    message_to_send, thread_id, ws, stop_event,
                    latitude=user_location["lat"], longitude=user_location["lon"],
                )

                logger.info(f"BOB response to {user.display_name}: {bob_response[:100]}...")
                await ws.send_json({"type": "bob_text", "text": bob_response})
                await ws.send_json({"type": "audio_end"})

                # Store exchange in per-user memory
                await asyncio.to_thread(
                    store_voice_exchange, transcript, bob_response, thread_id, user
                )
                await _track_session("update", session_id=thread_id, increment_messages=True)

                if stop_event.is_set():
                    stop_event.clear()

    except WebSocketDisconnect:
        logger.info(f"Voice session ended: {thread_id} ({user.display_name})")
    except Exception as e:
        logger.error(f"Voice error for {user.display_name}: {e}", exc_info=True)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        listener.cancel()
        await _track_session("close", session_id=thread_id)


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8150)

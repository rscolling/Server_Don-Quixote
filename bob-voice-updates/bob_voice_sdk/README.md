# bob_voice_sdk

A reusable voice loop SDK extracted from BOB Voice. The building blocks of a production-grade voice interface for AI agents, with no BOB-specific dependencies.

**Status:** pre-1.0 alpha. Lives inside the BOB monorepo for now. Will be extracted to its own PyPI package once the API stabilizes (Tier 3 roadmap item).

---

## What This Is

When you build a voice interface for an AI agent, you need:

1. **Speech-to-text** — capture user audio, send to a provider, get back text
2. **Text-to-speech** — take the agent's response, synthesize audio, stream it back
3. **Sentence chunking** — split the agent's streaming response on sentence boundaries so audio playback can start before the LLM finishes

That's the loop. BOB Voice does this end-to-end with sub-second latency. The pieces are reusable for any agent framework — not just BOB. This SDK is the proof.

---

## Public API

```python
from bob_voice_sdk import STTClient, TTSClient, SentenceChunker
```

### STTClient — speech-to-text

```python
stt = STTClient(provider="deepgram", api_key="dg_xxx", model="nova-2", language="en")
transcript = await stt.transcribe(audio_bytes, mimetype="audio/webm")
```

Today only Deepgram is supported. The interface is provider-agnostic so future versions can add OpenAI Whisper, AssemblyAI, AWS Transcribe.

### TTSClient — text-to-speech with caching

```python
tts = TTSClient(
    provider="elevenlabs",
    api_key="sk_xxx",
    voice_id="pNInz6obpgDQGcFmaJgB",  # Adam by default
    cache_size=100,
)
audio_bytes = await tts.synthesize("Hello world")
```

Built-in LRU cache means identical sentences (greetings, common phrases) only get synthesized once. Cache is per-instance.

### SentenceChunker — streaming sentence boundaries

```python
chunker = SentenceChunker()

async for token in llm_stream():
    for sentence in chunker.feed(token):
        audio = await tts.synthesize(sentence)
        await playback.queue(audio)

# Don't forget the final partial sentence after the stream ends
final = chunker.flush()
if final:
    audio = await tts.synthesize(final)
    await playback.queue(audio)
```

This is the latency trick. Without it, voice latency is `STT + LLM + TTS` (3-5 seconds). With it, voice latency is `STT + LLM-first-token + TTS-first-sentence` (~800ms).

---

## Full Loop Example

A minimal complete voice loop with this SDK:

```python
import asyncio
from bob_voice_sdk import STTClient, TTSClient, SentenceChunker

stt = STTClient(provider="deepgram", api_key="dg_xxx")
tts = TTSClient(provider="elevenlabs", api_key="sk_xxx")
chunker = SentenceChunker()

async def voice_turn(audio_bytes: bytes, llm_stream_fn) -> bytes:
    """One full voice turn: audio in, audio out."""

    # 1. Transcribe
    transcript = await stt.transcribe(audio_bytes)
    if not transcript:
        return b""

    # 2. Stream the agent's response and synthesize per sentence
    audio_chunks = []
    async for token in llm_stream_fn(transcript):
        for sentence in chunker.feed(token):
            audio = await tts.synthesize(sentence)
            audio_chunks.append(audio)

    # 3. Catch the final partial sentence
    final = chunker.flush()
    if final:
        audio_chunks.append(await tts.synthesize(final))

    return b"".join(audio_chunks)
```

That's a complete voice interface. Plug in any agent framework as `llm_stream_fn` (BOB, CrewAI, AutoGen, plain LangChain, or your own custom backend).

---

## Why Extract This

Three reasons:

1. **It's reusable.** The voice loop is the same for any agent system. There's no reason every framework should reinvent it.
2. **It separates concerns.** The voice service in BOB is mixing reusable infrastructure with BOB-specific glue. Pulling them apart makes both easier to maintain.
3. **It's a force multiplier.** A clean SDK that other frameworks can adopt is a better marketing artifact than a tightly-coupled service that only works with BOB.

The Tier 3 roadmap item explicitly calls for extracting this as a separable Python package. This is the prep work — the API is settled, the modules are isolated, the tests would be straightforward to add. The remaining steps (publish to PyPI, version it independently, set up CI) are mechanical once a maintainer commits to it.

---

## Dependencies

| Package | Required for | Install with |
|---|---|---|
| `deepgram-sdk` | STT (Deepgram backend) | `pip install deepgram-sdk` |
| `elevenlabs` | TTS (ElevenLabs backend) | `pip install elevenlabs` |

All deps are lazy-imported. You only need to install the ones for the providers you actually use.

---

## License

Same as BOB itself: MIT. See the parent repo's LICENSE.

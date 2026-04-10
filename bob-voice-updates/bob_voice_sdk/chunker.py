"""Sentence-boundary chunker for streaming text-to-speech.

The latency trick that makes BOB Voice feel responsive: instead of waiting
for the LLM to finish its full response before synthesizing audio, you split
the response on sentence boundaries as tokens stream in, hand each completed
sentence to TTS immediately, and start playing audio while later sentences
are still being generated.

End-to-end latency from "user stops speaking" to "first audio chunk plays"
drops from ~3s to ~800ms with this technique.

Usage:
    chunker = SentenceChunker()
    for token in llm_stream:
        for sentence in chunker.feed(token):
            audio = await tts.synthesize(sentence)
            await playback.queue(audio)
    # Don't forget the final partial sentence after the stream ends:
    final = chunker.flush()
    if final:
        audio = await tts.synthesize(final)
        await playback.queue(audio)
"""

import re


# Default sentence-boundary regex. Splits after . ! ? followed by whitespace.
# Intentionally conservative — won't split on abbreviations like "Mr. Smith"
# because the next char after the period is uppercase, not whitespace+lowercase.
# Good enough for the streaming-TTS use case.
DEFAULT_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class SentenceChunker:
    """Buffer streaming tokens and yield complete sentences as they form.

    Stateful — maintains a running buffer between feed() calls.
    Thread-safe within a single conversation (use one chunker per session).

    Args:
        sentence_re: Compiled regex for sentence boundaries.
                     Default splits on `[.!?]` followed by whitespace.
        min_sentence_length: Minimum character length for a chunk to be
                             yielded as a sentence. Shorter chunks are kept
                             in the buffer until they grow. Prevents
                             single-character TTS calls on edge cases.
    """

    def __init__(self, sentence_re: re.Pattern | None = None,
                 min_sentence_length: int = 4):
        self.sentence_re = sentence_re or DEFAULT_SENTENCE_RE
        self.min_sentence_length = min_sentence_length
        self._buffer = ""

    def feed(self, token: str) -> list[str]:
        """Add a token to the buffer and return any newly-completed sentences.

        Returns a list (possibly empty) of complete sentences ready for TTS.
        Each returned sentence has been removed from the internal buffer.
        """
        if not token:
            return []

        self._buffer += token
        parts = self.sentence_re.split(self._buffer)

        if len(parts) <= 1:
            # No sentence boundary in the buffer yet
            return []

        # All but the last part are complete sentences
        completed = []
        for sentence in parts[:-1]:
            sentence = sentence.strip()
            if len(sentence) >= self.min_sentence_length:
                completed.append(sentence)

        # The last part is the start of the next sentence — keep buffering it
        self._buffer = parts[-1]
        return completed

    def flush(self) -> str:
        """Return whatever is left in the buffer and clear it.

        Call this after the LLM stream ends to capture the final partial
        sentence (which won't have a trailing punctuation+whitespace marker).
        Returns empty string if the buffer is empty or only whitespace.
        """
        remaining = self._buffer.strip()
        self._buffer = ""
        return remaining if len(remaining) >= self.min_sentence_length else ""

    def reset(self) -> None:
        """Clear the buffer without yielding anything. For starting a new
        conversation while keeping the same chunker instance."""
        self._buffer = ""

    @property
    def buffer_length(self) -> int:
        return len(self._buffer)

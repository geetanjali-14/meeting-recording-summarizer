import logging
import math
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TranscriptChunk(BaseModel):
    """A bounded slice of transcript segments for structured extraction."""

    chunk_index: int
    total_chunks: int
    start_time: float
    end_time: float
    primary_segment_ids: list[str] = Field(
        default_factory=list,
        description="Segment IDs that belong primarily to this chunk",
    )
    all_segment_ids: list[str] = Field(
        default_factory=list,
        description="All segment IDs included in this chunk prompt (including overlap context)",
    )
    segments: list[dict[str, Any]] = Field(default_factory=list)
    estimated_tokens: int = 0


def estimate_segment_tokens(seg: dict[str, Any]) -> int:
    """Conservatively estimates token count for a formatted transcript segment line.

    Format: [SEG-ID: {id}][{start}s - {end}s] {speaker}: {text}
    Uses ceil(len(text)/3.0) + 18 tokens for metadata overhead.
    """
    text = seg.get("text", "") or ""
    metadata_chars = 36 + len(str(seg.get("speaker") or seg.get("speaker_label") or "")) + 20
    total_chars = len(text) + metadata_chars
    # 3.2 chars per token conservative estimate for English/code/symbols
    return max(5, math.ceil(total_chars / 3.2))


class TranscriptChunker:
    """Partitions timestamped transcript segments into token-bounded chunks with overlap context."""

    def __init__(
        self,
        max_prompt_tokens: int = 2800,
        overlap_tokens: int = 350,
        system_prompt_tokens: int = 500,
    ) -> None:
        """
        Args:
            max_prompt_tokens: Maximum tokens allocated for transcript text per chunk.
                               Kept conservative so prompt + output fits in 8000 TPM limit.
            overlap_tokens: Token count of preceding segments to include as context.
            system_prompt_tokens: Overhead reserved for instructions.
        """
        self.max_prompt_tokens = max_prompt_tokens
        self.overlap_tokens = overlap_tokens
        self.system_prompt_tokens = system_prompt_tokens

    def chunk_segments(self, segments: list[dict[str, Any]]) -> list[TranscriptChunk]:
        """Partitions segments into chronological, token-budgeted chunks.

        Guarantees:
        1. Chronological ordering is strictly preserved.
        2. Every single segment is assigned as a primary member to exactly one chunk.
        3. Preceding boundary segments are included as context without re-counting as primary.
        4. No empty chunks are generated if input has segments.
        """
        if not segments:
            return []

        # If any single segment exceeds max_prompt_tokens, split before evaluating budget
        has_oversized = any(estimate_segment_tokens(s) > self.max_prompt_tokens for s in segments)

        # If total estimated tokens fit within single chunk budget without oversized segments
        token_costs = [estimate_segment_tokens(s) for s in segments]
        total_tokens = sum(token_costs)

        if not has_oversized and total_tokens <= self.max_prompt_tokens:
            seg_ids = [str(s.get("segment_id") or s.get("id")) for s in segments]
            try:
                start_t = float(segments[0].get("start_time", 0.0) or 0.0)
            except (ValueError, TypeError):
                start_t = 0.0
            try:
                end_t = float(segments[-1].get("end_time", 0.0) or 0.0)
            except (ValueError, TypeError):
                end_t = 0.0
            return [
                TranscriptChunk(
                    chunk_index=0,
                    total_chunks=1,
                    start_time=start_t,
                    end_time=end_t,
                    primary_segment_ids=seg_ids,
                    all_segment_ids=seg_ids,
                    segments=segments,
                    estimated_tokens=total_tokens,
                )
            ]

        # Multi-chunk partitioning
        # If any single segment exceeds max_prompt_tokens, split its text into sub-segments
        expanded_segments: list[dict[str, Any]] = []
        for s in segments:
            cost = estimate_segment_tokens(s)
            if cost > self.max_prompt_tokens:
                text = str(s.get("text", "") or "")
                spk_str = str(s.get("speaker") or s.get("speaker_label") or "")
                metadata_overhead_chars = 36 + len(spk_str) + 20
                budget_chars = int((self.max_prompt_tokens - 10) * 3.2)
                max_text_chars = max(100, budget_chars - metadata_overhead_chars)

                try:
                    start_t = float(s.get("start_time", 0.0) or 0.0)
                except (ValueError, TypeError):
                    start_t = 0.0
                try:
                    end_t = float(s.get("end_time", 0.0) or 0.0)
                except (ValueError, TypeError):
                    end_t = 0.0

                seg_id = s.get("segment_id") or s.get("id")
                speaker = s.get("speaker") or s.get("speaker_label")

                # Slice unbroken text deterministically
                total_len = max(1, len(text))
                text_slices = [
                    text[i : i + max_text_chars] for i in range(0, total_len, max_text_chars)
                ]
                num_slices = len(text_slices)
                slice_dur = (end_t - start_t) / num_slices if num_slices > 0 else 0.0

                for s_idx, t_slice in enumerate(text_slices):
                    sub_start = start_t + (s_idx * slice_dur)
                    sub_end = start_t + ((s_idx + 1) * slice_dur)
                    expanded_segments.append(
                        {
                            "segment_id": seg_id,
                            "id": seg_id,
                            "speaker": speaker,
                            "speaker_label": speaker,
                            "start_time": sub_start,
                            "end_time": sub_end,
                            "text": t_slice,
                        }
                    )
            else:
                expanded_segments.append(s)

        token_costs = [estimate_segment_tokens(s) for s in expanded_segments]
        raw_chunks: list[dict[str, Any]] = []
        current_primary: list[dict[str, Any]] = []
        current_tokens = 0

        for seg, cost in zip(expanded_segments, token_costs, strict=True):
            if current_primary and (current_tokens + cost > self.max_prompt_tokens):
                raw_chunks.append(
                    {
                        "primary": current_primary,
                        "tokens": current_tokens,
                    }
                )
                current_primary = [seg]
                current_tokens = cost
            else:
                current_primary.append(seg)
                current_tokens += cost

        if current_primary:
            raw_chunks.append(
                {
                    "primary": current_primary,
                    "tokens": current_tokens,
                }
            )

        total_chunks = len(raw_chunks)
        final_chunks: list[TranscriptChunk] = []

        for idx, rc in enumerate(raw_chunks):
            primary_segs = rc["primary"]
            # Deduplicate primary_ids while preserving order if a segment was split
            seen_p_ids: set[str] = set()
            primary_ids: list[str] = []
            for s in primary_segs:
                sid = str(s.get("segment_id") or s.get("id"))
                if sid not in seen_p_ids:
                    seen_p_ids.add(sid)
                    primary_ids.append(sid)

            # Collect overlap context from previous chunks
            overlap_segs: list[dict[str, Any]] = []
            if idx > 0 and self.overlap_tokens > 0:
                acc_overlap_tokens = 0
                prev_primary = raw_chunks[idx - 1]["primary"]
                for p_seg in reversed(prev_primary):
                    c = estimate_segment_tokens(p_seg)
                    if acc_overlap_tokens + c <= self.overlap_tokens or not overlap_segs:
                        overlap_segs.insert(0, p_seg)
                        acc_overlap_tokens += c
                    else:
                        break

            all_segs = overlap_segs + primary_segs
            seen_a_ids: set[str] = set()
            all_ids: list[str] = []
            for s in all_segs:
                sid = str(s.get("segment_id") or s.get("id"))
                if sid not in seen_a_ids:
                    seen_a_ids.add(sid)
                    all_ids.append(sid)

            try:
                start_t = float(primary_segs[0].get("start_time", 0.0) or 0.0)
            except (ValueError, TypeError):
                start_t = 0.0
            try:
                end_t = float(primary_segs[-1].get("end_time", 0.0) or 0.0)
            except (ValueError, TypeError):
                end_t = 0.0
            chunk_tokens = sum(estimate_segment_tokens(s) for s in all_segs)

            final_chunks.append(
                TranscriptChunk(
                    chunk_index=idx,
                    total_chunks=total_chunks,
                    start_time=start_t,
                    end_time=end_t,
                    primary_segment_ids=primary_ids,
                    all_segment_ids=all_ids,
                    segments=all_segs,
                    estimated_tokens=chunk_tokens,
                )
            )

        logger.info(
            "Partitioned transcript of %d segments (%d tokens) into %d chunks",
            len(segments),
            total_tokens,
            total_chunks,
        )
        return final_chunks

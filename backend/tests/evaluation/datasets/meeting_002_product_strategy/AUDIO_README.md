# Audio Dataset Provenance & Synthesis Specification

## Overview
This directory contains acoustic benchmark audio and corresponding ground-truth annotations for evaluation in Phase 10.

## Audio Generation Details
- **Speech Synthesis Engine:** `espeak-ng` (eSpeak NG text-to-speech engine, GPL-3.0-or-later)
- **Audio Format:** 16,000 Hz, 16-bit PCM Mono WAV format (`audio.wav`)
- **Speech Sample Type:** Multi-speaker conversation synthesized directly from verified `transcript.json` utterances.
- **Voice Mapping:**
  - `SPEAKER_00`: `en-us` (American English male voice)
  - `SPEAKER_01`: `en-us+f3` (American English female voice variant 3)
  - `SPEAKER_02`: `en-gb` (British English male voice)
- **Licensing:** Audio generated using Debian/Ubuntu system `espeak-ng` package under open-source software license. Reference transcripts and annotations are proprietary project test benchmarks under MIT license.
- **Evaluation Status:**
  - Offline deterministic metrics (WER calculation, DER alignment, timestamp drift, extraction accuracy, zero-hallucination checks): **VALIDATED**.
  - Live vendor model evaluations (live Groq Whisper Turbo API, pyannote neural diarization on GPU, live Groq GPT-OSS inference latency/cost): **PENDING LIVE DEPLOYMENT/PIPELINE EXECUTION**.

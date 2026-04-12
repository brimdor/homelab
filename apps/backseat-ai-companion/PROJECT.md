# Backseat AI Gaming Companion

**Date:** 2026-04-07
**Status:** Parked / Discovery

## Concept
Voice-first, hands-free AI co-pilot that watches your PC game screen and provides real-time tips, strategy, and game knowledge. Self-improving — gathers data from the internet for any game.

## Key Requirements
- Any PC game (Linux + Windows)
- Voice trigger in/out (hands-free)
- Screen capture → vision analysis
- Fallback: player describes scene
- Game-specific knowledge via web scraping + RAG
- Proactive tips (volunteers info) + reactive (player asks)
- Smart: uses wikis, guides, Reddit, etc.

## Architecture (DRAFT)
- Wake word → STT → LLM Brain → TTS
- Screen capture → Vision model → Game state
- RAG knowledge base per game (ChromaDB)
- Web scraper: builds knowledge base on first play
- Cross-platform: Linux + Windows

## Stack Options
- Brain: Cloud (GPT-4V) vs Local (Ollama) vs Hybrid
- Vision: GPT-4V, LLaVA, or local
- STT: Whisper (local or cloud)
- TTS: ElevenLabs or local

## Open Questions
- [ ] Local or cloud brain? (privacy vs quality)
- [ ] Personality? (cheerleader, chill, sarcastic?)
- [ ] Proactive tips or only reactive?
- [ ] Interrupt behavior?
- [ ] Knowledge freshness / re-scraping?

## Next Steps
- Finalize stack decisions with Chris
- Write SPEC.md
- Build MVP

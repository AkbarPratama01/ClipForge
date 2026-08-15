"""ClipForge worker package.

Runs inside the backend image (``PYTHONPATH=/app:/worker``) and consumes
Redis-backed jobs. Phase 1 ships a connectivity-stub; real job types
(DOWNLOAD, TRANSCRIBE, ANALYZE, RENDER, ...) arrive with the job queue module.
"""

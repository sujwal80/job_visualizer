from backend.worker import WorkerEntrypoint

_worker = None

async def on_fetch(request, env):
    global _worker
    if _worker is None:
        _worker = WorkerEntrypoint(env)
    return await _worker.fetch(request)

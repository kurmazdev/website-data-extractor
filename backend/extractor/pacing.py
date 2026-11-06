"""Bounded per-origin scheduling shared by runs on the same event loop."""

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class SiteGate:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request: float = 0
    policy_spacing: float = 0
    users: int = 0


_gates = OrderedDict()


@asynccontextmanager
async def site_slot(origin):
    # Event loops must never share asyncio locks. Keep at most 128 idle/active
    # sites; active entries cannot be evicted while a request is queued.
    key = (asyncio.get_running_loop(), origin)
    gate = _gates.pop(key, None) or SiteGate()
    _gates[key] = gate
    gate.users += 1
    for old_key, old_gate in list(_gates.items()):
        if len(_gates) <= 128:
            break
        if old_gate.users == 0:
            del _gates[old_key]
    try:
        async with gate.lock:
            yield gate
    finally:
        gate.users -= 1

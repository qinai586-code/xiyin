"""Explicit adapter registration, observation freshness and bounded stop logic."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import math
import time

from .models import ActionReceipt, ActionRequest, AdapterOutcome, Observation


class BodyRegistry:
    def __init__(self, *, clock=time.monotonic, stop_timeout: float = 1.0):
        self._adapters = {}
        self._locks = {}
        self._observations: OrderedDict[str, Observation] = OrderedDict()
        self._active = {}
        self._unsettled = {}
        self._clock = clock
        self._stop_timeout = stop_timeout
        self._stopped = False
        self._epoch = 0

    def register(self, adapter) -> None:
        """Registration is host configuration, never a model-generated grant."""
        identifier = adapter.capability.adapter_id
        if identifier in self._adapters:
            raise ValueError("Stop and explicitly unregister an adapter before replacing it")
        self._adapters[identifier] = adapter
        self._locks[identifier] = asyncio.Lock()

    async def unregister(self, adapter_id: str) -> None:
        if adapter_id in self._active or adapter_id in self._unsettled:
            raise RuntimeError("Adapter has an active action; stop it first")
        adapter = self._adapters[adapter_id]
        await adapter.stop()
        del self._adapters[adapter_id]
        del self._locks[adapter_id]
        self._observations = OrderedDict((key, value) for key, value in self._observations.items()
                                         if value.adapter_id != adapter_id)

    def capabilities(self) -> list[dict]:
        return [adapter.capability.to_dict() for adapter in self._adapters.values()]

    async def health(self) -> dict:
        result = {}
        for identifier, adapter in self._adapters.items():
            if identifier in self._unsettled:
                result[identifier] = {"available": False, "detail": "Cancelled action cleanup is unresolved; stop and resume explicitly"}
                continue
            try:
                result[identifier] = await adapter.health()
            except Exception as exc:
                result[identifier] = {"available": False, "detail": str(exc)}
        return {"emergency_stopped": self._stopped, "adapters": result}

    async def observe(self, adapter_id: str) -> Observation:
        adapter = self._adapters[adapter_id]
        if adapter_id in self._unsettled:
            raise RuntimeError("Adapter has an unresolved cancelled action")
        health = await adapter.health()
        if not health.get("available"):
            raise RuntimeError(f"Adapter unavailable: {health.get('detail', adapter_id)}")
        observation = await adapter.observe()
        if observation.adapter_id != adapter_id or observation.adapter_version != adapter.capability.version:
            raise ValueError("Adapter observation identity/version mismatch")
        self._observations[observation.observation_id] = observation
        while len(self._observations) > 128:
            self._observations.popitem(last=False)
        return observation

    def _validate(self, request: ActionRequest, adapter, observation: Observation, epoch: int):
        now = self._clock()
        if self._stopped or epoch != self._epoch:
            raise InterruptedError("Body emergency stop or focus change invalidated the action")
        if not math.isfinite(request.deadline) or now >= request.deadline:
            raise ValueError("Action deadline expired")
        if not math.isfinite(request.max_observation_age) or request.max_observation_age <= 0:
            raise ValueError("Observation age limit must be positive and finite")
        age = now - observation.monotonic_time
        if age < 0 or age > request.max_observation_age:
            raise ValueError("Observation is stale or belongs to a different clock")
        if observation.adapter_id != request.adapter_id or observation.adapter_version != adapter.capability.version:
            raise ValueError("Observation does not match the current adapter version")
        if request.operation not in adapter.capability.operations:
            raise ValueError("Operation is not registered")
        if request.scope != adapter.capability.scope:
            raise PermissionError("Action scope does not match the host-authorized adapter scope")
        if request.expected_window is not None and request.expected_window != observation.window_id:
            raise ValueError("Expected window does not match observation")

    @staticmethod
    def _same_surface(before: Observation, current: Observation) -> bool:
        return (before.window_id, before.width, before.height, before.dpi, before.revision,
                before.adapter_version) == (current.window_id, current.width, current.height,
                                           current.dpi, current.revision, current.adapter_version)

    async def execute(self, request: ActionRequest, cancel: asyncio.Event | None = None) -> ActionReceipt:
        token = cancel or asyncio.Event()
        epoch = self._epoch
        adapter = self._adapters.get(request.adapter_id)

        def receipt(outcome: AdapterOutcome):
            status = outcome.status
            if status not in {"success", "failure", "cancelled", "unknown"}:
                status = "unknown"
            if status == "success" and not outcome.verified:
                status = "unknown"
            return ActionReceipt(request.action_id, request.adapter_id, request.operation, status,
                                 outcome.verified, outcome.detail, request.observation_id,
                                 evidence=outcome.evidence)

        if adapter is None:
            return receipt(AdapterOutcome("failure", detail="Adapter is not registered"))
        async with self._locks[request.adapter_id]:
            try:
                if request.adapter_id in self._unsettled or self._adapters.get(request.adapter_id) is not adapter:
                    raise RuntimeError("Adapter was replaced or has unresolved action cleanup")
                if token.is_set():
                    return receipt(AdapterOutcome("cancelled", detail="Cancelled before dispatch"))
                observation = self._observations.get(request.observation_id)
                if observation is None:
                    raise ValueError("Observation is missing or expired from the registry")
                self._validate(request, adapter, observation, epoch)
                health = await adapter.health()
                if not health.get("available"):
                    raise RuntimeError(f"Adapter unavailable: {health.get('detail', '')}")
                current = await adapter.observe()
                if not self._same_surface(observation, current):
                    await adapter.stop()
                    raise ValueError("Window, size, DPI, version or observed state changed; observe again")
                self._validate(request, adapter, observation, epoch)
                if token.is_set():
                    return receipt(AdapterOutcome("cancelled", detail="Cancelled during preflight"))
            except InterruptedError as exc:
                return receipt(AdapterOutcome("cancelled", detail=str(exc)))
            except Exception as exc:
                return receipt(AdapterOutcome("failure", detail=f"{type(exc).__name__}: {exc}"))
            task = asyncio.create_task(adapter.execute(request, token))
            cancelled = asyncio.create_task(token.wait())
            self._active[request.adapter_id] = (token, task)
            try:
                done, _ = await asyncio.wait((task, cancelled), timeout=max(0, request.deadline - self._clock()),
                                             return_when=asyncio.FIRST_COMPLETED)
                if task in done:
                    return receipt(task.result())
                token.set()
                # Physical release is attempted even if the adapter call is stuck.
                await self._bounded_stop(adapter)
                task.cancel()
                finished, _ = await asyncio.wait((task,), timeout=self._stop_timeout)
                if task in finished and not task.cancelled():
                    try:
                        return receipt(task.result())
                    except Exception:
                        pass
                return receipt(AdapterOutcome("unknown", detail="Cancellation/deadline after dispatch; completion not verified"))
            except asyncio.CancelledError:
                token.set()
                await self._bounded_stop(adapter)
                task.cancel()
                return receipt(AdapterOutcome("unknown", detail="Caller cancelled after dispatch; completion not verified"))
            except Exception as exc:
                return receipt(AdapterOutcome("unknown", detail=f"Adapter failed after dispatch: {type(exc).__name__}: {exc}"))
            finally:
                cancelled.cancel()
                await asyncio.gather(cancelled, return_exceptions=True)
                if not task.done():
                    task.cancel()
                    self._unsettled[request.adapter_id] = task
                    task.add_done_callback(_consume_task)
                self._active.pop(request.adapter_id, None)

    async def _bounded_stop(self, adapter) -> dict:
        task = asyncio.create_task(adapter.stop())
        done, _ = await asyncio.wait((task,), timeout=self._stop_timeout)
        if task not in done:
            task.cancel()
            task.add_done_callback(_consume_task)
            return {"status": "unknown", "detail": "Adapter stop acknowledgement timed out"}
        try:
            result = task.result()
            unresolved = isinstance(result, dict) and (result.get("status") == "unknown" or result.get("release_errors"))
            return {"status": "unknown" if unresolved else "stopped", "result": result}
        except Exception as exc:
            return {"status": "unknown", "detail": str(exc)}

    async def stop(self) -> dict:
        self._stopped = True
        self._epoch += 1
        for token, _ in self._active.values():
            token.set()
        result = await asyncio.gather(*(self._bounded_stop(adapter) for adapter in self._adapters.values()))
        return dict(zip(self._adapters, result))

    async def focus_lost(self) -> dict:
        """Invalidate pending observations/actions and release all key leases."""
        return await self.stop()

    def resume(self) -> None:
        if self._active or any(not task.done() for task in self._unsettled.values()):
            raise RuntimeError("Wait for active action cleanup before resuming")
        self._unsettled.clear()
        self._observations.clear()
        self._stopped = False


def _consume_task(task):
    if not task.cancelled():
        task.exception()

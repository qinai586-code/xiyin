"""One runtime's state, agenda, body, sleep, learning and maintenance services.

Domain commands do not infer authority from a model's prose. The local console
is owner-bound by the host entry; external adapters receive public text access.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import time
from uuid import uuid4

from .agenda import Agenda
from .contracts import InputEvent
from .self_state import SelfState
from .director import Director, FileSkillPlanner, validate_plan
from .context import RUNTIME_FACTS, RUNTIME_FACTS_V3


class DisabledModelProvider:
    """An explicit no-model runtime. It never fabricates a successful reply."""
    async def stream(self, messages, cancel):
        raise RuntimeError("Model is disabled for this runtime; no inference request was made")
        yield


class RuntimeServices:
    def _initialize_services(self, *, data_root_id):
        from .body.registry import BodyRegistry
        from .learning import LearningLab, BuiltinPolicyEvaluator
        from .sleep import SleepController
        from .supervisor import Supervisor
        self.agenda = Agenda(self.store)
        self.self_state = SelfState(self.store, persona=self.persona)
        self.director = Director(self.store, self.self_state, self.agenda, planner=FileSkillPlanner())
        self.body = BodyRegistry()
        self.sleep_controller = SleepController(self.store, agenda=self.agenda)
        self.lab = LearningLab(self.store, evaluator=BuiltinPolicyEvaluator())
        self.supervisor = (Supervisor(self.store, self.store.path.parent, data_root_id)
                           if data_root_id is not None else None)
        self.speech = None
        self.voice = None
        self._job_token = None
        self._job_active = False
        self._job_task = None
        self._active_task = None
        # Direct action dispatches are caller tasks the runtime does not own.
        # Shutdown must still drain them before closing the ledger, so they are
        # tracked here rather than left to finish by scheduling luck.
        self._action_tasks = set()
        self._stopped = False
        self._dispatch_lock = asyncio.Lock()
        self._last_input = time.monotonic()
        # The machine clock is the trusted source of "now"; tests may replace it.
        self.clock = lambda: datetime.now().astimezone()

    def _ensure_running(self):
        if self._stopped or (self.supervisor and self.supervisor.stop_requested()):
            raise RuntimeError("Runtime is stopped; explicitly resume before new work")

    def register_workspace(self, path):
        """Host-only grant. A chat message or generated path cannot register it."""
        self._authorize()
        from .body.actions import WorkspaceFileAdapter
        adapter = WorkspaceFileAdapter(Path(path))
        self.body.register(adapter)
        return adapter.capability.to_dict()

    def attach_speech(self, controller):
        """Host supplies a configured ASR/TTS/sink controller; no second Mind."""
        self._authorize()
        from .voice import RuntimeVoiceSession
        if self.speech is not None:
            raise RuntimeError("Close the previous voice session before attaching another body")
        self.speech = controller
        self.voice = RuntimeVoiceSession(self, controller)
        return self.voice

    def grounding_facts(self, session_id, scope):
        """Trusted facts she may state as they are: public data, not instructions.

        The model has no clock. Without this line a date or weekday in a reply
        is a guess (the reported wrong weekday was a grounding gap, not recall).
        """
        now = self.clock()
        offset = now.strftime("%z")
        zone = f"UTC{offset[:3]}:{offset[3:]}" if offset else "本机时区"
        weekday = "一二三四五六日"[now.weekday()]
        return (f"当前本机时间：{now.year}年{now.month}月{now.day}日，星期{weekday}，{now:%H:%M}（{zone}）。",)

    def continuity_facts(self, session_id, scope):
        """How long since this session last spoke, from the ledger and the clock.

        v3 tells her that after a restart she knows how much time has passed.
        That is only true if the time is in front of her; without this line
        an elapsed time in a reply would be invented.
        """
        last = self.store.last_utterance_at(session_id, scope)
        if last is None:
            return ("这段会话之前没有对话记录。",)
        now = self.clock()
        try:
            then = datetime.fromisoformat(last).astimezone(now.tzinfo)
        except (TypeError, ValueError):
            return ()
        line = f"这段会话上次有人说话：{then.year}年{then.month}月{then.day}日 {then:%H:%M}"
        seconds = (now - then).total_seconds()
        if seconds >= 0:
            line += "，距现在" + (
                "不到两分钟" if seconds < 120 else
                f"约{round(seconds / 60)}分钟" if seconds < 3600 else
                f"约{round(seconds / 3600)}小时" if seconds < 172800 else
                f"约{round(seconds / 86400)}天")
        return (line + "。",)

    def conversation_facts(self, session_id, scope, register="v1"):
        if register == "v3":
            return self._spoken_facts(session_id, scope)
        available = [item for item in self.body.capabilities() if item["available"]]
        facts = RUNTIME_FACTS
        if available or self.speech is not None:
            facts = facts.replace("当前接口提供文字交流和记录读取，未接入屏幕、设备操作或语音播放；许可本身不会增加能力。",
                                  "文字和记录读取已接入；操作须由运行核心调用已登记的身体接口，许可本身不会增加能力。")
            for item in available:
                facts += "\n已登记接口：" + item["adapter_id"] + "，可执行：" + "、".join(item["operations"]) + "。执行完成仍须核对回执。"
            if self.speech is not None:
                facts += "\n语音控制器已连接；合成、送达、客户端播放和输出观察是不同结果，不证明对方听见。"
        # Read-only projection: asking for context must not invent an observation.
        state = self.store.read_document("state", f"self:xiyin:{scope}:{session_id}")
        if state:
            activity = state["value"].get("activity", "idle")
            labels = {"idle": "空闲", "conversation": "交流", "rest": "休息", "stopped": "已停止"}
            facts += "\n当前活动：" + labels.get(activity, activity) + "。运行状态仅作当前背景，不用向对方逐项汇报。"
        # Attention, mood and footing reach expression here. The projection is
        # read-only and falls back to starting values, so the first turn of a
        # session carries the same kind of context as every later one.
        try:
            facts += "\n" + self.self_state.disposition(session_id, scope)["line"]
        except Exception:
            pass
        return facts

    def _spoken_facts(self, session_id, scope):
        """The v3 register of conversation_facts: same facts, her situation.

        The v1 state line ended "它不是主观体验", a metaphysical denial the
        character does not hold (Bible §18: she does not know) and the model
        turned into "作为AI，我没有真正的感情". Here the state is labelled as a
        runtime estimate, which is what the engineering claim actually is.
        """
        available = [item for item in self.body.capabilities() if item["available"]]
        facts = RUNTIME_FACTS_V3
        if available or self.speech is not None:
            facts = facts.replace("现在你只能打字交流和翻看记录，还看不到屏幕，也没接上形象和声音；对方同意也不会让你多出这些能力。",
                                  "文字和记录已接上；动作要通过已登记的接口执行，对方同意也不会让你多出能力。")
            for item in available:
                facts += "\n已登记接口：" + item["adapter_id"] + "，可执行：" + "、".join(item["operations"]) + "。做完要看回执。"
            if self.speech is not None:
                facts += "\n声音已接上；合成、送达和播放是不同结果，都不代表对方听见了。"
        state = self.store.read_document("state", f"self:xiyin:{scope}:{session_id}")
        labels = {"idle": "空闲", "conversation": "在聊天", "rest": "休息", "stopped": "已停止"}
        activity = state["value"].get("activity", "idle") if state else "idle"
        try:
            disposition = self.self_state.disposition(session_id, scope)
        except Exception:
            return facts
        attention = disposition["attention"]
        attention_text = ("注意力在当前这句话" if attention == "current_input" else
                          f"注意力在{attention}" if attention else "注意力没有特别集中在哪件事上")
        acted = disposition["footing"] != "这段会话还没有执行过动作"
        facts += ("\n当前状态（运行时估计，用来调语气，不用说出来）：" + labels.get(activity, activity)
                  + f"，{attention_text}，语气{disposition['tone']}，状态{disposition['energy']}"
                  + (f"，{disposition['footing']}" if acted else "") + "。")
        return facts

    async def emergency_stop(self, reason="owner requested stop"):
        self._stopped = True
        if self.supervisor:
            self.supervisor.request_stop(reason)
        self.cancel()
        if self._job_token:
            self._job_token.set()
        self.agenda.stop(reason)
        self.reconcile_goals()
        body_result = await self.body.stop()
        if self.speech is not None:
            await self.speech.cancel()
        self.self_state.observe("stop", {"reason": reason})
        return {"stopped": True, "body": body_result}

    async def watch_stop(self, token):
        """Independent of a busy scheduler/model; an owner stop reaches active work."""
        while not token.is_set():
            if self.supervisor and self.supervisor.stop_requested():
                token.set()
                if not self._stopped:
                    await self.emergency_stop("external owner stop")
                return
            try:
                await asyncio.wait_for(token.wait(), 0.05)
            except TimeoutError:
                pass

    async def shutdown(self):
        """Release physical input, drain owned tasks, then close the shared ledger."""
        self.cancel()
        if self._job_token:
            self._job_token.set()
        await self.body.stop()
        try:
            if self.voice is not None:
                await self.voice.close()
            elif self.speech is not None:
                await self.speech.close()
        finally:
            pending = {task for task in (self._active_task, self._job_task, *self._action_tasks)
                       if task is not None and task is not asyncio.current_task() and not task.done()}
            if pending:
                done, live = await asyncio.wait(pending, timeout=0.25)
                for task in live:
                    task.cancel()
                if live:
                    forced_done, live = await asyncio.wait(live, timeout=2)
                    done |= forced_done
                for task in done:
                    if not task.cancelled():
                        task.exception()
                if live:
                    raise RuntimeError("Runtime tasks did not drain; keep the data lease until process exit")
            self.close()

    async def dispatch(self, event: InputEvent):
        self._authorize()
        if not isinstance(event, InputEvent):
            raise ValueError("A host-bound InputEvent is required")
        kind, payload = event.kind, event.payload
        session, scope = event.session_id, event.scope
        if kind == "stop":
            return await self.emergency_stop(payload.get("reason", "owner requested stop"))
        if kind == "status":
            return {"self": self.self_state.snapshot(session, scope), "body": await self.body.health(),
                    "capabilities": self.body.capabilities(), "sleep": self.sleep_controller.state(),
                    "jobs": [row["value"] for row in self.store.list_documents("jobs")],
                    "goals": [row["value"] for row in self.store.list_documents("goals")],
                    "strategy": self.lab.active_strategy(),
                    "supervisor": self.supervisor.health() if self.supervisor else {"registered_data_root": False},
                    "model_enabled": not isinstance(self.provider, DisabledModelProvider),
                    "stopped": self._stopped or bool(self.supervisor and self.supervisor.stop_requested())}
        if kind == "resume":
            if self.supervisor:
                self.supervisor.clear_stop()
            self.body.resume()
            self._stopped = False
            self.sleep_controller.wake("explicit resume")
            return self.self_state.observe("wake", {}, session, scope)
        self._ensure_running()
        if kind == "wake":
            result = self.sleep_controller.wake(payload.get("reason", "owner input"))
            self.self_state.observe("wake", {}, session, scope)
            return result
        if kind == "text":
            self._last_input = time.monotonic()
            if self._job_token:
                self._job_token.set()
            chunks = []
            terminal = "error"
            detail = ""
            async for item in self.stream_turn(payload.get("text"), session_id=session, scope=scope):
                if item.type == "text_delta":
                    chunks.append(item.text)
                elif item.type in {"complete", "error", "cancelled"}:
                    terminal, detail = item.type, item.detail
            return {"text": "".join(chunks), "status": terminal, "detail": detail}
        if kind == "remember":
            return {"memory_id": self.remember(payload.get("text", ""), kind=payload.get("kind", "fact"),
                                               subject=payload.get("subject", "owner"), session_id=session,
                                               scope=scope, supersedes=payload.get("supersedes")), "status": "verified_success"}
        if kind == "feedback":
            return self.self_state.observe("user_feedback", payload, session, scope)
        if kind == "observe":
            result = await self.body.observe(payload.get("adapter_id", "workspace"))
            self.store.append_event("body_observation", result.to_dict(), session_id=session, scope=scope,
                                    origin="observation", status="recorded")
            return result.to_dict()
        if kind == "action":
            return await self.execute_action(payload, session, scope)
        if kind == "plan":
            return self.director.propose_goal(payload["objective"], self.body.capabilities(), session, scope)
        if kind == "grow":
            candidate = self.director.propose_growth(payload["kind"], payload["subject"], payload["statement"],
                                                     payload["evidence_refs"], session_id=session, scope=scope)
            return self.director.adopt_growth(candidate["id"]) if payload.get("adopt", True) else candidate
        if kind == "rollback_growth":
            return self.director.rollback_growth(payload["candidate_id"])
        if kind == "goal":
            return self.create_goal(payload, session, scope)
        if kind == "tick":
            return await self.tick()
        if kind == "resume_job":
            return self.agenda.resume(payload["job_id"])
        if kind == "sleep":
            if self._active or self._job_active:
                raise RuntimeError("Sleep waits for foreground work to finish or be cancelled")
            return await self.sleep_now(session, scope)
        if kind == "learn":
            candidate = self.lab.propose(payload["goal"], payload["evidence_refs"],
                                         strategy=payload["strategy"], session_id=session)
            from .learning import POLICY_CHECKS
            result = self.lab.evaluate(candidate["id"], payload.get("checks", POLICY_CHECKS))
            if payload.get("adopt", True) and result.get("status") == "evaluated" and result.get("assessment", {}).get("passed") is True:
                return self.lab.adopt(candidate["id"])
            return result
        if kind == "rollback_strategy":
            return self.lab.rollback()
        if kind == "backup":
            if not self.supervisor:
                raise RuntimeError("Backup requires the registered data root")
            return self.supervisor.create_backup(payload["directory"])
        if kind == "export_dataset":
            from .dataset import export_dataset
            return export_dataset(self.store, payload["directory"], session_id=session, scope=scope)
        raise ValueError("Operation is not connected")

    async def execute_action(self, payload, session, scope, *, cancel=None):
        from .body.models import ActionRequest
        self._ensure_running()
        adapter_id = payload.get("adapter_id", "workspace")
        capabilities = {item["adapter_id"]: item for item in self.body.capabilities()}
        if adapter_id not in capabilities:
            raise ValueError("Body adapter is not registered")
        # Host registry supplies scope, never the model's proposed filesystem path.
        # Recent verified failures lower `control`; that state makes her look
        # again instead of reusing a supplied observation. This only ever adds
        # verification, so a bad appraisal cannot loosen an action.
        try:
            caution = self.self_state.disposition(session, scope)["caution"]
        except Exception:
            caution = False
        observation_id = None if caution else payload.get("observation_id")
        reobserved = caution and bool(payload.get("observation_id"))
        if not observation_id:
            observation_id = (await self.body.observe(adapter_id)).observation_id
        strategy = self.lab.active_strategy()
        request = ActionRequest(adapter_id, payload["operation"], observation_id,
                                capabilities[adapter_id]["scope"], time.monotonic() + 10,
                                arguments=payload.get("arguments", {}), policy=strategy.get("policy", {}),
                                expected_window=payload.get("expected_window"))
        # Write an intent before dispatch. A crash after this event does not imply success.
        self.store.append_event("action_intent", {"action_id": request.action_id, "adapter_id": adapter_id,
                                                  "operation": request.operation,
                                                  "reobserved_after_failure": reobserved}, session_id=session,
                                scope=scope, origin="observation", status="recorded")
        token = cancel if cancel is not None else asyncio.Event()
        watcher = asyncio.create_task(self.watch_stop(token))
        # Stay registered until the receipt is on the ledger, not merely until
        # the adapter returns: the window this closes is exactly the one
        # between dispatch finishing and the outcome being recorded.
        current = asyncio.current_task()
        if current is not None:
            self._action_tasks.add(current)
        try:
            try:
                receipt = await self.body.execute(request, cancel=token)
            finally:
                if cancel is None:
                    token.set()
                if not self._stopped:
                    watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            status = {"success": "verified_success", "failure": "verified_failure"}.get(receipt.status, receipt.status)
            record = receipt.to_dict()
            evidence = self.store.append_event("action_result", record, session_id=session, scope=scope,
                                               origin="tool_result", status=status)
            self.self_state.observe("action_result", {"event_id": evidence, "status": status}, session, scope)
            return dict(record, event_id=evidence)
        finally:
            if current is not None:
                self._action_tasks.discard(current)

    def create_goal(self, payload, session, scope):
        title, steps = payload.get("title"), payload.get("steps")
        if not isinstance(title, str) or not title.strip() or not isinstance(steps, list) or not 1 <= len(steps) <= 32:
            raise ValueError("A goal needs a title and 1–32 typed action steps")
        normalized = [{"adapter_id": step.get("adapter_id", "workspace"),
                       "operation": step.get("operation"), "arguments": step.get("arguments", {})}
                      for step in steps if isinstance(step, dict)]
        if len(normalized) != len(steps) or any(set(step) - {"adapter_id", "operation", "arguments"} for step in steps):
            raise ValueError("Unexpected goal step fields")
        validated = validate_plan({"title": title, "steps": normalized}, self.body.capabilities())
        steps = validated["steps"]
        goal_id = "goal_" + uuid4().hex
        goal = {"id": goal_id, "title": title.strip(), "steps": steps, "session_id": session,
                "scope": scope, "status": "queued", "completed_steps": 0,
                "capability_bindings": validated["capability_bindings"]}
        with self.store.document_transaction():
            job = self.agenda.enqueue("goal", {"goal_id": goal_id, "session_id": session},
                                      priority=payload.get("priority", 0), scope=scope, resumable=False)
            goal["job_id"] = job["id"]
            self.store.write_document("goals", goal_id, goal, expected_version=0)
        return goal

    async def tick(self):
        self._ensure_running()
        if self._active or self._job_active:
            return {"status": "foreground_busy"}
        if (self.sleep_controller.state()["phase"] == "sleeping"
                and any(row["value"]["status"] == "queued" for row in self.store.list_documents("jobs"))):
            self.sleep_controller.wake("scheduled goal")
            self.self_state.observe("wake", {"reason": "scheduled goal"})
        job = self.agenda.claim_next()
        if job is None:
            return {"status": "idle"}
        self._job_active = True
        self._job_task = asyncio.current_task()
        self._job_token = asyncio.Event()
        goal_envelope = self.store.read_document("goals", job["payload"].get("goal_id", "missing"))
        try:
            if job["kind"] != "goal" or goal_envelope is None:
                return self.agenda.finish(job["id"], "failed", {"reason": "No executor for job kind"})
            goal = goal_envelope["value"]
            self.self_state.observe("activity", {"name": "task", "attention": goal["title"]}, goal["session_id"], goal["scope"])
            validated = validate_plan({"title": goal["title"], "steps": goal["steps"]}, self.body.capabilities())
            if validated["capability_bindings"] != goal.get("capability_bindings"):
                raise ValueError("Body capabilities changed since this goal was planned; replan before execution")
            results = []
            for step in goal["steps"][goal["completed_steps"]:]:
                if self._job_token.is_set() or self._active:
                    break
                result = await self.execute_action(step, goal["session_id"], goal["scope"], cancel=self._job_token)
                results.append(result)
                if result["status"] != "success":
                    break
                goal["completed_steps"] += 1
                with self.store.document_transaction():
                    latest = self.store.read_document("goals", goal["id"])
                    latest["value"]["completed_steps"] = goal["completed_steps"]
                    goal_envelope = self.store.write_document("goals", goal["id"], latest["value"],
                                                             expected_version=latest["version"])
                await asyncio.sleep(0)  # Speech/input/stop can preempt between bounded actions.
            success = goal["completed_steps"] == len(goal["steps"])
            outcome = "completed" if success else ("failed" if results and results[-1]["status"] == "failure" else "unknown")
            with self.store.document_transaction():
                current = self.agenda.get(job["id"])
                if current["status"] == "running":
                    current = self.agenda.finish(job["id"], outcome, {"receipts": results})
                latest = self.store.read_document("goals", goal["id"])
                latest["value"].update(status=current["status"], completed_steps=goal["completed_steps"])
                self.store.write_document("goals", goal["id"], latest["value"], expected_version=latest["version"])
                return current
        except BaseException as exc:
            with self.store.document_transaction():
                current = self.agenda.get(job["id"])
                if current["status"] == "running":
                    current = self.agenda.finish(job["id"], "unknown", {"reason": type(exc).__name__})
                if goal_envelope:
                    latest = self.store.read_document("goals", goal_envelope["key"])
                    latest["value"]["status"] = current["status"]
                    self.store.write_document("goals", latest["key"], latest["value"], expected_version=latest["version"])
            raise
        finally:
            self._job_task = None
            self._job_active = False
            self._job_token = None

    async def sleep_now(self, session="owner", scope="private"):
        self.sleep_controller.settle()
        result = await asyncio.to_thread(self.sleep_controller.consolidate, session, scope)
        if not result["interrupted"] and self.sleep_controller.state()["phase"] == "settling":
            # Consolidation is where feedback already on record becomes growth.
            # It runs only on an uninterrupted pass, so foreground input is
            # never waiting behind it, and every change stays rolled back-able.
            try:
                result = dict(result, growth=self.director.review_feedback_growth(session, scope))
            except Exception as exc:
                self.store.append_event("growth_review_error", {"error": type(exc).__name__},
                                        session_id=session, scope=scope, origin="observation", status="failed")
            self.sleep_controller.sleep()
            self.self_state.observe("rest", {}, session, scope)
        return result

    def reconcile_goals(self):
        for envelope in self.store.list_documents("goals"):
            goal = envelope["value"]
            job = self.agenda.get(goal["job_id"])
            if job["status"] in {"unknown", "cancelled", "failed"} and goal["status"] != job["status"]:
                goal["status"] = job["status"]
                self.store.write_document("goals", goal["id"], goal, expected_version=envelope["version"])

    async def run_background(self, closing: asyncio.Event, *, interval=0.25, idle_sleep_seconds=None):
        """One event loop, bounded jobs; user input/stop has priority over idle work."""
        if idle_sleep_seconds is None:
            idle_sleep_seconds = self.settings.idle_sleep_seconds
        while not closing.is_set():
            marker = self.supervisor.stop_requested() if self.supervisor else None
            if marker and not self._stopped:
                await self.emergency_stop(marker.get("reason", "external stop"))
            elif self._stopped and self.supervisor and not marker:
                # An independent, authorized owner console explicitly cleared it.
                self._stopped = False
                self.body.resume()
                self.self_state.observe("wake", {"reason": "external resume"})
            if not self._stopped and not (self.supervisor and self.supervisor.stop_requested()):
                try:
                    result = await self.tick()
                    if (result.get("status") == "idle" and idle_sleep_seconds > 0
                            and time.monotonic() - self._last_input >= idle_sleep_seconds
                            and self.sleep_controller.state()["phase"] == "awake"):
                        await self.sleep_now()
                except Exception as exc:
                    self.store.append_event("scheduler_error", {"error": type(exc).__name__},
                                            session_id="system", origin="observation", status="failed")
            try:
                await asyncio.wait_for(closing.wait(), timeout=interval)
            except TimeoutError:
                pass

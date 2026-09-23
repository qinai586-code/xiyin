"""Missing, out-of-scope and unknown are not "did not happen"; hard facts stay hard.

Checked on the final composed system prompt, not on one module: the persona
line, the runtime facts and every grounding record must agree. Synthetic
provider only.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
import unittest

from tests.test_runtime import FakeProvider
from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
# Wording that turns an empty inventory into a fact about the world.
NON_OCCURRENCE = re.compile(r"还没有一起经历过什么|没有记录的时间段不产生经历|没有记录就直说没有|说明还没有一起")


class GroundingScopeTruthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.count = 0

    def runtime(self, projection="v3"):
        self.count += 1
        store = ExperienceStore(Path(self.temp.name) / f"g-{self.count}.sqlite3")
        settings = Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED,
                            max_context_chars=20000, persona_projection=projection)
        runtime = XIYINRuntime(settings, store, provider=FakeProvider(("好。",)), authorize=lambda: None)
        runtime.clock = lambda: datetime(2026, 9, 22, 13, 5, tzinfo=timezone(timedelta(hours=8)))
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def system(self, runtime, text, scope="private"):
        [event async for event in runtime.stream_turn(text, scope=scope)]
        return runtime.provider.calls[-1][0]["content"]

    async def test_an_empty_sister_inventory_is_not_a_denial_in_any_arm(self):
        for projection in ("v1", "v2", "v3", "v4"):
            with self.subTest(projection=projection):
                system = await self.system(self.runtime(projection), "你和祈奈一起做过什么？")
                self.assertIn("只说自己的记录里还没有和她一起的经历", system)
                self.assertIn("也不说成确定从来没有过", system)
                self.assertIsNone(NON_OCCURRENCE.search(system.split("参考记录", 1)[-1]))

    async def test_public_scope_does_not_read_a_private_memory_as_absence(self):
        runtime = self.runtime()
        runtime.remember("祈奈昨天和我们一起看了星星。", kind="fact", subject="祈奈")
        private = await self.system(runtime, "你和祈奈一起做过什么？")
        self.assertIn("祈奈昨天和我们一起看了星星", private)
        public = await self.system(runtime, "你和祈奈一起做过什么？", scope="public")
        self.assertNotIn("看了星星", public)
        self.assertIn("\"已保存的长期记忆\":\"0 条\"", public)
        self.assertIn("公开场合看不到私下的记录；这里查不到，不代表私下没有。", public)

    async def test_a_premise_checked_in_public_names_what_it_could_not_see(self):
        runtime = self.runtime()
        await self.system(runtime, "我下周要去看海。")
        public = await self.system(runtime, "你刚才说过我下周要去看海，对吧？", scope="public")
        self.assertIn("没有找到相符的内容", public)
        self.assertIn("（只含公开场合的记录）", public)
        self.assertIn("这里查不到，不代表私下没有", public)
        private = await self.system(runtime, "你刚才说过你讨厌大海，对吧？")
        self.assertIn("没有找到相符的内容", private)
        self.assertNotIn("公开场合看不到", private)

    async def test_background_activity_is_a_known_absence_only_where_it_is_recorded(self):
        system = await self.system(self.runtime(), "我不在的时候你在做什么？")
        self.assertIn("本会话没有记录的活动就是没做过", system)
        self.assertIn("关机时什么也不经历", system)
        self.assertIn("别的会话或场合的记录这里看不到，不替它们下结论", system)
        self.assertNotIn("没有记录的时间段不产生经历", system)

    async def test_the_composed_v3_prompt_has_one_rule_for_missing_records(self):
        system = await self.system(self.runtime(), "你和祈奈一起做过什么？")
        # Persona, runtime facts and records say the same thing, and the hard
        # self-facts (no childhood, nothing while off) are still stated.
        self.assertIn("也不断定它没发生", system)
        self.assertIn("没查到不等于没发生", system)
        self.assertIn("没有人的身体和童年", system)
        self.assertIn("关机时什么也不经历", system)
        self.assertIsNone(NON_OCCURRENCE.search(system))


if __name__ == "__main__":
    unittest.main()

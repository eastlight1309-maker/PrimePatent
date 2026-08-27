# -*- coding: utf-8 -*-
"""설명(도움말) 화면 데이터 테스트.

설명은 실제 스코어링 상수에서 생성되므로, 배점을 바꾸면 설명도 함께 바뀌어야 한다.
"""

import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "python-lib"))

from flask import Flask  # noqa: E402

from primepatent.config import COMPONENT_MAX, COMPONENT_SOURCE  # noqa: E402
from primepatent.guide import COMPONENT_INFO, build_guide  # noqa: E402
from primepatent.webapp_routes import AppState, register_routes  # noqa: E402


class GuideDataTest(unittest.TestCase):
    def setUp(self):
        self.guide = build_guide()

    def test_totals_match_scoring_constants(self):
        self.assertEqual(self.guide["totalMax"], sum(COMPONENT_MAX.values()))
        self.assertEqual(self.guide["totalMax"], 100.0)
        self.assertAlmostEqual(self.guide["quantMax"] + self.guide["llmMax"],
                               self.guide["totalMax"], places=6)

    def test_every_component_is_documented(self):
        documented = {component["key"]
                      for area in self.guide["areas"] for component in area["components"]}
        self.assertEqual(documented, set(COMPONENT_MAX.keys()))
        self.assertEqual(len(documented), len(COMPONENT_MAX))
        # 설명 사전에 누락/잉여가 없어야 한다
        self.assertEqual(set(COMPONENT_INFO.keys()), set(COMPONENT_MAX.keys()))

    def test_component_max_and_source_match_code(self):
        for area in self.guide["areas"]:
            for component in area["components"]:
                self.assertEqual(component["max"], COMPONENT_MAX[component["key"]])
                self.assertEqual(component["source"], COMPONENT_SOURCE[component["key"]])
                self.assertAlmostEqual(component["quantMax"] + component["llmMax"],
                                       component["max"], places=6)

    def test_area_totals(self):
        totals = {area["key"]: area["max"] for area in self.guide["areas"]}
        self.assertEqual(totals, {"rights": 27.0, "tech": 21.0, "market": 27.0, "impact": 25.0})

    def test_every_component_has_explanation(self):
        for area in self.guide["areas"]:
            for component in area["components"]:
                self.assertTrue(component["how"].strip(), component["key"])
                self.assertTrue(component["fields"], component["key"])

    def test_country_weights_keep_declared_order(self):
        component = [c for area in self.guide["areas"] for c in area["components"]
                     if c["key"] == "market.entry"][0]
        countries = [item["country"] for item in component["weights"]]
        self.assertEqual(countries[0], "[소비] US")   # 가중치가 큰 순서로 선언됨
        self.assertTrue(any(c.startswith("[공급망]") for c in countries))
        consumer = sum(i["weight"] for i in component["weights"]
                       if i["country"].startswith("[소비]"))
        supply = sum(i["weight"] for i in component["weights"]
                     if i["country"].startswith("[공급망]"))
        self.assertAlmostEqual(consumer, 10.0, places=6)
        self.assertAlmostEqual(supply, 5.0, places=6)

    def test_grades_and_routes_present(self):
        self.assertEqual([g["grade"] for g in self.guide["grades"]], ["S", "A", "B", "C", "D"])
        self.assertEqual(len(self.guide["routes"]), 4)
        self.assertEqual(len(self.guide["steps"]), 7)
        self.assertGreaterEqual(len(self.guide["rules"]), 5)

    def test_field_groups_cover_catalog(self):
        from primepatent.columns import FIELDS
        total = sum(len(group["fields"]) for group in self.guide["fieldGroups"])
        self.assertEqual(total, len(FIELDS))
        required = [f for group in self.guide["fieldGroups"] for f in group["fields"]
                    if f["required"]]
        self.assertTrue(required)


class GuideApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask("guide")
        register_routes(self.app, AppState(local_root=os.path.join(BASE, "tmp", "guide_store")))
        self.client = self.app.test_client()

    def tearDown(self):
        import shutil
        shutil.rmtree(os.path.join(BASE, "tmp", "guide_store"), ignore_errors=True)

    def test_api_returns_guide(self):
        payload = self.client.get("/api/guide").get_json()
        self.assertTrue(payload["ok"])
        guide = payload["guide"]
        self.assertEqual(guide["totalMax"], 100.0)
        self.assertEqual(len(guide["areas"]), 4)
        self.assertEqual(sum(len(a["components"]) for a in guide["areas"]), len(COMPONENT_MAX))


if __name__ == "__main__":
    unittest.main(verbosity=2)

import unittest
from datetime import datetime

from api.main import _compute_table3_metrics
from core.network_builder import NetworkBuilder
from models.schemas import Commit, SmellInstance


class TestTable3Metrics(unittest.TestCase):
    def _commit(self, author_id, dt, files):
        return Commit(
            hash=f"{author_id}-{dt.isoformat()}",
            author_id=author_id,
            date=dt,
            tz_offset_minutes=60,
            message="test",
            files_modified=files,
        )

    def test_table3_metrics_and_turnover(self):
        commits_w1 = [
            self._commit("devA", datetime(2024, 1, 10, 10, 0, 0), ["a.py"]),
            self._commit("devB", datetime(2024, 1, 11, 11, 0, 0), ["a.py"]),
            self._commit("devA", datetime(2024, 1, 12, 12, 0, 0), ["b.py"]),
        ]
        nb1 = NetworkBuilder()
        nb1.build_collaboration_network(commits_w1)
        nb1.build_communication_network([])

        smells_w1 = [
            SmellInstance(
                smell_id="lone_wolf",
                name="Lone Wolf",
                type="Community",
                description="test",
                affected_entities=["devA"],
                message="test",
            )
        ]

        m1, state1 = _compute_table3_metrics(commits_w1, nb1, smells_w1, None)
        self.assertEqual(m1["devs"], 2)
        self.assertEqual(m1["code.only.devs"], 2)
        self.assertEqual(m1["ml.only.devs"], 0)
        self.assertEqual(m1["ratio.smelly.devs"], 0.5)
        self.assertIn("density", m1)

        commits_w2 = [
            self._commit("devA", datetime(2024, 4, 1, 10, 0, 0), ["c.py"]),
        ]
        nb2 = NetworkBuilder()
        nb2.build_collaboration_network(commits_w2)
        nb2.build_communication_network([])
        m2, _ = _compute_table3_metrics(commits_w2, nb2, [], state1)

        self.assertEqual(m2["devs"], 1)
        self.assertEqual(m2["global.turnover"], 0.5)
        self.assertEqual(m2["code.turnover"], 0.5)
        self.assertEqual(m2["ratio.smelly.quitters"], 0.0)


if __name__ == "__main__":
    unittest.main()

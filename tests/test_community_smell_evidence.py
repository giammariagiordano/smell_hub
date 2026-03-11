import unittest
from datetime import datetime

from analyzers.community_smells import CommunitySmellAnalyzer
from core.network_builder import NetworkBuilder
from models.schemas import Commit


class TestCommunitySmellEvidence(unittest.TestCase):
    def test_organizational_silo_includes_evidence(self):
        nb = NetworkBuilder()
        commits = [
            Commit(
                hash="a1",
                author_id="devA",
                date=datetime(2024, 1, 1, 10, 0, 0),
                message="a",
                files_modified=["x.py"],
            ),
            Commit(
                hash="b1",
                author_id="devB",
                date=datetime(2024, 1, 1, 11, 0, 0),
                message="b",
                files_modified=["x.py"],
            ),
        ]
        nb.build_collaboration_network(commits)
        nb.communication_source = "unit_test"
        nb.build_communication_network([("devA", "devC", datetime(2024, 1, 1, 12, 0, 0))])

        smells = CommunitySmellAnalyzer(nb).detect_organisational_silo()
        self.assertTrue(len(smells) >= 1)
        silo = smells[0]
        self.assertEqual(silo.smell_id, "organisational_silo")
        self.assertIn("evidence", silo.model_dump())
        self.assertIn("communication_source", silo.evidence)
        self.assertEqual(silo.evidence.get("communication_source"), "unit_test")


if __name__ == "__main__":
    unittest.main()

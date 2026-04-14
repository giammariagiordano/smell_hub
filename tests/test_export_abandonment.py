import unittest
from datetime import datetime

from api.main import _window_export_developers
from models.schemas import Developer, Project, ProjectMetrics, ProjectTimeWindow


class TestExportAbandonment(unittest.TestCase):
    def test_window_export_includes_previously_active_abandoned_developers(self):
        dev_a_w1 = Developer(
            id="devA",
            aliases=["Dev A"],
            emails=["a@example.com"],
            classification="Software Engineer",
            commits_count=3,
            last_commit_hash="abc123",
            last_commit_date=datetime(2024, 1, 15, 10, 0, 0),
            last_commit_message="last message",
        )
        dev_b_w2 = Developer(
            id="devB",
            aliases=["Dev B"],
            emails=["b@example.com"],
            classification="AI-Engineer",
            commits_count=2,
        )
        project = Project(
            id="p1",
            name="demo",
            url="https://example.com/repo.git",
            local_path="/tmp/repo",
            time_windows=[
                ProjectTimeWindow(
                    id="w1",
                    label="W1",
                    start_date=datetime(2024, 1, 1),
                    end_date=datetime(2024, 3, 31),
                    developers=[dev_a_w1],
                    metrics=ProjectMetrics(project_id="p1"),
                    collaboration_edges=[],
                ),
                ProjectTimeWindow(
                    id="w2",
                    label="W2",
                    start_date=datetime(2024, 4, 1),
                    end_date=datetime(2024, 6, 30),
                    developers=[dev_b_w2],
                    metrics=ProjectMetrics(project_id="p1"),
                    collaboration_edges=[],
                ),
            ],
        )

        exported = _window_export_developers(project, 1, project.time_windows[1].developers)
        by_id = {dev.id: dev for dev in exported}

        self.assertIn("devA", by_id)
        self.assertIn("devB", by_id)
        self.assertTrue(by_id["devA"].is_abandoned)
        self.assertEqual(by_id["devA"].abandonment_status, "Abandoned")
        self.assertEqual(by_id["devA"].last_interaction_window_id, "w1")
        self.assertEqual(by_id["devA"].abandoned_since_window_id, "w2")
        self.assertEqual(by_id["devA"].commits_count, 0)
        self.assertEqual(by_id["devA"].sentiment_messages_count, 0)
        self.assertFalse(by_id["devB"].is_abandoned)


if __name__ == "__main__":
    unittest.main()

import unittest
import threading
import time
from unittest.mock import MagicMock

from analyzers.role_topic_modeling import RoleTopicModelingAnalyzer


class TestRoleTopicModelingAnalyzer(unittest.TestCase):
    def test_incremental_preparation_matches_full_prepare(self):
        analyzer = RoleTopicModelingAnalyzer(config={})
        documents = [
            {
                "project_id": "p1",
                "project_name": "demo",
                "time_window_id": "w2",
                "time_window_label": "Window 2",
                "source_id": "issue:42:comment:1",
                "source_label": "Issue #42 comment",
                "source_url": "https://example.test/issues/42#comment-1",
                "source_type": "issue_comment",
                "is_open": True,
                "thread_id": "issue:42",
                "thread_label": "Issue #42",
                "thread_url": "https://example.test/issues/42",
                "thread_is_open": True,
                "developer_id": "bob",
                "role": "AI/ML Engineer",
                "text": "I disagree, the rollout should proceed this week.",
                "timestamp": "2024-01-02T13:00:00",
            },
            {
                "project_id": "p1",
                "project_name": "demo",
                "time_window_id": "w1",
                "time_window_label": "Window 1",
                "source_id": "issue:42",
                "source_label": "Issue #42",
                "source_url": "https://example.test/issues/42",
                "source_type": "issue",
                "is_open": True,
                "thread_id": "issue:42",
                "thread_label": "Issue #42",
                "thread_url": "https://example.test/issues/42",
                "thread_is_open": True,
                "developer_id": "alice",
                "role": "Software Engineer",
                "text": "We should not ship this model until the evaluation bug is fixed.",
                "timestamp": "2024-01-01T12:00:00",
            },
            {
                "project_id": "p1",
                "project_name": "demo",
                "time_window_id": "w3",
                "time_window_label": "Window 3",
                "source_id": "commit:abc1234",
                "source_label": "Commit abc1234",
                "source_url": "https://example.test/commit/abc1234",
                "source_type": "commit_message",
                "is_open": False,
                "thread_id": "commit:abc1234",
                "thread_label": "Commit abc1234",
                "thread_url": "https://example.test/commit/abc1234",
                "thread_is_open": False,
                "developer_id": "carol",
                "role": "Hybrid",
                "text": "Revert previous rollout attempt after failed benchmark.",
                "timestamp": "2024-01-03T08:00:00",
            },
        ]

        expected = analyzer._prepare_documents(documents)
        accumulator = analyzer.prepare_documents_incremental()
        for document in documents:
            analyzer.add_document_to_prepared(accumulator, document)
        actual = analyzer.finalize_prepared_documents(accumulator)

        self.assertEqual(actual, expected)

    def test_build_result_expands_conflict_participants_from_discussion_thread(self):
        analyzer = RoleTopicModelingAnalyzer(config={})
        prepared = {
            "source_breakdown": {"issue": 1, "issue_comment": 1},
            "discussion_source_count": 2,
            "potential_conflict_threads": [],
            "threads": [
                {
                    "thread_id": "issue:42",
                    "thread_label": "Issue #42",
                    "thread_url": "https://example.test/issues/42",
                    "source_type": "issue",
                    "is_open": True,
                    "participants": [
                        {"developer_id": "alice", "role": "Software Engineer"},
                        {"developer_id": "bob", "role": "AI/ML Engineer"},
                        {"developer_id": "carol", "role": "Hybrid"},
                    ],
                    "items": [
                        {
                            "source_id": "issue:42",
                            "developer_id": "alice",
                            "role": "Software Engineer",
                            "source_type": "issue",
                            "label": "Issue #42",
                        },
                        {
                            "source_id": "issue:42:comment:1",
                            "developer_id": "bob",
                            "role": "AI/ML Engineer",
                            "source_type": "issue_comment",
                            "label": "Issue #42 comment",
                        },
                    ],
                }
            ],
        }
        source_map = {
            "issue:42": {
                "source_id": "issue:42",
                "label": "Issue #42",
                "url": "https://example.test/issues/42",
                "source_type": "issue",
                "is_open": True,
                "thread_id": "issue:42",
            },
            "issue:42:comment:1": {
                "source_id": "issue:42:comment:1",
                "label": "Issue #42 comment",
                "url": "https://example.test/issues/42#comment-1",
                "source_type": "issue_comment",
                "is_open": True,
                "thread_id": "issue:42",
            },
        }
        developer_role_map = {
            "alice": "Software Engineer",
            "bob": "AI/ML Engineer",
            "carol": "Hybrid",
        }
        result = analyzer._build_result(
            data={
                "taxonomy_notes": [],
                "roles": [],
                "developers": [],
                "conflicts": [
                    {
                        "conflict_title": "Model rollout disagreement",
                        "developer_id": "alice",
                        "counterpart_id": "bob",
                        "participant_ids": ["alice", "bob"],
                        "participant_roles": [],
                        "role_combination": "",
                        "status": "open",
                        "summary": "Disagreement on whether to ship the new model.",
                        "resolution_summary": "",
                        "evidence_count": 2,
                        "open_conflict": True,
                        "primary_trace_source_id": "issue:42",
                        "trace_source_ids": ["issue:42", "issue:42:comment:1"],
                    }
                ],
            },
            source_count=2,
            source_map=source_map,
            developer_role_map=developer_role_map,
            counts_by_role={
                "Software Engineer": 1,
                "AI/ML Engineer": 1,
                "Hybrid": 1,
            },
            prepared=prepared,
        )
        self.assertEqual(len(result.conflicts), 1)
        conflict = result.conflicts[0]
        self.assertEqual(conflict.participant_ids, ["alice", "bob", "carol"])
        self.assertEqual(
            conflict.role_combination,
            "Software Engineer x AI/ML Engineer x Hybrid",
        )
        self.assertEqual(
            conflict.participant_roles,
            ["Software Engineer", "AI/ML Engineer", "Hybrid"],
        )

    def test_analyze_documents_runs_conflict_judge_even_with_single_candidate_run(self):
        analyzer = RoleTopicModelingAnalyzer(
            config={"api_key": "test-key", "model": "gpt-5-mini", "llm_runs": 1}
        )
        analyzer._request_structured_json = MagicMock(
            return_value={
                "rationale": "Normalized participants from the issue thread.",
                "conflicts": [
                    {
                        "conflict_title": "Model rollout disagreement",
                        "developer_id": "alice",
                        "counterpart_id": "bob",
                        "participant_ids": ["alice", "bob"],
                        "participant_roles": ["Software Engineer", "AI/ML Engineer"],
                        "role_combination": "Software Engineer x AI/ML Engineer",
                        "status": "open",
                        "summary": "Disagreement on whether to ship the new model.",
                        "resolution_summary": "",
                        "evidence_count": 1,
                        "open_conflict": True,
                        "primary_trace_source_id": "issue:42",
                        "trace_source_ids": ["issue:42"],
                    }
                ],
            }
        )
        analyzer._run_candidate_analysis = MagicMock(
            return_value={
                "taxonomy_notes": [],
                "roles": [],
                "developers": [],
                "conflicts": [],
            }
        )
        result = analyzer.analyze_documents(
            [
                {
                    "project_id": "p1",
                    "project_name": "demo",
                    "time_window_id": "w1",
                    "time_window_label": "Window 1",
                    "source_id": "issue:42",
                    "source_label": "Issue #42",
                    "source_url": "https://example.test/issues/42",
                    "source_type": "issue",
                    "is_open": True,
                    "thread_id": "issue:42",
                    "thread_label": "Issue #42",
                    "thread_url": "https://example.test/issues/42",
                    "thread_is_open": True,
                    "developer_id": "alice",
                    "role": "Software Engineer",
                    "text": "We should not ship this model until the evaluation bug is fixed.",
                    "timestamp": "2024-01-01T12:00:00",
                },
                {
                    "project_id": "p1",
                    "project_name": "demo",
                    "time_window_id": "w1",
                    "time_window_label": "Window 1",
                    "source_id": "issue:42:comment:1",
                    "source_label": "Issue #42 comment",
                    "source_url": "https://example.test/issues/42#comment-1",
                    "source_type": "issue_comment",
                    "is_open": True,
                    "thread_id": "issue:42",
                    "thread_label": "Issue #42",
                    "thread_url": "https://example.test/issues/42",
                    "thread_is_open": True,
                    "developer_id": "bob",
                    "role": "AI/ML Engineer",
                    "text": "I disagree, the rollout should proceed this week.",
                    "timestamp": "2024-01-01T13:00:00",
                },
            ],
            scope_label="demo",
        )
        self.assertTrue(result.judged)
        self.assertEqual(result.judge_model, "gpt-5-mini")
        self.assertEqual(analyzer._request_structured_json.call_count, 1)
        self.assertEqual(
            analyzer._request_structured_json.call_args.kwargs.get("schema_name"),
            "community_conflicts_judge",
        )

    def test_analyze_prepared_documents_runs_candidate_llm_calls_in_parallel(self):
        analyzer = RoleTopicModelingAnalyzer(
            config={"api_key": "test-key", "model": "gpt-5-mini", "judge_model": "gpt-5-mini", "llm_runs": 3}
        )
        prepared = analyzer._prepare_documents(
            [
                {
                    "project_id": "p1",
                    "project_name": "demo",
                    "time_window_id": "w1",
                    "time_window_label": "Window 1",
                    "source_id": "issue:42",
                    "source_label": "Issue #42",
                    "source_url": "https://example.test/issues/42",
                    "source_type": "issue",
                    "is_open": True,
                    "thread_id": "issue:42",
                    "thread_label": "Issue #42",
                    "thread_url": "https://example.test/issues/42",
                    "thread_is_open": True,
                    "developer_id": "alice",
                    "role": "Software Engineer",
                    "text": "We should not ship this model until the evaluation bug is fixed.",
                    "timestamp": "2024-01-01T12:00:00",
                },
                {
                    "project_id": "p1",
                    "project_name": "demo",
                    "time_window_id": "w1",
                    "time_window_label": "Window 1",
                    "source_id": "issue:42:comment:1",
                    "source_label": "Issue #42 comment",
                    "source_url": "https://example.test/issues/42#comment-1",
                    "source_type": "issue_comment",
                    "is_open": True,
                    "thread_id": "issue:42",
                    "thread_label": "Issue #42",
                    "thread_url": "https://example.test/issues/42",
                    "thread_is_open": True,
                    "developer_id": "bob",
                    "role": "AI/ML Engineer",
                    "text": "I disagree, the rollout should proceed this week.",
                    "timestamp": "2024-01-01T13:00:00",
                },
            ]
        )
        state = {"active": 0, "max_active": 0}
        state_lock = threading.Lock()

        def fake_run_candidate(scope_label, prepared_payload, run_index, total_runs):
            self.assertEqual(scope_label, "demo")
            self.assertEqual(total_runs, 3)
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.05)
            with state_lock:
                state["active"] -= 1
            return {
                "taxonomy_notes": [],
                "roles": [],
                "developers": [],
                "conflicts": [],
            }

        analyzer._run_candidate_analysis = MagicMock(side_effect=fake_run_candidate)
        analyzer._request_structured_json = MagicMock(
            return_value={
                "winner_index": 1,
                "rationale": "Run 1 is the most consistent.",
                "final_output": {
                    "taxonomy_notes": [],
                    "roles": [],
                    "developers": [],
                    "conflicts": [],
                },
            }
        )
        analyzer._run_conflict_judge = MagicMock(
            side_effect=lambda **kwargs: (kwargs["final_data"], "Participants normalized.")
        )

        result = analyzer.analyze_prepared_documents(prepared, scope_label="demo")

        self.assertEqual(result.status, "Completed")
        self.assertGreaterEqual(state["max_active"], 2)
        self.assertEqual(analyzer._run_candidate_analysis.call_count, 3)
        self.assertEqual(analyzer._request_structured_json.call_count, 1)
        self.assertTrue(result.judged)


if __name__ == "__main__":
    unittest.main()

import unittest

from api.main import _extract_login_from_noreply, _infer_gender_from_bio, _load_pronoun_sets


class TestGenderInference(unittest.TestCase):
    def test_extract_login_from_noreply(self):
        self.assertEqual(
            _extract_login_from_noreply("12345+octocat@users.noreply.github.com"),
            "octocat",
        )
        self.assertEqual(
            _extract_login_from_noreply("octocat@users.noreply.github.com"),
            "octocat",
        )
        self.assertIsNone(_extract_login_from_noreply("octocat@example.com"))

    def test_bio_she_her(self):
        gender, confidence, pronouns = _infer_gender_from_bio(
            "Staff engineer. Pronouns: she/her.", _load_pronoun_sets()
        )
        self.assertEqual(gender, "Woman")
        self.assertGreaterEqual(confidence, 0.7)
        self.assertIn("she", pronouns)

    def test_bio_he_they(self):
        gender, confidence, pronouns = _infer_gender_from_bio(
            "Open source maintainer - pronouns he/they", _load_pronoun_sets()
        )
        self.assertEqual(gender, "Multi-pronoun")
        self.assertGreaterEqual(confidence, 0.7)
        self.assertIn("he", pronouns)
        self.assertIn("they", pronouns)

    def test_bio_neopronouns(self):
        gender, confidence, pronouns = _infer_gender_from_bio(
            "pronouns: xe/xem", _load_pronoun_sets()
        )
        self.assertEqual(gender, "Non-binary")
        self.assertGreaterEqual(confidence, 0.7)
        self.assertIn("xe", pronouns)

    def test_bio_unknown(self):
        gender, confidence, pronouns = _infer_gender_from_bio(
            "Building distributed systems and infra", _load_pronoun_sets()
        )
        self.assertEqual(gender, "Unknown")
        self.assertEqual(confidence, 0.0)
        self.assertEqual(pronouns, [])


if __name__ == "__main__":
    unittest.main()

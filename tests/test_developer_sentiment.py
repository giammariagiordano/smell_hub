import unittest

from analyzers.developer_sentiment import DeveloperSentimentAnalyzer


class TestDeveloperSentiment(unittest.TestCase):
    def test_emotions_to_sentiment_positive(self):
        emotions = {
            "Anger": 0.1,
            "Fear": 0.1,
            "Sadness": 0.1,
            "Love": 0.8,
            "Joy": 0.7,
            "Surprise": 0.2,
        }
        score = DeveloperSentimentAnalyzer.emotions_to_sentiment(emotions)
        self.assertGreater(score, 0.15)
        self.assertEqual(DeveloperSentimentAnalyzer.sentiment_label(score), "Positive")

    def test_emotions_to_sentiment_negative(self):
        emotions = {
            "Anger": 0.8,
            "Fear": 0.7,
            "Sadness": 0.7,
            "Love": 0.1,
            "Joy": 0.1,
            "Surprise": 0.2,
        }
        score = DeveloperSentimentAnalyzer.emotions_to_sentiment(emotions)
        self.assertLess(score, -0.15)
        self.assertEqual(DeveloperSentimentAnalyzer.sentiment_label(score), "Negative")


if __name__ == "__main__":
    unittest.main()

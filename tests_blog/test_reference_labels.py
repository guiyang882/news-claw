import unittest

from workflows.blog_presentation import with_references


class ReferenceLabelsTests(unittest.TestCase):
    def test_extraction_label_is_removed_in_both_languages(self):
        for language in ("zh", "en"):
            for separator in ("—", "–", "-"):
                with self.subTest(language=language, separator=separator):
                    source = {"title": "Research access", "publisher": f"NVIDIA Newsroom {separator} article body",
                              "url": "https://example.com/research"}
                    rendered = with_references("Research text", [source], language)
                    self.assertIn("NVIDIA Newsroom. [Research access](https://example.com/research).", rendered)
                    self.assertNotIn("article body", rendered)
                    self.assertEqual(source["publisher"], f"NVIDIA Newsroom {separator} article body")

    def test_similar_publisher_names_and_body_are_preserved(self):
        source = {"title": "Research access", "publisher": "The article body journal",
                  "url": "https://example.com/research"}
        rendered = with_references("Quoted text: article body", [source], "en")
        self.assertIn("The article body journal.", rendered)
        self.assertTrue(rendered.startswith("Quoted text: article body"))

    def test_existing_bibliography_is_not_duplicated(self):
        body = "Research text\n\n## References\n\nAn existing source.\n"
        self.assertEqual(with_references(body, [], "en"), body)

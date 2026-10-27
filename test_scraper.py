#!/usr/bin/env python3
"""
Unit tests for Website Data Scraper
"""

import unittest
from scraper import ContentExtractor, scrape_website


SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Test Page Title - Automated Web Scraping</title>
    <meta name="description" content="A comprehensive test guide to extracting web data efficiently.">
    <meta name="keywords" content="scraping, automation, n8n, python">
    <meta name="author" content="Kacper Wozniak">
    <meta property="og:title" content="OpenGraph Test Page Title">
    <meta property="og:description" content="OpenGraph description for social sharing.">
    <meta property="og:image" content="https://example.com/assets/og-image.jpg">
    <meta name="twitter:card" content="summary_large_image">
    <link rel="canonical" href="https://example.com/blog/web-scraping-guide">
    <style>body { font-family: sans-serif; } .ad-banner { display: none; }</style>
    <script>console.log("Ignore this script content");</script>
</head>
<body>
    <header>
        <nav>
            <a href="/">Home</a>
            <a href="/about">About Us</a>
        </nav>
    </header>

    <main>
        <h1>Mastering Web Scraping with n8n</h1>
        <p>Web scraping allows automated collection of structured information from the internet.</p>
        
        <h2>Why Use n8n for Data Scraping?</h2>
        <p>n8n is a powerful workflow automation tool that enables visual programming and seamless integrations.</p>
        <p>You can check out our external partner at <a href="https://external-resource.org/docs">External Resource</a> or view the <a href="/internal-guide">Internal Guide</a>.</p>
        
        <img src="/images/diagram.png" alt="Architecture Diagram">

        <h3>Key Advantages</h3>
        <ul>
            <li>Zero coding required for visual workflows</li>
            <li>Direct integration with databases, LLMs, and webhooks</li>
        </ul>
    </main>

    <footer>
        <p>&copy; 2026 Test Site. All rights reserved.</p>
    </footer>
</body>
</html>
"""


class TestContentExtractor(unittest.TestCase):

    def setUp(self):
        self.parser = ContentExtractor(base_url="https://example.com/articles/")
        self.parser.feed(SAMPLE_HTML)
        self.data = self.parser.get_structured_data()

    def test_title_and_metadata(self):
        self.assertEqual(self.data["title"], "Test Page Title - Automated Web Scraping")
        meta = self.data["metadata"]
        self.assertEqual(meta["description"], "A comprehensive test guide to extracting web data efficiently.")
        self.assertEqual(meta["author"], "Kacper Wozniak")
        self.assertEqual(meta["keywords"], "scraping, automation, n8n, python")
        self.assertEqual(meta["language"], "en")
        self.assertEqual(meta["canonical"], "https://example.com/blog/web-scraping-guide")

    def test_open_graph_and_twitter(self):
        og = self.data["metadata"]["open_graph"]
        self.assertEqual(og["title"], "OpenGraph Test Page Title")
        self.assertEqual(og["description"], "OpenGraph description for social sharing.")
        self.assertEqual(og["image"], "https://example.com/assets/og-image.jpg")

        twitter = self.data["metadata"]["twitter_card"]
        self.assertEqual(twitter["card"], "summary_large_image")

    def test_headings_hierarchy(self):
        headings = self.data["headings"]
        self.assertEqual(len(headings), 3)
        self.assertEqual(headings[0]["level"], 1)
        self.assertEqual(headings[0]["text"], "Mastering Web Scraping with n8n")
        self.assertEqual(headings[1]["level"], 2)
        self.assertEqual(headings[1]["text"], "Why Use n8n for Data Scraping?")
        self.assertEqual(headings[2]["level"], 3)
        self.assertEqual(headings[2]["text"], "Key Advantages")

    def test_link_categorization(self):
        links = self.data["links"]
        self.assertEqual(links["total"], 2)
        self.assertEqual(links["internal_count"], 1)
        self.assertEqual(links["external_count"], 1)

        external = links["external"][0]
        self.assertEqual(external["href"], "https://external-resource.org/docs")
        self.assertEqual(external["text"], "External Resource")
        self.assertFalse(external["is_internal"])

        internal = links["internal"][0]
        self.assertEqual(internal["href"], "https://example.com/internal-guide")
        self.assertEqual(internal["text"], "Internal Guide")
        self.assertTrue(internal["is_internal"])

    def test_image_extraction(self):
        images = self.data["images"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["src"], "https://example.com/images/diagram.png")
        self.assertEqual(images[0]["alt"], "Architecture Diagram")

    def test_script_style_nav_ignored(self):
        raw_text = self.data["clean_text"]
        self.assertNotIn("Ignore this script content", raw_text)
        self.assertNotIn("body { font-family", raw_text)
        self.assertNotIn("Home", raw_text)  # in <nav>
        self.assertNotIn("About Us", raw_text)  # in <nav>
        self.assertNotIn("All rights reserved", raw_text)  # in <footer>

    def test_markdown_and_metrics(self):
        md = self.data["clean_markdown"]
        self.assertIn("# Mastering Web Scraping with n8n", md)
        self.assertIn("## Why Use n8n for Data Scraping?", md)
        self.assertIn("[External Resource](https://external-resource.org/docs)", md)
        self.assertIn("![Architecture Diagram](https://example.com/images/diagram.png)", md)

        stats = self.data["statistics"]
        self.assertGreater(stats["word_count"], 10)
        self.assertGreater(stats["character_count"], 50)
        self.assertGreaterEqual(stats["reading_time_minutes"], 1)


if __name__ == "__main__":
    unittest.main()

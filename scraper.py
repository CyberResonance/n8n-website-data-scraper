#!/usr/bin/env python3
"""
Website Data Scraper & Content Extractor
-----------------------------------------
Zero-dependency, production-grade web scraper and structured content extractor.
Extracts metadata, OpenGraph tags, article text, markdown, links, and headings.
Provides both CLI and lightweight HTTP microservice interfaces.
"""

import argparse
import html
from html.parser import HTMLParser
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler


class ContentExtractor(HTMLParser):
    """
    State-aware HTML parser that extracts structured content:
    - Title and meta tags (description, keywords, author, OpenGraph, Twitter Cards)
    - Headings hierarchy (H1-H6)
    - Clean Markdown conversion
    - Internal and external links
    - Media/Images
    - Plain text
    """

    IGNORE_TAGS = {"script", "style", "noscript", "svg", "iframe", "nav", "footer"}
    BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "tr", "blockquote"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.parsed_base = urlparse(base_url)

        # Extracted data structures
        self.title = ""
        self.meta_tags = {}
        self.og_tags = {}
        self.twitter_tags = {}
        self.canonical_url = ""
        self.language = ""
        
        self.headings = []
        self.links = []
        self.images = []

        # Internal parser state
        self._tag_stack = []
        self._current_text = []
        self._markdown_lines = []
        self._current_line = []
        self._in_title = False
        self._current_heading_level = None
        self._current_heading_text = []
        self._current_link_href = None
        self._current_link_text = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        self._tag_stack.append(tag)

        # Language from <html>
        if tag == "html" and "lang" in attr_dict:
            self.language = attr_dict["lang"]

        # Page Title
        if tag == "title":
            self._in_title = True

        # Meta tags & OpenGraph
        if tag == "meta":
            name = attr_dict.get("name", "").lower()
            prop = attr_dict.get("property", "").lower()
            content = attr_dict.get("content", "").strip()

            if name:
                if name.startswith("twitter:"):
                    self.twitter_tags[name[8:]] = content
                else:
                    self.meta_tags[name] = content
            if prop:
                if prop.startswith("og:"):
                    self.og_tags[prop[3:]] = content
                elif prop.startswith("twitter:"):
                    self.twitter_tags[prop[8:]] = content

        # Canonical URL
        if tag == "link" and attr_dict.get("rel", "").lower() == "canonical":
            href = attr_dict.get("href", "")
            if href:
                self.canonical_url = urljoin(self.base_url, href)

        # Skip ignored elements
        if any(ignored in self._tag_stack for ignored in self.IGNORE_TAGS):
            return

        # Headings
        if tag in self.HEADING_TAGS:
            self._flush_line()
            self._current_heading_level = int(tag[1])
            self._current_heading_text = []

        # Links
        if tag == "a" and "href" in attr_dict:
            raw_href = attr_dict["href"].strip()
            if raw_href and not raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                abs_href = urljoin(self.base_url, raw_href)
                self._current_link_href = abs_href
                self._current_link_text = []

        # Images
        if tag == "img" and "src" in attr_dict:
            src = urljoin(self.base_url, attr_dict["src"].strip())
            alt = attr_dict.get("alt", "").strip()
            self.images.append({"src": src, "alt": alt})
            self._current_line.append(f"![{alt}]({src})")

        # Block boundaries
        if tag in self.BLOCK_TAGS:
            self._flush_line()

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag == "title":
            self._in_title = False
            self.title = "".join(self._current_text).strip()
            self._current_text = []

        if any(ignored in self._tag_stack for ignored in self.IGNORE_TAGS):
            if self._tag_stack and self._tag_stack[-1] == tag:
                self._tag_stack.pop()
            elif tag in self._tag_stack:
                self._tag_stack.remove(tag)
            return

        # Complete heading
        if tag in self.HEADING_TAGS and self._current_heading_level is not None:
            heading_txt = "".join(self._current_heading_text).strip()
            if heading_txt:
                self.headings.append({
                    "level": self._current_heading_level,
                    "text": heading_txt
                })
                prefix = "#" * self._current_heading_level
                self._markdown_lines.append(f"{prefix} {heading_txt}")
                self._markdown_lines.append("")
            self._current_heading_level = None
            self._current_heading_text = []

        # Complete link
        if tag == "a" and self._current_link_href:
            link_txt = "".join(self._current_link_text).strip() or self._current_link_href
            parsed_link = urlparse(self._current_link_href)
            is_internal = parsed_link.netloc == "" or parsed_link.netloc == self.parsed_base.netloc
            self.links.append({
                "text": link_txt,
                "href": self._current_link_href,
                "is_internal": is_internal
            })
            self._current_line.append(f"[{link_txt}]({self._current_link_href})")
            self._current_link_href = None
            self._current_link_text = []

        if tag in self.BLOCK_TAGS:
            self._flush_line()

        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        elif tag in self._tag_stack:
            self._tag_stack.remove(tag)

    def handle_data(self, data):
        if self._in_title:
            self._current_text.append(data)
            return

        # Ignore text inside script, style, etc.
        if any(ignored in self._tag_stack for ignored in self.IGNORE_TAGS):
            return

        cleaned = re.sub(r"\s+", " ", data)
        if not cleaned:
            return

        if self._current_heading_level is not None:
            self._current_heading_text.append(cleaned)
        elif self._current_link_href is not None:
            self._current_link_text.append(cleaned)
        else:
            self._current_line.append(cleaned)

    def _flush_line(self):
        if self._current_line:
            line_str = " ".join("".join(self._current_line).split()).strip()
            if line_str:
                self._markdown_lines.append(line_str)
            self._current_line = []

    def get_structured_data(self) -> dict:
        self._flush_line()

        # Clean markdown document
        md_text = "\n\n".join([line for line in self._markdown_lines if line])
        md_text = re.sub(r"\n{3,}", "\n\n", md_text).strip()

        # Plain text
        plain_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md_text)
        plain_text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", plain_text)
        plain_text = re.sub(r"#+\s*", "", plain_text).strip()

        # Word count & reading metrics
        words = re.findall(r"\b\w+\b", plain_text)
        word_count = len(words)
        char_count = len(plain_text)
        est_reading_minutes = max(1, round(word_count / 200)) if word_count > 0 else 0

        # Group links into internal and external
        internal_links = [l for l in self.links if l["is_internal"]]
        external_links = [l for l in self.links if not l["is_internal"]]

        return {
            "title": self.title or self.og_tags.get("title", ""),
            "metadata": {
                "description": self.meta_tags.get("description") or self.og_tags.get("description", ""),
                "keywords": self.meta_tags.get("keywords", ""),
                "author": self.meta_tags.get("author") or self.og_tags.get("article:author", ""),
                "canonical": self.canonical_url or self.base_url,
                "language": self.language or "en",
                "open_graph": self.og_tags,
                "twitter_card": self.twitter_tags
            },
            "headings": self.headings,
            "links": {
                "total": len(self.links),
                "internal_count": len(internal_links),
                "external_count": len(external_links),
                "internal": internal_links[:50],  # cap preview list
                "external": external_links[:50]
            },
            "images": self.images[:50],
            "statistics": {
                "word_count": word_count,
                "character_count": char_count,
                "reading_time_minutes": est_reading_minutes
            },
            "clean_markdown": md_text,
            "clean_text": plain_text
        }


def scrape_website(url: str, timeout: int = 15, custom_headers: dict = None) -> dict:
    """
    Fetches and parses a webpage URL, returning structured metadata and content.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache"
    }
    if custom_headers:
        headers.update(custom_headers)

    req = urllib.request.Request(url, headers=headers)
    start_time = time.time()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            final_url = response.geturl()
            status_code = response.getcode()
            charset = response.headers.get_content_charset() or "utf-8"
            raw_bytes = response.read()
            html_content = raw_bytes.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return {
            "success": False,
            "url": url,
            "status_code": e.code,
            "error": f"HTTP Error {e.code}: {e.reason}",
            "execution_time_seconds": round(time.time() - start_time, 3)
        }
    except Exception as e:
        return {
            "success": False,
            "url": url,
            "status_code": 0,
            "error": str(e),
            "execution_time_seconds": round(time.time() - start_time, 3)
        }

    # Parse HTML
    parser = ContentExtractor(base_url=final_url)
    parser.feed(html_content)
    result = parser.get_structured_data()

    result["success"] = True
    result["url"] = url
    result["final_url"] = final_url
    result["status_code"] = status_code
    result["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result["execution_time_seconds"] = round(time.time() - start_time, 3)

    return result


class ScraperHttpServer(BaseHTTPRequestHandler):
    """Lightweight HTTP API handler for local microservice mode."""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/scrape":
            params = dict(q.split("=", 1) for q in parsed.query.split("&") if "=" in q)
            target_url = urllib.parse.unquote(params.get("url", ""))
            if not target_url:
                self._send_response_json(400, {"success": False, "error": "Missing 'url' query parameter"})
                return
            result = scrape_website(target_url)
            self._send_response_json(200, result)
        elif parsed.path == "/health":
            self._send_response_json(200, {"status": "ok", "service": "Website Data Scraper"})
        else:
            self._send_response_json(404, {"error": "Not Found. Use GET /scrape?url=<url> or POST /scrape"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/scrape":
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len)
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                self._send_response_json(400, {"success": False, "error": "Invalid JSON body"})
                return

            target_url = payload.get("url")
            if not target_url:
                self._send_response_json(400, {"success": False, "error": "Missing 'url' field in JSON body"})
                return

            timeout = int(payload.get("timeout", 15))
            headers = payload.get("headers")
            result = scrape_website(target_url, timeout=timeout, custom_headers=headers)
            self._send_response_json(200, result)
        else:
            self._send_response_json(404, {"error": "Not Found. Use POST /scrape with {\"url\": \"...\"}"})

    def _send_response_json(self, status: int, data: dict):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {args[0]} - {args[1]}\n")


def main():
    parser = argparse.ArgumentParser(description="Website Data Scraper & Structured Content Extractor")
    parser.add_argument("--url", "-u", type=str, help="Target URL to scrape")
    parser.add_argument("--format", "-f", choices=["json", "markdown", "text"], default="json", help="Output format")
    parser.add_argument("--output", "-o", type=str, help="Save result to file")
    parser.add_argument("--timeout", "-t", type=int, default=15, help="Request timeout in seconds")
    parser.add_argument("--serve", action="store_true", help="Start standalone HTTP microservice API")
    parser.add_argument("--port", "-p", type=int, default=8765, help="Port for HTTP microservice (default: 8765)")

    args = parser.parse_args()

    if args.serve:
        server_addr = ("", args.port)
        httpd = HTTPServer(server_addr, ScraperHttpServer)
        print(f"🚀 Website Data Scraper server running on http://localhost:{args.port}")
        print(f"   - GET  http://localhost:{args.port}/scrape?url=https://example.com")
        print(f"   - POST http://localhost:{args.port}/scrape  (JSON: {{'url': '...'}})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
            httpd.server_close()
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    result = scrape_website(args.url, timeout=args.timeout)

    if args.format == "markdown":
        output_str = result.get("clean_markdown", "")
    elif args.format == "text":
        output_str = result.get("clean_text", "")
    else:
        output_str = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Successfully saved scraped data to {args.output}")
    else:
        print(output_str)


if __name__ == "__main__":
    main()

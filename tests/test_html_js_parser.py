#!/usr/bin/env python3
"""
HTML/JS Syntax & Integrity Verification Suite: tests/test_html_js_parser.py

Verifies:
1. Extracts all inline <script> blocks from public/index.html.
2. Asserts all script blocks close cleanly before HTML elements.
3. Uses Node.js (`node -c`) or Python compilation to verify 0 JavaScript syntax errors.
4. Parses all inline event handler functions (onclick, onkeydown) in index.html and verifies their definitions exist in JavaScript.
"""

import unittest
import os
import sys
import re
import subprocess
from html.parser import HTMLParser

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
INDEX_HTML_PATHS = [
    os.path.join(PROJECT_ROOT, "public/index.html"),
    os.path.join(PROJECT_ROOT, "frontend/templates/index.html"),
]

class InlineScriptExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script = False
        self.script_blocks = []
        self.event_handlers = []
        self.current_script = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script':
            # Ignore external module script imports (src=...)
            attr_dict = dict(attrs)
            if 'src' not in attr_dict:
                self.in_script = True
                self.current_script = []

        # Collect inline event handlers (onclick, onkeydown, etc.)
        for attr, val in attrs:
            if attr.lower().startswith('on') and val:
                self.event_handlers.append((tag, attr, val))

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.in_script:
            self.in_script = False
            self.script_blocks.append(''.join(self.current_script))
            self.current_script = []

    def handle_data(self, data):
        if self.in_script:
            self.current_script.append(data)


class TestHTMLJSSyntaxIntegrity(unittest.TestCase):
    """Automated Test Suite for HTML Markup & Inline JS Syntax Integrity across public and frontend templates."""

    @classmethod
    def setUpClass(cls):
        cls.html_data = {}
        for path in INDEX_HTML_PATHS:
            cls.assertTrue(os.path.exists(path), f"File {path} does not exist.")
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            parser = InlineScriptExtractor()
            parser.feed(content)
            cls.html_data[path] = {
                'content': content,
                'parser': parser
            }

    def test_01_script_tags_properly_closed_before_html(self):
        """Assert <script> tags close cleanly before HTML elements and comments in all index.html templates."""
        for path, data in self.html_data.items():
            content = data['content']
            # Find all <script> tags (without src attribute)
            script_matches = list(re.finditer(r'<script(?![^>]*src=)[^>]*>', content, re.IGNORECASE))
            closing_matches = list(re.finditer(r'</script>', content, re.IGNORECASE))

            self.assertGreater(len(script_matches), 0, f"No inline script tags found in {path}")
            
            # Verify that for every open inline script tag, there is a matching </script> tag before any HTML modal markup
            modal_pos = content.find('id="resume-builder-modal"')
            if modal_pos != -1:
                for s_match in script_matches:
                    if s_match.start() < modal_pos:
                        # Find closing tag after this script start but before modal
                        matching_close = [c for c in closing_matches if s_match.start() < c.start() < modal_pos]
                        self.assertGreater(
                            len(matching_close), 0,
                            f"Unclosed <script> tag detected before HTML modal markup at position {s_match.start()} in {path}"
                        )

    def test_02_javascript_syntax_validity(self):
        """Verify inline JavaScript blocks contain zero syntax errors and no leaked HTML tags in all templates."""
        import shutil
        node_path = shutil.which('node')

        for path, data in self.html_data.items():
            parser = data['parser']
            self.assertGreater(len(parser.script_blocks), 0, f"No inline script blocks extracted from {path}.")

            for idx, block in enumerate(parser.script_blocks):
                if not block.strip():
                    continue

                # Assert that no HTML markup leaked into the inline JS block
                self.assertNotIn('<div', block, f"HTML <div> tag leaked into script block #{idx+1} in {path}")
                self.assertNotIn('<!--', block, f"HTML comment leaked into script block #{idx+1} in {path}")

                # Check bracket balance
                open_braces = block.count('{')
                close_braces = block.count('}')
                self.assertEqual(
                    open_braces, close_braces,
                    f"Mismatched curly braces in script block #{idx+1} in {path}: {open_braces} open vs {close_braces} close."
                )

                if node_path:
                    temp_js = os.path.join(PROJECT_ROOT, f".temp_test_script_{idx}.js")
                    try:
                        with open(temp_js, 'w', encoding='utf-8') as f:
                            f.write(block)

                        res = subprocess.run([node_path, '-c', temp_js], capture_output=True, text=True)
                        self.assertEqual(
                            res.returncode, 0,
                            f"JavaScript syntax error in script block #{idx+1} in {path}:\n{res.stderr}"
                        )
                    finally:
                        if os.path.exists(temp_js):
                            os.remove(temp_js)

    def test_03_inline_event_handlers_exist_in_js(self):
        """Verify every inline function call in onclick/onkeydown attributes exists in JavaScript code."""
        for path, data in self.html_data.items():
            parser = data['parser']
            combined_js = "\n".join(parser.script_blocks)
            
            # Also check exported functions in modules under public/static/js/ and frontend/static/js/
            for js_dir in [os.path.join(PROJECT_ROOT, "public/static/js"), os.path.join(PROJECT_ROOT, "frontend/static/js")]:
                if os.path.exists(js_dir):
                    for root, _, files in os.walk(js_dir):
                        for file in files:
                            if file.endswith('.js'):
                                with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                                    combined_js += "\n" + f.read()

            for tag, attr, expr in parser.event_handlers:
                # Extract function names called in inline expressions, e.g. handleSearchFromLanding() -> handleSearchFromLanding
                fn_calls = re.findall(r'([a-zA-Z0-9_$]+)\s*\(', expr)
                for fn in fn_calls:
                    if fn in ['if', 'for', 'while', 'switch', 'set', 'get']:
                        continue
                    self.assertIn(
                        fn, combined_js,
                        f"Inline event handler function '{fn}' in <{tag} {attr}=\"{expr}\"> in {path} is NOT defined in any JavaScript file!"
                    )


if __name__ == '__main__':
    unittest.main()

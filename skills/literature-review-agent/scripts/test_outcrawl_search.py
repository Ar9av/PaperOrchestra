#!/usr/bin/env python3
"""
test_outcrawl_search.py: regression tests for the optional Outcrawl Phase 1
backend.

Stdlib only; the HTTP call is stubbed, so no key or network is needed:

    python3 skills/literature-review-agent/scripts/test_outcrawl_search.py
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

import outcrawl_search
from outcrawl_search import ACADEMIC_DOMAINS, SNIPPET_CAP, build_query, normalize


def hit(url: str, title: str = "T", snippet: str = "S", rank: int = 1) -> dict:
    return {"url": url, "title": title, "snippet": snippet, "rank": rank}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class BuildQueryTest(unittest.TestCase):
    def test_plain_query_is_unchanged(self):
        self.assertEqual(build_query("sparse attention", None), "sparse attention")

    def test_academic_domains_become_site_operators(self):
        q = build_query("sparse attention", ACADEMIC_DOMAINS)
        self.assertTrue(q.startswith("sparse attention ("))
        for d in ACADEMIC_DOMAINS:
            self.assertIn(f"site:{d}", q)
        self.assertEqual(q.count(" OR "), len(ACADEMIC_DOMAINS) - 1)


class NormalizeTest(unittest.TestCase):
    def test_maps_fields_to_candidate_format(self):
        resp = {"hits": [hit("https://arxiv.org/abs/1", " Title ", " Body ", 3)]}
        [c] = normalize(resp, ["related_work[2.1]"], 10)
        self.assertEqual(c, {
            "title": "Title",
            "snippet": "Body",
            "source_url": "https://arxiv.org/abs/1",
            "discovered_for": ["related_work[2.1]"],
            "_outcrawl_rank": 3,
        })

    def test_drops_non_http_urls(self):
        resp = {"hits": [hit("ftp://x"), hit(""), hit("http://ok.org/a")]}
        out = normalize(resp, ["intro"], 10)
        self.assertEqual([c["source_url"] for c in out], ["http://ok.org/a"])

    def test_caps_snippet_and_limit(self):
        resp = {"hits": [hit(f"https://a.org/{i}", snippet="x" * 5000) for i in range(5)]}
        out = normalize(resp, ["intro"], 2)
        self.assertEqual(len(out), 2)
        self.assertEqual(len(out[0]["snippet"]), SNIPPET_CAP)

    def test_handles_missing_fields(self):
        out = normalize({"hits": [{"url": "https://a.org"}]}, ["intro"], 10)
        self.assertEqual(out[0]["title"], "")
        self.assertEqual(out[0]["snippet"], "")
        self.assertIsNone(out[0]["_outcrawl_rank"])
        self.assertEqual(normalize({}, ["intro"], 10), [])

    def test_discovered_for_is_copied_per_candidate(self):
        tags = ["intro"]
        out = normalize({"hits": [hit("https://a.org"), hit("https://b.org")]}, tags, 10)
        out[0]["discovered_for"].append("x")
        self.assertEqual(out[1]["discovered_for"], ["intro"])
        self.assertEqual(tags, ["intro"])


class SearchTest(unittest.TestCase):
    def test_missing_key_exits_1(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("sys.stderr", new=io.StringIO()) as err, \
                self.assertRaises(SystemExit) as cm:
            outcrawl_search.search("q", 5, None)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("OUTCRAWL_API_KEY", err.getvalue())

    def test_request_shape(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["req"] = req
            captured["timeout"] = timeout
            return FakeResponse(json.dumps({"hits": []}).encode())

        with mock.patch.dict(os.environ, {"OUTCRAWL_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(outcrawl_search.search("q", 7, ["arxiv.org"]), {"hits": []})

        req = captured["req"]
        self.assertEqual(req.full_url, outcrawl_search.OUTCRAWL_ENDPOINT)
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer k")
        self.assertEqual(req.get_header("User-agent"), outcrawl_search.USER_AGENT)
        self.assertEqual(json.loads(req.data), {"query": "q (site:arxiv.org)", "limit": 7})


class MainTest(unittest.TestCase):
    def run_main(self, argv, response):
        with mock.patch.object(sys, "argv", ["outcrawl_search.py", *argv]), \
                mock.patch.object(outcrawl_search, "search", return_value=response) as s, \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()):
            code = outcrawl_search.main()
        return code, out.getvalue(), s

    def test_clamps_num_results(self):
        _, _, s = self.run_main(["--query", "q", "--num-results", "99"], {"hits": [hit("https://a.org")]})
        self.assertEqual(s.call_args.args[1], outcrawl_search.MAX_NUM)
        _, _, s = self.run_main(["--query", "q", "--num-results", "0"], {"hits": [hit("https://a.org")]})
        self.assertEqual(s.call_args.args[1], 1)

    def test_empty_results_exit_1(self):
        code, out, _ = self.run_main(["--query", "q"], {"hits": []})
        self.assertEqual(code, 1)
        self.assertEqual(out, "")

    def test_default_output_is_candidates(self):
        code, out, _ = self.run_main(["--query", "q", "--discovered-for", "related_work[2.1]"],
                                     {"hits": [hit("https://a.org")]})
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["candidates"][0]["discovered_for"], ["related_work[2.1]"])

    def test_raw_output_is_unmodified(self):
        resp = {"hits": [hit("https://a.org")], "usage": {"credits": "0.5"}}
        code, out, _ = self.run_main(["--query", "q", "--raw"], resp)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), resp)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Later pages, partial failures and changing heads must remain visible."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock
from urllib.parse import urlsplit, parse_qs

from fastapi import HTTPException
from parallax.github_delivery import GitHubDelivery
from parallax.store import Store


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.service=GitHubDelivery(Store(Path(self.temp.name)),config={})
        self.service.binding=lambda *_: {"installation":1,"repository":2,"full_name":"test/repo"}
        self.service.token=AsyncMock(return_value="ephemeral")
        with self.service.store.connect() as db:
            db.execute("INSERT INTO github_publications VALUES(?,?,?,?,?,?)",("operation","space","workflow","actor","fingerprint",json.dumps({"binding":"binding","pr":1,"url":"https://github.com/test/repo/pull/1","commit":"a"*40})))
        self.fail_page=None; self.changing_head=False; self.unbounded=False; self.large=False
        self.calls=[]; self.head_reads=0
        self.service.remote=self.remote

    async def remote(self,binding,token,path):
        self.calls.append(path)
        endpoint=urlsplit(path).path
        if endpoint=="/pulls/1":
            self.head_reads+=1
            return {"head":{"sha":("b" if self.changing_head and self.head_reads>1 else "a")*40}}
        page=int(parse_qs(urlsplit(path).query)["page"][0])
        if (endpoint,page)==self.fail_page: raise HTTPException(502,"private upstream text")
        if endpoint.endswith("check-runs"):
            count=100 if page==1 or self.unbounded else 1
            return {"total_count":1001 if self.unbounded else 101,"check_runs":[{"id":100*(page-1)+i,"name":"later failing check" if page>1 else "check","status":"completed","conclusion":"failure" if page>1 else "success","html_url":"https://github.com/test/repo/actions/1","private_extra":"discard"} for i in range(count)]}
        if endpoint.endswith("/status"): return {"total_count":0,"statuses":[]}
        if endpoint.endswith("/reviews"):
            return [{"id":1,"state":"CHANGES_REQUESTED","body":"x"*(1024*1024+1),"html_url":"https://github.com/test/repo/pull/1"}] if self.large else []
        return []

    async def test_later_failed_check_is_not_hidden(self):
        result=await self.service.feedback("space","workflow")
        self.assertEqual(len(result["checks"]),101)
        self.assertEqual(result["checks"][-1]["conclusion"],"failure")
        self.assertEqual(result["page_counts"]["checks"],2)
        self.assertFalse(result["incomplete"])
        self.assertNotIn("private_extra",result["checks"][0])
        self.assertGreater(result["refreshed_at"],0)

    async def test_later_page_error_retains_evidence_and_marks_partial(self):
        self.fail_page=("/commits/"+"a"*40+"/check-runs",2)
        result=await self.service.feedback("space","workflow")
        self.assertEqual(len(result["checks"]),100)
        self.assertTrue(result["incomplete"])
        self.assertIn("checks",result["feedback_errors"])
        self.assertNotIn("private upstream",json.dumps(result))

    async def test_head_change_invalidates_feedback_completeness(self):
        self.changing_head=True
        result=await self.service.feedback("space","workflow")
        self.assertTrue(result["incomplete"])
        self.assertIn("head",result["feedback_errors"])

    async def test_page_and_byte_limits_are_explicit(self):
        self.unbounded=True; self.large=True
        result=await self.service.feedback("space","workflow")
        self.assertTrue(result["incomplete"])
        self.assertEqual(len(result["checks"]),1000)
        self.assertEqual(result["reviews"],[])
        self.assertIn("reviews",result["feedback_errors"])
        self.assertEqual(result["page_counts"]["checks"],10)

"""Remote edits during an interrupted publication must never create a PR."""
import unittest

import httpx

import test_github_delivery as fixtures


class PublicationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.GitHubTests.asyncSetUp
    handle = fixtures.GitHubTests.handle

    async def interrupted_before_pr(self):
        original = self.service.remote

        async def fail_after_saved_commit(binding, token, path):
            if path.startswith('/pulls?') and self.mutations:
                raise httpx.ReadTimeout('interrupted before PR creation')
            return await original(binding, token, path)

        self.service.remote = fail_after_saved_commit
        with self.assertRaises(httpx.ReadTimeout):
            await self.service.publish('space', 'actor', self.request, self.package)
        self.service.remote = original
        self.assertEqual(self.mutations, 1)
        self.assertEqual(self.pr_creations, 0)
        return self.head

    async def test_saved_commit_refuses_external_rewind_to_original_base(self):
        await self.interrupted_before_pr()
        self.head = self.base
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            await self.service.publish('space', 'actor', self.request, self.package)
        self.assertEqual(self.pr_creations, 0)
        self.assertEqual(self.mutations, 1)

    async def test_saved_commit_refuses_removed_branch_before_pr_creation(self):
        await self.interrupted_before_pr()
        self.head = None
        with self.assertRaisesRegex(ValueError, 'removed'):
            await self.service.publish('space', 'actor', self.request, self.package)
        self.assertIsNone(self.head)
        self.assertEqual(self.pr_creations, 0)

    async def test_saved_commit_recovers_without_new_commit_or_duplicate_pr(self):
        commit = await self.interrupted_before_pr()
        result = await self.service.publish('space', 'actor', self.request, self.package)
        self.assertEqual(result['commit'], commit)
        self.assertEqual((self.mutations, self.pr_creations), (1, 1))


if __name__ == '__main__':
    unittest.main()

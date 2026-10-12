"""New workflows take package roots from the folder's saved project profile, when unambiguous."""
import unittest
from unittest.mock import AsyncMock, patch

from parallax.models import ProjectProfile
import test_workflows as workflow_fixtures


class WorkflowPackageRootsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = workflow_fixtures.WorkflowTests.asyncSetUp
    asyncTearDown = workflow_fixtures.WorkflowTests.asyncTearDown
    check_project = workflow_fixtures.WorkflowTests.check_project
    request = workflow_fixtures.WorkflowTests.request

    def profile(self, name, workspace, roots):
        self.store.put_project_profile(name, ProjectProfile(workspace=str(workspace), package_roots=roots).model_dump())

    async def start(self):
        with patch.object(self.service, "_launch", AsyncMock()):
            started = await self.service.start(self.request())
        return self.service.get(started["id"])

    async def test_without_a_profile_the_task_has_no_roots(self):
        self.assertEqual((await self.start())["spec"]["package_roots"], [])

    async def test_saved_profile_roots_become_fixed_task_settings(self):
        (self.project / "packages" / "app").mkdir(parents=True)
        self.profile("app", self.project, ["packages/app"])
        task = await self.start()
        self.assertEqual(task["spec"]["package_roots"], ["packages/app"])
        # Later profile edits do not change a task that already started.
        self.profile("app", self.project, ["."])
        self.assertEqual(self.service.get(task["id"])["spec"]["package_roots"], ["packages/app"])

    async def test_profiles_for_other_folders_or_in_conflict_supply_nothing(self):
        other = self.root / "other"
        other.mkdir()
        self.profile("other", other, ["."])
        self.assertEqual((await self.start())["spec"]["package_roots"], [])
        self.profile("one", self.project, ["."])
        self.profile("two", self.project, ["packages/app"])
        self.assertEqual(self.store.project_roots(str(self.project)), [])

    async def test_equivalent_paths_and_agreeing_profiles_resolve_to_one_folder(self):
        self.profile("one", self.project, ["."])
        self.profile("two", self.project / "." / ".." / self.project.name, ["."])
        alias = self.root / "alias"
        alias.symlink_to(self.project, target_is_directory=True)
        self.assertEqual(self.store.project_roots(str(alias)), ["."])


if __name__ == "__main__":
    unittest.main()

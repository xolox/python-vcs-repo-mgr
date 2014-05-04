# Automated tests for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 4, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

# Standard library modules.
import logging
import shutil
import tempfile
import unittest

# External dependencies.
import coloredlogs

# The module we're testing.
from vcs_repo_mgr import GitRepo

GIT_REPO = 'git@github.com:xolox/python-verboselogs.git'

class VcsRepoMgrTestCase(unittest.TestCase):

    def setUp(self):
        coloredlogs.install()
        coloredlogs.set_level(logging.DEBUG)
        self.directory = tempfile.mkdtemp()
        self.repository = GitRepo(local=self.directory, remote=GIT_REPO)

    def tearDown(self):
        shutil.rmtree(self.directory)

    def runTest(self):

        # Test repository.exists on a non existing repository.
        self.assertEqual(self.repository.exists, False)

        # Test repository.create().
        self.repository.create()

        # Test repository.exists on an existing repository.
        self.assertEqual(self.repository.exists, True)

        # Test repository.update().
        self.repository.update()

        # Test repository branches.
        self.assertEqual(len(self.repository.branches), 1)
        self.assertTrue('master' in self.repository.branches)

        # Test repository.find_revision_number().
        revision_number = self.repository.find_revision_number('master')
        self.assertEqual(type(revision_number), int)
        self.assertTrue(revision_number > 0)

        # Test repository.find_revision_id().
        revision_id = self.repository.find_revision_id('master')
        self.assertEqual(type(revision_id), str)
        self.assertTrue(revision_id.startswith(self.repository.branches['master'].revision_id))

# vim: ts=4 sw=4 et

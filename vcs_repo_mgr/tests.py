# Automated tests for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 10, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

# Standard library modules.
import logging
import os
import random
import shutil
import tempfile
import unittest

# External dependencies.
import coloredlogs

# The module we're testing.
from vcs_repo_mgr import GitRepo, HgRepo

class VcsRepoMgrTestCase(unittest.TestCase):

    def setUp(self):
        coloredlogs.install()
        coloredlogs.set_level(logging.DEBUG)
        self.git_directory = tempfile.mkdtemp()
        self.hg_directory = tempfile.mkdtemp()
        self.export_directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.git_directory)
        shutil.rmtree(self.hg_directory)
        shutil.rmtree(self.export_directory)

    def test_git_repo(self):
        self.repo_test_helper(repo=GitRepo(local=self.git_directory,
                                           remote='https://github.com/xolox/python-verboselogs.git'),
                              main_branch='master')

    def test_hg_repo(self):
        self.repo_test_helper(repo=HgRepo(local=self.hg_directory,
                                          remote='https://bitbucket.org/ianb/virtualenv'),
                              main_branch='trunk')

    def test_argument_checking(self):
        non_existing_repo = os.path.join(tempfile.gettempdir(), '/tmp/non-existing-repo-%i' % random.randint(0, 1000))
        self.assertRaises(Exception, GitRepo, local=non_existing_repo)

    def repo_test_helper(self, repo, main_branch):

        # Test repository.exists on a non existing repository.
        self.assertEqual(repo.exists, False)

        # Test repository.create().
        repo.create()

        # Test repository.exists on an existing repository.
        self.assertEqual(repo.exists, True)

        # Test repository.update().
        repo.update()

        # Test repository.__repr__().
        self.assertTrue(isinstance(repr(repo), str))

        # Test repository branches.
        self.assertEqual(len(repo.branches), 1)
        self.assertTrue(main_branch in repo.branches)

        # Test repository export.
        repo.export(self.export_directory, main_branch)
        num_files = 0
        for root, dirs, files in os.walk(self.export_directory):
            num_files += len(files)
        self.assertTrue(num_files > 0)
        shutil.rmtree(self.export_directory)

        # Test repository.find_revision_number().
        revision_number = repo.find_revision_number(main_branch)
        self.assertEqual(type(revision_number), int)
        self.assertTrue(revision_number > 0)

        # Test repository.find_revision_id().
        revision_id = repo.find_revision_id(main_branch)
        try:
            self.assertTrue(isinstance(revision_id, unicode))
        except NameError:
            self.assertTrue(isinstance(revision_id, str))
        self.assertTrue(revision_id.startswith(repo.branches[main_branch].revision_id))

# vim: ts=4 sw=4 et

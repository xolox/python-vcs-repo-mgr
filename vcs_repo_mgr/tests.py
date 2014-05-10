# Automated tests for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 10, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

# Standard library modules.
import logging
import os
import random
import re
import shutil
import tempfile
import unittest

# External dependencies.
import coloredlogs

# The module we're testing.
from vcs_repo_mgr import GitRepo, HgRepo, find_configured_repository

# Initialize a logger.
logger = logging.getLogger(__name__)

# We need these in multiple places.
REVISION_ID_PATTERN = re.compile('^[A-Fa-f0-9]+$')
REMOTE_GIT_REPO = 'https://github.com/xolox/python-verboselogs.git'

class VcsRepoMgrTestCase(unittest.TestCase):

    def setUp(self):
        coloredlogs.install()
        coloredlogs.set_level(logging.DEBUG)

    def test_git_repo(self):
        with TemporaryDirectory() as local_checkout:
            self.repo_test_helper(repo=GitRepo(local=local_checkout, remote=REMOTE_GIT_REPO),
                                  main_branch='master')

    def test_hg_repo(self):
        with TemporaryDirectory() as local_checkout:
            self.repo_test_helper(repo=HgRepo(local=local_checkout,
                                              remote='https://bitbucket.org/ianb/virtualenv'),
                                  main_branch='trunk')

    def test_configured_repo(self):
        with TemporaryDirectory() as config_directory:
            with TemporaryDirectory() as local_checkout:
                import vcs_repo_mgr
                vcs_repo_mgr.USER_CONFIG_FILE = os.path.join(config_directory, 'vcs-repo-mgr.ini')
                with open(vcs_repo_mgr.USER_CONFIG_FILE, 'w') as handle:
                    handle.write('[test]\n')
                    handle.write('type = git\n')
                    handle.write('local = %s\n' % local_checkout)
                    handle.write('remote = %s\n' % REMOTE_GIT_REPO)
                repository = find_configured_repository('test')
                self.repo_test_helper(repo=repository, main_branch='master')

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
        for rev in repo.branches.values():
            self.assertTrue(rev.branch_name)
            self.assertTrue(rev.revision_number > 0)
            self.assertTrue(REVISION_ID_PATTERN.match(rev.revision_id))

        # Test repository export.
        with TemporaryDirectory() as export_directory:
            repo.export(os.path.join(export_directory, 'subdirectory'), main_branch)
            num_files = 0
            for root, dirs, files in os.walk(export_directory):
                num_files += len(files)
            self.assertTrue(num_files > 0)

        # Test repository.find_revision_number().
        revision_number = repo.find_revision_number(main_branch)
        self.assertEqual(type(revision_number), int)
        self.assertTrue(revision_number > 0)

        # Test repository.find_revision_id().
        revision_id = repo.find_revision_id(main_branch)
        self.assertTrue(REVISION_ID_PATTERN.match(revision_id))
        try:
            self.assertTrue(isinstance(revision_id, unicode))
        except NameError:
            self.assertTrue(isinstance(revision_id, str))
        self.assertTrue(revision_id.startswith(repo.branches[main_branch].revision_id))

class TemporaryDirectory(object):

    """
    Easy temporary directory creation & cleanup using the :keyword:`with` statement:

    .. code-block:: python

       with TemporaryDirectory() as directory:
           # Do something useful here.
           assert os.path.isdir(directory)
    """

    def __enter__(self):
        self.temporary_directory = tempfile.mkdtemp()
        logger.debug("Created temporary directory: %s", self.temporary_directory)
        return self.temporary_directory

    def __exit__(self, exc_type, exc_value, traceback):
        logger.debug("Cleaning up temporary directory: %s", self.temporary_directory)
        shutil.rmtree(self.temporary_directory)
        del self.temporary_directory

# vim: ts=4 sw=4 et

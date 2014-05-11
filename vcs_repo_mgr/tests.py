# Automated tests for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 11, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

# Standard library modules.
import logging
import os
import random
import re
import shutil
import sys
import tempfile
import unittest

try:
    # Python 2.x.
    from StringIO import StringIO
except ImportError:
    # Python 3.x.
    from io import StringIO

# External dependencies.
import coloredlogs

# The module we're testing.
from vcs_repo_mgr import GitRepo, find_configured_repository
from vcs_repo_mgr.cli import main

# Initialize a logger.
logger = logging.getLogger(__name__)

# We need these in multiple places.
REVISION_NR_PATTERN = re.compile('^[0-9]+$')
REVISION_ID_PATTERN = re.compile('^[A-Fa-f0-9]+$')
REMOTE_GIT_REPO = 'https://github.com/xolox/python-verboselogs.git'

class VcsRepoMgrTestCase(unittest.TestCase):

    def setUp(self):
        coloredlogs.install()
        coloredlogs.set_level(logging.DEBUG)

    def test_git_repo(self):
        self.repo_test_helper(repo_type='git',
                              remote=REMOTE_GIT_REPO,
                              main_branch='master')

    def test_hg_repo(self):
        self.repo_test_helper(repo_type='hg',
                              remote='https://bitbucket.org/ianb/virtualenv',
                              main_branch='trunk')

    def test_argument_checking(self):
        non_existing_repo = os.path.join(tempfile.gettempdir(), '/tmp/non-existing-repo-%i' % random.randint(0, 1000))
        self.assertRaises(Exception, GitRepo, local=non_existing_repo)

    def repo_test_helper(self, repo_type, remote, main_branch):
        with TemporaryDirectory() as config_directory:
            with TemporaryDirectory() as local_checkout:

                # Change the default configuration file location.
                import vcs_repo_mgr
                vcs_repo_mgr.USER_CONFIG_FILE = os.path.join(config_directory, 'vcs-repo-mgr.ini')

                # Create a configuration file for testing.
                with open(vcs_repo_mgr.USER_CONFIG_FILE, 'w') as handle:

                    # Valid repository definition.
                    handle.write('[test]\n')
                    handle.write('type = %s\n' % repo_type)
                    handle.write('local = %s\n' % local_checkout)
                    handle.write('remote = %s\n' % remote)

                    # Duplicate repository definition #1.
                    handle.write('[test_2]\n')
                    handle.write('type = git\n')
                    handle.write('local = %s\n' % local_checkout)
                    handle.write('remote = %s\n' % REMOTE_GIT_REPO)

                    # Duplicate repository definition #2.
                    handle.write('[test-2]\n')
                    handle.write('type = git\n')
                    handle.write('local = %s\n' % local_checkout)
                    handle.write('remote = %s\n' % REMOTE_GIT_REPO)

                    # Invalid repository definition.
                    handle.write('[unsupported-repo-type]\n')
                    handle.write('type = bzr\n')
                    handle.write('local = /tmp/random-bzr-checkout\n')

                # Check error handling in Python API.
                self.assertRaises(ValueError, find_configured_repository, 'non-existing')
                self.assertRaises(ValueError, find_configured_repository, 'test-2')
                self.assertRaises(ValueError, find_configured_repository, 'unsupported-repo-type')

                # Test Python API with valid configured repository.
                repository = find_configured_repository('test')

                # Python API - Test repository.exists on a non existing repository.
                self.assertEqual(repository.exists, False)

                # Python API - Test repository.create().
                repository.create()

                # Python API - Test repository.exists on an existing repository.
                self.assertEqual(repository.exists, True)

                # Python API - Test repository.update().
                repository.update()

                # Python API - Test repository.__repr__().
                self.assertTrue(isinstance(repr(repository), str))

                # Python API - Test repository branches.
                self.assertEqual(len(repository.branches), 1)
                self.assertTrue(main_branch in repository.branches)
                for rev in repository.branches.values():
                    self.assertTrue(rev.branch)
                    self.assertTrue(rev.revision_number > 0)
                    self.assertTrue(REVISION_ID_PATTERN.match(rev.revision_id))
                    # Test revision.__repr__().
                    self.assertTrue(isinstance(repr(rev), str))

                # Python API - Test repository export.
                with TemporaryDirectory() as export_directory:
                    repository.export(os.path.join(export_directory, 'subdirectory'), main_branch)
                    self.checkExport(export_directory)

                # Python API - Test repository.find_revision_number().
                revision_number = repository.find_revision_number(main_branch)
                self.assertEqual(type(revision_number), int)
                self.assertTrue(revision_number > 0)

                # Python API - Test repository.find_revision_id().
                revision_id = repository.find_revision_id(main_branch)
                self.assertTrue(REVISION_ID_PATTERN.match(revision_id))
                try:
                    self.assertTrue(isinstance(revision_id, unicode))
                except NameError:
                    self.assertTrue(isinstance(revision_id, str))
                self.assertTrue(revision_id.startswith(repository.branches[main_branch].revision_id))

                # Test command line interface with valid configured repository.
                self.assertTrue(REVISION_NR_PATTERN.match(call('--repository=test', '--revision=%s' % main_branch, '--find-revision-number')))
                self.assertTrue(REVISION_ID_PATTERN.match(call('--repository=test', '--revision=%s' % main_branch, '--find-revision-id')))
                self.assertEqual(call('--repository=test', '--find-directory').strip(), local_checkout)
                call('--repository=test', '--update')
                with TemporaryDirectory() as export_directory:
                    call('--repository=test', '--revision=%s' % main_branch, '--export=%s' % export_directory)
                    self.checkExport(export_directory)

    def checkExport(self, directory):
        num_files = 0
        for root, dirs, files in os.walk(directory):
            num_files += len(files)
        self.assertTrue(num_files > 0)

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

def call(*arguments):
    saved_stdout = sys.stdout
    saved_argv = sys.argv
    try:
        sys.stdout = StringIO()
        sys.argv = [sys.argv[0]] + list(arguments)
        main()
        return sys.stdout.getvalue()
    finally:
        sys.stdout = saved_stdout
        sys.argv = saved_argv

# vim: ts=4 sw=4 et

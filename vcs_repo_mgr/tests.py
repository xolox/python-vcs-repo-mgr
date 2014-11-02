# Automated tests for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: November 2, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

# Standard library modules.
import hashlib
import logging
import os
import random
import re
import shutil
import sys
import tempfile
import unittest

# External dependencies.
import coloredlogs
from six.moves import StringIO

# The module we're testing.
import vcs_repo_mgr
from vcs_repo_mgr import (
        AmbiguousRepositoryNameError, coerce_repository,
        find_configured_repository, GitRepo, HgRepo, limit_vcs_updates,
        NoSuchRepositoryError, UnknownRepositoryTypeError,
)
from vcs_repo_mgr.cli import main

# Initialize a logger.
logger = logging.getLogger(__name__)

# We need these in multiple places.
DIGITS_PATTERN = re.compile('^[0-9]+$')
HEX_SUM_PATTERN = re.compile('^[A-Fa-f0-9]+$')

# Locations of remote repositories.
REMOTE_BZR_REPO = 'lp:python-apt'
REMOTE_GIT_REPO = 'https://github.com/xolox/python-verboselogs.git'
REMOTE_HG_REPO = 'https://bitbucket.org/ianb/virtualenv'

# Global state of the test suite.
TEMPORARY_DIRECTORIES = []
LOCAL_CHECKOUTS = {}

def create_temporary_directory():
    """
    Create a temporary directory that will be cleaned up when the test suite is
    torn down.
    """
    temporary_directory = tempfile.mkdtemp()
    TEMPORARY_DIRECTORIES.append(temporary_directory)
    return temporary_directory

def create_local_checkout(remote):
    """
    Create a directory for a local checkout of a remote repository.
    """
    context = hashlib.sha1()
    context.update(remote.encode('utf-8'))
    key = context.hexdigest()
    if key not in LOCAL_CHECKOUTS:
        LOCAL_CHECKOUTS[key] = create_temporary_directory()
    return LOCAL_CHECKOUTS[key]

def tearDownModule():
    """
    Clean up temporary directories.
    """
    for directory in TEMPORARY_DIRECTORIES:
        shutil.rmtree(directory)

class VcsRepoMgrTestCase(unittest.TestCase):

    def __init__(self, *args, **kw):
        """
        Initialize the test suite.
        """
        # Initialize super classes.
        super(VcsRepoMgrTestCase, self).__init__(*args, **kw)
        # Set up logging to the terminal.
        coloredlogs.install()
        coloredlogs.set_level(logging.DEBUG)

    def test_argument_checking(self):
        """
        Test that subclasses of :py:class:`Repository` raise an exception on
        non-existing local directories when no remote location is given.
        """
        non_existing_repo = os.path.join(tempfile.gettempdir(), '/tmp/non-existing-repo-%i' % random.randint(0, 1000))
        self.assertRaises(Exception, GitRepo, local=non_existing_repo)

    def test_repository_coercion(self):
        """
        Test that auto vivification of repositories is supported.
        """
        # Test argument type checking.
        self.assertRaises(ValueError, coerce_repository, None)
        # Test auto vivification of git repositories.
        repository = coerce_repository('https://github.com/xolox/python-vcs-repo-mgr.git')
        self.assertTrue('0.5' in repository.tags)
        # Test auto vivification of other repositories.
        repository = coerce_repository('hg+%s' % REMOTE_HG_REPO)
        self.assertTrue(isinstance(repository, HgRepo))
        # Test that Repository objects pass through untouched.
        self.assertTrue(repository is coerce_repository(repository))

    def test_command_line_interface(self):
        """
        Test the command line interface.
        """
        call('--help')
        self.assertRaises(SystemExit, call, '--repository=non-existing', '--find-directory')
        repository = self.create_repo_using_config('git', REMOTE_GIT_REPO)
        self.assertTrue(DIGITS_PATTERN.match(call('--repository=test', '--revision=master', '--find-revision-number')))
        self.assertTrue(HEX_SUM_PATTERN.match(call('--repository=test', '--revision=master', '--find-revision-id')))
        self.assertEqual(call('--repository=test', '--find-directory', '--verbose').strip(), repository.local)
        with limit_vcs_updates():
            call('--repository=test', '--update')
            call('--repository=test', '--update')
        export_directory = os.path.join(create_temporary_directory(), 'non-existing-subdirectory')
        call('--repository=test', '--revision=master', '--export=%s' % export_directory)
        self.assertTrue(os.path.join(export_directory, 'setup.py'))
        self.assertTrue(os.path.join(export_directory, 'verboselogs.py'))

    def test_a_revision_number_summing(self):
        """
        Test summing of local revision numbers.
        """
        self.create_repo_using_config('git', REMOTE_GIT_REPO, 'hg', REMOTE_HG_REPO)
        output = call('--sum-revisions', 'test', '1.0', 'second', '1.2')
        self.assertEqual(output.strip(), '125')
        # An uneven number of arguments should report an error.
        self.assertRaises(SystemExit, call, '--sum-revisions', 'test', '1.0', 'second')

    def test_hg_repo(self):
        """
        Tests for Mercurial repository support.
        """
        # Instantiate a HgRepo object using a configuration file.
        repository = self.create_repo_using_config('hg', REMOTE_HG_REPO)
        # Test HgRepo.create().
        repository.create()
        # Test HgRepo.exists on an existing repository.
        self.assertEqual(repository.exists, True)
        # Test HgRepo.update().
        repository.update()
        # Test repr(HgRepo).
        self.assertTrue(isinstance(repr(repository), str))
        # Test HgRepo.branches
        self.validate_all_revisions(repository.branches)
        self.assertTrue('trunk' in repository.branches)
        # Test HgRepo.tags.
        self.validate_all_revisions(repository.tags)
        for tag_name in ['tip', '1.2', '1.3.4', '1.4.9', '1.5.2']:
            self.assertTrue(tag_name in repository.tags)
        assert repository.tags['1.5'].revision_number > repository.tags['1.2'].revision_number
        # Test HgRepo.find_revision_id().
        self.assertTrue(repository.find_revision_id('1.2').startswith('ffa882669ca9'))
        # Test HgRepo.find_revision_number().
        self.assertEqual(repository.find_revision_number('1.2'), 124)
        # Test HgRepo.export().
        export_directory = create_temporary_directory()
        repository.export(revision='1.2', directory=export_directory)
        # Make sure the contents were properly exported.
        self.assertTrue(os.path.isfile(os.path.join(export_directory, 'setup.py')))
        self.assertTrue(os.path.isfile(os.path.join(export_directory, 'virtualenv.py')))

    def test_git_repo(self):
        """
        Tests for git repository support.
        """
        # Instantiate a GitRepo object using a configuration file.
        repository = self.create_repo_using_config('git', REMOTE_GIT_REPO)
        # Test GitRepo.create().
        repository.create()
        # Test GitRepo.exists on an existing repository.
        self.assertEqual(repository.exists, True)
        # Test GitRepo.update().
        repository.update()
        # Test repr(GitRepo).
        self.assertTrue(isinstance(repr(repository), str))
        # Test GitRepo.branches
        self.validate_all_revisions(repository.branches)
        self.assertTrue('master' in repository.branches)
        # Test GitRepo.tags.
        self.validate_all_revisions(repository.tags)
        self.assertTrue('1.0' in repository.tags)
        self.assertTrue('1.0.1' in repository.tags)
        assert repository.tags['1.0.1'].revision_number > repository.tags['1.0'].revision_number
        # Test GitRepo.find_revision_id().
        self.assertEqual(repository.find_revision_id('1.0'), 'f6b89e5314d951bba4aa876ddbeef1deeb18932c')
        # Test GitRepo.export().
        export_directory = create_temporary_directory()
        repository.export(revision='1.0', directory=export_directory)
        # Make sure the contents were properly exported.
        self.assertTrue(os.path.isfile(os.path.join(export_directory, 'setup.py')))
        self.assertTrue(os.path.isfile(os.path.join(export_directory, 'verboselogs.py')))

    def test_bzr_repo(self):
        """
        Tests for Bazaar repository support.
        """
        # Instantiate a BzrRepo object using a configuration file.
        repository = self.create_repo_using_config('bzr', REMOTE_BZR_REPO)
        # Test BzrRepo.create().
        repository.create()
        # Test BzrRepo.exists on an existing repository.
        self.assertEqual(repository.exists, True)
        # Test BzrRepo.update().
        repository.update()
        # Test repr(BzrRepo).
        self.assertTrue(isinstance(repr(repository), str))
        # Test BzrRepo.branches.
        self.validate_all_revisions(repository.branches)
        # Test BzrRepo.tags.
        self.validate_all_revisions(repository.tags, id_pattern=re.compile(r'^\S+$'))
        self.assertTrue('0.7.9' in repository.tags)
        self.assertTrue('0.8.9' in repository.tags)
        self.assertTrue('0.9.3.9' in repository.tags)
        assert repository.tags['0.8.9'].revision_number > repository.tags['0.7.9'].revision_number
        # Test BzrRepo.find_revision_id().
        self.assertEqual(repository.find_revision_id('0.8.9'), 'git-v1:e2e4d3dd3dc2a41469f5d559cbdb5ca6c5057f01')
        # Test BzrRepo.export().
        export_directory = create_temporary_directory()
        repository.export(revision='0.7.9', directory=export_directory)
        # Make sure the contents were properly exported.
        self.assertTrue(os.path.isfile(os.path.join(export_directory, 'setup.py')))
        self.assertTrue(os.path.isdir(os.path.join(export_directory, 'apt')))

    def create_repo_using_config(self, repository_type, remote_location, second_repository_type=None, second_remote_location=None):
        """
        Instantiate a :py:class:`.Repository` object by creating a temporary
        configuration file, thereby testing both configuration file handling
        and repository instantiation.
        """
        config_directory = create_temporary_directory()
        local_checkout = create_local_checkout(remote_location)
        vcs_repo_mgr.USER_CONFIG_FILE = os.path.join(config_directory, 'vcs-repo-mgr.ini')
        with open(vcs_repo_mgr.USER_CONFIG_FILE, 'w') as handle:
            # Create a valid repository definition.
            handle.write('[test]\n')
            handle.write('type = %s\n' % repository_type)
            handle.write('local = %s\n' % local_checkout)
            handle.write('remote = %s\n' % remote_location)
            # Create a second valid repository definition?
            if second_repository_type and second_remote_location:
                handle.write('[second]\n')
                handle.write('type = %s\n' % second_repository_type)
                handle.write('local = %s\n' % create_local_checkout(second_remote_location))
                handle.write('remote = %s\n' % second_remote_location)
            # Create the first of two duplicate definitions.
            handle.write('[test_2]\n')
            handle.write('type = %s\n' % repository_type)
            handle.write('local = %s\n' % local_checkout)
            handle.write('remote = %s\n' % remote_location)
            # Create the second of two duplicate definitions.
            handle.write('[test-2]\n')
            handle.write('type = %s\n' % repository_type)
            handle.write('local = %s\n' % local_checkout)
            handle.write('remote = %s\n' % remote_location)
            # Create an invalid repository definition.
            handle.write('[unsupported-repo-type]\n')
            handle.write('type = svn\n')
            handle.write('local = /tmp/random-svn-checkout\n')
        # Check the error handling in the Python API.
        self.assertRaises(NoSuchRepositoryError, find_configured_repository, 'non-existing')
        self.assertRaises(AmbiguousRepositoryNameError, find_configured_repository, 'test-2')
        self.assertRaises(UnknownRepositoryTypeError, find_configured_repository, 'unsupported-repo-type')
        # Test the Python API with a properly configured repository.
        return find_configured_repository('test')

    def validate_revision(self, revision, id_pattern=HEX_SUM_PATTERN):
        """
        Perform some generic sanity checks on :py:class:`Revision` objects.
        """
        self.assertTrue(revision.revision_number > 0)
        self.assertTrue(isinstance(repr(revision), str))
        self.assertTrue(id_pattern.match(revision.revision_id))

    def validate_all_revisions(self, mapping, **kw):
        """
        Perform some generic sanity checks on a dictionary with
        :py:class:`Revision` values. Randomly picks some revisions to sanity
        check (calculating the local revision number of a revision requires the
        execution of an external command and there's really no point in doing
        this hundreds of times).
        """
        revisions = list(mapping.values())
        random.shuffle(revisions)
        for revision in revisions[:10]:
            self.validate_revision(revision, **kw)

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

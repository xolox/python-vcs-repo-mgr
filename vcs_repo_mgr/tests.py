# Automated tests for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 16, 2015
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
        NoMatchingReleasesError, NoSuchRepositoryError,
        UnknownRepositoryTypeError, UPDATE_VARIABLE
)
from vcs_repo_mgr.cli import main

# Initialize a logger.
logger = logging.getLogger(__name__)

# Locations of remote repositories.
REMOTE_BZR_REPO = 'lp:python-apt'
REMOTE_GIT_REPO = 'https://github.com/xolox/python-verboselogs.git'
REMOTE_HG_REPO = 'https://bitbucket.org/ianb/virtualenv'
OUR_PUBLIC_REPO = 'https://github.com/xolox/python-vcs-repo-mgr.git'
PIP_ACCEL_REPO = 'https://github.com/paylogic/pip-accel.git'

# We need these in multiple places.
DIGITS_PATTERN = re.compile('^[0-9]+$')
HEX_SUM_PATTERN = re.compile('^[A-Fa-f0-9]+$')
VCS_FIELD_PATTERN = re.compile('Vcs-Git: %s#[A-Fa-f0-9]+$' % re.escape(REMOTE_GIT_REPO))

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
        Test that subclasses of :py:class:`Repository` raise an exception on:

        - Non-existing local directories when no remote location is given.
        - Invalid release schemes.
        - Invalid release filters.
        """
        non_existing_repo = os.path.join(tempfile.gettempdir(), 'vcs-repo-mgr', 'non-existing-repo-%i' % random.randint(0, 1000))
        self.assertRaises(ValueError, GitRepo)
        self.assertRaises(ValueError, GitRepo, local=non_existing_repo)
        self.assertRaises(ValueError, GitRepo, local=non_existing_repo, remote=REMOTE_GIT_REPO, release_scheme='not-tags-and-not-branches')
        self.assertRaises(ValueError, GitRepo, local=non_existing_repo, remote=REMOTE_GIT_REPO, release_scheme='tags', release_filter='regex with multiple (capture) (groups)')

    def test_repository_coercion(self):
        """
        Test that auto vivification of repositories is supported.
        """
        # Test argument type checking.
        self.assertRaises(ValueError, coerce_repository, None)
        # Test auto vivification of git repositories.
        repository = coerce_repository(OUR_PUBLIC_REPO)
        self.assertTrue('0.5' in repository.tags)
        # Test auto vivification of other repositories.
        repository = coerce_repository('hg+%s' % REMOTE_HG_REPO)
        self.assertTrue(isinstance(repository, HgRepo))
        # Test that type prefix parsing swallows UnknownRepositoryTypeError.
        self.assertRaises(ValueError, coerce_repository, '%s+with-a-plus-in-the-middle' % OUR_PUBLIC_REPO)
        # Test that Repository objects pass through untouched.
        self.assertTrue(repository is coerce_repository(repository))

    def test_command_line_interface(self):
        """
        Test the command line interface.
        """
        # The usage of --help should work (we can't actually validate the output of course).
        call('--help')
        # The usage of invalid repository names should raise an error.
        self.assertRaises(SystemExit, call, '--repository=non-existing', '--find-directory')
        # Create a temporary named repository for the purpose of running the test suite.
        repository = self.create_repo_using_config('git', REMOTE_GIT_REPO)
        # Test the --revision and --find-revision-number option.
        self.assertTrue(DIGITS_PATTERN.match(call('--repository=test', '--revision=master', '--find-revision-number')))
        # Test the --revision and --find-revision-id option.
        self.assertTrue(HEX_SUM_PATTERN.match(call('--repository=test', '--revision=master', '--find-revision-id')))
        # Test the --release option (the literal given on the right hand side was manually verified to correspond to the 0.19 tag.
        self.assertEqual(call('--repository=%s' % PIP_ACCEL_REPO, '--release=0.19', '--find-revision-id').strip(), 'c70d28908e4f43341dcbdccc5a478348bf9b1488')
        # Test the --vcs-control-field option.
        self.assertTrue(VCS_FIELD_PATTERN.match(call('--repository=test', '--vcs-control-field')))
        # Test the --find-directory option.
        self.assertEqual(call('--repository=test', '--find-directory', '--verbose').strip(), repository.local)
        # Test the limiting of repository updates (and the saving/restoring of
        # the environment variable which makes the update limiting work in
        # stacked contexts).
        bogus_update_variable_value = '42'
        os.environ[UPDATE_VARIABLE] = bogus_update_variable_value
        with limit_vcs_updates():
            call('--repository=test', '--update')
            call('--repository=test', '--update')
        self.assertEqual(os.environ[UPDATE_VARIABLE], bogus_update_variable_value)
        # Test the --export option.
        export_directory = os.path.join(create_temporary_directory(), 'non-existing-subdirectory')
        call('--repository=test', '--revision=master', '--export=%s' % export_directory)
        self.assertTrue(os.path.join(export_directory, 'setup.py'))
        self.assertTrue(os.path.join(export_directory, 'verboselogs.py'))
        # Test the --list-releases option.
        listing_of_releases = call('--repository=%s' % PIP_ACCEL_REPO, '--list-releases').splitlines()
        for expected_release_tag in ['0.1', '0.4.2', '0.8.20', '0.19.3']:
            self.assertTrue(expected_release_tag in listing_of_releases)

    def test_revision_number_summing(self):
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

    def test_release_objects(self):
        """
        Test creation and ordering of Release objects.
        """
        repository = self.create_repo_using_config('git', REMOTE_GIT_REPO)
        self.assertTrue(len(repository.releases) > 0)
        for identifier, release in repository.releases.items():
            self.assertEqual(identifier, release.identifier)
            self.assertEqual(release.identifier, release.revision.tag)

    def test_revision_ordering(self):
        """
        Test ordering of tags and releases.
        """
        repository = coerce_repository(PIP_ACCEL_REPO)
        def find_tag_index(looking_for_tag):
            for i, revision in enumerate(repository.ordered_tags):
                if revision.tag == looking_for_tag:
                    return i
            raise Exception("Failed to find tag by name!")
        # Regular sorting would screw up the order of the following two
        # examples so this is testing that the natural order sorting of tags
        # works as expected (Do What I Mean :-).
        self.assertTrue(find_tag_index('0.2') < find_tag_index('0.10'))
        self.assertTrue(find_tag_index('0.18') < find_tag_index('0.20'))
        def find_release_index(looking_for_release):
            for i, release in enumerate(repository.ordered_releases):
                if release.identifier == looking_for_release:
                    return i
            raise Exception("Failed to find tag by name!")
        self.assertTrue(find_release_index('0.2') < find_release_index('0.10'))
        self.assertTrue(find_release_index('0.18') < find_release_index('0.20'))

    def test_release_selection(self):
        """
        Test the selection of appropriate releases. Uses the command line
        interface where possible in order to test the "business logic" as well
        as the command line interface.
        """
        # Exact matches should always be honored (obviously :-).
        self.assertEqual(call('--repository=%s' % PIP_ACCEL_REPO, '--select-release=0.2').strip(), '0.2')
        # If e.g. a major.minor.PATCH release is not available, the release
        # immediately below that should be selected (in this case: same
        # major.minor but different PATCH level).
        self.assertEqual(call('--repository=%s' % PIP_ACCEL_REPO, '--select-release=0.19.5').strip(), '0.19.3')
        # Instantiate a repository for tests that can't be done through the CLI.
        repository = coerce_repository(PIP_ACCEL_REPO)
        # If no releases are available a known and documented exception should
        # be raised.
        self.assertRaises(NoMatchingReleasesError, repository.select_release, '0.0.1')
        # Release objects should support repr().
        release = repository.select_release('0.2')
        self.assertTrue(isinstance(repr(release), str))

    def test_factory_deduplication(self):
        """
        Test that :py:func:`coerce_repository()` and similar functions don't
        construct duplicate repository objects but return the previously
        constructed instance instead.
        """
        a = coerce_repository(PIP_ACCEL_REPO)
        b = coerce_repository(PIP_ACCEL_REPO)
        c = coerce_repository(OUR_PUBLIC_REPO)
        self.assertTrue(a is b)
        # Test our assumption about the `is' operator as well :-).
        self.assertTrue(a is not c)
        self.assertTrue(b is not c)

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
            handle.write('release-scheme = tags\n')
            handle.write('release-filter = (.+)\n')
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

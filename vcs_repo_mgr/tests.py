# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: June 24, 2017
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""Automated tests for the `vcs-repo-mgr` package."""

# Standard library modules.
import hashlib
import logging
import os
import random
import re
import shutil
import tempfile

# External dependencies.
from executor import ExternalCommandFailed, execute
from humanfriendly.testing import TestCase, random_string, run_cli

# The module we're testing.
import vcs_repo_mgr
from vcs_repo_mgr import (
    BzrRepo,
    FeatureBranchSpec,
    GitRepo,
    HgRepo,
    UPDATE_VARIABLE,
    coerce_feature_branch,
    coerce_repository,
    find_configured_repository,
    limit_vcs_updates,
)
from vcs_repo_mgr.exceptions import (
    AmbiguousRepositoryNameError,
    NoMatchingReleasesError,
    NoSuchRepositoryError,
    UnknownRepositoryTypeError,
    WorkingTreeNotCleanError,
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
    Create a temporary directory.

    The directory will be cleaned up when the test suite is torn down.
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


class VcsRepoMgrTestCase(TestCase):

    """Container for the `vcs-repo-mgr` test suite."""

    def test_argument_checking(self):
        """
        Test that subclasses of :class:`Repository` raise an exception on:

        - Non-existing local directories when no remote location is given.
        - Invalid release schemes.
        - Invalid release filters.
        """
        non_existing_repo = os.path.join(tempfile.gettempdir(),
                                         'vcs-repo-mgr',
                                         'non-existing-repo-%i' % random.randint(0, 1000))
        self.assertRaises(ValueError, GitRepo)
        self.assertRaises(ValueError, GitRepo, local=non_existing_repo)
        self.assertRaises(ValueError,
                          GitRepo,
                          local=non_existing_repo,
                          remote=REMOTE_GIT_REPO,
                          release_scheme='not-tags-and-not-branches')
        self.assertRaises(ValueError,
                          GitRepo,
                          local=non_existing_repo,
                          remote=REMOTE_GIT_REPO,
                          release_scheme='tags',
                          release_filter='regex with multiple (capture) (groups)')

    def test_coerce_repository(self):
        """
        Test that auto vivification of repositories is supported.
        """
        # Test argument type checking.
        self.assertRaises(ValueError, coerce_repository, None)
        # Test auto vivification of git repositories.
        repository = coerce_repository(OUR_PUBLIC_REPO)
        assert '0.5' in repository.tags
        # Test auto vivification of Mercurial repositories.
        repository = coerce_repository('hg+%s' % REMOTE_HG_REPO)
        assert isinstance(repository, HgRepo)
        # Test that type prefix parsing swallows UnknownRepositoryTypeError.
        self.assertRaises(ValueError, coerce_repository, '%s+with-a-plus-in-the-middle' % OUR_PUBLIC_REPO)
        # Test that Repository objects pass through untouched.
        assert repository is coerce_repository(repository)
        # Test that the repository type of an existing local clone can be inferred.
        for vcs_type, init_cmd in ((GitRepo, 'git init'),
                                   (HgRepo, 'hg init')):
            directory = create_temporary_directory()
            execute(*(init_cmd.split() + [directory]))
            repository = coerce_repository(directory)
            assert isinstance(repository, vcs_type)

    def test_coerce_feature_branch(self):
        """Test that feature branch coercion works correctly."""
        # Test argument type checking.
        self.assertRaises(ValueError, coerce_feature_branch, None)
        # Test the coercion of a feature branch expression to a FeatureBranchSpec object.
        feature_branch = coerce_feature_branch('https://github.com/xolox/python-vcs-repo-mgr#dev')
        assert isinstance(feature_branch, FeatureBranchSpec)
        assert feature_branch.location == 'https://github.com/xolox/python-vcs-repo-mgr'
        assert feature_branch.revision == 'dev'
        # Test that FeatureBranchSpec objects pass through untouched.
        assert feature_branch is coerce_feature_branch(feature_branch)

    def test_command_line_interface(self):
        """
        Test the command line interface.
        """
        # The usage of --help should work (we can't actually validate the output of course).
        returncode, output = run_cli(main, '--help', merged=True)
        assert returncode == 0
        assert "Usage:" in output
        # The usage of invalid repository names should raise an error.
        returncode, output = run_cli(main, '--repository=non-existing', '--find-directory')
        assert returncode != 0
        # Create a temporary named repository for the purpose of running the test suite.
        repository = self.create_repo_using_config('git', REMOTE_GIT_REPO)
        # Test the --revision and --find-revision-number option.
        returncode, output = run_cli(main, '--repository=test', '--revision=master', '--find-revision-number')
        assert returncode == 0
        assert DIGITS_PATTERN.match(output)
        # Test the --revision and --find-revision-id option.
        returncode, output = run_cli(main, '--repository=test', '--revision=master', '--find-revision-id')
        assert returncode == 0
        assert HEX_SUM_PATTERN.match(output)
        # Test the --release option (the literal given on the right hand side
        # was manually verified to correspond to the 0.19 tag.
        returncode, output = run_cli(main, '--repository=%s' % PIP_ACCEL_REPO, '--release=0.19', '--find-revision-id')
        assert returncode == 0
        assert output.strip() == 'c70d28908e4f43341dcbdccc5a478348bf9b1488'
        # Test the --vcs-control-field option.
        returncode, output = run_cli(main, '--repository=test', '--vcs-control-field')
        assert returncode == 0
        assert VCS_FIELD_PATTERN.match(output)
        # Test the --find-directory option.
        returncode, output = run_cli(main, '--repository=test', '--find-directory', '--verbose')
        assert returncode == 0
        assert output.strip() == repository.local
        # Test the limiting of repository updates (and the saving/restoring of
        # the environment variable which makes the update limiting work in
        # stacked contexts).
        bogus_update_variable_value = '42'
        os.environ[UPDATE_VARIABLE] = bogus_update_variable_value
        with limit_vcs_updates():
            run_cli(main, '--repository=test', '--update')
            run_cli(main, '--repository=test', '--update')
        assert os.environ[UPDATE_VARIABLE] == bogus_update_variable_value
        # Test the --export option.
        export_directory = os.path.join(create_temporary_directory(), 'non-existing-subdirectory')
        run_cli(main, '--repository=test', '--revision=master', '--export=%s' % export_directory)
        assert os.path.join(export_directory, 'setup.py')
        assert os.path.join(export_directory, 'verboselogs.py')
        # Test the --list-releases option.
        returncode, output = run_cli(main, '--repository=%s' % PIP_ACCEL_REPO, '--list-releases')
        listing_of_releases = output.splitlines()
        for expected_release_tag in ['0.1', '0.4.2', '0.8.20', '0.19.3']:
            assert expected_release_tag in listing_of_releases

    def test_revision_number_summing(self):
        """
        Test summing of local revision numbers.
        """
        self.create_repo_using_config('git', REMOTE_GIT_REPO, 'hg', REMOTE_HG_REPO)
        returncode, output = run_cli(main, '--sum-revisions', 'test', '1.0', 'second', '1.2')
        assert output.strip() == '125'
        # An uneven number of arguments should report an error.
        returncode, output = run_cli(main, '--sum-revisions', 'test', '1.0', 'second')
        assert returncode != 0

    def test_author_handling(self):
        """Test get_author()."""
        repo = GitRepo(remote=REMOTE_GIT_REPO, author=None)
        # Test that get_author() complains when no author details are available.
        self.assertRaises(ValueError, repo.get_author)
        # Test that get_author() complains when the author details can't be parsed.
        self.assertRaises(ValueError, repo.get_author, 'Peter')
        # Test that get_author() correctly parses the expected author details format.
        details = repo.get_author('Peter Odding <peter@peterodding.com>')
        assert details['author_name'] == 'Peter Odding'
        assert details['author_email'] == 'peter@peterodding.com'

    def test_hg_repo(self):
        """
        Test Mercurial repository support.
        """
        # Instantiate a HgRepo object using a configuration file.
        repository = self.create_repo_using_config('hg', REMOTE_HG_REPO)
        # Test HgRepo.create().
        repository.create()
        # Test HgRepo.exists on an existing repository.
        assert repository.exists, "Expected local Mercurial checkout to exist!"
        # Test HGRepo.is_bare on an existing repository.
        assert repository.is_bare, "Expected bare Mercurial checkout!"
        # The virtualenv repository doesn't have a branch named `default' (it
        # uses `trunk' instead) which breaks check_working_tree_support().
        repository.default_revision = 'trunk'
        # Test working tree support.
        self.check_working_tree_support(repository)
        # Test HgRepo.update().
        repository.update()
        # Test repr(HgRepo).
        assert isinstance(repr(repository), str)
        # Test HgRepo.branches
        self.validate_all_revisions(repository.branches)
        assert 'trunk' in repository.branches
        # Test HgRepo.tags.
        self.validate_all_revisions(repository.tags)
        for tag_name in ['tip', '1.2', '1.3.4', '1.4.9', '1.5.2']:
            assert tag_name in repository.tags
        assert repository.tags['1.5'].revision_number > repository.tags['1.2'].revision_number
        # Test HgRepo.find_revision_id().
        assert repository.find_revision_id('1.2').startswith('ffa882669ca9')
        # Test HgRepo.find_revision_number().
        assert repository.find_revision_number('1.2') == 124
        # Test HgRepo.export().
        export_directory = create_temporary_directory()
        repository.export(revision='1.2', directory=export_directory)
        # Make sure the contents were properly exported.
        assert os.path.isfile(os.path.join(export_directory, 'setup.py'))
        assert os.path.isfile(os.path.join(export_directory, 'virtualenv.py'))

    def test_git_repo(self):
        """
        Test git repository support.
        """
        # Instantiate a GitRepo object using a configuration file.
        repository = self.create_repo_using_config('git', REMOTE_GIT_REPO)
        # Test GitRepo.create().
        repository.create()
        # Test GitRepo.exists on an existing repository.
        assert repository.exists, "Expected local Git checkout to exist!"
        # Test GitRepo.is_bare on an existing repository.
        assert repository.is_bare, "Expected bare Git checkout!"
        # Test working tree support.
        self.check_working_tree_support(repository)
        # Test GitRepo.update().
        repository.update()
        # Test repr(GitRepo).
        assert isinstance(repr(repository), str)
        # Test GitRepo.branches
        self.validate_all_revisions(repository.branches)
        assert 'master' in repository.branches
        # Test GitRepo.tags.
        self.validate_all_revisions(repository.tags)
        assert '1.0' in repository.tags
        assert '1.0.1' in repository.tags
        assert repository.tags['1.0.1'].revision_number > repository.tags['1.0'].revision_number
        # Test GitRepo.find_revision_id().
        assert repository.find_revision_id('1.0') == 'f6b89e5314d951bba4aa876ddbeef1deeb18932c'
        # Test GitRepo.export().
        export_directory = create_temporary_directory()
        repository.export(revision='1.0', directory=export_directory)
        # Make sure the contents were properly exported.
        assert os.path.isfile(os.path.join(export_directory, 'setup.py'))
        assert os.path.isfile(os.path.join(export_directory, 'verboselogs.py'))

    def test_bzr_repo(self):
        """
        Test Bazaar repository support.
        """
        # Instantiate a BzrRepo object using a configuration file.
        repository = self.create_repo_using_config('bzr', REMOTE_BZR_REPO)
        # Test BzrRepo.create().
        try:
            repository.create()
        except ExternalCommandFailed:
            # Bazaar support in vcs-repo-mgr and in particular in the test
            # suite has always been a bitch to support and lately (June 2017)
            # all Travis CI builds have started failing [1] because `bzr branch
            # lp:apt-python' consistently fails with an obscure internal error
            # in Bazaar. At the same time I almost never `need to resort' to
            # using the Bazaar support in vcs-repo-mgr nowadays, because I work
            # less and less with Bazaar repositories (fortunately :-p). Because
            # I don't have a working replacement repository right now, I've
            # decided to be pragmatic about things for now :-).
            # [1] https://travis-ci.org/xolox/python-vcs-repo-mgr/builds/246606302
            return self.skipTest("Bazaar checkout failed")
        # Test BzrRepo.exists on an existing repository.
        assert repository.exists, "Expected local Bazaar checkout to exist!"
        # Test BzrRepo.is_bare on an existing repository.
        assert repository.is_bare, "Expected bare Bazaar checkout!"
        # Test working tree support.
        self.check_working_tree_support(repository)
        # Test BzrRepo.update().
        repository.update()
        # Test repr(BzrRepo).
        assert isinstance(repr(repository), str)
        # Test BzrRepo.branches.
        self.validate_all_revisions(repository.branches)
        # Test BzrRepo.tags.
        self.validate_all_revisions(repository.tags, id_pattern=re.compile(r'^\S+$'))
        assert '0.7.9' in repository.tags
        assert '0.8.9' in repository.tags
        assert '0.9.3.9' in repository.tags
        assert repository.tags['0.8.9'].revision_number > repository.tags['0.7.9'].revision_number
        # Test BzrRepo.find_revision_id().
        assert repository.find_revision_id('0.8.9') == 'git-v1:e2e4d3dd3dc2a41469f5d559cbdb5ca6c5057f01'
        # Test BzrRepo.export().
        export_directory = create_temporary_directory()
        repository.export(revision='0.7.9', directory=export_directory)
        # Make sure the contents were properly exported.
        assert os.path.isfile(os.path.join(export_directory, 'setup.py'))
        assert os.path.isdir(os.path.join(export_directory, 'apt'))

    def check_working_tree_support(self, source_repo, file_to_change='setup.py'):
        """Shared logic to check working tree support."""
        # Make sure the source repository contains a bare checkout.
        assert source_repo.is_bare, "Expected a bare repository checkout!"
        # Create a clone of the repository that does have a working tree.
        cloned_repo = self.clone_repo(source_repo, bare=False)
        # Make sure the clone doesn't exist yet.
        assert not cloned_repo.exists
        # Create the clone.
        cloned_repo.create()
        # Make sure the clone was created.
        assert cloned_repo.exists
        # Make sure the clone has a working tree.
        assert not cloned_repo.is_bare
        # Make sure we can check whether the working tree is clean.
        assert cloned_repo.is_clean, "Expected working tree to be clean?!"
        # If the working tree is clean this shouldn't raise an exception.
        cloned_repo.ensure_clean()
        # Now change the contents of a tracked file.
        filename = os.path.join(cloned_repo.local, file_to_change)
        with open(filename, 'a') as handle:
            handle.write("\n# An innocent comment :-).\n")
        # Make sure the working tree is no longer clean.
        assert not cloned_repo.is_clean, "Expected working to be dirty?!"
        # Once the working tree is dirty this should raise the expected exception.
        self.assertRaises(WorkingTreeNotCleanError, cloned_repo.ensure_clean)
        self.check_checkout_support(cloned_repo)
        self.check_commit_support(cloned_repo)
        self.check_branch_support(cloned_repo)
        self.check_merge_up_support(cloned_repo)
        self.check_push_support(cloned_repo, source_repo)

    def clone_repo(self, repository, **kw):
        """Clone a repository object."""
        # TODO Cloning of repository objects might deserve being a feature?
        properties = 'bare', 'default_revision', 'release_scheme', 'release_filter'
        options = dict((n, getattr(repository, n)) for n in properties)
        options.update(kw)
        return repository.__class__(
            author="Peter Odding <vcs-repo-mgr@peterodding.com>",
            local=create_temporary_directory(),
            remote=repository.local,
            **options
        )

    def check_checkout_support(self, repository):
        """Make sure that checkout() works and it can clean the working tree."""
        logger.info("Testing checkout() support ..")
        try:
            repository.checkout(clean=True)
        except NotImplementedError as e:
            logger.warning("%s", e)
        else:
            assert repository.is_clean, "Expected working tree to be clean?!"
            # Make sure the repository has some tags.
            assert repository.ordered_tags, "Need repository with tags to test checkout() support!"
            # Check out some random tags.
            available_tags = list(repository.tags.keys())
            for i in range(5):
                tag = random.choice(available_tags)
                repository.checkout(revision=tag)

    def check_commit_support(self, repository):
        """Make sure we can add files and make new commits."""
        logger.info("Testing add_files() and commit() support ..")
        try:
            # Make sure we start with a clean working tree.
            repository.checkout(clean=True)
            # Pick a random filename to add to the repository.
            file_to_add = random_string()
            # Create the new file.
            with open(os.path.join(repository.local, file_to_add), 'w') as handle:
                handle.write("Testing, 1, 2, 3 ..\n")
            # Stage the addition of the new file.
            repository.add_files(file_to_add)
            # Make sure the working tree is dirty now.
            assert not repository.is_clean
            # Commit the change we made and ensure that commit() actually
            # creates a new revision in the relevant branch.
            with EnsureNewCommit(repository):
                repository.commit(message="This is a test")
            # Make sure the working tree is clean again.
            assert repository.is_clean
        except NotImplementedError as e:
            logger.warning("%s", e)

    def check_branch_support(self, repository):
        """Make sure we can create new branches."""
        logger.info("Testing create_branch() support ..")
        try:
            # Generate a non-existing branch name.
            while True:
                branch_name = random_string()
                if branch_name not in repository.branches:
                    break
            # Make sure we start with a clean working tree.
            repository.checkout(clean=True)
            # Create the new branch.
            repository.create_branch(branch_name)
            # Mutate a tracked file in the repository's working tree.
            self.mutate_working_tree(repository)
            # Make sure the working tree is no longer clean.
            assert not repository.is_clean
            # Commit the change we made and ensure that commit() actually
            # creates a new revision in the relevant branch.
            with EnsureNewCommit(repository, branch_name=branch_name):
                repository.commit(message="This is a test")
            # Make sure the working tree is clean again.
            assert repository.is_clean
            # Make sure we are on the expected branch.
            assert repository.current_branch == branch_name
            # Make sure the new branch has been created.
            assert branch_name in repository.branches
            # Since we just went through the effort of creating a new branch
            # and committing a change to that branch, we now have all the
            # preconditions we need to check merge support (yes this is a
            # kludge that should be refactored at some point).
            self.check_merge_support(repository, branch_name, repository.default_revision)
            # Delete the branch we just created.
            repository.delete_branch(branch_name)
            # Make sure the new branch has been deleted.
            assert branch_name not in repository.branches
        except NotImplementedError as e:
            logger.warning("%s", e)

    def check_merge_support(self, repository, source_branch, target_branch):
        """Make sure we can create new branches."""
        logger.info("Testing merge() support ..")
        try:
            with EnsureNewCommit(repository, branch_name=target_branch):
                repository.checkout(target_branch)
                assert repository.is_clean
                repository.merge(source_branch)
                assert not repository.is_clean
                repository.commit(message="This is a merge test")
        except NotImplementedError as e:
            logger.warning("%s", e)

    def check_merge_up_support(self, repository, num_branches=5):
        """Make sure we can merge changes up through release branches."""
        logger.info("Testing merge_up() support ..")
        try:
            # Clone the repository with a custom release scheme/filter.
            repository = self.clone_repo(
                repository, bare=False,
                release_scheme='branches',
                release_filter='^v(\d*)$',
            )
            # Pick a directory name of which we can reasonably expect that
            # no existing repository will already contain this directory.
            unique_directory = 'vcs-repo-mgr-merge-up-support-%s' % random_string()
            absolute_directory = os.path.join(repository.local, unique_directory)
            # Create the release branches.
            previous_branch = repository.current_branch
            for i in range(1, num_branches + 1):
                branch_name = 'v%i' % i
                repository.checkout(revision=previous_branch)
                repository.create_branch(branch_name)
                if not os.path.isdir(absolute_directory):
                    os.mkdir(absolute_directory)
                with open(os.path.join(absolute_directory, branch_name), 'w') as handle:
                    handle.write("Version %i\n" % i)
                repository.add_files(all=True)
                repository.commit(message="Create release branch %s" % branch_name)
                previous_branch = branch_name
            # Create a feature branch based on the initial release branch.
            feature_branch = 'vcs-repo-mgr-feature-branch-%s' % random_string()
            repository.checkout('v1')
            repository.create_branch(feature_branch)
            with open(os.path.join(absolute_directory, 'v1'), 'w') as handle:
                handle.write("Version 1.1\n")
            repository.commit(message="Fixed a bug in version 1")
            assert feature_branch in repository.branches
            # Merge the change up into the release branches.
            expected_revision = repository.find_revision_id(revision=feature_branch)
            merged_revision = repository.merge_up(target_branch='v1', feature_branch=feature_branch)
            assert merged_revision == expected_revision
            # Make sure the feature branch was closed.
            assert feature_branch not in repository.branches
            # Validate the contents of the default branch.
            repository.checkout()
            entries = os.listdir(absolute_directory)
            assert all('v%i' % i in entries for i in range(1, num_branches + 1))
        except NotImplementedError as e:
            logger.warning("%s", e)

    def check_push_support(self, cloned_repo, source_repo):
        """Check whether changes can be pushed from one repository to another."""
        try:
            # Sanity check (in a simplistic and naive way) that downstream
            # contains more change sets than upstream.
            downstream_commits = cloned_repo.find_revision_number(cloned_repo.default_revision)
            upstream_commits = source_repo.find_revision_number(source_repo.default_revision)
            if downstream_commits > upstream_commits:
                # Push the changes from downstream to upstream.
                cloned_repo.push(remote=source_repo.local)
                # Make sure the commit was propagated from downstream to upstream.
                downstream_commits = cloned_repo.find_revision_number(cloned_repo.default_revision)
                upstream_commits = source_repo.find_revision_number(cloned_repo.default_revision)
                assert downstream_commits <= upstream_commits
            else:
                # The Bazaar support in vcs-repo-mgr is lacking features needed
                # by the test suite to create new commits, hence there will be
                # no difference between the two repositories and we can't test
                # push() support.
                assert isinstance(cloned_repo, BzrRepo)
                assert isinstance(source_repo, BzrRepo)
        except NotImplementedError as e:
            logger.warning("%s", e)

    def mutate_working_tree(self, repository):
        """Mutate an arbitrary tracked file in the repository's working tree."""
        vcs_directory = os.path.abspath(repository.vcs_directory)
        for root, dirs, files in os.walk(repository.local):
            for filename in files:
                # Make sure we don't directly change VCS metadata files (it
                # could corrupt the repository).
                pathname = os.path.abspath(os.path.join(root, filename))
                common_prefix = os.path.commonprefix([vcs_directory, pathname])
                if common_prefix != vcs_directory:
                    with open(pathname, 'a') as handle:
                        handle.write('\n\n# This is a test\n')
                    return

    def test_release_objects(self):
        """
        Test creation and ordering of Release objects.
        """
        repository = self.create_repo_using_config('git', REMOTE_GIT_REPO)
        assert len(repository.releases) > 0
        for identifier, release in repository.releases.items():
            assert identifier == release.identifier
            assert release.identifier == release.revision.tag

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
        assert find_tag_index('0.2') < find_tag_index('0.10')
        assert find_tag_index('0.18') < find_tag_index('0.20')

        def find_release_index(looking_for_release):
            for i, release in enumerate(repository.ordered_releases):
                if release.identifier == looking_for_release:
                    return i
            raise Exception("Failed to find tag by name!")

        assert find_release_index('0.2') < find_release_index('0.10')
        assert find_release_index('0.18') < find_release_index('0.20')

    def test_release_selection(self):
        """
        Test the selection of appropriate releases.

        Uses the command line interface where possible in order to test the
        "business logic" as well as the command line interface.
        """
        # Exact matches should always be honored (obviously :-).
        returncode, output = run_cli(main, '--repository=%s' % PIP_ACCEL_REPO, '--select-release=0.2')
        assert returncode == 0
        assert output.strip() == '0.2'
        # If e.g. a major.minor.PATCH release is not available, the release
        # immediately below that should be selected (in this case: same
        # major.minor but different PATCH level).
        returncode, output = run_cli(main, '--repository=%s' % PIP_ACCEL_REPO, '--select-release=0.19.5')
        assert returncode == 0
        assert output.strip() == '0.19.3'
        # Instantiate a repository for tests that can't be done through the CLI.
        repository = coerce_repository(PIP_ACCEL_REPO)
        # If no releases are available a known and documented exception should
        # be raised.
        self.assertRaises(NoMatchingReleasesError, repository.select_release, '0.0.1')
        # Release objects should support repr().
        release = repository.select_release('0.2')
        assert isinstance(repr(release), str)

    def test_factory_deduplication(self):
        """
        Test caching of previously loaded repository objects.

        This method tests that :func:`coerce_repository()` and similar
        functions don't construct duplicate repository objects but return the
        previously constructed instance instead.
        """
        a = coerce_repository(PIP_ACCEL_REPO)
        b = coerce_repository(PIP_ACCEL_REPO)
        c = coerce_repository(OUR_PUBLIC_REPO)
        assert a is b
        # Test our assumption about the `is' operator as well :-).
        assert a is not c
        assert b is not c

    def create_repo_using_config(self, repository_type, remote_location,
                                 second_repository_type=None,
                                 second_remote_location=None):
        """
        Test configuration file loading.

        Instantiates a :class:`.Repository` object by creating a temporary
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
        repository = find_configured_repository('test')
        # Make sure `last_updated' doesn't blow up on repositories without a local clone.
        if repository.exists:
            assert repository.last_updated > 0
        else:
            assert repository.last_updated == 0
        # Hand the constructed repository over to the caller.
        return repository

    def validate_revision(self, revision, id_pattern=HEX_SUM_PATTERN):
        """
        Perform some generic sanity checks on :class:`Revision` objects.
        """
        assert revision.revision_number > 0
        assert isinstance(repr(revision), str)
        assert id_pattern.match(revision.revision_id)

    def validate_all_revisions(self, mapping, **kw):
        """
        Validate the given dictionary of revisions.

        Performs some generic sanity checks on a dictionary with
        :class:`Revision` values. Randomly picks some revisions to sanity
        check (calculating the local revision number of a revision requires the
        execution of an external command and there's really no point in doing
        this hundreds of times).
        """
        revisions = list(mapping.values())
        random.shuffle(revisions)
        for revision in revisions[:10]:
            self.validate_revision(revision, **kw)


class EnsureNewCommit(object):

    """Context manager which ensures that a new commit is made."""

    def __init__(self, repository, branch_name=None):
        """Initialize a :class:`EnsureNewCommit` object."""
        self.repository = repository
        self.branch_name = branch_name
        self.old_id = None

    def __enter__(self):
        """Capture the global revision id of the most recent commit on the given branch."""
        if self.branch_name in self.repository.branches:
            self.old_id = self.repository.find_revision_id(revision=self.branch_name)

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Make sure a new commit was introduced since :func:`__enter__()`."""
        if exc_type is None:
            new_id = self.repository.find_revision_id(revision=self.branch_name)
            assert new_id != self.old_id

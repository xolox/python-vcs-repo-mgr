# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 7, 2018
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""Test suite for the `vcs-repo-mgr` package."""

# Standard library modules.
import codecs
import logging
import os
import shutil
import tempfile
import time

# External dependencies.
from humanfriendly import parse_path
from humanfriendly.testing import (
    MockedHomeDirectory,
    TemporaryDirectory,
    TestCase,
    random_string,
    run_cli,
)
from mock import MagicMock
from six import string_types

# The module we're testing.
from vcs_repo_mgr import (
    Author,
    FeatureBranchSpec,
    Release,
    Remote,
    USER_CONFIG_FILE,
    coerce_author,
    coerce_feature_branch,
    coerce_repository,
    find_configured_repository,
    limit_vcs_updates,
    sum_revision_numbers,
)
from vcs_repo_mgr.backends.bzr import BzrRepo
from vcs_repo_mgr.backends.git import GitRepo
from vcs_repo_mgr.backends.hg import HgRepo
from vcs_repo_mgr.cli import main
from vcs_repo_mgr.exceptions import (
    AmbiguousRepositoryNameError,
    MergeConflictError,
    MissingWorkingTreeError,
    NoMatchingReleasesError,
    NoSuchRepositoryError,
    UnknownRepositoryTypeError,
    WorkingTreeNotCleanError,
)

AUTHOR_NAME = 'John Doe'
AUTHOR_EMAIL = 'john.doe@example.com'
AUTHOR_COMBINED = '%s <%s>' % (AUTHOR_NAME, AUTHOR_EMAIL)
TEMPORARY_DIRECTORIES = []

# Initialize a logger.
logger = logging.getLogger(__name__)


def prepare_config(config):
    """Prepare the ``~/.vcs-repo-mgr.ini`` configuration file."""
    with open(parse_path(USER_CONFIG_FILE), 'w') as handle:
        for name, options in config.items():
            handle.write('[%s]\n' % name)
            for key, value in options.items():
                handle.write('%s = %s\n' % (key, value))


def setUpModule():
    """Create a temporary ``$HOME`` directory."""
    pathname = tempfile.mkdtemp()
    TEMPORARY_DIRECTORIES.append(pathname)
    os.environ['HOME'] = pathname


def tearDownModule():
    """Cleanup the temporary ``$HOME`` directory."""
    while TEMPORARY_DIRECTORIES:
        shutil.rmtree(TEMPORARY_DIRECTORIES.pop(0))
    os.environ['HOME'] = ''


class VcsRepoMgrTestCase(TestCase):

    """Unit tests for the common functionality in `vcs-repo-mgr`."""

    def test_cli_usage(self):
        """Test the command line interface's usage message."""
        for arguments in [], ['-h'], ['--help']:
            returncode, output = run_cli(main, *arguments)
            self.assertEquals(returncode, 0)
            assert "Usage: vcs-tool" in output

    def test_coerce_author(self):
        """Test :func:`vcs_repo_mgr.coerce_author()`."""
        # Make sure an exception is raised on invalid types.
        self.assertRaises(ValueError, coerce_author, None)
        # Make sure an exception is raised on invalid string values.
        self.assertRaises(ValueError, coerce_author, AUTHOR_NAME)
        # Create an Author object by parsing a string.
        author = coerce_author(AUTHOR_COMBINED)
        assert isinstance(author, Author)
        # Check the parsed components.
        assert author.name == AUTHOR_NAME
        assert author.email == AUTHOR_EMAIL
        assert author.combined == AUTHOR_COMBINED
        # Make sure Author objects pass through untouched.
        assert author is coerce_author(author)

    def test_coerce_feature_branch(self):
        """Test :func:`vcs_repo_mgr.coerce_feature_branch()`."""
        # Make sure an exception is raised on invalid types.
        self.assertRaises(ValueError, coerce_feature_branch, None)
        # Create a FeatureBranchSpec object by parsing a string.
        feature_branch = coerce_feature_branch('https://github.com/xolox/python-vcs-repo-mgr#dev')
        assert isinstance(feature_branch, FeatureBranchSpec)
        # Check the parsed components.
        assert feature_branch.location == 'https://github.com/xolox/python-vcs-repo-mgr'
        assert feature_branch.revision == 'dev'
        # Make sure FeatureBranchSpec objects pass through untouched.
        assert feature_branch is coerce_feature_branch(feature_branch)

    def test_coerce_repository(self):
        """Test :func:`vcs_repo_mgr.coerce_repository()`."""
        # Test argument type checking.
        self.assertRaises(ValueError, coerce_repository, None)
        # Test that Repository objects pass through untouched.
        with TemporaryDirectory() as directory:
            repository = GitRepo(local=directory)
            assert repository is coerce_repository(repository)
        # Test that a version control type can be prefixed
        # to the location of a repository using a plus.
        for prefix, vcs_type in (('bzr', BzrRepo), ('git', GitRepo), ('hg', HgRepo)):
            with TemporaryDirectory() as directory:
                location = '%s+%s' % (prefix, directory)
                assert isinstance(coerce_repository(location), vcs_type)
        # Test that version control type prefix parsing swallows
        # UnknownRepositoryTypeError (due to "unexpected plusses").
        self.assertRaises(ValueError, coerce_repository, 'definitely+not+as+expected')
        # Test that locations ending with `.git' are recognized.
        with TemporaryDirectory() as directory:
            location = '%s/test.git' % directory
            assert isinstance(coerce_repository(location), GitRepo)

    def test_default_local(self):
        """Test default locations of local repositories."""
        with TemporaryDirectory() as directory:
            source = GitRepo(local=os.path.join(directory), bare=False)
            target = GitRepo(remote=source.local, bare=False)
            # Make sure the default local repository directory or
            # one of its parent directories is writable to us.
            directory = target.local
            while directory:
                if os.access(directory, os.W_OK):
                    break
                parent = os.path.dirname(directory)
                assert parent != directory
                directory = parent

    def test_ensure_hexadecimal_string(self):
        """Test ensure_hexadecimal_string()."""
        with TemporaryDirectory() as directory:
            repository = GitRepo(local=directory)
            self.assertRaises(
                ValueError, repository.ensure_hexadecimal_string,
                'definitely not a hexadecimal string',
                'some random command',
            )

    def test_find_configured_repository(self):
        """Test :func:`vcs_repo_mgr.find_configured_repository()`."""
        with MockedHomeDirectory() as home:
            # Prepare the locations of several local repositories.
            bazaar_directory = os.path.join(home, 'a-bazaar-repository')
            git_directory = os.path.join(home, 'a-git-repository')
            mercurial_directory = os.path.join(home, 'a-mercurial-repository')
            # Generate the configuration file.
            prepare_config({
                'my-bazaar-repo': {
                    'bare': 'true',
                    'local': bazaar_directory,
                    'type': 'bazaar',
                },
                'my-git-repo': {
                    'bare': 'true',
                    'local': git_directory,
                    'release-filter': '(.+)',
                    'release-scheme': 'tags',
                    'type': 'git',
                },
                'my-mercurial-repo': {
                    'bare': 'false',
                    'local': mercurial_directory,
                    'type': 'mercurial',
                },
                'ambiguous-name': dict(type='git'),
                'ambiguous_name': dict(type='mercurial'),
                'unknown-type': dict(type='svn'),
            })
            # Make sure the configured Bazaar repository is loaded correctly.
            bazaar_repository = find_configured_repository('my-bazaar-repo')
            assert isinstance(bazaar_repository, BzrRepo)
            assert bazaar_repository.local == bazaar_directory
            assert bazaar_repository.bare is True
            # Make sure the configured git repository is loaded correctly.
            git_repository = find_configured_repository('my-git-repo')
            assert isinstance(git_repository, GitRepo)
            assert git_repository.local == git_directory
            assert git_repository.bare is True
            assert git_repository.release_scheme == 'tags'
            assert git_repository.release_filter == '(.+)'
            # Make sure the configured Mercurial repository is loaded correctly.
            mercurial_repository = find_configured_repository('my-mercurial-repo')
            assert isinstance(mercurial_repository, HgRepo)
            assert mercurial_repository.local == mercurial_directory
            assert mercurial_repository.bare is False
            # Test caching of previously constructed repository objects.
            assert bazaar_repository is find_configured_repository('my-bazaar-repo')
            assert git_repository is find_configured_repository('my-git-repo')
            assert mercurial_repository is find_configured_repository('my-mercurial-repo')
            # Make sure unknown repository names raise the expected exception.
            self.assertRaises(NoSuchRepositoryError, find_configured_repository, 'non-existing')
            # Make sure ambiguous repository names raise the expected exception.
            self.assertRaises(AmbiguousRepositoryNameError, find_configured_repository, 'ambiguous-name')
            # Make sure unknown repository types raise the expected exception.
            self.assertRaises(UnknownRepositoryTypeError, find_configured_repository, 'unknown-type')

    def test_find_directory(self):
        """Test the translation of repository names into repository directories."""
        with MockedHomeDirectory() as home:
            repository = GitRepo(local=os.path.join(home, 'repo'))
            prepare_config({
                'find-directory-test': {
                    'local': repository.local,
                    'type': repository.ALIASES[0],
                }
            })
            returncode, output = run_cli(
                main, '--repository=find-directory-test',
                '--find-directory',
            )
            self.assertEquals(returncode, 0)
            self.assertEquals(output.strip(), repository.local)

    def test_release_filter_validation(self):
        """Make sure the release filter validation refuses patterns with more than one capture group."""
        with TemporaryDirectory() as directory:
            self.assertRaises(
                ValueError, setattr,
                GitRepo(local=directory),
                'release_filter', '(foo)bar(baz)',
            )

    def test_release_scheme_validation(self):
        """Make sure the release scheme validation refuses invalid values."""
        with TemporaryDirectory() as directory:
            self.assertRaises(
                ValueError, setattr,
                GitRepo(local=directory),
                'release_scheme', 'invalid',
            )

    def test_repository_argument_validation(self):
        """Make sure Repository objects must be created with a local directory or remote location set."""
        self.assertRaises(ValueError, GitRepo)

    def test_sum_revision_numbers(self):
        """Test :func:`vcs_repo_mgr.sum_revision_numbers()`."""
        with MockedHomeDirectory() as home:
            # Prepare two local repositories.
            repo_one = GitRepo(author=AUTHOR_COMBINED, bare=False, local=os.path.join(home, 'repo-one'))
            repo_two = HgRepo(author=AUTHOR_COMBINED, bare=False, local=os.path.join(home, 'repo-two'))
            # Create an initial commit in each of the repositories.
            for repo in repo_one, repo_two:
                repo.create()
                repo.context.write_file('README', "This is a %s repository.\n" % repo.friendly_name)
                repo.add_files('README')
                repo.commit("Initial commit")
            # Check the argument validation in sum_revision_numbers().
            self.assertRaises(ValueError, sum_revision_numbers, repo_one.local)
            # Prepare a configuration file so we can test the command line interface.
            prepare_config({
                'repo-one': {
                    'type': repo_one.ALIASES[0],
                    'local': repo_one.local,
                },
                'repo-two': {
                    'type': repo_two.ALIASES[0],
                    'local': repo_two.local,
                },
            })
            # Make sure `vcs-tool --sum-revisions' works.
            returncode, output = run_cli(
                main, '--sum-revisions',
                'repo-one', repo_one.default_revision,
                'repo-two', repo_two.default_revision,
            )
            self.assertEquals(returncode, 0)
            initial_summed_revision_number = int(output)
            self.assertEquals(initial_summed_revision_number, sum([
                repo_one.find_revision_number(),
                repo_two.find_revision_number(),
            ]))
            # Create an additional commit.
            repo_one.context.write_file('README', "Not the same contents.\n")
            repo_one.commit("Additional commit")
            # Make sure the revision number has increased.
            returncode, output = run_cli(
                main, '--sum-revisions',
                'repo-one', repo_one.default_revision,
                'repo-two', repo_two.default_revision,
            )
            updated_summed_revision_number = int(output)
            assert updated_summed_revision_number > initial_summed_revision_number


class BackendTestCase(object):

    """Abstract test case for version control repository manipulation."""

    exceptionsToSkip = [NotImplementedError]
    """Translate NotImplementedError into a skipped test."""

    repository_type = None
    """The :class:`.Repository` subclass to test."""

    def check_pull(self, bare):
        """Test pulling of changes from another repository."""
        with TemporaryDirectory() as directory:
            # Initialize two repository objects of the parametrized type.
            source = self.get_instance(local=os.path.join(directory, 'source'), bare=False)
            target = self.get_instance(local=os.path.join(directory, 'target'), bare=bare)
            # Create the source repository with an initial commit.
            self.create_initial_commit(source)
            # Get the global commit id of the initial commit.
            initial_commit = source.find_revision_id()
            # Create the target repository as an empty repository.
            target.create()
            # Pull from the source repository into the target repository.
            target.pull(remote=source.local)
            # Check that our initial commit made it into the target repository.
            assert target.find_revision_id() == initial_commit

    def check_selective_push_or_pull(self, direction):
        """Test pushing and pulling of specific revisions."""
        with TemporaryDirectory() as directory:
            # Initialize two repository objects of the parametrized type.
            source, target = self.get_source_and_target(directory)
            # Create two new branches in the source repository.
            for branch_name in 'shared', 'private':
                source.checkout()
                source.create_branch(branch_name)
                source.context.write_file(branch_name, "This is the '%s' branch." % branch_name)
                source.add_files(branch_name)
                source.commit("Created '%s' branch" % branch_name)
            # Sanity check the current state of things.
            assert 'private' in source.branches
            assert 'private' not in target.branches
            assert 'shared' in source.branches
            assert 'shared' not in target.branches
            # Push or pull the 'shared' branch but not the 'private' branch.
            if direction == 'push':
                source.push(remote=target.local, revision='shared')
            else:
                target.pull(remote=source.local, revision='shared')
            # Sanity check the new state of things.
            assert 'private' in source.branches
            assert 'private' not in target.branches
            assert 'shared' in source.branches
            assert 'shared' in target.branches

    def create_initial_commit(self, repository):
        """Commit a README file in a repository as the initial commit."""
        repository.create()
        self.commit_file(
            repository=repository,
            filename='README',
            contents="This will be part of the initial commit.\n",
            message="Initial commit",
        )

    def create_followup_commit(self, repository):
        """Change the contents of the previously committed README file."""
        self.commit_file(
            repository=repository,
            filename='README',
            contents="Not the same contents.\n",
            message="Changes to README",
        )

    def commit_file(self, repository, filename=None, contents=None, message=None):
        """Commit a file to the given repository."""
        filename = filename or random_string(15)
        contents = contents or random_string(1024)
        exists = repository.context.exists(filename)
        repository.context.write_file(filename, contents)
        repository.add_files(filename)
        repository.commit(message=message or ("Committing %s file '%s'" % (
            "changed" if exists else "new", filename,
        )))

    def get_instance(self, **options):
        """Shortcut to create a new repository object of the parametrized type."""
        options.setdefault('author', AUTHOR_COMBINED)
        return self.repository_type(**options)

    def get_source_and_target(self, directory):
        """Shortcut to create two repositories where one is a clone of the other."""
        source = self.get_instance(bare=False, local=os.path.join(directory, 'source'))
        target = self.get_instance(bare=True, local=os.path.join(directory, 'target'), remote=source.local)
        # Create an initial commit in the source repository.
        self.create_initial_commit(source)
        # Create the target repository by cloning the source (including the
        # initial commit). If we hadn't created an initial commit first there
        # would be no common ancestor change set in the two repositories and
        # that would break the push() and pull() tests.
        target.create()
        return source, target

    def test_checkout(self):
        """Test checking out of branches."""
        contents_on_default_branch = b"This will be part of the initial commit.\n"
        contents_on_dev_branch = b"Not the same contents.\n"
        unversioned_contents = b"This was never committed.\n"
        with TemporaryDirectory() as directory:
            repository = self.get_instance(bare=False, local=directory)
            self.create_initial_commit(repository)
            # Commit a change to README on another branch.
            repository.create_branch('dev')
            self.create_followup_commit(repository)
            # Make sure the working tree can be updated to the default branch.
            repository.checkout()
            self.assertEquals(repository.context.read_file('README'), contents_on_default_branch)
            # Make sure the working tree can be updated to the `dev' branch.
            repository.checkout('dev')
            self.assertEquals(repository.context.read_file('README'), contents_on_dev_branch)
            # Make sure changes in the working tree can be discarded.
            repository.context.write_file('README', unversioned_contents)
            repository.checkout(clean=True)
            self.assertEquals(repository.context.read_file('README'), contents_on_default_branch)

    def test_clone(self):
        """Test cloning of local repositories."""
        with TemporaryDirectory() as directory:
            # Initialize two repository objects of the parametrized type.
            source = self.get_instance(local=os.path.join(directory, 'source'), bare=False)
            target = self.get_instance(local=os.path.join(directory, 'target'), remote=source.local)
            # Create the source repository with an initial commit on the default branch.
            self.create_initial_commit(source)
            # Sanity check that we just created our first commit.
            initial_commit = source.find_revision_id()
            # Create the target repository by cloning the source repository.
            target.create()
            # Check that our initial commit made it into the target repository.
            assert target.find_revision_id() == initial_commit

    def test_clone_all_branches(self):
        """
        Test that cloning of repositories copies all branches.

        This is a regression test for https://github.com/xolox/python-vcs-repo-mgr/issues/4.
        """
        branch_names = ['v1', 'v2', 'v3', 'v4', 'v5']
        with TemporaryDirectory() as directory:
            # Create a source (upstream) repository with multiple branches.
            source = self.get_instance(local=os.path.join(directory, 'source'), bare=False)
            for name in branch_names:
                source.create_branch(name)
                self.commit_file(
                    repository=source,
                    filename='VERSION',
                    contents=name,
                )
            # Sanity check the source repository.
            for name in branch_names:
                assert name in source.branches
            # Create the target repository by cloning the source repository.
            target = self.get_instance(
                local=os.path.join(directory, 'target'),
                remote=source.local,
                # It's important that the target repository is not bare,
                # because the issue reported involved a fresh git clone with a
                # working tree not reporting the same available branches (the
                # same behavior didn't manifest in a bare git repository).
                bare=False,
            )
            target.create()
            # Sanity check the target repository.
            for name in branch_names:
                assert name in target.branches

    def test_coerce_repository(self):
        """Test :func:`vcs_repo_mgr.coerce_repository()`."""
        with TemporaryDirectory() as directory:
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(local=directory)
            repository.create()
            # Test that the version control system of an existing local
            # repository can be inferred from the directory contents.
            coerced = coerce_repository(repository.local)
            assert isinstance(coerced, type(repository))

    def test_current_branch(self):
        """Test introspection of the currently checked out branch."""
        with TemporaryDirectory() as directory:
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(bare=False, local=directory)
            # Create the repository with an initial commit.
            self.create_initial_commit(repository)
            # Sanity check that the current branch is not the same one that we
            # are assuming doesn't exist yet :-).
            assert repository.current_branch != 'dev'
            # Create and check out a different branch.
            repository.create_branch('dev')
            # Create a commit on the branch to make sure that the
            # branch has actually been created (e.g. in Mercurial).
            repository.context.write_file('README', "Not the same contents.\n")
            repository.commit(message="Commit on 'dev' branch")
            # Make sure the current branch is properly detected.
            assert repository.current_branch == 'dev'

    def test_default_author(self):
        """Test introspection of default author configured in version control system."""
        with MockedHomeDirectory() as home:
            # Create the version control system specific
            # configuration file with the default author.
            self.configure_author(home, AUTHOR_NAME, AUTHOR_EMAIL)
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(local=os.path.join(home, 'repo'))
            # Clear the override set by get_instance() so that the value of
            # the `author' property is computed by calling get_author().
            del repository.author
            # Make sure the default author was picked up from the
            # configuration file.
            repository.author.name == AUTHOR_NAME
            repository.author.email == AUTHOR_EMAIL
            repository.author.combined == AUTHOR_COMBINED

    def test_delete_branch(self):
        """Test deletion/closing of branches."""
        with TemporaryDirectory() as directory:
            repository = self.get_instance(bare=False, local=directory)
            self.create_initial_commit(repository)
            repository.create_branch('dev')
            self.create_followup_commit(repository)
            # Check that Repository.branches includes the new branch.
            assert 'dev' in repository.branches
            # Merge the new branch into the default branch.
            repository.checkout()
            repository.merge(revision='dev')
            repository.commit(message="Merged 'dev' branch")
            # Delete the new branch.
            repository.delete_branch('dev')
            # Check that Repository.branches no longer includes the new branch.
            assert 'dev' not in repository.branches

    def test_ensure_exists(self):
        """Test ensure_exists()."""
        with TemporaryDirectory() as directory:
            repository = self.get_instance(local=directory)
            self.assertRaises(ValueError, repository.ensure_exists)

    def test_export(self):
        """Test exporting of revisions."""
        with TemporaryDirectory() as directory:
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(bare=False, local=os.path.join(directory, 'repo'))
            repository.create()
            # Commit a file to the repository.
            versioned_filename = random_string(10)
            versioned_contents = random_string(250)
            self.commit_file(
                repository=repository,
                filename=versioned_filename,
                contents=versioned_contents,
                message="Initial commit",
            )
            # Export the initial revision.
            export_directory = os.path.join(directory, 'export')
            returncode, output = run_cli(
                main, '--repository=%s' % repository.local,
                '--export=%s' % export_directory,
            )
            self.assertEquals(returncode, 0)
            # Check that the file we committed was exported.
            exported_file = os.path.join(export_directory, versioned_filename)
            self.assertTrue(os.path.isfile(exported_file))
            with codecs.open(exported_file, 'r', 'UTF-8') as handle:
                self.assertEquals(handle.read(), versioned_contents)

    def test_find_revision_number(self):
        """Test querying the command line interface for local revision numbers."""
        with TemporaryDirectory() as directory:
            repository = self.get_instance(bare=False, local=directory)
            repository.create()
            self.create_initial_commit(repository)
            # Check the revision number of the initial commit.
            initial_revision_number = repository.find_revision_number()
            assert initial_revision_number in (0, 1)
            # Create a second commit.
            self.create_followup_commit(repository)
            # Check the revision number of the second commit.
            second_revision_number = repository.find_revision_number()
            assert second_revision_number in (1, 2)
            assert second_revision_number > initial_revision_number
            # Get the local revision number of a revision using the command line interface.
            returncode, output = run_cli(
                main, '--repository=%s' % repository.local,
                '--find-revision-number',
            )
            self.assertEquals(returncode, 0)
            self.assertEquals(int(output), second_revision_number)

    def test_find_revision_id(self):
        """Test querying the command line interface for global revision ids."""
        with TemporaryDirectory() as directory:
            repository = self.get_instance(bare=False, local=directory)
            repository.create()
            self.create_initial_commit(repository)
            # Check the global revision id of the initial commit.
            revision_id = repository.find_revision_id()
            self.assertIsInstance(revision_id, string_types)
            self.assertTrue(revision_id)
            # Get the global revision id using the command line interface.
            returncode, output = run_cli(
                main, '--repository=%s' % repository.local,
                '--find-revision-id',
            )
            self.assertEquals(returncode, 0)
            self.assertEquals(output.strip(), revision_id)

    def test_init(self):
        """Test initialization of new, empty repositories."""
        with TemporaryDirectory() as directory:
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(local=directory)
            # Sanity check that the local repository doesn't exist yet.
            assert repository.exists is False
            # Make sure that Repository.create() claims
            # to have just created the local repository.
            assert repository.create() is True
            # Sanity check that the local repository now exists.
            assert repository.exists is True
            # Make sure that Repository.create() doesn't try to create the repository again.
            assert repository.create() is False

    def test_is_clean(self):
        """Test check whether working directory is clean."""
        with TemporaryDirectory() as directory:
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(bare=False, local=directory)
            # Create the local repository.
            repository.create()
            # Make sure the working tree is considered clean.
            assert repository.is_clean is True
            # Commit a file to version control.
            self.create_initial_commit(repository)
            # Make sure the working tree is still considered clean.
            assert repository.is_clean is True
            # Change the previously committed file.
            repository.context.write_file('README', "Not the same contents.\n")
            # Make sure the working tree is now considered dirty.
            assert repository.is_clean is False
            # Make sure ensure_clean() now raises the expected exception.
            self.assertRaises(WorkingTreeNotCleanError, repository.ensure_clean)

    def test_last_updated(self):
        """Make sure the last_updated logic is robust."""
        with TemporaryDirectory() as directory:
            # Initialize two repository objects of the parametrized type.
            source = self.get_instance(local=os.path.join(directory, 'source'), bare=False)
            target = self.get_instance(local=os.path.join(directory, 'target'), remote=source.local)
            # Create the source repository with an initial commit.
            self.create_initial_commit(source)
            # Make sure `last_updated' doesn't raise an exception when the
            # local repository doesn't exist yet.
            assert target.last_updated == 0
            # Create the target repository by cloning the source.
            target.create()
            # Make sure the value of `last_updated' has been changed.
            assert target.last_updated > 0

    def test_limit_updates(self):
        """Test limiting of repository updates."""
        with TemporaryDirectory() as directory:
            source, target = self.get_source_and_target(directory)
            # Wait until the cloning of the target repository is more than a second ago.
            while int(time.time()) <= int(target.last_updated):
                time.sleep(0.1)
            # Use the context manager to limit repository updates.
            with limit_vcs_updates():
                pull_command = target.get_pull_command()
                # The first pull() is expected to be executed.
                target.get_pull_command = MagicMock(return_value=pull_command)
                target.pull()
                assert target.get_pull_command.called
                # The second pull() should be skipped.
                target.get_pull_command = MagicMock(return_value=pull_command)
                target.pull()
                assert not target.get_pull_command.called

    def test_list_releases(self):
        """Test listing of releases."""
        with MockedHomeDirectory() as home:
            repository = self.get_instance(
                bare=False,
                local=os.path.join(home, 'repo'),
                release_scheme='branches',
                release_filter=r'^r(\d{4})$',
            )
            self.create_initial_commit(repository)
            # Create some release branches to test with.
            releases = '1720', '1722', '1723', '1724', '1726'
            features = '12345', '23456', '34567', '45678'
            for release_id in releases:
                repository.create_branch('r' + release_id)
                self.commit_file(repository)
            for feature_id in features:
                repository.create_branch('c' + feature_id)
                self.commit_file(repository)
            # Configure the repository's release scheme and filter.
            prepare_config({
                'list-repo': {
                    'local': repository.local,
                    'release-filter': repository.release_filter,
                    'release-scheme': repository.release_scheme,
                    'type': repository.ALIASES[0],
                }
            })
            returncode, output = run_cli(main, '--repository=list-repo', '--list-releases')
            listed_releases = output.splitlines()
            assert returncode == 0
            for release_id in releases:
                assert release_id in listed_releases
            for feature_id in features:
                assert feature_id not in listed_releases

    def test_merge_conflicts(self):
        """Test handling of merge conflicts."""
        with TemporaryDirectory() as directory:
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(bare=False, local=directory)
            # Create the local repository.
            repository.create()
            # Create an initial commit in the repository.
            versioned_filename = random_string(10)
            versioned_contents = random_string(250)
            self.commit_file(
                repository=repository,
                filename=versioned_filename,
                contents=versioned_contents,
                message="Initial commit",
            )
            # Create a new branch in which we'll modify
            # the file that the initial commit created.
            repository.create_branch('dev')
            self.commit_file(
                repository=repository,
                filename=versioned_filename,
                message="Commit on 'dev' branch",
            )
            # Now modify the same file in the default branch.
            repository.checkout()
            self.commit_file(
                repository=repository,
                filename=versioned_filename,
                message="Commit on default branch",
            )
            # Now try to merge the 'dev' branch into the default branch
            # (triggering the merge conflict) and make sure that the intended
            # exception type is raised.
            self.assertRaises(MergeConflictError, repository.merge, 'dev')
            # Make sure the filename of the file with merge conflicts is
            # available to callers.
            assert repository.merge_conflicts == [versioned_filename]

    def test_merge_up(self):
        """Test merging up through release branches."""
        initial_release_branches = ['v1', 'v2', 'v3', 'v4']
        intermediate_release_branch = 'v3.1'
        final_release_branches = ['v1', 'v2', 'v3', intermediate_release_branch, 'v4']
        with MockedHomeDirectory() as home:
            self.configure_author(home, AUTHOR_NAME, AUTHOR_EMAIL)
            # Initialize a repository object of the parametrized type.
            repository = self.get_instance(
                bare=False,
                local=os.path.join(home, 'repo'),
                release_filter=r'^v(\d+(?:\.\d+)*)$',
                release_scheme='branches',
            )
            # Add the repository to ~/.vcs-repo-mgr.ini.
            prepare_config({
                'merge-up-test': {
                    'local': repository.local,
                    'release-filter': r'^v(\d+(?:\.\d+)*)$',
                    'release-scheme': 'branches',
                    'type': repository.ALIASES[0],
                },
            })
            # Make sure the repository contains an initial commit on the
            # default branch, otherwise the merge process will try to
            # checkout() the default branch which can fail when that branch
            # "doesn't have any contents yet".
            self.create_initial_commit(repository)
            # Create the release branches.
            previous_branch = repository.current_branch
            for branch_name in initial_release_branches:
                repository.checkout(revision=previous_branch)
                repository.create_branch(branch_name)
                self.commit_file(
                    repository=repository,
                    filename=branch_name,
                    contents="This is release branch '%s'\n" % branch_name,
                    message="Create release branch '%s'" % branch_name,
                )
                previous_branch = branch_name
            # Create a feature branch based on the initial release branch.
            feature_branch = 'feature-%s' % random_string(10)
            repository.checkout('v3')
            repository.create_branch(feature_branch)
            self.commit_file(
                repository=repository,
                filename=intermediate_release_branch,
                contents="This will be release branch '%s'\n" % intermediate_release_branch,
                message="Fixed a bug in version 3!",
            )
            assert feature_branch in repository.branches
            # Merge the change up into the release branches using the command line interface.
            returncode, output = run_cli(
                main, '--repository=merge-up-test',
                '--revision=v3.1', '--merge-up',
                feature_branch, merged=True,
            )
            self.assertEquals(returncode, 0)
            # Make sure the feature branch was closed.
            assert feature_branch not in repository.branches
            # Validate the contents of the default branch.
            repository.checkout()
            # Check that all of the release branches have been merged into the
            # default branch by checking the `v1', `v2', etc. filenames.
            entries = repository.context.list_entries('.')
            assert all(fn in entries for fn in final_release_branches)
            # Make sure the contents of the bug fix were merged up.
            assert repository.context.read_file('v1') == b"This is release branch 'v1'\n"
            assert repository.context.read_file('v2') == b"This is release branch 'v2'\n"
            assert repository.context.read_file('v3') == b"This is release branch 'v3'\n"
            assert repository.context.read_file('v3.1') == b"This will be release branch 'v3.1'\n"
            assert repository.context.read_file('v4') == b"This is release branch 'v4'\n"

    def test_pull_revision(self):
        """Test pulling of specific revisions."""
        self.check_selective_push_or_pull('pull')

    def test_pull_with_working_tree(self):
        """Test pulling of changes into a repository with a working tree."""
        self.check_pull(bare=False)

    def test_pull_without_working_tree(self):
        """Test pulling of changes into a repository with a working tree."""
        self.check_pull(bare=True)

    def test_push(self):
        """Test pulling of changes from another repository."""
        with TemporaryDirectory() as directory:
            # Initialize two repository objects of the parametrized type.
            source, target = self.get_source_and_target(directory)
            # Create a new commit in the source repository.
            self.create_followup_commit(source)
            # Get the global commit id of the commit.
            commit_id = source.find_revision_id()
            # Push from the source repository to the target repository.
            source.push(remote=target.local)
            # Check that our commit made it into the target repository.
            assert target.find_revision_id() == commit_id

    def test_push_revision(self):
        """Test pulling of specific revisions."""
        self.check_selective_push_or_pull('push')

    def test_remotes(self):
        """Test introspection of remote repositories."""
        with TemporaryDirectory() as directory:
            # Initialize two repository objects of the parametrized type.
            source = self.get_instance(local=os.path.join(directory, 'source'), bare=False)
            target = self.get_instance(local=os.path.join(directory, 'target'), remote=source.local)
            # Create the source repository with an initial commit.
            self.create_initial_commit(source)
            # Create the target repository by cloning the source repository.
            target.create()
            # Sanity check the remotes of the target repository.
            assert isinstance(target.default_pull_remote, Remote)
            assert target.default_pull_remote.location == source.local
            assert isinstance(target.default_push_remote, Remote)
            assert target.default_push_remote.location == source.local

    def test_select_release(self):
        """Test release selection."""
        with MockedHomeDirectory() as home:
            repository = self.get_instance(
                bare=False,
                local=os.path.join(home, 'repo'),
                release_scheme='branches',
                release_filter=r'^release-(.+)$',
            )
            self.create_initial_commit(repository)
            # Make sure the correct exception is raised when no matching release is found.
            self.assertRaises(NoMatchingReleasesError, repository.select_release, '1.1')
            # Create some release branches to test with.
            for release in ('1.0', '1.1', '1.2',
                            '2.0', '2.1', '2.2', '2.3',
                            '3.0', '3.1'):
                repository.create_branch('release-%s' % release)
                self.commit_file(repository)
            # Try to select a non-existing release.
            release = repository.select_release('2.7')
            # Make sure the highest release that is isn't
            # higher than the given release was selected.
            self.assertIsInstance(release, Release)
            self.assertEquals(release.identifier, '2.3')
            self.assertEquals(release.revision.branch, 'release-2.3')
            # Try the same thing we did above, but now using the command line
            # interface. To do this we first need to configure the repository's
            # release scheme and filter.
            prepare_config({
                'select-repo': {
                    'bare': 'false',
                    'local': repository.local,
                    'release-filter': '^release-(.+)$',
                    'release-scheme': 'branches',
                    'type': repository.ALIASES[0],
                }
            })
            returncode, output = run_cli(
                main, '--repository=select-repo',
                '--select-release=2.7', merged=True,
            )
            assert returncode == 0
            assert output.strip() == '2.3'

    def test_tags(self):
        """Test that tags can be created and introspected."""
        with TemporaryDirectory() as directory:
            repository = self.get_instance(bare=False, local=directory)
            # Create an initial commit and give it a tag.
            self.create_initial_commit(repository)
            initial_tag = random_string(10)
            assert initial_tag not in repository.tags
            repository.create_tag(initial_tag)
            assert initial_tag in repository.tags
            # Create a follow up commit and give it a tag.
            self.create_followup_commit(repository)
            followup_tag = random_string(10)
            assert followup_tag not in repository.tags
            repository.create_tag(followup_tag)
            assert followup_tag in repository.tags

    def test_vcs_control_field(self):
        """Test that Debian ``Vcs-*`` control file fields can be generated."""
        with TemporaryDirectory() as directory:
            repository = self.get_instance(bare=False, local=directory)
            self.create_initial_commit(repository)
            returncode, output = run_cli(
                main, '--repository=%s' % repository.local,
                '--vcs-control-field',
            )
            self.assertEquals(returncode, 0)
            assert repository.control_field in output
            assert repository.find_revision_id() in output

    def test_working_tree_present(self):
        """Test that repositories can be created with a working tree."""
        with TemporaryDirectory() as directory:
            repository = self.get_instance(bare=False, local=directory)
            # Create a commit in the repository. The fact that we can even do
            # this already confirms that the repository has a working tree :-P.
            self.create_initial_commit(repository)
            # Check the `bare' and `is_bare' properties.
            assert repository.bare is False
            assert repository.is_bare is False
            # Check `ensure_working_tree' and `supports_working_tree'.
            repository.ensure_working_tree()

    def test_working_tree_absent(self):
        """Test that repositories can be created without a working tree."""
        with TemporaryDirectory() as directory:
            # Create a bare repository.
            repository = self.get_instance(bare=True, local=directory)
            repository.create()
            assert repository.bare is True
            assert repository.is_bare is True
            # Check `ensure_working_tree' and `supports_working_tree'. We
            # can't use assertRaises() here because Mercurial repositories
            # always support a working tree, this explains why we just call
            # ensure_working_tree() and swallow the one expected exception.
            try:
                repository.ensure_working_tree()
            except MissingWorkingTreeError:
                pass


class BzrTestCase(BackendTestCase, TestCase):

    """Test case that runs :class:`BackendTestCase` using :class:`.BzrRepo`."""

    repository_type = BzrRepo

    def configure_author(self, home, name, email):
        """Configure the default author for Bazaar."""
        filename = os.path.join(home, '.bazaar', 'bazaar.conf')
        directory = os.path.dirname(filename)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with open(filename, 'w') as handle:
            handle.write('[DEFAULT]\n')
            handle.write('email = %s <%s>\n' % (name, email))


class GitTestCase(BackendTestCase, TestCase):

    """Test case that runs :class:`BackendTestCase` using :class:`.GitRepo`."""

    repository_type = GitRepo

    def configure_author(self, home, name, email):
        """Configure the default author for git."""
        with open(os.path.join(home, '.gitconfig'), 'w') as handle:
            handle.write('[user]\n')
            handle.write('name = %s\n' % name)
            handle.write('email = %s\n' % email)


class HgTestCase(BackendTestCase, TestCase):

    """Test case that runs :class:`BackendTestCase` using :class:`.HgRepo`."""

    repository_type = HgRepo

    def configure_author(self, home, name, email):
        """Configure the default author for Mercurial."""
        with open(os.path.join(home, '.hgrc'), 'w') as handle:
            handle.write('[ui]\n')
            handle.write('username = %s <%s>\n' % (name, email))

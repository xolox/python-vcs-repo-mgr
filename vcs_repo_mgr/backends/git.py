# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 7, 2018
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""Support for git version control repositories."""

# Standard library modules.
import logging
import os
import re

# External dependencies.
from executor import quote
from humanfriendly import coerce_boolean
from humanfriendly.text import split
from property_manager import required_property

# Modules included in our package.
from vcs_repo_mgr import Author, Remote, Repository, Revision

# Public identifiers that require documentation.
__all__ = (
    'GitRepo',
)

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

# A compiled regular expression pattern to match branch names in
# the output of the 'git for-each-ref --format=%(refname)' command.
REFNAME_TO_BRANCH = re.compile('^refs/heads/(.+)|refs/remotes/[^/]+/(.+)$')


class GitRepo(Repository):

    """Manage git version control repositories."""

    ALIASES = ['git']

    # Class methods.

    @classmethod
    def contains_repository(cls, context, directory):
        """Check whether the given directory contains a local repository."""
        directory = cls.get_vcs_directory(context, directory)
        return context.is_file(os.path.join(directory, 'config'))

    @staticmethod
    def get_vcs_directory(context, directory):
        """Get the pathname of the directory containing the version control metadata files."""
        nested = os.path.join(directory, '.git')
        return nested if context.is_directory(nested) else directory

    # Instance properties.

    @required_property
    def control_field(self):
        """The name of the Debian control file field for git repositories (the string 'Vcs-Git')."""
        return 'Vcs-Git'

    @property
    def current_branch(self):
        """The name of the branch that's currently checked out in the working tree (a string or :data:`None`)."""
        output = self.context.capture('git', 'rev-parse', '--abbrev-ref', 'HEAD', check=False, silent=True)
        return output if output != 'HEAD' else None

    @required_property
    def default_revision(self):
        """The default revision for git repositories (the string 'master')."""
        return 'master'

    @required_property
    def friendly_name(self):
        """A user friendly name for the version control system (the string 'git')."""
        return 'git'

    @property
    def is_bare(self):
        """
        :data:`True` if the repository has no working tree, :data:`False` if it does.

        The value of this property is computed by running
        the ``git config --get core.bare`` command.
        """
        # Make sure the local repository exists.
        self.create()
        # Ask git whether this is a bare repository.
        return coerce_boolean(self.context.capture(
            'git', 'config', '--get', 'core.bare',
        ))

    @property
    def is_clean(self):
        """
        :data:`True` if the working tree (and index) is clean, :data:`False` otherwise.

        The implementation of :attr:`GitRepo.is_clean` checks whether ``git
        diff`` reports any differences. This command has several variants:

        1. ``git diff`` shows the difference between the index and working tree.
        2. ``git diff --cached`` shows the difference between the last commit and index.
        3. ``git diff HEAD`` shows the difference between the last commit and working tree.

        The implementation of :attr:`GitRepo.is_clean` uses the third command
        (``git diff HEAD``) in an attempt to hide the existence of git's index
        from callers that are trying to write code that works with Git and
        Mercurial using the same Python API.
        """
        # Make sure the local repository exists.
        self.create()
        # Check whether the `git diff HEAD' output is empty.
        listing = self.context.capture('git', 'diff', 'HEAD', check=False, silent=True)
        return len(listing.splitlines()) == 0

    @property
    def known_remotes(self):
        """The names of the configured remote repositories (a list of :class:`.Remote` objects)."""
        objects = []
        for line in self.context.capture('git', 'remote', '--verbose').splitlines():
            tokens = line.split()
            if len(tokens) >= 2:
                name = tokens[0]
                objects.append(Remote(
                    default=(name == 'origin'),
                    location=tokens[1], name=name, repository=self,
                    # We fall back to allowing both roles when we fail to
                    # recognize either role because:
                    #
                    #  1. This code is relatively new and may be buggy.
                    #  2. Practically speaking most git repositories will use
                    #     the same remote for pushing and pulling and in fact
                    #     this remote is likely to be the only remote :-).
                    roles=(['pull'] if '(fetch)' in tokens
                           else (['push'] if '(push)' in tokens
                           else (['push', 'pull']))),
                ))
        return objects

    @property
    def merge_conflicts(self):
        """The filenames of any files with merge conflicts (a list of strings)."""
        filenames = set()
        listing = self.context.capture('git', 'ls-files', '--unmerged', '-z')
        for entry in split(listing, '\0'):
            # The output of `git ls-files --unmerged -z' consists of two
            # tab-delimited fields per zero-byte terminated record, where the
            # first field contains metadata and the second field contains the
            # filename. A single filename can be output more than once.
            metadata, _, name = entry.partition('\t')
            if metadata and name:
                filenames.add(name)
        return sorted(filenames)

    @property
    def supports_working_tree(self):
        """The opposite of :attr:`bare` (a boolean)."""
        return not self.is_bare

    # Instance methods.

    def find_author(self):
        """Get the author information from the version control system."""
        return Author(name=self.context.capture('git', 'config', 'user.name', check=False, silent=True),
                      email=self.context.capture('git', 'config', 'user.email', check=False, silent=True))

    def find_branches(self):
        """Find information about the branches in the repository."""
        listing = self.context.capture('git', 'for-each-ref', '--format=%(refname)\t%(objectname)')
        for line in listing.splitlines():
            tokens = line.split('\t')
            if len(tokens) == 2:
                match = REFNAME_TO_BRANCH.match(tokens[0])
                if match:
                    name = next(g for g in match.groups() if g)
                    if name != 'HEAD':
                        yield Revision(
                            branch=name,
                            repository=self,
                            revision_id=tokens[1],
                        )

    def find_revision_id(self, revision=None):
        """Find the global revision id of the given revision."""
        # Make sure the local repository exists.
        self.create()
        # Try to find the revision id of the specified revision.
        revision = revision or self.default_revision
        output = self.context.capture('git', 'rev-parse', revision)
        # Validate the `git rev-parse' output.
        return self.ensure_hexadecimal_string(output, 'git rev-parse')

    def find_revision_number(self, revision=None):
        """Find the local revision number of the given revision."""
        # Make sure the local repository exists.
        self.create()
        # Try to find the revision number of the specified revision.
        revision = revision or self.default_revision
        output = self.context.capture('git', 'rev-list', revision, '--count')
        if not (output and output.isdigit()):
            msg = "Failed to find local revision number! ('git rev-list --count' gave unexpected output)"
            raise ValueError(msg)
        return int(output)

    def find_tags(self):
        """Find information about the tags in the repository."""
        listing = self.context.capture('git', 'show-ref', '--tags', check=False)
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and tokens[1].startswith('refs/tags/'):
                yield Revision(
                    repository=self,
                    revision_id=tokens[0],
                    tag=tokens[1][len('refs/tags/'):],
                )

    def get_add_files_command(self, *filenames):
        """Get the command to include added and/or removed files in the working tree in the next commit."""
        command = ['git', 'add']
        if filenames:
            command.append('--')
            command.extend(filenames)
        else:
            command.extend(('--all', '.'))
        return command

    def get_checkout_command(self, revision, clean=False):
        """Get the command to update the working tree of the local repository."""
        if clean:
            # This looks a bit obscure but it does the right thing: We give our
            # superclass a shell command that chains together two git commands.
            return ['git checkout . && git checkout %s' % quote(revision)]
        else:
            return ['git', 'checkout', revision]

    def get_commit_command(self, message, author=None):
        """Get the command to commit changes to tracked files in the working tree."""
        command = ['git']
        if author:
            command.extend(('-c', 'user.name=%s' % author.name))
            command.extend(('-c', 'user.email=%s' % author.email))
        command.append('commit')
        command.append('--all')
        command.append('--message')
        command.append(message)
        return command

    def get_create_branch_command(self, branch_name):
        """Get the command to create a new branch based on the working tree's revision."""
        return ['git', 'checkout', '-b', branch_name]

    def get_create_tag_command(self, tag_name):
        """Get the command to create a new tag based on the working tree's revision."""
        return ['git', 'tag', tag_name]

    def get_create_command(self):
        """Get the command to create the local repository."""
        command = ['git', 'clone' if self.remote else 'init']
        if self.bare:
            command.append('--bare')
        if self.remote:
            command.append(self.remote)
        command.append(self.local)
        return command

    def get_delete_branch_command(self, branch_name, message=None, author=None):
        """Get the command to delete or close a branch in the local repository."""
        return ['git', 'branch', '--delete', branch_name]

    def get_export_command(self, directory, revision):
        """Get the command to export the complete tree from the local repository."""
        shell_command = 'git archive %s | tar --extract --directory=%s'
        return [shell_command % (quote(revision), quote(directory))]

    def get_merge_command(self, revision):
        """Get the command to merge a revision into the current branch (without committing the result)."""
        return [
            'git',
            '-c', 'user.name=%s' % self.author.name,
            '-c', 'user.email=%s' % self.author.email,
            'merge', '--no-commit', '--no-ff',
            revision,
        ]

    def get_pull_command(self, remote=None, revision=None):
        """
        Get the command to pull changes from a remote repository into the local repository.

        When you pull a specific branch using git, the default behavior is to
        pull the change sets from the remote branch into the local repository
        and merge them into the *currently checked out* branch.

        What Mercurial does is to pull the change sets from the remote branch
        into the local repository and create a local branch whose contents
        mirror those of the remote branch. Merging is left to the operator.

        In my opinion the default behavior of Mercurial is more sane and
        predictable than the default behavior of git and so :class:`GitRepo`
        tries to emulate the default behavior of Mercurial.

        When a specific revision is pulled, the revision is assumed to be a
        branch name and git is instructed to pull the change sets from the
        remote branch into a local branch with the same name.

        .. warning:: The logic described above will undoubtedly break when
                     `revision` is given but is not a branch name. I'd fix
                     this if I knew how to, but I don't...
        """
        if revision:
            revision = '%s:%s' % (revision, revision)
        if self.bare:
            return [
                'git', 'fetch',
                remote or 'origin',
                # http://stackoverflow.com/a/10697486
                revision or '+refs/heads/*:refs/heads/*',
            ]
        else:
            command = ['git', 'pull']
            if remote or revision:
                command.append(remote or 'origin')
                if revision:
                    command.append(revision)
        return command

    def get_push_command(self, remote=None, revision=None):
        """Get the command to push changes from the local repository to a remote repository."""
        # TODO What about tags?
        command = ['git', '-c', 'push.default=matching', 'push']
        if remote or revision:
            command.append(remote or 'origin')
            if revision:
                command.append(revision)
        return command

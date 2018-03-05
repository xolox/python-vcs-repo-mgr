# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 5, 2018
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""Support for Mercurial version control repositories."""

# Standard library modules.
import logging
import os

# External dependencies.
from executor import quote
from property_manager import required_property

# Modules included in our package.
from vcs_repo_mgr import Remote, Repository, Revision, coerce_author

# Public identifiers that require documentation.
__all__ = (
    'HgRepo',
)

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


class HgRepo(Repository):

    """Manage Mercurial version control repositories."""

    ALIASES = ['hg', 'mercurial']

    # Class methods.

    @staticmethod
    def get_vcs_directory(context, directory):
        """Get the pathname of the directory containing the version control metadata files."""
        return os.path.join(directory, '.hg')

    # Instance properties.

    @required_property
    def control_field(self):
        """The name of the Debian control file field for Mercurial repositories (the string 'Vcs-Hg')."""
        return 'Vcs-Hg'

    @property
    def current_branch(self):
        """The name of the branch that's currently checked out in the working tree (a string or :data:`None`)."""
        return self.context.capture('hg', 'branch', check=False, silent=True)

    @required_property
    def default_revision(self):
        """The default revision for Mercurial repositories (the string 'default')."""
        return 'default'

    @required_property
    def friendly_name(self):
        """A user friendly name for the version control system (the string 'Mercurial')."""
        return "Mercurial"

    @property
    def is_bare(self):
        """
        :data:`True` if the repository has no working tree, :data:`False` if it does.

        The value of this property is computed by running the ``hg id`` command
        to check whether the special global revision id ``000000000000`` is
        reported.
        """
        # Make sure the local repository exists.
        self.create()
        # Check the global revision id of the working tree.
        try:
            output = self.context.capture('hg', 'id', silent=True)
            tokens = output.split()
            return int(tokens[0]) == 0
        except Exception:
            return False

    @property
    def is_clean(self):
        """:data:`True` if the working tree is clean, :data:`False` otherwise."""
        # Make sure the local repository exists.
        self.create()
        # Check whether the `hg diff' output is empty.
        listing = self.context.capture('hg', 'diff')
        return len(listing.splitlines()) == 0

    @property
    def known_remotes(self):
        """The names of the configured remote repositories (a list of :class:`.Remote` objects)."""
        objects = []
        for line in self.context.capture('hg', 'paths').splitlines():
            name, _, location = line.partition('=')
            if name and location:
                name = name.strip()
                objects.append(Remote(
                    default=(name in ('default', 'default-push')),
                    location=location.strip(), name=name, repository=self,
                    # We give the `default-push' remote the `push' role only,
                    # while allowing both roles for other remotes. This isn't
                    # strictly speaking correct but it will prevent
                    # Repository.pull() from considering the `default-push'
                    # remote as a suitable default to pull from (which is not
                    # what Mercurial does when you run `hg pull').
                    roles=(['push'] if name == 'default-push' else ['push', 'pull']),
                ))
        return objects

    @property
    def merge_conflicts(self):
        """The filenames of any files with merge conflicts (a list of strings)."""
        filenames = set()
        listing = self.context.capture('hg', 'resolve', '--list')
        for line in listing.splitlines():
            tokens = line.split(None, 1)
            if len(tokens) == 2:
                status, name = tokens
                if status and name and status.upper() != 'R':
                    filenames.add(name)
        return sorted(filenames)

    @property
    def supports_working_tree(self):
        """Always :data:`True` for Mercurial repositories."""
        return True

    # Instance methods.

    def find_author(self):
        """Get the author information from the version control system."""
        return coerce_author(self.context.capture('hg', 'config', 'ui.username'))

    def find_branches(self):
        """
        Find the branches in the Mercurial repository.

        :returns: A generator of :class:`.Revision` objects.

        .. note:: Closed branches are not included.
        """
        listing = self.context.capture('hg', 'branches')
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and ':' in tokens[1]:
                revision_number, revision_id = tokens[1].split(':')
                yield Revision(
                    branch=tokens[0],
                    repository=self,
                    revision_id=revision_id,
                    revision_number=int(revision_number),
                )

    def find_revision_id(self, revision=None):
        """Find the global revision id of the given revision."""
        # Make sure the local repository exists.
        self.create()
        # Try to find the revision id of the specified revision.
        revision = revision or self.default_revision
        output = self.context.capture('hg', 'id', '--rev=%s' % revision, '--debug', '--id').rstrip('+')
        # Validate the `hg id --debug --id' output.
        return self.ensure_hexadecimal_string(output, 'hg id --id')

    def find_revision_number(self, revision=None):
        """Find the local revision number of the given revision."""
        # Make sure the local repository exists.
        self.create()
        # Try to find the revision number of the specified revision.
        revision = revision or self.default_revision
        output = self.context.capture('hg', 'id', '--rev=%s' % revision, '--num').rstrip('+')
        # Validate the `hg id --num' output.
        if not output.isdigit():
            msg = "Failed to find local revision number! ('hg id --num' gave unexpected output)"
            raise EnvironmentError(msg)
        return int(output)

    def find_tags(self):
        """Find information about the tags in the repository."""
        listing = self.context.capture('hg', 'tags')
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and ':' in tokens[1]:
                revision_number, revision_id = tokens[1].split(':')
                yield Revision(
                    repository=self,
                    revision_id=revision_id,
                    revision_number=int(revision_number),
                    tag=tokens[0],
                )

    def get_add_files_command(self, *filenames):
        """Get the command to include added and/or removed files in the working tree in the next commit."""
        command = ['hg', 'addremove']
        command.extend(filenames)
        return command

    def get_checkout_command(self, revision, clean=False):
        """Get the command to update the working tree of the local repository."""
        command = ['hg', 'update']
        if clean:
            command.append('--clean')
        command.append('--rev=%s' % revision)
        return command

    def get_commit_command(self, message, author=None):
        """
        Get the command to commit changes to tracked files in the working tree.

        This method uses the ``hg remove --after`` to match the semantics of
        ``git commit --all`` (which is _not_ the same as ``hg commit
        --addremove``) however ``hg remove --after`` is _very_ verbose (it
        comments on every existing file in the repository) and it ignores the
        ``--quiet`` option. This explains why I've decided to silence the
        standard error stream (though I feel I may regret this later).
        """
        tokens = ['hg remove --after 2>/dev/null; hg commit']
        if author:
            tokens.append('--user=%s' % quote(author.combined))
        tokens.append('--message=%s' % quote(message))
        return [' '.join(tokens)]

    def get_create_branch_command(self, branch_name):
        """Get the command to create a new branch based on the working tree's revision."""
        return ['hg', 'branch', branch_name]

    def get_create_tag_command(self, tag_name):
        """Get the command to create a new tag based on the working tree's revision."""
        return ['hg', 'tag', tag_name]

    def get_create_command(self):
        """Get the command to create the local repository."""
        command = ['hg', 'clone' if self.remote else 'init']
        if self.bare and self.remote:
            command.append('--noupdate')
        if self.remote:
            command.append(self.remote)
        command.append(self.local)
        return command

    def get_delete_branch_command(self, branch_name, message, author):
        """Get the command to delete or close a branch in the local repository."""
        tokens = ['hg update --rev=%s && hg commit' % quote(branch_name)]
        if author:
            tokens.append('--user=%s' % quote(author.combined))
        tokens.append('--message=%s' % quote(message))
        tokens.append('--close-branch')
        return [' '.join(tokens)]

    def get_export_command(self, directory, revision):
        """Get the command to export the complete tree from the local repository."""
        return ['hg', 'archive', '--rev=%s' % revision, directory]

    def get_merge_command(self, revision):
        """Get the command to merge a revision into the current branch (without committing the result)."""
        return ['hg', '--config', 'ui.merge=internal:merge', 'merge', '--rev=%s' % revision]

    def get_pull_command(self, remote=None, revision=None):
        """Get the command to pull changes from a remote repository into the local repository."""
        command = ['hg', 'pull']
        if remote:
            command.append(remote)
        if revision:
            command.append('--rev=%s' % revision)
        return command

    def get_push_command(self, remote=None, revision=None):
        """Get the command to push changes from the local repository to a remote repository."""
        command = ['hg', 'push', '--new-branch']
        if revision:
            command.append('--rev=%s' % revision)
        if remote:
            command.append(remote)
        return command

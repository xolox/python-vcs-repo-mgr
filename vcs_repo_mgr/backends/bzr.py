# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 5, 2018
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""Support for Bazaar version control repositories."""

# Standard library modules.
import logging
import os

# External dependencies.
from humanfriendly.text import compact, is_empty_line
from property_manager import required_property

# Modules included in our package.
from vcs_repo_mgr import Remote, Repository, Revision, coerce_author

# Public identifiers that require documentation.
__all__ = (
    'BzrRepo',
)

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


class BzrRepo(Repository):

    """Manage Bazaar version control repositories."""

    ALIASES = ['bzr', 'bazaar']

    # Class methods.

    @classmethod
    def contains_repository(cls, context, directory):
        """Check whether the given directory contains a local repository."""
        directory = cls.get_vcs_directory(context, directory)
        return context.is_file(os.path.join(directory, 'branch-format'))

    @staticmethod
    def get_vcs_directory(context, directory):
        """Get the pathname of the directory containing the version control metadata files."""
        return os.path.join(directory, '.bzr')

    # Instance properties.

    @required_property
    def control_field(self):
        """The name of the Debian control file field for Bazaar repositories (the string 'Vcs-Bzr')."""
        return 'Vcs-Bzr'

    @required_property
    def default_revision(self):
        """The default revision for Bazaar repositories (the string 'last:1')."""
        return 'last:1'

    @property
    def friendly_name(self):
        """A user friendly name for the version control system (the string 'Bazaar')."""
        return "Bazaar"

    @property
    def is_bare(self):
        """
        :data:`True` if the repository has no working tree, :data:`False` if it does.

        The value of this property is computed by checking whether the
        ``.bzr/checkout`` directory exists (it doesn't exist in Bazaar
        repositories created using ``bzr branch --no-tree ...``).
        """
        # Make sure the local repository exists.
        self.create()
        # Check the existence of the directory.
        checkout_directory = os.path.join(self.vcs_directory, 'checkout')
        return not self.context.is_directory(checkout_directory)

    @property
    def is_clean(self):
        """:data:`True` if the working tree is clean, :data:`False` otherwise."""
        # Make sure the local repository exists.
        self.create()
        # Check whether the `bzr diff' output is empty.
        listing = self.context.capture('bzr', 'diff', check=False)
        return len(listing.splitlines()) == 0

    @property
    def known_remotes(self):
        """The names of the configured remote repositories (a list of :class:`.Remote` objects)."""
        objects = []
        output = self.context.capture(
            'bzr', 'config', 'parent_location',
            check=False, silent=True,
        )
        if output and not output.isspace():
            location = output.strip()
            # The `bzr branch' command has the unusual habit of converting
            # absolute pathnames into relative pathnames. Although I get why
            # this can be preferred over the use of absolute pathnames I
            # nevertheless want vcs-repo-mgr to communicate to its callers as
            # unambiguously as possible, so if we detect a relative pathname
            # we convert it to an absolute pathname.
            if location.startswith('../'):
                location = os.path.normpath(os.path.join(self.local, location))
            objects.append(Remote(
                default=True,
                location=location,
                repository=self,
                roles=['push', 'pull'],
            ))
        return objects

    @property
    def supports_working_tree(self):
        """The opposite of :attr:`bare` (a boolean)."""
        return not self.is_bare

    # Instance methods.

    def find_author(self):
        """Get the author information from the version control system."""
        return coerce_author(self.context.capture('bzr', 'whoami'))

    def find_branches(self):
        """
        Find information about the branches in the repository.

        Bazaar repository support doesn't support branches so this method logs
        a warning message and returns an empty list. Consider using tags
        instead.
        """
        logger.warning("Bazaar repository support doesn't include branches (consider using tags instead).")
        return []

    def find_revision_id(self, revision=None):
        """Find the global revision id of the given revision."""
        # Make sure the local repository exists.
        self.create()
        # Try to find the revision id of the specified revision.
        revision = revision or self.default_revision
        output = self.context.capture(
            'bzr', 'version-info', '--revision=%s' % revision,
            '--custom', '--template={revision_id}',
        )
        # Validate the `bzr version-info' output.
        if not output:
            msg = "Failed to find global revision id! ('bzr version-info' gave unexpected output)"
            raise ValueError(msg)
        return output

    def find_revision_number(self, revision=None):
        """
        Find the local revision number of the given revision.

        .. note:: Bazaar has the concept of dotted revision numbers:

                   For revisions which have been merged into a branch, a dotted
                   notation is used (e.g., 3112.1.5). Dotted revision numbers
                   have three numbers. The first number indicates what mainline
                   revision change is derived from. The second number is the
                   branch counter. There can be many branches derived from the
                   same revision, so they all get a unique number. The third
                   number is the number of revisions since the branch started.
                   For example, 3112.1.5 is the first branch from revision
                   3112, the fifth revision on that branch.

                   (From http://doc.bazaar.canonical.com/bzr.2.6/en/user-guide/zen.html#understanding-revision-numbers)

                  However we really just want to give a bare integer to our
                  callers. It doesn't have to be globally accurate, but it
                  should increase as new commits are made. Below is the
                  equivalent of the git implementation for Bazaar.
        """
        # Make sure the local repository exists.
        self.create()
        # Try to find the revision number of the specified revision.
        revision = revision or self.default_revision
        output = self.context.capture('bzr', 'log', '--revision=..%s' % revision, '--line')
        revision_number = len([line for line in output.splitlines() if not is_empty_line(line)])
        if not (revision_number > 0):
            msg = "Failed to find local revision number! ('bzr log --line' gave unexpected output)"
            raise EnvironmentError(msg)
        return revision_number

    def find_tags(self):
        """
        Find information about the tags in the repository.

        .. note:: The ``bzr tags`` command reports tags pointing to
                  non-existing revisions as ``?`` but doesn't provide revision
                  ids. We can get the revision ids using the ``bzr tags
                  --show-ids`` command but this command doesn't mark tags
                  pointing to non-existing revisions. We combine the output of
                  both because we want all the information.
        """
        valid_tags = []
        listing = self.context.capture('bzr', 'tags')
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) == 2 and tokens[1] != '?':
                valid_tags.append(tokens[0])
        listing = self.context.capture('bzr', 'tags', '--show-ids')
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) == 2 and tokens[0] in valid_tags:
                tag, revision_id = tokens
                yield Revision(
                    repository=self,
                    revision_id=tokens[1],
                    tag=tokens[0],
                )

    def get_add_files_command(self, *filenames):
        """Get the command to include added and/or removed files in the working tree in the next commit."""
        command = ['bzr', 'add']
        command.extend(filenames)
        return command

    def get_commit_command(self, message, author=None):
        """Get the command to commit changes to tracked files in the working tree."""
        command = ['bzr', 'commit']
        if author:
            command.extend(('--author', author.combined))
        command.append('--message')
        command.append(message)
        return command

    def get_create_command(self):
        """Get the command to create the local repository."""
        command = ['bzr', 'branch' if self.remote else 'init']
        if self.bare:
            command.append('--no-tree')
        if self.remote:
            command.append(self.remote)
        command.append(self.local)
        return command

    def get_create_tag_command(self, tag_name):
        """Get the command to create a new tag based on the working tree's revision."""
        return ['bzr', 'tag', tag_name]

    def get_export_command(self, directory, revision):
        """Get the command to export the complete tree from the local repository."""
        return ['bzr', 'export', '--revision=%s' % revision, directory]

    def get_pull_command(self, remote=None, revision=None):
        """Get the command to pull changes from a remote repository into the local repository."""
        if revision:
            raise NotImplementedError(compact("""
                Bazaar repository support doesn't include
                the ability to pull specific revisions!
            """))
        command = ['bzr', 'pull']
        if remote:
            command.append(remote)
        return command

    def get_push_command(self, remote=None, revision=None):
        """Get the command to push changes from the local repository to a remote repository."""
        if revision:
            raise NotImplementedError(compact("""
                Bazaar repository support doesn't include
                the ability to push specific revisions!
            """))
        command = ['bzr', 'push']
        if remote:
            command.append(remote)
        return command

    def update_context(self):
        """
        Make sure Bazaar respects the configured author.

        This method first calls :func:`.Repository.update_context()` and then
        it sets the ``$BZR_EMAIL`` environment variable based on the value of
        :attr:`~Repository.author` (but only if :attr:`~Repository.author` was
        set by the caller).

        This is a workaround for a weird behavior of Bazaar that I've observed
        when running under Python 2.6: The ``bzr commit --author`` command line
        option is documented but it doesn't prevent Bazaar from nevertheless
        reporting the following error::

         bzr: ERROR: Unable to determine your name.
         Please, set your name with the 'whoami' command.
         E.g. bzr whoami "Your Name <name@example.com>"
        """
        # Call our superclass.
        super(BzrRepo, self).update_context()
        # Try to ensure that $BZR_EMAIL is set (see above for the reason)
        # but only if the `author' property was set by the caller (more
        # specifically there's no point in setting $BZR_EMAIL to the
        # output of `bzr whoami').
        if self.__dict__.get('author'):
            environment = self.context.options.setdefault('environment', {})
            environment.setdefault('BZR_EMAIL', self.author.combined)

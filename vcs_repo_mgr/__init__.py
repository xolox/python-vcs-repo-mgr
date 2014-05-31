# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 31, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""
Here's how it works:

>>> from vcs_repo_mgr import GitRepo
>>> repo = GitRepo(local='/tmp/verboselogs.git', remote='git@github.com:xolox/python-verboselogs.git')
>>> repo.exists
False
>>> repo.create()
Cloning into bare repository '/tmp/verboselogs.git'...
remote: Reusing existing pack: 7, done.
remote: Total 7 (delta 0), reused 0 (delta 0)
Receiving objects: 100% (7/7), done.
>>> repo.exists
True
>>> repo.update()
From github.com:xolox/python-verboselogs
 * branch            HEAD       -> FETCH_HEAD
>>> repo.branches
{'master': Revision(repository=GitRepo(local='/tmp/verboselogs.git',
                                       remote='git@github.com:xolox/python-verboselogs.git'),
                    revision_id='f6b89e5',
                    branch='master')}

.. note:: This module handles subprocess management using the
          :py:func:`executor.execute()` function which means
          :py:exc:`executor.ExternalCommandFailed` can be
          raised at any point.
"""

# Semi-standard module versioning.
__version__ = '0.2.4'

# Standard library modules.
import functools
import logging
import os
import pipes
import re

try:
    # Python 2.x.
    import ConfigParser as configparser
except ImportError:
    # Python 3.x.
    import configparser

# External dependencies.
from executor import execute
from humanfriendly import concatenate, format_path

# Known configuration file locations.
USER_CONFIG_FILE = os.path.expanduser('~/.vcs-repo-mgr.ini')
SYSTEM_CONFIG_FILE = '/etc/vcs-repo-mgr.ini'

# Initialize a logger.
logger = logging.getLogger(__name__)

# Inject our logger into all execute() calls.
execute = functools.partial(execute, logger=logger)

def find_configured_repository(name):
    """
    Find a version control repository defined by the user in one of the
    following configuration files:

    1. ``/etc/vcs-repo-mgr.ini``
    2. ``~/.vcs-repo-mgr.ini``

    Repositories defined in the second file override repositories defined in
    the first. Here is an example of a repository definition:

    .. code-block:: ini

       [vcs-repo-mgr]
       type = git
       local = /home/peter/projects/vcs-repo-mgr
       remote = git@github.com:xolox/python-vcs-repo-mgr.git

    Two VCS types are currently supported: ``hg`` (``mercurial`` is also
    accepted) and ``git``. If an unsupported VCS type is used or no repository
    can be found matching the given name :py:exc:`exceptions.ValueError` is
    raised.

    :param name: The name of the repository (a string).
    :returns: A :py:class:`Repository` object.
    """
    parser = configparser.RawConfigParser()
    for config_file in [SYSTEM_CONFIG_FILE, USER_CONFIG_FILE]:
        if os.path.isfile(config_file):
            logger.debug("Loading configuration file: %s", format_path(config_file))
            parser.read(config_file)
    matching_repos = [r for r in parser.sections() if normalize_name(name) == normalize_name(r)]
    if not matching_repos:
        msg = "No repositories found matching the name %r!"
        raise ValueError(msg % name)
    elif len(matching_repos) != 1:
        msg = "Multiple repositories found matching the name %r! (%s)"
        raise ValueError(msg % (name, concatenate(map(repr, matching_repos))))
    else:
        options = dict(parser.items(matching_repos[0]))
        vcs_type = options.get('type', '').lower()
        if vcs_type in ('hg', 'mercurial'):
            return HgRepo(local=options.get('local'), remote=options.get('remote'))
        elif vcs_type == 'git':
            return GitRepo(local=options.get('local'), remote=options.get('remote'))
        else:
            raise ValueError("VCS type not supported! (%s)" % vcs_type)

def normalize_name(name):
    """
    Normalize a repository name so that minor variations in character case
    and/or punctuation don't disrupt the name matching in
    :py:func:`find_configured_repository()`.

    :param name: The name of a repository (a string).
    :returns: The normalized repository name (a string).
    """
    return re.sub('[^a-z0-9]', '', name.lower())

class Repository(object):

    """
    Base class for version control repository interfaces. Don't use this
    directly, use :py:class:`HgRepo` and/or :py:class:`GitRepo` instead.
    """

    def __init__(self, local=None, remote=None):
        """
        Initialize a version control repository interface. Raises
        :py:exc:`exceptions.ValueError` if the local repository doesn't exist
        and no remote repository is specified.

        :param local: The pathname of the directory where the local clone of
                      the repository is stored (a string). This directory
                      doesn't have to exist, but in that case ``remote`` must
                      be given.
        :param remote: The URL of the remote repository (a string). If this is
                       not given then the local directory must already exist
                       and contain a supported repository.
        """
        self.local = local
        self.remote = remote
        if not (self.exists or self.remote):
            msg = "Local repository (%r) doesn't exist and no remote repository specified!"
            raise ValueError(msg % self.local)

    @property
    def exists(self):
        """
        Check if the local directory contains a supported version control repository.

        :returns: ``True`` if the local directory contains a repository, ``False`` otherwise.
        """
        raise NotImplemented()

    def create(self):
        """
        Create the local clone of the remote version control repository, if it
        doesn't already exist.

        :returns: ``True`` if the repository was just created, ``False`` if it
                  already existed.
        """
        if self.exists:
            return False
        else:
            logger.info("Creating %s clone of %s at %s ..",
                        self.friendly_name, self.remote, self.local)
            execute(self.create_command.format(local=pipes.quote(self.local),
                                               remote=pipes.quote(self.remote)))
            return True

    def update(self):
        """
        Update the local clone of the remote version control repository.

        .. note:: Automatically creates the local repository on the first run.
        """
        if self.remote and not self.create():
            logger.info("Updating %s clone of %s at %s ..",
                        self.friendly_name, self.remote, self.local)
            execute(self.update_command.format(local=pipes.quote(self.local),
                                               remote=pipes.quote(self.remote)))

    def export(self, directory, revision=None):
        """
        Export the complete tree (at the specified revision) from the local
        version control repository.

        :param directory: The directory where the tree should be exported (a
                          string).
        :param revision: The revision to export (a string). Defaults to the
                         latest revision in the default branch.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        revision = revision or self.default_revision
        logger.info("Exporting revision %s of %s to %s ..", revision, self.local, directory)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        execute(self.export_command.format(local=pipes.quote(self.local),
                                           revision=pipes.quote(revision),
                                           directory=pipes.quote(directory)))

    def find_revision_number(self, revision=None):
        """
        Find the local revision number of the given revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string). Defaults to the latest revision in
                         the default branch.
        :returns: The local revision number (an integer).

        .. note:: Automatically creates the local repository on the first run.
        """
        raise NotImplemented()

    def find_revision_id(self, revision):
        """
        Find the global revision id of the given revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string). Defaults to the latest revision in
                         the default branch.
        :returns: The global revision id (a hexadecimal string).

        .. note:: Automatically creates the local repository on the first run.
        """
        raise NotImplemented()

    @property
    def branches(self):
        """
        Find information about the branches in the version control repository.

        :returns: A :py:class:`dict` with branch names (strings) as keys and
                  :py:class:`Revision` objects as values.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        mapping = {}
        for revision in self.find_branches():
            mapping[revision.branch] = revision
        return mapping

    def __repr__(self):
        fields = []
        if self.local:
            fields.append("local=%r" % self.local)
        if self.remote:
            fields.append("remote=%r" % self.remote)
        return "%s(%s)" % (self.__class__.__name__, ', '.join(fields))

class Revision(object):

    """
    :py:class:`Revision` objects represent a specific revision in a
    :py:class:`Repository`. The following fields are available:

    :ivar repository: The :py:class:`Repository` object of the
          version control repository containing the revision.

    :ivar revision_id: A string containing a global revision id (a hexadecimal
          hash) comparable between local and remote repositories. Useful to
          unambiguously refer to a revision and its history. This field is
          always available.

    :ivar revision_number: A local revision number (an incrementing
          integer). Useful as a build number or when a simple, incrementing
          version number is required. Should not be used to unambiguously refer
          to a revision. If not available this will be ``None``.

    :ivar branch: The name of the branch in which the revision exists (a
          string). If not available this will be ``None``.
    """

    def __init__(self, repository, revision_id, revision_number=None, branch=None):
        """
        Create a :py:class:`Revision` object.

        :param repository: A :py:class:`Repository` object.
        :param revision_id: A string containing a hexadecimal hash.
        :param revision_number: The revision number (an integer, optional).
        :param branch: The name of the branch (a string, optional).
        """
        self.repository = repository
        self.revision_id = revision_id
        self._revision_number = revision_number
        self.branch = branch

    @property
    def revision_number(self):
        if self._revision_number is None:
            self._revision_number = self.repository.find_revision_number(self.revision_id)
        return self._revision_number

    def __repr__(self):
        fields = ["repository=%r" % self.repository,
                  "revision_id=%r" % self.revision_id]
        if self.branch:
            fields.append("branch=%r" % self.branch)
        if self._revision_number is not None:
            fields.append("revision_number=%r" % self._revision_number)
        return "%s(%s)" % (self.__class__.__name__, ', '.join(fields))

class HgRepo(Repository):

    """
    Version control repository interface for Mercurial_ repositories.

    .. _Mercurial: http://mercurial.selenic.com/
    """

    friendly_name = 'Mercurial'
    default_revision = 'default'
    create_command = 'hg clone --noupdate {remote} {local}'
    update_command = 'hg pull --repository {local} {remote}'
    export_command = 'hg archive --repository {local} --rev {revision} {directory}'

    @property
    def exists(self):
        return os.path.isdir(os.path.join(self.local, '.hg'))

    def find_revision_number(self, revision=None):
        self.create()
        revision = revision or self.default_revision
        result = execute('hg', '--repository', self.local, 'id', '--rev', revision, '--num', capture=True).rstrip('+')
        assert result and result.isdigit(), "Failed to find local revision number! ('hg id --num' gave unexpected output)"
        return int(result)

    def find_revision_id(self, revision=None):
        self.create()
        revision = revision or self.default_revision
        result = execute('hg', '--repository', self.local, 'id', '--rev', revision, '--debug', '--id', capture=True).rstrip('+')
        assert re.match('^[A-Fa-z0-9]+$', result), "Failed to find global revision id! ('hg id --id' gave unexpected output)"
        return result

    def find_branches(self):
        listing = execute('hg', '--repository', self.local, 'branches', capture=True)
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) >= 2:
                revision_number, revision_id = tokens[1].split(':')
                yield Revision(repository=self,
                               revision_id=revision_id,
                               revision_number=int(revision_number),
                               branch=tokens[0])

class GitRepo(Repository):

    """
    Version control repository interface for Git_ repositories.

    .. _Git: http://git-scm.com/
    """

    friendly_name = 'Git'
    default_revision = 'master'
    create_command = 'git clone --bare {remote} {local}'
    update_command = 'cd {local} && git fetch {remote}'
    export_command = 'cd {local} && git archive {revision} | tar --extract --directory={directory}'

    @property
    def exists(self):
        return (os.path.isdir(os.path.join(self.local, '.git')) or
                os.path.isfile(os.path.join(self.local, 'config')))

    def find_revision_number(self, revision=None):
        self.create()
        revision = revision or self.default_revision
        result = execute('git', 'rev-list', revision, '--count', capture=True, directory=self.local)
        assert result and result.isdigit(), "Failed to find local revision number! ('git rev-list --count' gave unexpected output)"
        return int(result)

    def find_revision_id(self, revision=None):
        self.create()
        revision = revision or self.default_revision
        result = execute('git', 'rev-parse', revision, capture=True, directory=self.local)
        assert re.match('^[A-Fa-z0-9]+$', result), "Failed to find global revision id! ('git rev-parse' gave unexpected output)"
        return result

    def find_branches(self):
        listing = execute('git', 'branch', '--list', '--verbose', capture=True, directory=self.local)
        for line in listing.splitlines():
            line = line.lstrip('*').strip()
            if not line.startswith('(no branch)'):
                tokens = line.split()
                if len(tokens) >= 2:
                    yield Revision(repository=self,
                                   revision_id=tokens[1],
                                   branch=tokens[0])

# vim: ts=4 sw=4 et

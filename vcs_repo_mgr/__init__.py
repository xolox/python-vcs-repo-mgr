# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 8, 2015
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
__version__ = '0.13'

# Standard library modules.
import functools
import logging
import operator
import os
import pipes
import re
import tempfile
import time

# External dependencies.
from executor import execute
from humanfriendly import concatenate, format_path
from natsort import natsort, natsort_key
from six import string_types
from six.moves import configparser
from six.moves import urllib_parse as urlparse

# Known configuration file locations.
USER_CONFIG_FILE = os.path.expanduser('~/.vcs-repo-mgr.ini')
SYSTEM_CONFIG_FILE = '/etc/vcs-repo-mgr.ini'

# Environment variable used to rate limit repository updates.
UPDATE_VARIABLE = 'VCS_REPO_MGR_UPDATE_LIMIT'

# Initialize a logger.
logger = logging.getLogger(__name__)

# Inject our logger into all execute() calls.
execute = functools.partial(execute, logger=logger)

# Dictionary of previously constructed Repository objects.
loaded_repositories = {}

def coerce_repository(value):
    """
    Convert a string (taken to be a repository name or URL) to a
    :py:class:`Repository` object.

    :param value: The name or URL of a repository (a string or a
                  :py:class:`Repository` object).
    :returns: A :py:class:`Repository` object.
    :raises: :py:exc:`exceptions.ValueError` when the given ``value`` is not a
             string or a :py:class:`Repository` object or if the value is a string but
             doesn't match the name of any configured repository and also can't
             be parsed as the location of a remote repository.
    """
    # Repository objects pass through untouched.
    if isinstance(value, Repository):
        return value
    # We expect a string with a name or URL.
    if not isinstance(value, string_types):
        msg = "Expected string or Repository object as argument, got %s instead!"
        raise ValueError(msg % type(value))
    # If the string matches the name of a configured repository we'll return that.
    try:
        return find_configured_repository(value)
    except NoSuchRepositoryError:
        pass
    # At this point we'll assume the string is the location of a remote
    # repository. First lets see if the repository type is prefixed to the
    # remote location with a `+' in between (pragmatic but ugly :-).
    vcs_type, _, remote = value.partition('+')
    if vcs_type and remote:
        try:
            return repository_factory(vcs_type, remote=remote)
        except UnknownRepositoryTypeError:
            pass
    # Check for remote locations that end with the suffix `.git' (fairly common).
    if value.endswith('.git'):
        return repository_factory('git', remote=value)
    # If all else fails, at least give a clear explanation of the problem.
    msg = ("The string %r doesn't match the name of any configured repository"
           " and it also can't be parsed as the location of a remote"
           " repository! (maybe you forgot to prefix the type?)")
    raise ValueError(msg % value)

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
       release-scheme = tags
       release-filter = .*

    Three VCS types are currently supported: ``hg`` (``mercurial`` is also
    accepted), ``git`` and ``bzr`` (``bazaar`` is also accepted). If an
    unsupported VCS type is used or no repository can be found matching the
    given name :py:exc:`exceptions.ValueError` is raised.

    :param name: The name of the repository (a string).
    :returns: A :py:class:`Repository` object.
    :raises: :py:exc:`NoSuchRepositoryError` when the given repository name
             doesn't match any of the configured repositories.
    :raises: :py:exc:`AmbiguousRepositoryNameError` when the given repository
             name is ambiguous (i.e. it matches multiple repository names).
    :raises: :py:exc:`UnknownRepositoryTypeError` when a repository definition
             with an unknown type is encountered.
    """
    parser = configparser.RawConfigParser()
    for config_file in [SYSTEM_CONFIG_FILE, USER_CONFIG_FILE]:
        if os.path.isfile(config_file):
            logger.debug("Loading configuration file: %s", format_path(config_file))
            parser.read(config_file)
    matching_repos = [r for r in parser.sections() if normalize_name(name) == normalize_name(r)]
    if not matching_repos:
        msg = "No repositories found matching the name %r!"
        raise NoSuchRepositoryError(msg % name)
    elif len(matching_repos) != 1:
        msg = "Multiple repositories found matching the name %r! (%s)"
        raise AmbiguousRepositoryNameError(msg % (name, concatenate(map(repr, matching_repos))))
    else:
        options = dict(parser.items(matching_repos[0]))
        vcs_type = options.get('type', '').lower()
        return repository_factory(vcs_type,
                                  local=options.get('local'),
                                  remote=options.get('remote'),
                                  release_scheme=options.get('release-scheme'),
                                  release_filter=options.get('release-filter'))

def repository_factory(vcs_type, **kw):
    """
    Instantiate a :py:class:`Repository` object based on the given type and arguments.

    :param vcs_type: One of the strings 'bazaar', 'bzr', 'git', 'hg' or 'mercurial'.
    :param kw: The keyword arguments to :py:func:`Repository.__init__()`.
    :returns: A :py:class:`Repository` object.
    :raises: :py:exc:`UnknownRepositoryTypeError` when the given type is unknown.
    """
    # Resolve the VCS type string to a Repository subclass.
    vcs_type = vcs_type.lower()
    if vcs_type in ('bzr', 'bazaar'):
        constructor = BzrRepo
    elif vcs_type == 'git':
        constructor = GitRepo
    elif vcs_type in ('hg', 'mercurial'):
        constructor = HgRepo
    else:
        raise UnknownRepositoryTypeError("Unknown VCS repository type! (%r)" % vcs_type)
    # Generate a cache key that we will use to avoid constructing duplicates.
    cache_key = tuple('%s=%s' % (k, v) for k, v in sorted(kw.items()))
    logger.debug("Generated repository cache key: %r", cache_key)
    if cache_key in loaded_repositories:
        logger.debug("Repository previously constructed, returning cached instance ..")
    else:
        logger.debug("Repository not yet constructed, creating new instance ..")
        loaded_repositories[cache_key] = constructor(**kw)
    return loaded_repositories[cache_key]

def find_cache_directory(remote):
    """
    Find the directory where temporary local checkouts are to be stored.

    :returns: The absolute pathname of a directory (a string).
    """
    return os.path.join('/var/cache/vcs-repo-mgr' if os.access('/var/cache', os.W_OK) else tempfile.gettempdir(),
                        urlparse.quote(remote, safe=''))

def normalize_name(name):
    """
    Normalize a repository name so that minor variations in character case
    and/or punctuation don't disrupt the name matching in
    :py:func:`find_configured_repository()`.

    :param name: The name of a repository (a string).
    :returns: The normalized repository name (a string).
    """
    return re.sub('[^a-z0-9]', '', name.lower())

def sum_revision_numbers(arguments):
    """
    Sum revision numbers of multiple repository/revision pairs. This is useful
    when you're building a package based on revisions from multiple VCS
    repositories. By taking changes in all repositories into account when
    generating version numbers you can make sure that your version number is
    bumped with every single change.

    :param arguments: A list of strings with repository names and revision
                      strings.
    :returns: A single integer containing the summed revision numbers.
    """
    if len(arguments) % 2 != 0:
        raise ValueError("Please provide an even number of arguments! (one or more repository/revision pairs)")
    summed_revision_number = 0
    while arguments:
        repository = coerce_repository(arguments.pop(0))
        summed_revision_number += repository.find_revision_number(arguments.pop(0))
    return summed_revision_number

class limit_vcs_updates(object):

    """
    Avoid duplicate repository updates.

    This context manager uses an environment variable to ensure that each
    configured repository isn't updated more than once by the current process
    and/or subprocesses.
    """

    def __enter__(self):
        self.old_value = os.environ.get(UPDATE_VARIABLE)
        os.environ[UPDATE_VARIABLE] = '%i' % time.time()

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        if self.old_value is not None:
            os.environ[UPDATE_VARIABLE] = self.old_value
        elif UPDATE_VARIABLE in os.environ:
            del os.environ[UPDATE_VARIABLE]

class Repository(object):

    """
    Base class for version control repository interfaces. Don't use this
    directly, use :py:class:`HgRepo` and/or :py:class:`GitRepo` instead.
    """

    def __init__(self, local=None, remote=None, release_scheme=None, release_filter=None):
        """
        Initialize a version control repository interface.

        :param local: The pathname of the directory where the local clone of
                      the repository is stored (a string). If ``remote`` is not
                      given this argument is required. If ``remote`` is given:

                      - The ``local`` argument can be omitted. In this case a
                        temporary directory with a stable location will be
                        selected using :py:func:`find_cache_directory()`.
                      - A non-existing local directory can be given, this
                        directory will be created by cloning the remote
                        repository.
        :param remote: The URL of the remote repository (a string). If this is
                       not given then the local directory must already exist
                       and contain a supported repository.
        :param release_scheme: One of the strings 'tags' (the default) or
                               'branches'. This determines whether
                               :py:attr:`Repository.releases` is based on
                               :py:attr:`Repository.tags` or
                               :py:attr:`Repository.branches`.
        :param release_filter: A string containing a regular expression or the
                               result of :py:func:`re.compile()`. The regular
                               expression is used by
                               :py:attr:`Repository.releases` to match tags or
                               branches that signify "releases". If the regular
                               expression contains a single capture group, the
                               identifier of a :py:class:`Release` object is
                               set to the substring captured by the capture
                               group (instead of the complete tag or branch
                               name). This defaults to the regular expression
                               ``.*`` matching any branch or tag name.
        :raises: :py:exc:`exceptions.ValueError` for any of the following:

                 - Neither the local repository directory nor the remote
                   repository location is specified.
                 - The local repository directory doesn't exist and no remote
                   repository location is specified.
                 - The given release scheme is not 'tags' or 'branches'.
                 - The release filter regular expression contains more than one
                   capture group (if you need additional groups but without the
                   capturing aspect use a non-capturing group).
        """
        self.local = local
        self.remote = remote
        self.release_scheme = release_scheme or 'tags'
        self.release_filter = release_filter or '.*'
        # Make sure the caller specified at least the local *or* remote.
        if not (self.local or self.remote):
            raise ValueError("No local and no remote repository specified! (one of the two is required)")
        # If the caller specified a remote repository but no local clone we
        # assume they don't care about the location of the local clone so we
        # can make something up (i.e. vcs-repo-mgr will act as an exclusive
        # proxy to the local clone).
        if self.remote and not self.local:
            self.local = find_cache_directory(self.remote)
        # Make sure we know how to get access to (a copy of) the repository.
        if not (self.exists or self.remote):
            msg = "Local repository (%r) doesn't exist and no remote repository specified!"
            raise ValueError(msg % self.local)
        # Make sure the release scheme was properly specified.
        known_release_schemes = ('branches', 'tags')
        if self.release_scheme not in known_release_schemes:
            msg = "Release scheme %r is not supported! (valid options are %s)"
            raise ValueError(msg % (self.release_scheme, concatenate(map(repr, known_release_schemes))))
        # Make sure the release filter is a valid regular expression. This code
        # is written so that callers can pass in their own compiled regular
        # expression if they want to do that.
        if isinstance(self.release_filter, string_types):
            self.release_filter = re.compile(self.release_filter)
        # At this point we should be dealing with a regular expression object:
        # Make sure the regular expression has zero or one capture group.
        if self.release_filter.groups > 1:
            msg = "Release filter regular expression pattern is expected to have zero or one capture group, but it has %i instead!"
            raise ValueError(msg % self.release_filter.groups)

    @property
    def vcs_directory(self):
        """
        Find the "dot" directory containing the VCS files.

        :returns: The pathname of a directory (a string).
        """
        raise NotImplementedError()

    @property
    def exists(self):
        """
        Check if the local directory contains a supported version control repository.

        :returns: ``True`` if the local directory contains a repository, ``False`` otherwise.
        """
        raise NotImplementedError()

    @property
    def last_updated_file(self):
        """
        The pathname of the file used to mark the last successful update (a string).
        """
        return os.path.join(self.vcs_directory, 'vcs-repo-mgr.txt')

    @property
    def last_updated(self):
        """
        Find the date and time when `vcs-repo-mgr` last checked for updates.

        :returns: The number of seconds since the UNIX epoch (0 for remote
                  repositories that don't have a local clone yet).
        """
        try:
            with open(self.last_updated_file) as handle:
                return int(handle.read())
        except Exception:
            return 0

    def mark_updated(self):
        """
        Mark a successful repository update so that :py:attr:`last_updated` can report it.
        """
        with open(self.last_updated_file, 'w') as handle:
            handle.write('%i\n' % time.time())

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
            self.mark_updated()
            return True

    def update(self):
        """
        Update the local clone of the remote version control repository.

        .. note:: Automatically creates the local repository on the first run.
        """
        if not self.remote:
            # If there is no remote configured, there's nothing we can do!
            return
        if self.create():
            # If the local clone didn't exist yet and we just created it,
            # we can skip the update (since there's no point).
            return
        global_last_update = int(os.environ.get(UPDATE_VARIABLE, '0'))
        if global_last_update and self.last_updated >= global_last_update:
            # If an update limit has been enforced we also skip the update.
            return
        logger.info("Updating %s clone of %s at %s ..",
                    self.friendly_name, self.remote, self.local)
        execute(self.update_command.format(local=pipes.quote(self.local),
                                           remote=pipes.quote(self.remote)))
        self.mark_updated()

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
        raise NotImplementedError()

    def find_revision_id(self, revision=None):
        """
        Find the global revision id of the given revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string). Defaults to the latest revision in
                         the default branch.
        :returns: The global revision id (a hexadecimal string).

        .. note:: Automatically creates the local repository on the first run.
        """
        raise NotImplementedError()

    def generate_control_field(self, revision=None):
        """
        Generate a Debian control file name/value pair for the given repository
        and revision. This generates a ``Vcs-Bzr`` field for Bazaar_
        repositories, a ``Vcs-Hg`` field for Mercurial_ repositories and a
        ``Vcs-Git`` field for Git_ repositories.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string). Defaults to the latest revision in
                         the default branch.
        :returns: A tuple with two strings: The name of the field and the value.
        """
        value = "%s#%s" % (self.remote or self.local, self.find_revision_id(revision))
        return self.control_field, value

    @property
    def branches(self):
        """
        Find information about the branches in the version control repository.

        :returns: A :py:class:`dict` with branch names (strings) as keys and
                  :py:class:`Revision` objects as values.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        return dict((r.branch, r) for r in self.find_branches())

    @property
    def ordered_branches(self):
        """
        Find information about the branches in the version control repository.

        :returns: An ordered :py:class:`list` of :py:class:`Revision` objects.
                  The list is ordered by performing a `natural order sort
                  <https://pypi.python.org/pypi/naturalsort>`_ of branch names
                  in ascending order (i.e. the first value is the "oldest"
                  branch and the last value is the "newest" branch).

        .. note:: Automatically creates the local repository on the first run.
        """
        return natsort(self.branches.values(), key=operator.attrgetter('branch'))

    @property
    def tags(self):
        """
        Find information about the tags in the version control repository.

        :returns: A :py:class:`dict` with tag names (strings) as keys and
                  :py:class:`Revision` objects as values.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        return dict((r.tag, r) for r in self.find_tags())

    @property
    def ordered_tags(self):
        """
        Find information about the tags in the version control repository.

        :returns: An ordered :py:class:`list` of :py:class:`Revision` objects.
                  The list is ordered by performing a `natural order sort
                  <https://pypi.python.org/pypi/naturalsort>`_ of tag names
                  in ascending order (i.e. the first value is the "oldest"
                  tag and the last value is the "newest" tag).

        .. note:: Automatically creates the local repository on the first run.
        """
        return natsort(self.tags.values(), key=operator.attrgetter('tag'))

    @property
    def releases(self):
        """
        Find information about the releases in the version control repository.

        :returns: A :py:class:`dict` with release identifiers (strings) as keys
                  and :py:class:`Release` objects as values.

        .. note:: Automatically creates the local repository on the first run.

        Here's a simple example based on the public git repository of the
        vcs-repo-mgr project:

        >>> from vcs_repo_mgr import coerce_repository
        >>> from pprint import pprint
        >>> repository = coerce_repository('https://github.com/xolox/python-vcs-repo-mgr.git')
        >>> pprint(repository.releases)
        {'0.1':   Release(revision=Revision(...), identifier='0.1'  ),
         '0.1.1': Release(revision=Revision(...), identifier='0.1.1'),
         '0.1.2': Release(revision=Revision(...), identifier='0.1.2'),
         '0.1.3': Release(revision=Revision(...), identifier='0.1.3'),
         '0.1.4': Release(revision=Revision(...), identifier='0.1.4'),
         '0.1.5': Release(revision=Revision(...), identifier='0.1.5'),
         '0.2':   Release(revision=Revision(...), identifier='0.2'  ),
         '0.2.1': Release(revision=Revision(...), identifier='0.2.1'),
         '0.2.2': Release(revision=Revision(...), identifier='0.2.2'),
         '0.2.3': Release(revision=Revision(...), identifier='0.2.3'),
         '0.2.4': Release(revision=Revision(...), identifier='0.2.4'),
         '0.3':   Release(revision=Revision(...), identifier='0.3'  ),
         '0.3.1': Release(revision=Revision(...), identifier='0.3.1'),
         '0.3.2': Release(revision=Revision(...), identifier='0.3.2'),
         '0.4':   Release(revision=Revision(...), identifier='0.4'  ),
         '0.5':   Release(revision=Revision(...), identifier='0.5'  ),
         '0.6':   Release(revision=Revision(...), identifier='0.6'  ),
         '0.6.1': Release(revision=Revision(...), identifier='0.6.1'),
         '0.6.2': Release(revision=Revision(...), identifier='0.6.2'),
         '0.6.3': Release(revision=Revision(...), identifier='0.6.3'),
         '0.6.4': Release(revision=Revision(...), identifier='0.6.4'),
         '0.7':   Release(revision=Revision(...), identifier='0.7'  )}
        """
        available_releases = {}
        available_revisions = getattr(self, self.release_scheme)
        for identifier, revision in available_revisions.items():
            match = self.release_filter.match(identifier)
            if match:
                # If the regular expression contains a capturing group we
                # set the release identifier to the captured substring
                # instead of the complete tag/branch identifier.
                captures = match.groups()
                if captures:
                    identifier = captures[0]
                available_releases[identifier] = Release(revision=revision, identifier=identifier)
        return available_releases

    @property
    def ordered_releases(self):
        """
        Find information about the releases in the version control repository.

        :returns: An ordered :py:class:`list` of :py:class:`Release` objects.
                  The list is ordered by performing a `natural order sort
                  <https://pypi.python.org/pypi/naturalsort>`_ of release
                  identifiers in ascending order (i.e. the first value is the
                  "oldest" release and the last value is the newest
                  "release").

        .. note:: Automatically creates the local repository on the first run.
        """
        return natsort(self.releases.values(), key=operator.attrgetter('identifier'))

    def select_release(self, highest_allowed_release):
        """
        Select the newest release that is not newer than the given release.

        :param highest_allowed_release: The identifier of the release that sets
                                        the upper bound for the selection (a
                                        string).
        :returns: The identifier of the selected release (a string).
        :raises: :py:exc:`NoMatchingReleasesError` when no matching releases
                 are found.
        """
        matching_releases = []
        highest_allowed_key = natsort_key(highest_allowed_release)
        for release in self.ordered_releases:
            release_key = natsort_key(release.identifier)
            if release_key <= highest_allowed_key:
                matching_releases.append(release)
        if not matching_releases:
            msg = "No releases below or equal to %r found in repository!"
            raise NoMatchingReleasesError(msg % highest_allowed_release)
        return matching_releases[-1]

    def release_to_branch(self, release_id):
        """
        Shortcut to translate a release identifier to a branch name.

        :param release_id: A :py:attr:`Release.identifier` value (a string).
        :returns: A branch name (a string).
        :raises: :py:exc:`~exceptions.TypeError` when the repository is not
                 using branches as its release scheme.
        """
        if self.release_scheme != 'branches':
            raise TypeError("Repository isn't using 'branches' release scheme!")
        return self.releases[release_id].revision.branch

    def release_to_tag(self, release_id):
        """
        Shortcut to translate a release identifier to a tag name.

        :param release_id: A :py:attr:`Release.identifier` value (a string).
        :returns: A tag name (a string).
        :raises: :py:exc:`~exceptions.TypeError` when the repository is not
                 using tags as its release scheme.
        """
        if self.release_scheme != 'tags':
            raise TypeError("Repository isn't using 'tags' release scheme!")
        return self.releases[release_id].revision.tag

    def find_branches(self):
        """
        Find information about the branches in the version control repository.

        This is an internal method that is expected to be implemented by
        subclasses of :py:class:`Repository` and is used by
        :py:attr:`Repository.branches`.

        :returns: A generator of :py:class:`Revision` objects.
        """
        raise NotImplementedError()

    def find_tags(self):
        """
        Find information about the tags in the version control repository.

        This is an internal method that is expected to be implemented by
        subclasses of :py:class:`Repository` and is used by
        :py:attr:`Repository.tags`.

        :returns: A generator of :py:class:`Revision` objects.
        """
        raise NotImplementedError()

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

    :ivar tag: The name of the tag associated to the revision (a string). If
          not available this will be ``None``.
    """

    def __init__(self, repository, revision_id, revision_number=None, branch=None, tag=None):
        """
        Create a :py:class:`Revision` object.

        :param repository: A :py:class:`Repository` object.
        :param revision_id: A string containing a hexadecimal hash.
        :param revision_number: The revision number (an integer, optional).
        :param branch: The name of the branch (a string, optional).
        :param tag: The name of the tag (a string, optional).
        """
        self.repository = repository
        self.revision_id = revision_id
        self._revision_number = revision_number
        self.branch = branch
        self.tag = tag

    @property
    def revision_number(self):
        if self._revision_number is None:
            self._revision_number = self.repository.find_revision_number(self.revision_id)
        return self._revision_number

    def __repr__(self):
        fields = ["repository=%r" % self.repository]
        if self.branch:
            fields.append("branch=%r" % self.branch)
        if self.tag:
            fields.append("tag=%r" % self.tag)
        if self._revision_number is not None:
            fields.append("revision_number=%r" % self._revision_number)
        fields.append("revision_id=%r" % self.revision_id)
        return "%s(%s)" % (self.__class__.__name__, ', '.join(fields))

class Release(object):

    """
    Most version control repositories are used to store software projects and
    most software projects have the concept of "releases": *Specific versions
    of a software project that have been given a human and machine readable
    version number (in one form or another).* :py:class:`Release` objects exist
    to capture this concept in a form that is concrete enough to be generally
    useful while being abstract enough to be used in various ways (because
    every software project has its own scheme for releases).


    By default the :py:class:`Release` objects created by
    :py:attr:`Repository.releases` are based on :py:attr:`Repository.tags`, but
    using the ``release_scheme`` argument to the :py:class:`Repository`
    constructor you can specify that releases should be based on
    :py:attr:`Repository.branches` instead. Additionally you can use the
    ``release_filter`` argument to specify a regular expression that will be
    used to distinguish valid releases from other tags/branches.

    :ivar revision: The :py:class:`Revision` that the release relates to.

    :ivar identifier: The name of the tag or branch (a string). If a
          ``release_filter`` containing a single capture group is used this
          identifier is set to the captured substring instead of the complete
          tag or branch name.
    """

    def __init__(self, revision, identifier):
        """
        Initialize a release.

        :param revision: The :py:class:`Revision` that the release relates to.
        :param identifier: The (substring of the) tag or branch name that the
                           release is based on (a string).
        """
        self.revision = revision
        self.identifier = identifier

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, ', '.join([
            "revision=%r" % self.revision,
            "identifier=%r" % self.identifier,
        ]))

class HgRepo(Repository):

    """
    Version control repository interface for Mercurial_ repositories.

    .. _Mercurial: http://mercurial.selenic.com/
    """

    friendly_name = 'Mercurial'
    default_revision = 'default'
    control_field = 'Vcs-Hg'
    create_command = 'hg clone --noupdate {remote} {local}'
    update_command = 'hg pull --repository {local} {remote}'
    export_command = 'hg archive --repository {local} --rev {revision} {directory}'

    @property
    def vcs_directory(self):
        return os.path.join(self.local, '.hg')

    @property
    def exists(self):
        return os.path.isdir(self.vcs_directory)

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
            if len(tokens) >= 2 and ':' in tokens[1]:
                revision_number, revision_id = tokens[1].split(':')
                yield Revision(repository=self,
                               revision_id=revision_id,
                               revision_number=int(revision_number),
                               branch=tokens[0])

    def find_tags(self):
        listing = execute('hg', '--repository', self.local, 'tags', capture=True)
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and ':' in tokens[1]:
                revision_number, revision_id = tokens[1].split(':')
                yield Revision(repository=self,
                               revision_id=revision_id,
                               revision_number=int(revision_number),
                               tag=tokens[0])

class GitRepo(Repository):

    """
    Version control repository interface for Git_ repositories.

    .. _Git: http://git-scm.com/
    """

    friendly_name = 'Git'
    default_revision = 'master'
    control_field = 'Vcs-Git'
    create_command = 'git clone --bare {remote} {local}'
    update_command = 'cd {local} && git fetch {remote}'
    export_command = 'cd {local} && git archive {revision} | tar --extract --directory={directory}'

    @property
    def vcs_directory(self):
        directory = os.path.join(self.local, '.git')
        return directory if os.path.isdir(directory) else self.local

    @property
    def exists(self):
        return os.path.isfile(os.path.join(self.vcs_directory, 'config'))

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

    def find_tags(self):
        listing = execute('git', 'show-ref', '--tags', capture=True, directory=self.local)
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and tokens[1].startswith('refs/tags/'):
                yield Revision(repository=self,
                               revision_id=tokens[0],
                               tag=tokens[1][len('refs/tags/'):])

class BzrRepo(Repository):

    """
    Version control repository interface for Bazaar_ repositories.

    .. _Bazaar: http://bazaar.canonical.com/en/
    """

    friendly_name = 'Bazaar'
    default_revision = 'last:1'
    control_field = 'Vcs-Bzr'
    create_command = 'bzr branch --use-existing-dir {remote} {local}'
    update_command = 'cd {local} && bzr pull {remote}'
    export_command = 'cd {local} && bzr export --revision={revision} {directory}'

    @property
    def vcs_directory(self):
        return os.path.join(self.local, '.bzr')

    @property
    def exists(self):
        return os.path.isfile(os.path.join(self.vcs_directory, 'branch-format'))

    def find_revision_number(self, revision=None):
        # Bazaar has the concept of dotted revision numbers:
        #
        #   For revisions which have been merged into a branch, a dotted
        #   notation is used (e.g., 3112.1.5). Dotted revision numbers have
        #   three numbers. The first number indicates what mainline revision
        #   change is derived from. The second number is the branch counter.
        #   There can be many branches derived from the same revision, so they
        #   all get a unique number. The third number is the number of
        #   revisions since the branch started. For example, 3112.1.5 is the
        #   first branch from revision 3112, the fifth revision on that
        #   branch.
        #
        #   (From http://doc.bazaar.canonical.com/bzr.2.6/en/user-guide/zen.html#understanding-revision-numbers)
        #
        # However we really just want to give a bare integer to our callers. It
        # doesn't have to be globally accurate, but it should increase as new
        # commits are made. Below is the equivalent of the git implementation
        # for Bazaar.
        self.create()
        revision = revision or self.default_revision
        result = execute('bzr', 'log', '--revision=..%s' % revision, '--line', capture=True, directory=self.local)
        revision_number = len([line for line in result.splitlines() if line and not line.isspace()])
        assert revision_number > 0, "Failed to find local revision number! ('bzr log --line' gave unexpected output)"
        return revision_number

    def find_revision_id(self, revision=None):
        self.create()
        revision = revision or self.default_revision
        result = execute('bzr', 'version-info', '--revision=%s' % revision, '--custom', '--template={revision_id}', capture=True, directory=self.local)
        logger.debug("Output of 'bzr version-info' command: %s", result)
        assert result, "Failed to find global revision id! ('bzr version-info' gave unexpected output)"
        return result

    def find_branches(self):
        logger.warning("Bazaar repository support doesn't include branches (consider using tags instead).")
        return []

    def find_tags(self):
        # The `bzr tags' command reports tags pointing to non-existing
        # revisions as `?' but doesn't provide revision ids. We can get the
        # revision ids using the `bzr tags --show-ids' command but this command
        # doesn't mark tags pointing to non-existing revisions. We combine
        # the output of both because we want all the information.
        valid_tags = []
        listing = execute('bzr', 'tags', capture=True, directory=self.local)
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) == 2 and tokens[1] != '?':
                valid_tags.append(tokens[0])
        listing = execute('bzr', 'tags', '--show-ids', capture=True, directory=self.local)
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) == 2 and tokens[0] in valid_tags:
                tag, revision_id = tokens
                yield Revision(repository=self,
                               revision_id=tokens[1],
                               tag=tokens[0])

class NoSuchRepositoryError(Exception):
    """
    Exception raised by :py:func:`find_configured_repository()` when the given
    repository name doesn't match any of the configured repositories.
    """

class AmbiguousRepositoryNameError(Exception):
    """
    Exception raised by :py:func:`find_configured_repository()` when the given
    repository name is ambiguous (i.e. it matches multiple repository names).
    """

class UnknownRepositoryTypeError(Exception):
    """
    Exception raised by :py:func:`find_configured_repository()` when it
    encounters a repository definition with an unknown type.
    """

class NoMatchingReleasesError(Exception):
    """
    Exception raised by :py:func:`Repository.select_release()` when no matching
    releases are found in the repository.
    """

# vim: ts=4 sw=4 et

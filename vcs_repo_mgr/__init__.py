# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 8, 2018
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""
Python API for the `vcs-repo-mgr` package.

.. note:: This module handles subprocess management using :mod:`executor`. This
          means that the :exc:`~executor.ExternalCommandFailed` exception can
          be raised at (more or less) any point.

Getting started
===============

When using `vcs-repo-mgr` as a Python API the following top level entities
should help you get started:

- The :class:`Repository` class implements most of the functionality exposed
  by the `vcs-repo-mgr` project. In practice you'll use one of the subclasses
  which implement support for a specific VCS system (:class:`.BzrRepo`,
  :class:`.GitRepo` and :class:`.HgRepo`).

  - :class:`Repository` objects construct :class:`Revision` and
    :class:`Release` objects so you'll most likely be using these.

- The :func:`find_configured_repository()` function constructs instances of
  :class:`Repository` subclasses based on configuration files. This is
  useful when you find yourself frequently instantiating the same
  :class:`Repository` instances and you'd rather refer to a repository name
  in your code than repeating the complete local and remote locations
  everywhere in your code (this kind of duplication is bad after all :-).

- You can choose to directly instantiate :class:`.BzrRepo`,
  :class:`.GitRepo` and/or :class:`.HgRepo` instances or you can use one of
  the helper functions that instantiate repository objects for you
  (:func:`coerce_repository()` and :func:`repository_factory()`).

Common operations
=================

The operations supported by Bazaar, Git and Mercurial have confusingly similar
names *except when they don't* (don't even get me started about subtly
different semantics ;-) and so one challenge while developing `vcs-repo-mgr`
has been to come up with good names that adequately capture the semantics of
operations (just for the record: I'm not claiming that I always succeed on the
first try :-).

In case you find yourself as confused as I have found myself at times, the
following table lists common repository operations supported by `vcs-repo-mgr`
and their equivalent Bazaar, Git and Mercurial commands:

==================================  =================  =====================  =============
Python API (`vcs-repo-mgr`)         Bazaar             Git                    Mercurial
==================================  =================  =====================  =============
:func:`Repository.create()`         bzr init/branch    git init/clone         hg init/clone
:func:`Repository.pull()`           bzr pull           git fetch/pull         hg pull
:func:`Repository.push()`           bzr push           git push               hg push
:func:`Repository.checkout()`       (not implemented)  git checkout           hg update
:func:`Repository.commit()`         (not implemented)  git commit             hg commit
:func:`Repository.create_branch()`  (not implemented)  git checkout -b        hg branch
:func:`Repository.merge()`          (not implemented)  git merge --no-commit  hg merge
==================================  =================  =====================  =============

.. note:: As you can see from the table above I'm slowly but surely forgetting
          about keeping Bazaar support up to par, if only because I don't like
          the "lowest common denominator" approach where useful Git and
          Mercurial features aren't exposed because there's no clear
          alternative for Bazaar. Also I work a lot less with Bazaar which
          means I'm lacking knowledge; keeping Bazaar support up to par at all
          times drags down my progress significantly.

          In contrast while there are of course a lot of small details that
          differ between Git and Mercurial, I'm still convinced that it's
          useful to hide these differences, because overall the two systems are
          so similar that it seems worth it to me (so far :-).
"""

# Standard library modules.
import logging
import operator
import os
import re
import sys
import tempfile
import time

# External dependencies.
from executor import ExternalCommandFailed
from executor.contexts import LocalContext
from humanfriendly import Timer, coerce_boolean, coerce_pattern, format_path, parse_path
from humanfriendly.text import compact, concatenate, format, pluralize
from humanfriendly.prompts import prompt_for_confirmation
from humanfriendly.terminal import connected_to_terminal
from natsort import natsort, natsort_key
from property_manager import PropertyManager, required_property, mutable_property, set_property
from six import add_metaclass, string_types
from six.moves import configparser
from six.moves import urllib_parse as urlparse

# Modules included in our package.
from vcs_repo_mgr.exceptions import (
    AmbiguousRepositoryNameError,
    MergeConflictError,
    MissingWorkingTreeError,
    NoMatchingReleasesError,
    NoSuchRepositoryError,
    UnknownRepositoryTypeError,
    WorkingTreeNotCleanError,
)

# Semi-standard module versioning.
__version__ = '4.1'

USER_CONFIG_FILE = '~/.vcs-repo-mgr.ini'
"""The location of the user-specific configuration file (a string, parsed using :func:`.parse_path()`)."""

SYSTEM_CONFIG_FILE = '/etc/vcs-repo-mgr.ini'
"""The pathname of the system wide configuration file (a string)."""

UPDATE_VARIABLE = 'VCS_REPO_MGR_UPDATE_LIMIT'
"""The name of the environment variable that's used to rate limit repository updates (a string)."""

KNOWN_RELEASE_SCHEMES = ('branches', 'tags')
"""The names of valid release schemes (a tuple of strings)."""

BUNDLED_BACKENDS = ('bzr', 'git', 'hg')
"""The names of the version control modules provided by `vcs-repo-mgr` (a tuple of strings)."""

REPOSITORY_TYPES = set()
"""Available :class:`Repository` subclasses (a :class:`set` of :class:`type` objects)."""

HEX_PATTERN = re.compile('^[A-Fa-f0-9]+$')
"""Compiled regular expression pattern to match hexadecimal strings."""

# Initialize a logger.
logger = logging.getLogger(__name__)

# Dictionary of previously constructed Repository objects.
loaded_repositories = {}


def coerce_author(value):
    """
    Coerce strings to :class:`Author` objects.

    :param value: A string or :class:`Author` object.
    :returns: An :class:`Author` object.
    :raises: :exc:`~exceptions.ValueError` when `value`
             isn't a string or :class:`Author` object.
    """
    # Author objects pass through untouched.
    if isinstance(value, Author):
        return value
    # In all other cases we expect a string.
    if not isinstance(value, string_types):
        msg = "Expected Author object or string as argument, got %s instead!"
        raise ValueError(msg % type(value))
    # Try to parse the `name <email>' format.
    match = re.match('^(.+?) <(.+?)>$', value)
    if not match:
        msg = "Provided author information isn't in 'name <email>' format! (%r)"
        raise ValueError(msg % value)
    return Author(
        name=match.group(1).strip(),
        email=match.group(2).strip(),
    )


def coerce_feature_branch(value):
    """
    Convert a string to a :class:`FeatureBranchSpec` object.

    :param value: A string or :class:`FeatureBranchSpec` object.
    :returns: A :class:`FeatureBranchSpec` object.
    """
    # Repository objects pass through untouched.
    if isinstance(value, FeatureBranchSpec):
        return value
    # We expect a string with a name or URL.
    if not isinstance(value, string_types):
        msg = "Expected string or FeatureBranchSpec object as argument, got %s instead!"
        raise ValueError(msg % type(value))
    return FeatureBranchSpec(expression=value)


def coerce_repository(value, context=None):
    """
    Convert a string (taken to be a repository name or location) to a :class:`Repository` object.

    :param value: The name or location of a repository (a string) or a
                  :class:`Repository` object.
    :param context: An execution context created by :mod:`executor.contexts`
                    (defaults to :class:`executor.contexts.LocalContext`).
    :returns: A :class:`Repository` object.
    :raises: :exc:`~exceptions.ValueError` when the given value is not a string
             or a :class:`Repository` object or if the value is a string but
             doesn't match the name of any configured repository and also can't
             be parsed as the location of a repository.

    The :func:`coerce_repository()` function creates :class:`Repository` objects:

    1. If the value is already a :class:`Repository` object it is returned to
       the caller untouched.
    2. If the value is accepted by :func:`find_configured_repository()` then
       the resulting :class:`Repository` object is returned.
    3. If the value is a string that starts with a known VCS type prefix (e.g.
       ``hg+https://bitbucket.org/ianb/virtualenv``) the prefix is removed from
       the string and a :class:`Repository` object is returned:

       - If the resulting string points to an existing local directory it will
         be used to set :attr:`~Repository.local`.
       - Otherwise the resulting string is used to set
         :attr:`~Repository.remote`.
    4. If the value is a string pointing to an existing local directory, the
       VCS type is inferred from the directory's contents and a
       :class:`Repository` object is returned whose :attr:`~Repository.local`
       property is set to the local directory.
    5. If the value is a string that ends with ``.git`` (a common idiom for git
       repositories) a :class:`Repository` object is returned:

       - If the value points to an existing local directory it will be used to
         set :attr:`~Repository.local`.
       - Otherwise the value is used to set :attr:`~Repository.remote`.
    """
    # Coerce the context argument.
    context = context or LocalContext()
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
    # Parse and try to resolve the VCS type prefix.
    vcs_type, _, location = value.partition('+')
    if vcs_type and location:
        kw = {
            'context': context,
            'local' if context.exists(location) else 'remote': location,
        }
        try:
            return repository_factory(vcs_type, **kw)
        except UnknownRepositoryTypeError:
            pass
    # Try to infer the type of an existing local repository.
    for cls in load_backends():
        if cls.contains_repository(context, value):
            return repository_factory(cls, context=context, local=value)
    # Check for locations that end with `.git' (a common idiom for remote
    # git repositories) even if the location isn't prefixed with `git+'.
    if value.endswith('.git'):
        from vcs_repo_mgr.backends.git import GitRepo
        return repository_factory(GitRepo, **{
            'context': context,
            'local' if context.exists(value) else 'remote': value,
        })
    # If all else fails, at least give a clear explanation of the problem.
    msg = ("The string %r doesn't match the name of any configured repository"
           " and it also can't be parsed as the location of a remote"
           " repository! (maybe you forgot to prefix the type?)")
    raise ValueError(msg % value)


def find_cache_directory(remote):
    """
    Find the directory where temporary local checkouts are to be stored.

    :returns: The absolute pathname of a directory (a string).
    """
    return os.path.join('/var/cache/vcs-repo-mgr' if os.access('/var/cache', os.W_OK) else tempfile.gettempdir(),
                        urlparse.quote(remote, safe=''))


def find_configured_repository(name):
    """
    Find a version control repository defined by the user in a configuration file.

    :param name: The name of the repository (a string).
    :returns: A :class:`Repository` object.
    :raises: :exc:`~vcs_repo_mgr.exceptions.NoSuchRepositoryError` when the
             given repository name doesn't match any of the configured
             repositories.
    :raises: :exc:`~vcs_repo_mgr.exceptions.AmbiguousRepositoryNameError`
             when the given repository name is ambiguous (i.e. it matches
             multiple repository names).
    :raises: :exc:`~vcs_repo_mgr.exceptions.UnknownRepositoryTypeError` when
             a repository definition with an unknown type is encountered.

    The following configuration files are supported:

    1. ``/etc/vcs-repo-mgr.ini``
    2. ``~/.vcs-repo-mgr.ini``

    Repositories defined in the second file override repositories defined in
    the first. Here is an example of a repository definition:

    .. code-block:: ini

       [vcs-repo-mgr]
       type = git
       local = ~/projects/vcs-repo-mgr
       remote = git@github.com:xolox/python-vcs-repo-mgr.git
       bare = true
       release-scheme = tags
       release-filter = .*

    Three VCS types are currently supported: ``hg`` (``mercurial`` is also
    accepted), ``git`` and ``bzr`` (``bazaar`` is also accepted).
    """
    parser = configparser.RawConfigParser()
    for config_file in [SYSTEM_CONFIG_FILE, USER_CONFIG_FILE]:
        config_file = parse_path(config_file)
        if os.path.isfile(config_file):
            logger.debug("Loading configuration file (%s) ..", format_path(config_file))
            parser.read(config_file)
    matching_repos = [r for r in parser.sections() if normalize_name(name) == normalize_name(r)]
    if not matching_repos:
        msg = "No repositories found matching the name '%s'!"
        raise NoSuchRepositoryError(msg % name)
    elif len(matching_repos) != 1:
        msg = "Multiple repositories found matching the name '%s'! (matches: %s)"
        raise AmbiguousRepositoryNameError(msg % (name, concatenate(map(repr, matching_repos))))
    else:
        kw = {}
        # Get the repository specific options.
        options = dict(parser.items(matching_repos[0]))
        vcs_type = options.get('type', '').lower()
        # Process the `local' directory pathname.
        local_path = options.get('local')
        if local_path:
            # Expand a leading tilde and/or environment variables.
            kw['local'] = parse_path(local_path)
        # Process the `bare' option.
        bare = options.get('bare', None)
        if bare is not None:
            # Default to bare=None but enable configuration
            # file(s) to enforce bare=True or bare=False.
            kw['bare'] = coerce_boolean(bare)
        # Process the `remote', `release_scheme' and `release_filter' options.
        for name in 'remote', 'release-scheme', 'release-filter':
            value = options.get(name)
            if value is not None:
                kw[name.replace('-', '_')] = value
        return repository_factory(vcs_type, **kw)


def load_backends():
    """
    Load the backend modules bundled with `vcs-repo-mgr`.

    :returns: The value of :data:`REPOSITORY_TYPES`.

    When :data:`REPOSITORY_TYPES` is empty this function will import each of
    the backend modules listed in :data:`BUNDLED_BACKENDS` before it accesses
    :data:`REPOSITORY_TYPES`, to make sure that all of the :class:`Repository`
    subclasses bundled with `vcs-repo-mgr` are registered.
    """
    # Load the bundled backend modules?
    if not REPOSITORY_TYPES:
        for name in BUNDLED_BACKENDS:
            __import__('vcs_repo_mgr.backends.%s' % name)
    # Return the subclasses registered by our metaclass.
    return REPOSITORY_TYPES


def normalize_name(name):
    """
    Normalize a repository name.

    :param name: The name of a repository (a string).
    :returns: The normalized repository name (a string).

    This makes sure that minor variations in character case and/or punctuation
    don't disrupt the name matching in :func:`find_configured_repository()`.
    """
    return re.sub('[^a-z0-9]', '', name.lower())


def repository_factory(vcs_type, **kw):
    """
    Instantiate a :class:`Repository` object based on the given type and arguments.

    :param vcs_type: One of the strings 'bazaar', 'bzr', 'git', 'hg' or
                     'mercurial' or a subclass of :class:`Repository`.
    :param kw: The keyword arguments to :func:`Repository.__init__()`.
    :returns: A :class:`Repository` object.
    :raises: :exc:`~vcs_repo_mgr.exceptions.UnknownRepositoryTypeError` when
             the given type is unknown.
    """
    # Resolve VCS aliases to Repository subclasses.
    if isinstance(vcs_type, string_types):
        vcs_type = vcs_type.lower()
        for cls in load_backends():
            if vcs_type in cls.ALIASES:
                vcs_type = cls
                break
    # Make sure we have a valid repository type to work with.
    if not (isinstance(vcs_type, type) and issubclass(vcs_type, Repository)):
        raise UnknownRepositoryTypeError("Unknown VCS repository type! (%r)" % vcs_type)
    # Generate a cache key that we will use to avoid constructing duplicates.
    cache_key = tuple('%s=%s' % (k, v) for k, v in sorted(kw.items()))
    logger.debug("Generated repository cache key: %r", cache_key)
    if cache_key in loaded_repositories:
        logger.debug("Repository previously constructed, returning cached instance ..")
    else:
        logger.debug("Repository not yet constructed, creating new instance ..")
        loaded_repositories[cache_key] = vcs_type(**kw)
    return loaded_repositories[cache_key]


def sum_revision_numbers(arguments):
    """
    Sum revision numbers of multiple repository/revision pairs.

    :param arguments: A list of strings with repository names and revision
                      strings.
    :returns: A single integer containing the summed revision numbers.

    This is useful when you're building a package based on revisions from
    multiple VCS repositories. By taking changes in all repositories into
    account when generating version numbers you can make sure that your version
    number is bumped with every single change.
    """
    arguments = list(arguments)
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
        """Set :data:`UPDATE_VARIABLE` to the current time when entering the context."""
        self.old_value = os.environ.get(UPDATE_VARIABLE)
        os.environ[UPDATE_VARIABLE] = '%i' % time.time()

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Restore the previous value of :data:`UPDATE_VARIABLE` when leaving the context."""
        if self.old_value is not None:
            os.environ[UPDATE_VARIABLE] = self.old_value
        elif UPDATE_VARIABLE in os.environ:
            del os.environ[UPDATE_VARIABLE]


class Author(PropertyManager):

    """An author for commits in version control repositories."""

    @property
    def combined(self):
        """The name and e-mail address of the author combined into one string (a string)."""
        return u'%s <%s>' % (self.name, self.email)

    @required_property
    def email(self):
        """The e-mail address of the author (a string)."""

    @required_property
    def name(self):
        """The name of the author (a string)."""


class FeatureBranchSpec(PropertyManager):

    """
    Simple and human friendly feature branch specifications.
    """

    @required_property
    def expression(self):
        """
        The feature branch specification provided by the user (a string).

        The value of this property is parsed as follows:

        - If :attr:`expression` contains two nonempty substrings separated by
          the character ``#`` it is split into two parts where the first part
          is used to set :attr:`location` and the second part is used to set
          :attr:`revision`.

        - Otherwise :attr:`expression` is interpreted as a revision without a
          location (in this case :attr:`location` will be :data:`None`).

        Some examples to make things more concrete:

        >>> from vcs_repo_mgr import FeatureBranchSpec
        >>> FeatureBranchSpec(expression='https://github.com/xolox/python-vcs-repo-mgr.git#remote-feature-branch')
        FeatureBranchSpec(expression='https://github.com/xolox/python-vcs-repo-mgr.git#remote-feature-branch',
                          location='https://github.com/xolox/python-vcs-repo-mgr.git',
                          revision='remote-feature-branch')
        >>> FeatureBranchSpec(expression='local-feature-branch')
        FeatureBranchSpec(expression='local-feature-branch',
                          location=None,
                          revision='local-feature-branch')
        """

    @mutable_property
    def location(self):
        """The location of the repository that contains :attr:`revision` (a string or :data:`None`)."""
        location, _, revision = self.expression.partition('#')
        return location if location and revision else None

    @mutable_property
    def revision(self):
        """The name of the feature branch (a string)."""
        location, _, revision = self.expression.partition('#')
        return revision if location and revision else self.expression


class Repository(PropertyManager):

    """
    Abstract base class for managing version control repositories.

    In general you should not use the :class:`Repository` class directly,
    instead you should use the relevant subclass (:class:`.BzrRepo`,
    :class:`.GitRepo` or :class:`.HgRepo`).
    """

    # Class properties.

    ALIASES = []
    """
    A list of strings with names for the repository type.

    The :func:`repository_factory()` function searches the :attr:`ALIASES` of
    all known subclasses of :class:`Repository` in order to map repository
    specifications like ``hg+https://bitbucket.org/ianb/virtualenv`` to the
    correct :class:`Repository` subclass.
    """

    repr_properties = ['local', 'remote']
    """The properties included in the output of :func:`repr()`."""

    # Class methods.

    @classmethod
    def contains_repository(cls, context, directory):
        """
        Check whether the given directory contains a local repository.

        :param directory: The pathname of a directory (a string).
        :returns: :data:`True` if the directory contains a local repository,
                  :data:`False` otherwise.

        By default :func:`contains_repository()` just checks whether the
        directory reported by :func:`get_vcs_directory()` exists, but
        :class:`Repository` subclasses can override this class method to
        improve detection accuracy.
        """
        return context.is_directory(cls.get_vcs_directory(context, directory))

    @staticmethod
    def get_vcs_directory(context, directory):
        """
        Get the pathname of the directory containing the version control metadata files.

        :param context: An execution context created by :mod:`executor.contexts`.
        :param directory: The pathname of a directory (a string).
        :returns: The pathname of the directory containing the version control
                  metadata files (a string). In most cases this will be a
                  subdirectory of the given directory, but it may also be the
                  directory itself.

        This static method needs to be implemented by subclasses:

        - If `directory` doesn't exist this should not raise exceptions.
        - If `directory` does exist its contents may influence the result of
          :func:`get_vcs_directory()` in order to cope with version control
          backends whose directory layout changes depending on whether they are
          :attr:`bare` (I'm looking at you git).
        """
        raise NotImplementedError()

    # Instance properties.

    @mutable_property(cached=True)
    def author(self):
        """
        The author for new commits (an :class:`Author` object or :data:`None`).

        When you set this property the new value is coerced using
        :func:`coerce_author()` (that is to say, strings are automatically
        converted to an :class:`Author` object).

        The default value of this property is computed by :func:`find_author()`
        (a method that needs to be implemented subclasses).
        """
        return self.find_author()

    @author.setter
    def author(self, value):
        """Automatically coerce strings to :class:`Author` objects."""
        set_property(self, 'author', coerce_author(value))

    @mutable_property
    def bare(self):
        """
        Whether the local repository should have a working tree or not (a boolean or :data:`None`).

        This property specifies whether the local repository should have a
        working tree or not:

        - :data:`True` means the local repository doesn't need and shouldn't
          have a working tree (in older versions of `vcs-repo-mgr` this was the
          default and only choice).

        - :data:`False` means the local repository does need a working tree
          (for example because you want to create new commits).

        The value of :attr:`bare` defaults to auto-detection using
        :attr:`is_bare` for repositories that already exist locally, if only to
        preserve compatibility with versions of `vcs-repo-mgr` that didn't have
        working tree support.

        For repositories that don't exist locally yet, :attr:`bare` defaults to
        :data:`True` so that :func:`create()` defaults to creating repositories
        without a working tree.

        If :attr:`bare` is explicitly set and the local clone already exists it
        will be checked by :func:`__init__()` to make sure that the values of
        :attr:`bare` and :attr:`is_bare` match. If they don't an exception will
        be raised.
        """
        return self.is_bare if self.exists else True

    @property
    def branches(self):
        """
        A dictionary that maps branch names to :class:`Revision` objects.

        Here's an example based on a mirror of the git project's repository:

        >>> from pprint import pprint
        >>> from vcs_repo_mgr.backends.git import GitRepo
        >>> repository = GitRepo(remote='https://github.com/git/git.git')
        >>> pprint(repository.branches)
        {'maint':  Revision(repository=GitRepo(...), branch='maint',  revision_id='16018ae'),
         'master': Revision(repository=GitRepo(...), branch='master', revision_id='8440f74'),
         'next':   Revision(repository=GitRepo(...), branch='next',   revision_id='38e7071'),
         'pu':     Revision(repository=GitRepo(...), branch='pu',     revision_id='d61c1fa'),
         'todo':   Revision(repository=GitRepo(...), branch='todo',   revision_id='dea8a2d')}
        """
        # Make sure the local repository exists.
        self.create()
        # Create a mapping of branch names to revisions.
        return dict((r.branch, r) for r in self.find_branches())

    @mutable_property
    def compiled_filter(self):
        """
        The result of :func:`re.compile()` on :attr:`release_filter`.

        If :attr:`release_filter` isn't a string then it is assumed to be a
        compiled regular expression object and returned directly.
        """
        return coerce_pattern(self.release_filter)

    @mutable_property(cached=True)
    def context(self):
        """An execution context created by :mod:`executor.contexts`."""
        return LocalContext()

    @required_property
    def control_field(self):
        """The name of the Debian control file field for the version control system (a string)."""

    @property
    def current_branch(self):
        """
        The name of the branch that's currently checked out in the working tree (a string or :data:`None`).

        This property needs to be implemented by subclasses. It should not
        raise an exception when the current branch can't be determined.
        """
        raise NotImplementedError()

    @property
    def default_pull_remote(self):
        """The default remote for pulls (a :class:`Remote` object or :data:`None`)."""
        return self.find_remote(default=True, role='pull')

    @property
    def default_push_remote(self):
        """The default remote for pushes (a :class:`Remote` object or :data:`None`)."""
        return self.find_remote(default=True, role='push')

    @required_property
    def default_revision(self):
        """
        The default revision of this version control system (a string).

        This property needs to be implemented by subclasses.
        """

    @property
    def exists(self):
        """:data:`True` if the local repository exists, :data:`False` otherwise."""
        return self.contains_repository(self.context, self.local)

    @required_property
    def friendly_name(self):
        """A user friendly name for the version control system (a string)."""

    @property
    def is_bare(self):
        """
        :data:`True` if the repository has no working tree, :data:`False` if it does.

        This property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def is_clean(self):
        """
        :data:`True` if the working tree is clean, :data:`False` otherwise.

        This property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def known_remotes(self):
        """
        Remote repositories connected to the local repository (a list of :class:`Remote` objects).

        This property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def last_updated(self):
        """
        The date and time when `vcs-repo-mgr` last checked for updates (an integer).

        Used internally by :func:`pull()` when used in combination with
        :class:`limit_vcs_updates`. The value is a UNIX time stamp (0 for
        remote repositories that don't have a local clone yet).
        """
        try:
            if self.context.exists(self.last_updated_file):
                return int(self.context.read_file(self.last_updated_file))
        except Exception:
            pass
        return 0

    @property
    def last_updated_file(self):
        """The pathname of the file used to mark the last successful update (a string)."""
        return os.path.join(self.vcs_directory, 'vcs-repo-mgr.txt')

    @mutable_property(cached=True)
    def local(self):
        """The pathname of the local repository (a string)."""
        if self.remote:
            return find_cache_directory(self.remote)

    @property
    def merge_conflicts(self):
        """
        The filenames of any files with merge conflicts (a list of strings).

        This property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def ordered_branches(self):
        """
        The values in :attr:`branches` ordered by branch name (a list of :class:`Revision` objects).

        The list is ordered by performing a `natural order sort
        <https://pypi.python.org/pypi/naturalsort>`_ of branch names in
        ascending order (i.e. the first value is the "oldest" branch and the
        last value is the "newest" branch).
        """
        return natsort(self.branches.values(), key=operator.attrgetter('branch'))

    @property
    def ordered_releases(self):
        """
        The values in :attr:`releases` ordered by release identifier (a list of :class:`Release` objects).

        The list is ordered by performing a `natural order sort
        <https://pypi.python.org/pypi/naturalsort>`_ of release identifiers in
        ascending order (i.e. the first value is the "oldest" release and the
        last value is the "newest" release).
        """
        return natsort(self.releases.values(), key=operator.attrgetter('identifier'))

    @property
    def ordered_tags(self):
        """
        The values in :attr:`tags` ordered by tag name (a list of :class:`Revision` objects).

        The list is ordered by performing a `natural order sort
        <https://pypi.python.org/pypi/naturalsort>`_ of tag names in ascending
        order (i.e. the first value is the "oldest" tag and the last value is
        the "newest" tag).
        """
        return natsort(self.tags.values(), key=operator.attrgetter('tag'))

    @property
    def release_branches(self):
        """A dictionary that maps branch names to :class:`Release` objects."""
        self.ensure_release_scheme('branches')
        return dict((r.revision.branch, r) for r in self.releases.values())

    @mutable_property
    def release_filter(self):
        """
        The repository's release filter (a string or regular expression, defaults to ``.*``).

        The value of :attr:`release_filter` should be a string containing a
        regular expression or the result of :func:`re.compile()`. The regular
        expression is used by :attr:`Repository.releases` to match tags or
        branches that signify "releases". If the regular expression contains a
        single capture group, the identifier of a :class:`Release` object is
        set to the substring captured by the capture group (instead of the
        complete tag or branch name). This defaults to the regular expression
        ``.*`` which matches any branch or tag name.
        """
        return '.*'

    @release_filter.setter
    def release_filter(self, value):
        """Validate the release filter."""
        compiled_pattern = coerce_pattern(value)
        if compiled_pattern.groups > 1:
            raise ValueError(compact("""
                Release filter regular expression pattern is expected to have
                zero or one capture group, but it has {count} instead!
            """, count=compiled_pattern.groups))
        set_property(self, 'release_filter', value)
        set_property(self, 'compiled_filter', compiled_pattern)

    @mutable_property
    def release_scheme(self):
        """
        The repository's release scheme (a string, defaults to 'tags').

        The value of :attr:`release_scheme` determines whether
        :attr:`Repository.releases` is based on :attr:`Repository.tags` or
        :attr:`Repository.branches`. It should match one of the values in
        :data:`KNOWN_RELEASE_SCHEMES`. If an invalid value is set
        :exc:`~exceptions.ValueError` will be raised.
        """
        return 'tags'

    @release_scheme.setter
    def release_scheme(self, value):
        """Validate the release scheme."""
        if value not in KNOWN_RELEASE_SCHEMES:
            msg = "Release scheme %r is not supported! (valid options are %s)"
            raise ValueError(msg % (value, concatenate(map(repr, KNOWN_RELEASE_SCHEMES))))
        set_property(self, 'release_scheme', value)

    @property
    def releases(self):
        r"""
        A dictionary that maps release identifiers to :class:`Release` objects.

        Here's an example based on a mirror of the git project's repository
        which shows the last ten releases based on tags, where each release
        identifier captures a tag without its 'v' prefix:

        >>> from pprint import pprint
        >>> from vcs_repo_mgr.backends.git import GitRepo
        >>> repository = GitRepo(remote='https://github.com/git/git.git',
        ...                      release_scheme='tags',
        ...                      release_filter=r'^v(\d+(?:\.\d+)*)$')
        >>> pprint(repository.ordered_releases[-10:])
        [Release(revision=Revision(..., tag='v2.2.2', ...), identifier='2.2.2'),
         Release(revision=Revision(..., tag='v2.3.0', ...), identifier='2.3.0'),
         Release(revision=Revision(..., tag='v2.3.1', ...), identifier='2.3.1'),
         Release(revision=Revision(..., tag='v2.3.2', ...), identifier='2.3.2'),
         Release(revision=Revision(..., tag='v2.3.3', ...), identifier='2.3.3'),
         Release(revision=Revision(..., tag='v2.3.4', ...), identifier='2.3.4'),
         Release(revision=Revision(..., tag='v2.3.5', ...), identifier='2.3.5'),
         Release(revision=Revision(..., tag='v2.3.6', ...), identifier='2.3.6'),
         Release(revision=Revision(..., tag='v2.3.7', ...), identifier='2.3.7'),
         Release(revision=Revision(..., tag='v2.4.0', ...), identifier='2.4.0')]
        """
        available_releases = {}
        available_revisions = getattr(self, self.release_scheme)
        for identifier, revision in available_revisions.items():
            match = self.compiled_filter.match(identifier)
            if match:
                # If the regular expression contains a capturing group we
                # set the release identifier to the captured substring
                # instead of the complete tag/branch identifier.
                captures = match.groups()
                if captures:
                    identifier = captures[0]
                available_releases[identifier] = Release(
                    revision=revision,
                    identifier=identifier,
                )
        return available_releases

    @mutable_property
    def remote(self):
        """The location of the remote repository (a string or :data:`None`)."""

    @property
    def supports_working_tree(self):
        """
        :data:`True` if the repository supports a working tree, :data:`False` otherwise.

        This property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def tags(self):
        """
        A dictionary that maps tag names to :class:`Revision` objects.

        Here's an example based on a mirror of the git project's repository:

        >>> from pprint import pprint
        >>> from vcs_repo_mgr.backends.git import GitRepo
        >>> repository = GitRepo(remote='https://github.com/git/git.git')
        >>> pprint(repository.tags)
        {'v0.99': Revision(repository=GitRepo(...),
                           tag='v0.99',
                           revision_id='d6602ec5194c87b0fc87103ca4d67251c76f233a'),
         'v0.99.1': Revision(repository=GitRepo(...),
                             tag='v0.99.1',
                             revision_id='f25a265a342aed6041ab0cc484224d9ca54b6f41'),
         'v0.99.2': Revision(repository=GitRepo(...),
                             tag='v0.99.2',
                             revision_id='c5db5456ae3b0873fc659c19fafdde22313cc441'),
         ..., # dozens of tags omitted to keep this example short
         'v2.3.6': Revision(repository=GitRepo(...),
                            tag='v2.3.6',
                            revision_id='8e7304597727126cdc52771a9091d7075a70cc31'),
         'v2.3.7': Revision(repository=GitRepo(...),
                            tag='v2.3.7',
                            revision_id='b17db4d9c966de30f5445632411c932150e2ad2f'),
         'v2.4.0': Revision(repository=GitRepo(...),
                            tag='v2.4.0',
                            revision_id='67308bd628c6235dbc1bad60c9ad1f2d27d576cc')}
        """
        # Make sure the local repository exists.
        self.create()
        # Create a mapping of tag names to revisions.
        return dict((r.tag, r) for r in self.find_tags())

    @property
    def vcs_directory(self):
        """The pathname of the directory containing the version control metadata files (a string)."""
        return self.get_vcs_directory(self.context, self.local)

    # Instance methods.

    def __init__(self, *args, **kw):
        """
        Initialize a :class:`Repository` object.

        Refer to the initializer of the superclass
        (:class:`~property_manager.PropertyManager`)
        for details about argument handling.

        During initialization :exc:`~exceptions.ValueError`
        can be raised for any of the following reasons:

        - Neither :attr:`local` nor :attr:`remote` is specified.
        - The local repository doesn't exist and :attr:`remote`
          isn't specified.
        - The local repository already exists but the values of :attr:`bare`
          and :attr:`is_bare` don't match.
        - The :attr:`release_scheme` is invalid.
        - The :attr:`release_filter` regular expression contains more than one
          capture group (if you need additional groups but without the
          capturing aspect use a non-capturing group).
        """
        # Initialize our superclass.
        super(Repository, self).__init__(*args, **kw)
        # Make sure the caller specified at least the local *or* remote.
        if not (self.local or self.remote):
            raise ValueError("No local and no remote repository specified! (one of the two is required)")
        # Abort if the caller's preference for the existence of a working
        # tree doesn't match the state of an existing local repository.
        if self.exists and self.bare != self.is_bare:
            raise ValueError(compact(
                """
                A repository {requested_state} a working tree was requested
                but the existing local repository at {location}
                {actual_state} have a working tree!
                """,
                requested_state=("without" if self.bare else "with"),
                actual_state=("doesn't" if self.is_bare else "does"),
                location=format_path(self.local),
            ))
        # Ensure that all further commands are executed in the local repository.
        self.update_context()

    def add_files(self, *filenames, **kw):
        """
        Include added and/or removed files in the working tree in the next commit.

        :param filenames: The filenames of the files to include in the next
                          commit (zero or more strings). If no arguments are
                          given all untracked files are added.
        :param kw: Keyword arguments are ignored (instead of raising
                   :exc:`~exceptions.TypeError`) to enable backwards
                   compatibility with older versions of `vcs-repo-mgr`
                   where the keyword argument `all` was used.
        """
        # Make sure the local repository exists and supports a working tree.
        self.create()
        self.ensure_working_tree()
        # Include added and/or removed files in the next commit.
        logger.info("Staging changes to be committed in %s ..", format_path(self.local))
        self.context.execute(*self.get_add_files_command(*filenames))

    def checkout(self, revision=None, clean=False):
        """
        Update the working tree of the local repository to the specified revision.

        :param revision: The revision to check out (a string,
                         defaults to :attr:`default_revision`).
        :param clean: :data:`True` to discard changes in the working tree,
                      :data:`False` otherwise.
        """
        # Make sure the local repository exists and supports a working tree.
        self.create()
        self.ensure_working_tree()
        # Update the working tree of the local repository.
        revision = revision or self.default_revision
        logger.info("Checking out revision '%s' in %s ..", revision, format_path(self.local))
        self.context.execute(*self.get_checkout_command(revision, clean))

    def commit(self, message, author=None):
        """
        Commit changes to tracked files in the working tree.

        :param message: The commit message (a string).
        :param author: Override :attr:`author` (refer to
                       :func:`coerce_author()` for details
                       on argument handling).
        """
        # Make sure the local repository exists and supports a working tree.
        self.ensure_exists()
        self.ensure_working_tree()
        logger.info("Committing changes in %s: %s", format_path(self.local), message)
        author = coerce_author(author) if author else self.author
        self.context.execute(*self.get_commit_command(message, author))

    def create(self):
        """
        Create the local repository (if it doesn't already exist).

        :returns: :data:`True` if the local repository was just created,
                  :data:`False` if it already existed.

        What :func:`create()` does depends on the situation:

        - When :attr:`exists` is :data:`True` nothing is done.
        - When the :attr:`local` repository doesn't exist but a :attr:`remote`
          repository location is given, a clone of the remote repository is
          created.
        - When the :attr:`local` repository doesn't exist and no :attr:`remote`
          repository has been specified then a new local repository will be
          created.

        When :func:`create()` is responsible for creating the :attr:`local`
        repository it will make sure the :attr:`bare` option is respected.
        """
        if self.exists:
            logger.debug("Local %s repository (%s) already exists, ignoring request to create it.",
                         self.friendly_name, format_path(self.local))
            return False
        else:
            timer = Timer()
            if self.remote:
                logger.info("Creating local %s repository (%s) by cloning %s ..",
                            self.friendly_name, format_path(self.local), self.remote)
            else:
                logger.info("Creating local %s repository (%s) ..",
                            self.friendly_name, format_path(self.local))
            self.context.execute(*self.get_create_command())
            logger.debug("Took %s to %s local %s repository.",
                         timer, "clone" if self.remote else "create",
                         self.friendly_name)
            if self.remote:
                self.mark_updated()
            # Ensure that all further commands are executed in the local repository.
            self.update_context()
            return True

    def create_branch(self, branch_name):
        """
        Create a new branch based on the working tree's revision.

        :param branch_name: The name of the branch to create (a string).

        This method automatically checks out the new branch, but note that the
        new branch may not actually exist until a commit has been made on the
        branch.
        """
        # Make sure the local repository exists and supports a working tree.
        self.create()
        self.ensure_working_tree()
        # Create the new branch in the local repository.
        logger.info("Creating branch '%s' in %s ..", branch_name, format_path(self.local))
        self.context.execute(*self.get_create_branch_command(branch_name))

    def create_release_branch(self, branch_name):
        """
        Create a new release branch.

        :param branch_name: The name of the release branch to create (a string).
        :raises: The following exceptions can be raised:

                  - :exc:`~exceptions.TypeError` when :attr:`release_scheme`
                    isn't set to 'branches'.
                  - :exc:`~exceptions.ValueError` when the branch name doesn't
                    match the configured :attr:`release_filter` or no parent
                    release branches are available.

        This method automatically checks out the new release branch, but note
        that the new branch may not actually exist until a commit has been made
        on the branch.
        """
        # Validate the release scheme.
        self.ensure_release_scheme('branches')
        # Validate the name of the release branch.
        if self.compiled_filter.match(branch_name) is None:
            msg = "The branch name '%s' doesn't match the release filter!"
            raise ValueError(msg % branch_name)
        # Make sure the local repository exists.
        self.create()
        # Figure out the correct parent release branch.
        candidates = natsort([r.revision.branch for r in self.ordered_releases] + [branch_name])
        index = candidates.index(branch_name) - 1
        if index < 0:
            msg = "Failed to determine suitable parent branch for release branch '%s'!"
            raise ValueError(msg % branch_name)
        parent_branch = candidates[index]
        self.checkout(parent_branch)
        self.create_branch(branch_name)

    def create_tag(self, tag_name):
        """
        Create a new tag based on the working tree's revision.

        :param tag_name: The name of the tag to create (a string).
        """
        # Make sure the local repository exists and supports a working tree.
        self.create()
        self.ensure_working_tree()
        # Create the new tag in the local repository.
        logger.info("Creating tag '%s' in %s ..", tag_name, format_path(self.local))
        self.context.execute(*self.get_create_tag_command(tag_name))

    def delete_branch(self, branch_name, message=None, author=None):
        """
        Delete or close a branch in the local repository.

        :param branch_name: The name of the branch to delete or close (a string).
        :param message: The message to use when closing the branch requires a
                        commit (a string or :data:`None`, defaults to the
                        string "Closing branch NAME").
        :param author: Override :attr:`author` (refer to
                       :func:`coerce_author()` for details
                       on argument handling).
        """
        # Make sure the local repository exists.
        self.create()
        # Delete the branch in the local repository.
        logger.info("Deleting branch '%s' in %s ..", branch_name, format_path(self.local))
        self.context.execute(*self.get_delete_branch_command(
            author=(coerce_author(author) if author else self.author),
            message=(message or ("Closing branch %s" % branch_name)),
            branch_name=branch_name,
        ))

    def ensure_clean(self):
        """
        Make sure the working tree is clean (contains no changes to tracked files).

        :raises: :exc:`~vcs_repo_mgr.exceptions.WorkingTreeNotCleanError`
                 when the working tree contains changes to tracked files.
        """
        if not self.is_clean:
            raise WorkingTreeNotCleanError(compact("""
                The repository's local working tree ({local})
                contains changes to tracked files!
            """, local=format_path(self.local)))

    def ensure_exists(self):
        """
        Make sure the local repository exists.

        :raises: :exc:`~exceptions.ValueError` when the
                 local repository doesn't exist yet.
        """
        if not self.exists:
            msg = "The local %s repository %s doesn't exist!"
            raise ValueError(msg % (self.friendly_name, format_path(self.local)))

    def ensure_hexadecimal_string(self, value, command=None):
        """
        Make sure the given value is a hexadecimal string.

        :param value: The value to check (a string).
        :param command: The command that produced the value (a string or :data:`None`).
        :returns: The validated hexadecimal string.
        :raises: :exc:`~exceptions.ValueError` when `value` is not a hexadecimal string.
        """
        if not HEX_PATTERN.match(value):
            msg = "Expected a hexadecimal string, got '%s' instead!"
            if command:
                msg += " ('%s' gave unexpected output)"
                msg %= (value, command)
            else:
                msg %= value
            raise ValueError(msg)
        return value

    def ensure_release_scheme(self, expected_scheme):
        """
        Make sure the release scheme is correctly configured.

        :param expected_scheme: The expected release scheme (a string).
        :raises: :exc:`~exceptions.TypeError` when :attr:`release_scheme`
                 doesn't match the expected release scheme.
        """
        if self.release_scheme != expected_scheme:
            msg = "Repository isn't using '%s' release scheme!"
            raise TypeError(msg % expected_scheme)

    def ensure_working_tree(self):
        """
        Make sure the local repository has working tree support.

        :raises: :exc:`~vcs_repo_mgr.exceptions.MissingWorkingTreeError` when
                 the local repository doesn't support a working tree.
        """
        if not self.supports_working_tree:
            raise MissingWorkingTreeError(compact("""
                A working tree is required but the local {friendly_name}
                repository at {directory} doesn't support a working tree!
            """, friendly_name=self.friendly_name, directory=format_path(self.local)))

    def export(self, directory, revision=None):
        """
        Export the complete tree from the local version control repository.

        :param directory: The directory where the tree should be exported
                          (a string).
        :param revision: The revision to export (a string or :data:`None`,
                         defaults to :attr:`default_revision`).
        """
        # Make sure the local repository exists.
        self.create()
        # Export the tree from the local repository.
        timer = Timer()
        revision = revision or self.default_revision
        logger.info("Exporting revision '%s' in %s to %s ..", revision, format_path(self.local), directory)
        self.context.execute('mkdir', '-p', directory)
        self.context.execute(*self.get_export_command(directory, revision))
        logger.debug("Took %s to pull changes from remote %s repository.", timer, self.friendly_name)

    def find_author(self):
        """
        Get the author information from the version control system.

        :returns: An :class:`Author` object or :data:`None`.

        This method needs to be implemented by subclasses. It is expected to
        get the author information from the version control system (if
        available).
        """
        raise NotImplementedError()

    def find_branches(self):
        """
        Find information about the branches in the repository.

        :returns: A generator of :class:`Revision` objects.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def find_tags(self):
        """
        Find information about the tags in the repository.

        :returns: A generator of :class:`Revision` objects.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def find_remote(self, default=False, name=None, role=None):
        """
        Find a remote repository connected to the local repository.

        :param default: :data:`True` to only look for default remotes,
                        :data:`False` otherwise.
        :param name: The name of the remote to look for
                     (a string or :data:`None`).
        :param role: A role that the remote should have
                     (a string or :data:`None`).
        :returns: A :class:`Remote` object or :data:`None`.
        """
        for remote in self.known_remotes:
            if ((remote.default if default else True) and
                    (remote.name == name if name else True) and
                    (role in remote.roles if role else True)):
                return remote

    def find_revision_id(self, revision=None):
        """
        Find the global revision id of the given revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string, defaults to :attr:`default_revision`).
        :returns: The global revision id (a hexadecimal string).

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def find_revision_number(self, revision=None):
        """
        Find the local revision number of the given revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string, defaults to :attr:`default_revision`).
        :returns: The local revision number (an integer).

        This method needs to be implemented by subclasses:

        - With each commit that is added to the repository, the local revision
          number needs to increase.

        - Whether revision numbers start counting from zero or one is left to
          the version control system. To make things more concrete: While
          Bazaar and git count from one, Mercurial counts from zero.
        """
        raise NotImplementedError()

    def generate_control_field(self, revision=None):
        """
        Generate a Debian control file field referring for this repository and revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string, defaults to :attr:`default_revision`).
        :returns: A tuple with two strings: The name of the field and the value.

        This generates a `Vcs-Bzr` field for Bazaar repositories, a `Vcs-Git`
        field for Git repositories and a `Vcs-Hg` field for Mercurial
        repositories. Here's an example based on the public git repository of
        the `vcs-repo-mgr` project:

        >>> from vcs_repo_mgr import coerce_repository
        >>> repository = coerce_repository('https://github.com/xolox/python-vcs-repo-mgr.git')
        >>> repository.generate_control_field()
        ('Vcs-Git', 'https://github.com/xolox/python-vcs-repo-mgr.git#b617731b6c0ca746665f597d2f24b8814b137ebc')
        """
        value = "%s#%s" % (self.remote or self.local, self.find_revision_id(revision))
        return self.control_field, value

    def get_add_files_command(self, *filenames):
        """
        Get the command to include added and/or removed files in the working tree in the next commit.

        :param filenames: The filenames of the files to include in the next
                          commit (zero or more strings). If no arguments are
                          given all untracked files are added.
        :returns: A list of strings.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_checkout_command(self, revision, clean=False):
        """
        Get the command to update the working tree of the local repository.

        :param revision: The revision to check out (a string,
                         defaults to :attr:`default_revision`).
        :param clean: :data:`True` to discard changes in the working tree,
                      :data:`False` otherwise.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_commit_command(self, message, author=None):
        """
        Get the command to commit changes to tracked files in the working tree.

        :param message: The commit message (a string).
        :param author: An :class:`Author` object or :data:`None`.
        :returns: A list of strings.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_create_command(self):
        """
        Get the command to create the local repository.

        :returns: A list of strings.

        This method needs to be implemented by subclasses:

        - When :attr:`remote` is set the command is expected to create a local
          repository based on the remote repository.
        - When :attr:`remote` isn't set the command is expected to create an
          empty local repository.
        - In either case :attr:`bare` should be respected.
        """
        raise NotImplementedError()

    def get_create_branch_command(self, branch_name):
        """
        Get the command to create a new branch based on the working tree's revision.

        :param branch_name: The name of the branch to create (a string).
        :returns: A list of strings.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_create_tag_command(self, tag_name):
        """
        Get the command to create a new tag based on the working tree's revision.

        :param tag_name: The name of the tag to create (a string).
        :returns: A list of strings.
        """
        raise NotImplementedError()

    def get_delete_branch_command(self, branch_name, message=None, author=None):
        """
        Get the command to delete or close a branch in the local repository.

        :param branch_name: The name of the branch to create (a string).
        :param message: The message to use when closing the branch requires
                        a commit (a string, defaults to the string
                        "Closing branch NAME").
        :param author: Override :attr:`author` (refer to
                       :func:`coerce_author()` for details
                       on argument handling).
        :returns: A list of strings.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_export_command(self, directory, revision):
        """
        Get the command to export the complete tree from the local repository.

        :param directory: The directory where the tree should be exported
                          (a string).
        :param revision: The revision to export (a string,
                         defaults to :attr:`default_revision`).

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_merge_command(self, revision):
        """
        Get the command to merge a revision into the current branch (without committing the result).

        :param revision: The revision to merge in (a string,
                         defaults to :attr:`default_revision`).

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_pull_command(self, remote=None, revision=None):
        """
        Get the command to pull changes from a remote repository into the local repository.

        :param remote: The location of a remote repository (a string or :data:`None`).
        :param revision: A specific revision to pull (a string or :data:`None`).
        :returns: A list of strings.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_push_command(self, remote=None, revision=None):
        """
        Get the command to push changes from the local repository to a remote repository.

        :param remote: The location of a remote repository (a string or :data:`None`).
        :param revision: A specific revision to push (a string or :data:`None`).
        :returns: A list of strings.

        This method needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    def interactive_merge_conflict_handler(self, exception):
        """
        Give the operator a chance to interactively resolve merge conflicts.

        :param exception: An :exc:`~executor.ExternalCommandFailed` object.
        :returns: :data:`True` if the operator has interactively resolved any
                  merge conflicts (and as such the merge error doesn't need to
                  be propagated), :data:`False` otherwise.

        This method checks whether :data:`sys.stdin` is connected to a terminal
        to decide whether interaction with an operator is possible. If it is
        then an interactive terminal prompt is used to ask the operator to
        resolve the merge conflict(s). If the operator confirms the prompt, the
        merge error is swallowed instead of propagated. When :data:`sys.stdin`
        is not connected to a terminal or the operator denies the prompt the
        merge error is propagated.
        """
        if connected_to_terminal(sys.stdin):
            logger.info(compact("""
                It seems that I'm connected to a terminal so I'll give you a
                chance to interactively fix the merge conflict(s) in order to
                avoid propagating the merge error. Please mark or stage your
                changes but don't commit the result just yet (it will be done
                for you).
            """))
            while True:
                if prompt_for_confirmation("Ignore merge error because you've resolved all conflicts?"):
                    if self.merge_conflicts:
                        logger.warning("I'm still seeing merge conflicts, please double check! (%s)",
                                       concatenate(self.merge_conflicts))
                    else:
                        # The operator resolved all conflicts.
                        return True
                else:
                    # The operator wants us to propagate the error.
                    break
        return False

    def is_feature_branch(self, branch_name):
        """
        Try to determine whether a branch name refers to a feature branch.

        :param branch_name: The name of a branch (a string).
        :returns: :data:`True` if the branch name appears to refer to a feature
                  branch, :data:`False` otherwise.

        This method is used by :func:`merge_up()` to determine whether the
        feature branch that was merged should be deleted or closed.

        If the branch name matches :attr:`default_revision` or one of the
        branch names of the :attr:`releases` then it is not considered a
        feature branch, which means it won't be closed.
        """
        # The following checks are intentionally ordered from lightweight to heavyweight.
        if branch_name == self.default_revision:
            # The default branch is never a feature branch.
            return False
        elif branch_name not in self.branches:
            # Invalid branch names can't be feature branch names.
            return False
        elif self.release_scheme == 'branches' and branch_name in self.release_branches:
            # Release branches are not feature branches.
            return False
        else:
            # Other valid branches are considered feature branches.
            return True

    def mark_updated(self):
        """Mark a successful update so that :attr:`last_updated` can report it."""
        self.context.write_file(self.last_updated_file, '%i\n' % time.time())

    def merge(self, revision=None):
        """
        Merge a revision into the current branch (without committing the result).

        :param revision: The revision to merge in (a string or :data:`None`,
                         defaults to :attr:`default_revision`).
        :raises: The following exceptions can be raised:

                 - :exc:`~vcs_repo_mgr.exceptions.MergeConflictError` if the
                   merge command reports an error and merge conflicts are
                   detected that can't be (or haven't been) resolved
                   interactively.
                 - :exc:`~executor.ExternalCommandFailed` if the merge command
                   reports an error but no merge conflicts are detected.

        Refer to the documentation of :attr:`merge_conflict_handler` if you
        want to customize the handling of merge conflicts.
        """
        # Make sure the local repository exists and supports a working tree.
        self.create()
        self.ensure_working_tree()
        # Merge the specified revision into the current branch.
        revision = revision or self.default_revision
        logger.info("Merging revision '%s' in %s ..", revision, format_path(self.local))
        try:
            self.context.execute(*self.get_merge_command(revision))
        except ExternalCommandFailed as e:
            # Check for merge conflicts.
            conflicts = self.merge_conflicts
            if conflicts:
                # Always warn about merge conflicts and log the relevant filenames.
                explanation = format("Merge failed due to conflicts in %s! (%s)",
                                     pluralize(len(conflicts), "file"),
                                     concatenate(sorted(conflicts)))
                logger.warning("%s", explanation)
                if self.merge_conflict_handler(e):
                    # Trust the operator (or caller) and swallow the exception.
                    return
                else:
                    # Raise a specific exception for merge conflicts.
                    raise MergeConflictError(explanation)
            else:
                # Don't swallow the exception or obscure the traceback
                # in case we're not `allowed' to handle the exception.
                raise

    @mutable_property
    def merge_conflict_handler(self):
        """The merge conflict handler (a callable, defaults to :func:`interactive_merge_conflict_handler()`)."""
        return self.interactive_merge_conflict_handler

    def merge_up(self, target_branch=None, feature_branch=None, delete=True, create=True):
        """
        Merge a change into one or more release branches and the default branch.

        :param target_branch: The name of the release branch where merging of
                              the feature branch starts (a string or
                              :data:`None`, defaults to
                              :attr:`current_branch`).
        :param feature_branch: The feature branch to merge in (any value
                               accepted by :func:`coerce_feature_branch()`).
        :param delete: :data:`True` (the default) to delete or close the
                       feature branch after it is merged, :data:`False`
                       otherwise.
        :param create: :data:`True` to automatically create the target branch
                       when it doesn't exist yet, :data:`False` otherwise.
        :returns: If `feature_branch` is given the global revision id of the
                  feature branch is returned, otherwise the global revision id
                  of the target branch (before any merges performed by
                  :func:`merge_up()`) is returned. If the target branch is
                  created by :func:`merge_up()` and `feature_branch` isn't
                  given then :data:`None` is returned.
        :raises: The following exceptions can be raised:

                 - :exc:`~exceptions.TypeError` when `target_branch` and
                   :attr:`current_branch` are both :data:`None`.
                 - :exc:`~exceptions.ValueError` when the given target branch
                   doesn't exist (based on :attr:`branches`) and `create` is
                   :data:`False`.
                 - :exc:`~executor.ExternalCommandFailed` if a command fails.
        """
        timer = Timer()
        repository_was_created = self.create()
        revision_to_merge = None
        # Default the target branch to the current branch.
        if not target_branch:
            target_branch = self.current_branch
            if not target_branch:
                raise TypeError("You need to specify the target branch! (where merging starts)")
        # Parse the feature branch specification.
        feature_branch = coerce_feature_branch(feature_branch) if feature_branch else None
        # Make sure we start with a clean working tree.
        self.ensure_clean()
        # Make sure we're up to date with our upstream repository (if any).
        if not repository_was_created:
            self.pull()
        # Checkout or create the target branch.
        logger.debug("Checking if target branch exists (%s) ..", target_branch)
        if target_branch in self.branches:
            self.checkout(revision=target_branch)
            # Get the global revision id of the release branch we're about to merge.
            revision_to_merge = self.find_revision_id(target_branch)
        elif not create:
            raise ValueError("The target branch %r doesn't exist!" % target_branch)
        elif self.compiled_filter.match(target_branch):
            self.create_release_branch(target_branch)
        else:
            self.create_branch(target_branch)
        # Check if we need to merge in a feature branch.
        if feature_branch:
            if feature_branch.location:
                # Pull in the feature branch.
                self.pull(remote=feature_branch.location,
                          revision=feature_branch.revision)
            # Get the global revision id of the feature branch we're about to merge.
            revision_to_merge = self.find_revision_id(feature_branch.revision)
            # Merge in the feature branch.
            self.merge(revision=feature_branch.revision)
            # Commit the merge.
            self.commit(message="Merged %s" % feature_branch.expression)
        # We skip merging up through release branches when the target branch is
        # the default branch (in other words, there's nothing to merge up).
        if target_branch != self.default_revision:
            # Find the release branches in the repository.
            release_branches = [release.revision.branch for release in self.ordered_releases]
            logger.debug("Found %s: %s",
                         pluralize(len(release_branches), "release branch", "release branches"),
                         concatenate(release_branches))
            # Find the release branches after the target branch.
            later_branches = release_branches[release_branches.index(target_branch) + 1:]
            logger.info("Found %s after target branch (%s): %s",
                        pluralize(len(later_branches), "release branch", "release branches"),
                        target_branch,
                        concatenate(later_branches))
            # Determine the branches that need to be merged.
            branches_to_upmerge = later_branches + [self.default_revision]
            logger.info("Merging up from '%s' to %s: %s",
                        target_branch,
                        pluralize(len(branches_to_upmerge), "branch", "branches"),
                        concatenate(branches_to_upmerge))
            # Merge the feature branch up through the selected branches.
            merge_queue = [target_branch] + branches_to_upmerge
            while len(merge_queue) >= 2:
                from_branch = merge_queue[0]
                to_branch = merge_queue[1]
                logger.info("Merging '%s' into '%s' ..", from_branch, to_branch)
                self.checkout(revision=to_branch)
                self.merge(revision=from_branch)
                self.commit(message="Merged %s" % from_branch)
                merge_queue.pop(0)
        # Check if we need to delete or close the feature branch.
        if delete and feature_branch and self.is_feature_branch(feature_branch.revision):
            # Delete or close the feature branch.
            self.delete_branch(
                branch_name=feature_branch.revision,
                message="Closing feature branch %s" % feature_branch.revision,
            )
            # Update the working tree to the default branch.
            self.checkout()
        logger.info("Done! Finished merging up in %s.", timer)
        return revision_to_merge

    def pull(self, remote=None, revision=None):
        """
        Pull changes from a remote repository into the local repository.

        :param remote: The location of a remote repository (a string or :data:`None`).
        :param revision: A specific revision to pull (a string or :data:`None`).

        If used in combination with :class:`limit_vcs_updates` this won't
        perform redundant updates.
        """
        remote = remote or self.remote
        # Make sure the local repository exists.
        if self.create() and (remote == self.remote or not remote):
            # Don't waste time pulling from a remote repository that we just cloned.
            logger.info("Skipping pull from default remote because we just created the local %s repository.",
                        self.friendly_name)
            return
        # Make sure there is a remote repository to pull from.
        if not (remote or self.default_pull_remote):
            logger.info("Skipping pull (no default remote is configured).")
            return
        # Check if we're about to perform a redundant pull.
        update_limit = int(os.environ.get(UPDATE_VARIABLE, '0'))
        if update_limit and self.last_updated >= update_limit:
            logger.info("Skipping pull due to update limit.")
            return
        # Pull the changes from the remote repository.
        timer = Timer()
        logger.info("Pulling changes from %s into local %s repository (%s) ..",
                    remote or "default remote", self.friendly_name, format_path(self.local))
        self.context.execute(*self.get_pull_command(remote=remote, revision=revision))
        logger.debug("Took %s to pull changes from remote %s repository.", timer, self.friendly_name)
        self.mark_updated()

    def push(self, remote=None, revision=None):
        """
        Push changes from the local repository to a remote repository.

        :param remote: The location of a remote repository (a string or :data:`None`).
        :param revision: A specific revision to push (a string or :data:`None`).

        .. warning:: Depending on the version control backend the push command
                     may fail when there are no changes to push. No attempt has
                     been made to make this behavior consistent between
                     implementations (although the thought has crossed my
                     mind and I'll likely revisit this in the future).
        """
        # Make sure the local repository exists.
        self.ensure_exists()
        # Make sure there is a remote repository to push to.
        if not (remote or self.remote or self.default_push_remote):
            logger.info("Skipping push (no default remote is configured).")
        # Push the changes to the remote repository.
        timer = Timer()
        logger.info("Pushing changes from %s to %s ..",
                    format_path(self.local),
                    remote or self.remote or "default remote")
        self.context.execute(*self.get_push_command(remote, revision))
        logger.debug("Took %s to push changes to remote repository.", timer)

    def release_to_branch(self, release_id):
        """
        Shortcut to translate a release identifier to a branch name.

        :param release_id: A :attr:`Release.identifier` value (a string).
        :returns: A branch name (a string).
        :raises: :exc:`~exceptions.TypeError` when :attr:`release_scheme` isn't
                 'branches'.
        """
        self.ensure_release_scheme('branches')
        return self.releases[release_id].revision.branch

    def release_to_tag(self, release_id):
        """
        Shortcut to translate a release identifier to a tag name.

        :param release_id: A :attr:`Release.identifier` value (a string).
        :returns: A tag name (a string).
        :raises: :exc:`~exceptions.TypeError` when :attr:`release_scheme` isn't
                 'tags'.
        """
        self.ensure_release_scheme('tags')
        return self.releases[release_id].revision.tag

    def select_release(self, highest_allowed_release):
        """
        Select the newest release that is not newer than the given release.

        :param highest_allowed_release: The identifier of the release that sets
                                        the upper bound for the selection (a
                                        string).
        :returns: The identifier of the selected release (a string).
        :raises: :exc:`~vcs_repo_mgr.exceptions.NoMatchingReleasesError`
                 when no matching releases are found.
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

    def update(self, remote=None):
        """Alias for :func:`pull()` to enable backwards compatibility."""
        self.pull(remote=remote)

    def update_context(self):
        """
        Try to ensure that external commands are executed in the local repository.

        What :func:`update_context()` does depends on whether the directory
        given by :attr:`local` exists:

        - If :attr:`local` exists then the working directory of :attr:`context`
          will be set to :attr:`local`. This is to ensure that version control
          commands are run inside of the intended version control repository.

        - If :attr:`local` doesn't exist then the working directory of
          :attr:`context` is cleared. This avoids external commands from
          failing due to an invalid (non existing) working directory.
        """
        if self.context.is_directory(self.local):
            # Set the working directory of the execution context
            # to the directory containing the local repository.
            self.context.options['directory'] = self.local
        else:
            # Clear the execution context's working directory.
            self.context.options.pop('directory', None)


class RepositoryMeta(type):

    """Metaclass for automatic registration of :class:`Repository` subclasses."""

    def __init__(cls, name, bases, dict):
        """Register a :class:`Repository` subclass as soon as it is defined."""
        # Initialize our superclass.
        type.__init__(cls, name, bases, dict)
        # Don't register the Repository class itself.
        if issubclass(cls, Repository):
            # Register the Repository subclass.
            REPOSITORY_TYPES.add(cls)


# We apply the metaclass after defining the `Repository' class, otherwise we'll
# cause a NameError exception because RepositoryMeta.__init__() is called
# before Repository has been defined...
Repository = add_metaclass(RepositoryMeta)(Repository)


class Release(PropertyManager):

    """
    Release objects are revisions that specify a software "release".

    Most version control repositories are used to store software projects and
    most software projects have the concept of "releases": *Specific versions
    of a software project that have been given a human and machine readable
    version number (in one form or another).* :class:`Release` objects exist
    to capture this concept in a form that is concrete enough to be generally
    useful while being abstract enough to be used in various ways (because
    every software project has its own scheme for releases).

    By default the :class:`Release` objects created by
    :attr:`Repository.releases` are based on :attr:`Repository.tags`, but using
    :attr:`Repository.release_scheme` you can specify that releases should be
    based on :attr:`Repository.branches` instead. Additionally you can use
    :attr:`Repository.release_filter` to specify a regular expression that
    will be used to distinguish valid releases from other tags/branches.
    """

    @required_property
    def revision(self):
        """The revision that the release relates to (a :class:`Revision` object)."""

    @required_property
    def identifier(elf):
        """
        The name of the tag or branch (a string).

        If a :attr:`Repository.release_filter` containing a single capture
        group is used this identifier is set to the captured substring instead
        of the complete tag or branch name.
        """


class Remote(PropertyManager):

    """A remote repository connected to a local repository."""

    @required_property
    def default(self):
        """:data:`True` if this is a default remote repository, :data:`False` otherwise."""

    @required_property
    def location(self):
        """The location of the remote repository (a string)."""

    @mutable_property
    def name(self):
        """The name of the remote repository (a string or :data:`None`)."""

    @required_property(repr=False)
    def repository(self):
        """The local repository (a :class:`Repository` object)."""

    @required_property
    def roles(self):
        """
        The roles of the remote repository (a list of of strings).

        Currently the roles 'pull' and 'push' are supported.
        """


class Revision(PropertyManager):

    """:class:`Revision` objects represent a specific revision in a :class:`Repository`."""

    @mutable_property
    def branch(self):
        """
        The name of the branch in which the revision exists (a string or :data:`None`).

        When this property is not available its value will be :data:`None`.
        """

    @required_property(repr=False)
    def repository(self):
        """The local repository that contains the revision (a :class:`Repository` object)."""

    @required_property
    def revision_id(self):
        """
        The global revision id of the revision (a string containing a hexadecimal hash).

        Global revision ids are comparable between local and remote
        repositories, which makes them useful to unambiguously refer to a
        revision and its history.

        This property is always available.
        """

    @mutable_property(cached=True)
    def revision_number(self):
        """
        The local revision number of the revision (an integer or :data:`None`).

        Local revision numbers are integers that increment with each commit.
        This makes them useful as a build number or when a simple, incrementing
        version number is required. They should not be used to unambiguously
        refer to a revision (use :attr:`revision_id` for that instead).

        When this property is not available its value will be :data:`None`.
        """
        return self.repository.find_revision_number(self.revision_id)

    @mutable_property
    def tag(self):
        """
        The name of the tag associated to the revision (a string or :data:`None`).

        When this property is not available its value will be :data:`None`.
        """

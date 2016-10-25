# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 26, 2016
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
  which implement support for a specific VCS system (:class:`BzrRepo`,
  :class:`GitRepo` and :class:`HgRepo`).

  - :class:`Repository` objects construct :class:`Revision` and
    :class:`Release` objects so you'll most likely be using these.

- The :func:`find_configured_repository()` function constructs instances of
  :class:`Repository` subclasses based on configuration files. This is
  useful when you find yourself frequently instantiating the same
  :class:`Repository` instances and you'd rather refer to a repository name
  in your code than repeating the complete local and remote locations
  everywhere in your code (this kind of duplication is bad after all :-).

- You can choose to directly instantiate :class:`BzrRepo`,
  :class:`GitRepo` and/or :class:`HgRepo` instances or you can use one of
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

==================================  =================  =====================  =========
Python API (`vcs-repo-mgr`)         Bazaar             Git                    Mercurial
==================================  =================  =====================  =========
:func:`Repository.create()`         bzr branch         git clone              hg clone
:func:`Repository.update()`         bzr pull           git fetch              hg pull
:func:`Repository.push()`           bzr push           git push               hg push
:func:`Repository.checkout()`       (not implemented)  git checkout           hg update
:func:`Repository.commit()`         (not implemented)  git commit             hg commit
:func:`Repository.create_branch()`  (not implemented)  git checkout -b        hg branch
:func:`Repository.merge()`          (not implemented)  git merge --no-commit  hg merge
==================================  =================  =====================  =========

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
import functools
import logging
import operator
import os
import re
import sys
import tempfile
import time

# External dependencies.
from executor import ExternalCommandFailed, execute, quote
from humanfriendly import Timer, coerce_boolean, format_path, parse_path
from humanfriendly.text import compact, concatenate, format, pluralize, split
from humanfriendly.prompts import prompt_for_confirmation
from humanfriendly.terminal import connected_to_terminal
from natsort import natsort, natsort_key
from property_manager import PropertyManager, lazy_property, required_property, writable_property
from six import string_types
from six.moves import configparser
from six.moves import urllib_parse as urlparse

# Modules included in our package.
from vcs_repo_mgr.exceptions import (
    AmbiguousRepositoryNameError,
    MergeConflictError,
    NoMatchingReleasesError,
    NoSuchRepositoryError,
    UnknownRepositoryTypeError,
    WorkingTreeNotCleanError,
)

# Semi-standard module versioning.
__version__ = '0.33'

USER_CONFIG_FILE = os.path.expanduser('~/.vcs-repo-mgr.ini')
"""The absolute pathname of the user-specific configuration file (a string)."""

SYSTEM_CONFIG_FILE = '/etc/vcs-repo-mgr.ini'
"""The absolute pathname of the system wide configuration file (a string)."""

UPDATE_VARIABLE = 'VCS_REPO_MGR_UPDATE_LIMIT'
"""The name of the environment variable that's used to rate limit repository updates (a string)."""

KNOWN_RELEASE_SCHEMES = ('branches', 'tags')
"""The names of valid release schemes (a tuple of strings)."""

REPOSITORY_TYPES = set()
"""Available :class:`Repository` subclasses (a :class:`set` of :class:`type` objects)."""

# Initialize a logger.
logger = logging.getLogger(__name__)

# Inject our logger into all execute() calls.
execute = functools.partial(execute, logger=logger)

# Dictionary of previously constructed Repository objects.
loaded_repositories = {}


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
    return FeatureBranchSpec(value)


def coerce_repository(value):
    """
    Convert a string (taken to be a repository name or location) to a :class:`Repository` object.

    :param value: The name or location of a repository (a string) or a
                  :class:`Repository` object.
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
        kw = {'local' if os.path.exists(location) else 'remote': location}
        try:
            return repository_factory(vcs_type, **kw)
        except UnknownRepositoryTypeError:
            pass
    # Try to infer the repository type of an existing local clone.
    for cls in REPOSITORY_TYPES:
        if cls.contains_repository(value):
            return repository_factory(cls, local=value)
    # Check for locations that end with `.git' (a common idiom for remote
    # git repositories) even if the location isn't prefixed with `git+'.
    if value.endswith('.git'):
        kw = {'local' if os.path.exists(value) else 'remote': value}
        return repository_factory(GitRepo, **kw)
    # If all else fails, at least give a clear explanation of the problem.
    msg = ("The string %r doesn't match the name of any configured repository"
           " and it also can't be parsed as the location of a remote"
           " repository! (maybe you forgot to prefix the type?)")
    raise ValueError(msg % value)


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
        local_path = options.get('local')
        if local_path:
            # Expand a leading tilde and/or environment variables.
            local_path = parse_path(local_path)
        bare = options.get('bare', None)
        if bare is not None:
            # Default to bare=None but enable configuration file(s)
            # to enforce bare=True or bare=False.
            bare = coerce_boolean(bare)
        return repository_factory(
            vcs_type,
            local=local_path,
            remote=options.get('remote'),
            bare=bare,
            release_scheme=options.get('release-scheme'),
            release_filter=options.get('release-filter'),
        )


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
        for cls in REPOSITORY_TYPES:
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


def find_cache_directory(remote):
    """
    Find the directory where temporary local checkouts are to be stored.

    :returns: The absolute pathname of a directory (a string).
    """
    return os.path.join('/var/cache/vcs-repo-mgr' if os.access('/var/cache', os.W_OK) else tempfile.gettempdir(),
                        urlparse.quote(remote, safe=''))


def normalize_name(name):
    """
    Normalize a repository name.

    :param name: The name of a repository (a string).
    :returns: The normalized repository name (a string).

    This makes sure that minor variations in character case and/or punctuation
    don't disrupt the name matching in :func:`find_configured_repository()`.
    """
    return re.sub('[^a-z0-9]', '', name.lower())


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


class Repository(PropertyManager):

    """
    Base class for version control repository interfaces.

    Please don't use this directly, use subclasses like :class:`HgRepo` and/or
    :class:`GitRepo` instead.
    """

    ALIASES = []
    """
    A list of strings with aliases/names for the repository type.

    The :func:`repository_factory()` function searches the :attr:`ALIASES` of
    all known subclasses of :class:`Repository` in order to map repository
    specifications like ``hg+https://bitbucket.org/ianb/virtualenv`` to the
    correct :class:`Repository` subclass.
    """

    @staticmethod
    def get_vcs_directory(directory):
        """
        Get the pathname of the directory containing the VCS metadata files.

        :param directory: The pathname of a local directory (a string). The
                          directory doesn't have to exist.
        :returns: A subdirectory of the given directory or the directory itself
                  (a string).

        This static method needs to be implemented by :class:`Repository`
        subclasses.
        """
        raise NotImplementedError()

    @classmethod
    def contains_repository(cls, directory):
        """
        Check whether the given directory contains a local clone.

        :param directory: The pathname of a local directory (a string).
        :returns: :data:`True` if it looks like the directory contains a local
                  clone, :data:`False` otherwise.

        By default :func:`contains_repository()` just checks whether the result
        of :func:`get_vcs_directory()` points to an existing local directory.
        :class:`Repository` subclasses can override this class method to
        improve detection accuracy.
        """
        return os.path.isdir(cls.get_vcs_directory(directory))

    def __init__(self, local=None, remote=None, bare=None, release_scheme=None, release_filter=None, **kw):
        """
        Initialize a version control repository interface.

        :param local: Used to set :attr:`local`.
        :param remote: Used to set :attr:`remote`.
        :param bare: Used to set :attr:`bare`.
        :param release_scheme: Used to set :attr:`release_scheme`.
        :param release_filter: Used to set :attr:`release_filter`.
        :raises: :exc:`~exceptions.ValueError` for any of the following:

                 - Neither the local repository directory nor the remote
                   repository location is specified.
                 - The local repository directory doesn't exist and no remote
                   repository location is specified.
                 - The local repository directory already exists but
                   :attr:`is_bare` doesn't match the status requested with the
                   `bare` keyword argument.
                 - The given release scheme is not 'tags' or 'branches'.
                 - The release filter regular expression contains more than one
                   capture group (if you need additional groups but without the
                   capturing aspect use a non-capturing group).

        This method supports two calling conventions:

        1. The old calling convention consists of up to five positional
           arguments and is supported to preserve backwards compatibility
           (refer to the arguments documented above).
        2. The new calling convention is to pass only the required keyword
           arguments, this improves extensibility. Please refer to the
           :class:`~property_manager.PropertyManager` documentation for details
           about the handling of keyword arguments.
        """
        # Translate positional arguments (dictated by backwards compatibility)
        # into keyword arguments (expected by our superclass constructor).
        if local is not None:
            kw['local'] = local
        if remote is not None:
            kw['remote'] = remote
        if bare is not None:
            kw['bare'] = bare
        if release_scheme is not None:
            kw['release_scheme'] = release_scheme
        if release_filter is not None:
            kw['release_filter'] = release_filter
        # Make sure the caller specified at least the local *or* remote.
        if not kw.get('local') and not kw.get('remote'):
            raise ValueError("No local and no remote repository specified! (one of the two is required)")
        # Initialize super classes.
        super(Repository, self).__init__(**kw)
        # Make sure the release scheme was properly specified.
        if self.release_scheme not in KNOWN_RELEASE_SCHEMES:
            msg = "Release scheme %r is not supported! (valid options are %s)"
            raise ValueError(msg % (self.release_scheme, concatenate(map(repr, KNOWN_RELEASE_SCHEMES))))
        # At this point we should be dealing with a regular expression object:
        # Make sure the regular expression has zero or one capture group.
        if self.compiled_filter.groups > 1:
            raise ValueError(compact("""
                Release filter regular expression pattern is expected to have
                zero or one capture group, but it has {count} instead!
            """, count=self.compiled_filter.groups))
        # Validation that's conditional to whether the local clone exists.
        if self.exists:
            if self.bare != self.is_bare:
                # Abort if the caller's preference for the existence of a
                # working tree doesn't match the existing repository state.
                raise ValueError(format(
                    "%s was requested but existing local clone (%s) is a %s!",
                    "Bare checkout" if self.bare else "Checkout with working tree",
                    self.local,
                    "bare checkout" if self.is_bare else "checkout with a working tree",
                ))
        else:
            # Make sure we know how to get access to (a copy of) the repository.
            if not self.remote:
                msg = "Local repository (%r) doesn't exist and no remote repository specified!"
                raise ValueError(msg % self.local)

    @required_property(cached=True)
    def local(self):
        """
        The pathname of the repository's local clone (a string).

        If :attr:`remote` is set but :attr:`local` isn't set it is assumed that
        the location of the local clone doesn't matter (because `vcs-repo-mgr`
        will act as an exclusive proxy to the local clone) and :attr:`local` is
        computed (once) using :func:`find_cache_directory()`.
        """
        if self.remote:
            return find_cache_directory(self.remote)

    @writable_property
    def remote(self):
        """
        The location of the remote (upstream) repository (a string).

        In most cases :attr:`remote` will be a URL pointing to a remote
        repository but it can also be a pathname of a local directory. If
        :attr:`remote` isn't given then :attr:`local` must be set to the
        pathname of an existing local repository clone.
        """

    @writable_property
    def bare(self):
        """
        Whether the local repository clone should be bare (a boolean or :data:`None`).

        This property specifies whether the local repository clone should have
        a working tree or not:

        - :data:`True` means the local clone doesn't need and shouldn't have a
          working tree (in older versions of `vcs-repo-mgr` this was the
          default and only choice).

        - :data:`False` means the local clone does need a working tree (for
          example because you want to commit).

        The value of :attr:`bare` defaults to :attr:`is_bare` for repositories
        with an existing local clone, if only to preserve compatibility with
        versions of `vcs-repo-mgr` that didn't have working tree support. For
        repositories without a local clone, :attr:`bare` defaults to
        :data:`True` so that :func:`create()` defaults to creating bare clones.

        If :attr:`bare` is explicitly set and the local clone already exists it
        will be checked by :func:`__init__()` to make sure that the values of
        :attr:`bare` and :attr:`is_bare` match. If they don't an exception will
        be raised.
        """
        return self.is_bare if self.exists else True

    @writable_property
    def release_scheme(self):
        """
        The repository's release scheme (a string, defaults to 'tags').

        The value of :attr:`release_scheme` determines whether
        :attr:`Repository.releases` is based on :attr:`Repository.tags` or
        :attr:`Repository.branches`. It should match one of the values in
        :data:`KNOWN_RELEASE_SCHEMES`.
        """
        return 'tags'

    @writable_property
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

    @property
    def compiled_filter(self):
        """
        The result of :func:`re.compile()` on :attr:`release_filter`.

        If :attr:`release_filter` isn't a string then it is assumed to be a
        compiled regular expression object and returned directly.
        """
        pattern = self.release_filter
        if isinstance(pattern, string_types):
            pattern = re.compile(pattern)
        return pattern

    @writable_property
    def author(self):
        """
        The author for commits created using :func:`commit()` (a string).

        This is a string of the form ``name <email>`` where both the name and
        the email address are required (this is actually a slight
        simplification, but I digress).

        The :attr:`author` property needs to be provided by subclasses and/or
        the caller (by passing it to :func:`__init__()` as a keyword
        argument).
        """

    @required_property
    def friendly_name(self):
        """
        The human friendly name for the repository's version control system (a string).

        The :attr:`friendly_name` property needs to be provided by subclasses
        and/or the caller (by passing it to :func:`__init__()` as a keyword
        argument).
        """

    @required_property
    def vcs_directory(self):
        """The pathname of the directory containing the local clone's VCS files (a string)."""
        return self.get_vcs_directory(self.local)

    @required_property
    def default_revision(self):
        """
        The default revision for the given version control system and repository (a string).

        The :attr:`default_revision` property needs to be implemented by
        subclasses and/or passed to :func:`__init__()` as a keyword argument.
        """

    @property
    def current_branch(self):
        """
        The name of the branch that's currently checked out in the working tree (a string or :data:`None`).

        The :attr:`current_branch` property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def merge_conflicts(self):
        """
        The filenames of any files with merge conflicts (a list of strings).

        The :attr:`merge_conflicts` property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def exists(self):
        """:data:`True` if the local clone exists, :data:`False` otherwise."""
        return self.contains_repository(self.local)

    @property
    def last_updated_file(self):
        """
        The pathname of the file used to mark the last successful update (a string).

        Used internally by the :attr:`last_updated` property.
        """
        return os.path.join(self.vcs_directory, 'vcs-repo-mgr.txt')

    @property
    def last_updated(self):
        """
        The date/time when `vcs-repo-mgr` last checked for updates (an integer).

        Used internally by :func:`update()` when used in combination with
        :class:`limit_vcs_updates`. The value is a UNIX time stamp (0 for
        remote repositories that don't have a local clone yet).
        """
        try:
            with open(self.last_updated_file) as handle:
                return int(handle.read())
        except Exception:
            return 0

    def mark_updated(self):
        """
        Mark a successful update so that :attr:`last_updated` can report it.

        Used internally by :func:`update()`.
        """
        with open(self.last_updated_file, 'w') as handle:
            handle.write('%i\n' % time.time())

    def get_author(self, author=None):
        """
        Get the name and email address of the author for commits.

        :param author: Override the value of :attr:`author` (a string). If
                       :attr:`author` is :data:`None` this argument is
                       required.
        :returns: A dictionary with the keys 'author_name' and 'author_email'
                 and string values.
        :raises: :exc:`~exceptions.ValueError` when no author information is
                 available or the author information is in the wrong format.
        """
        author = author or self.author
        if not author:
            raise ValueError("You need to specify an author!")
        match = re.match('^(.+?) <(.+?)>$', author)
        if not match:
            msg = "The provided author information (%s) isn't in the 'name <email>' format!"
            raise ValueError(msg % author)
        name = match.group(1)
        email = match.group(2)
        return dict(
            author_name=name,
            author_email=email,
            author_combined=u"%s <%s>" % (name, email),
        )

    def get_command(self, method_name, attribute_name, **kw):
        """
        Get the command for a given VCS operation.

        :param method_name: The name of the method that wants to execute the
                            command (a string).
        :param attribute_name: The name of the attribute that is expected to
                               hold the VCS command (a string).
        :param kw: Any keyword arguments are shell escaped and interpolated
                   into the VCS command.
        :returns: The VCS command (a string).
        :raises: :exc:`~exceptions.NotImplementedError` when the requested
                 attribute isn't available (e.g. because the VCS operation
                 isn't supported).
        """
        command_template = getattr(self, attribute_name, None)
        if command_template is None:
            msg = "Repository.%s() not supported for %s repositories!"
            raise NotImplementedError(msg % (method_name, self.friendly_name))
        quoted_arguments = dict((k, quote(v)) for k, v in kw.items())
        return command_template.format(**quoted_arguments)

    def create(self, remote=None):
        """
        Create the local clone of the remote version control repository.

        :param remote: Overrides the value of :attr:`remote` for the duration
                       of the call to :func:`create()`.
        :returns: :data:`True` if the repository was just created,
                  :data:`False` if it already existed.
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        It's not an error if the repository already exists.
        """
        if self.exists:
            return False
        else:
            remote = remote or self.remote
            logger.info("Creating %s clone of %s at %s ..", self.friendly_name, remote, self.local)
            execute(self.get_command(
                method_name='create',
                attribute_name='create_command' if self.bare else 'create_command_non_bare',
                local=self.local,
                remote=remote,
            ))
            self.mark_updated()
            return True

    def update(self, remote=None):
        """
        Update the local clone of the remote version control repository.

        :param remote: Overrides the value of :attr:`remote` for the duration
                       of the call to :func:`update()`.
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        If used in combination with :class:`limit_vcs_updates` this won't
        perform redundant updates.

        .. note:: Automatically creates the local repository on the first run.
        """
        remote = remote or self.remote
        update_limit = int(os.environ.get(UPDATE_VARIABLE, '0'))
        if not remote:
            # If there's no remote there's nothing we can do!
            logger.debug("Skipping update (pull) because there's no remote.")
        elif self.create(remote=remote):
            # If the local clone didn't exist yet and we just created it,
            # we can skip the update (since there's no point).
            logger.debug("Skipping update (pull) because local repository was just created.")
        elif update_limit and self.last_updated >= update_limit:
            # If an update limit has been enforced we also skip the update.
            logger.debug("Skipping update (pull) due to update limit.")
        else:
            logger.info("Pulling %s updates from %s into %s ..", self.friendly_name, remote, self.local)
            execute(self.get_command(
                method_name='update',
                attribute_name='update_command',
                local=self.local,
                remote=remote,
            ))
            self.mark_updated()

    def push(self, remote=None):
        """
        Push changes from the local repository to a remote repository.

        :param remote: Overrides the value of :attr:`remote` for the duration
                       of the call to :func:`push()`.
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        .. warning:: Depending on the version control backend the push command
                     may fail when there are no changes to push. No attempt has
                     been made to make this behavior consistent between
                     implementations (although the thought has crossed my
                     mind and I'll likely revisit this in the future).
        """
        remote = remote or self.remote
        if not remote:
            # If there's no remote there's nothing we can do!
            logger.debug("Skipping push because there's no remote.")
        else:
            logger.info("Pushing %s updates from %s to %s ..", self.friendly_name, self.local, remote)
            execute(self.get_command(
                method_name='push',
                attribute_name='push_command',
                local=self.local,
                remote=remote,
            ))

    def checkout(self, revision=None, clean=False):
        """
        Update the repository's local working tree to the specified revision.

        :param revision: The revision to check out (a string, defaults to
                         :attr:`default_revision`).
        :param clean: If :data:`True` any changes in the working tree are
                      discarded (defaults to :data:`False`).
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        revision = revision or self.default_revision
        logger.info("Checking out revision %s in %s ..", revision, self.local)
        execute(self.get_command(
            method_name='checkout',
            attribute_name='checkout_command_clean' if clean else 'checkout_command',
            local=self.local,
            revision=revision,
        ))

    def create_branch(self, branch_name):
        """
        Create a new branch based on the working tree's revision.

        :param branch_name: The name of the branch to create (a string).
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        This method automatically checks out the new branch, but note that the
        new branch may not actually exist until a commit has been made on the
        branch.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        logger.info("Creating branch %s in %s ..", branch_name, self.local)
        execute(self.get_command(
            method_name='create_branch',
            attribute_name='create_branch_command',
            local=self.local,
            branch_name=branch_name,
        ))

    def delete_branch(self, branch_name, message=None):
        """
        Delete (or close) a branch in the local repository clone.

        :param branch_name: The name of the branch to delete (a string).
        :param message: The message to use when closing the branch requires a
                        commit (a string or :data:`None`). Defaults to "Closing
                        branch NAME".
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        logger.info("Deleting branch %s in %s ..", branch_name, self.local)
        message = message or ("Closing branch %s" % branch_name)
        execute(self.get_command(
            method_name='delete_branch',
            attribute_name='delete_branch_command',
            local=self.local,
            branch_name=branch_name,
            message=message,
            **self.get_author()
        ))

    def merge(self, revision=None):
        """
        Merge a revision into the current branch (without committing the result).

        :param revision: The revision to merge in (a string, defaults to
                         :attr:`default_revision`).
        :raises: The following exceptions can be raised:

                 - :exc:`~vcs_repo_mgr.exceptions.MergeConflictError` if the
                   merge command reports an error and merge conflicts are
                   detected that can't be (or haven't been) resolved
                   interactively.
                 - :exc:`~executor.ExternalCommandFailed` if the merge command
                   reports an error but no merge conflicts are detected.

        Refer to the documentation of :attr:`merge_conflict_handler` if you
        want to customize the handling of merge conflicts.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        revision = revision or self.default_revision
        logger.info("Merging revision %s in %s ..", revision, self.local)
        try:
            execute(self.get_command(
                method_name='merge',
                attribute_name='merge_command',
                local=self.local,
                revision=revision,
                **self.get_author()
            ))
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

    @writable_property
    def merge_conflict_handler(self):
        """The merge conflict handler (a callable, defaults to :func:`interactive_merge_conflict_handler()`)."""
        return self.interactive_merge_conflict_handler

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

    def merge_up(self, target_branch=None, feature_branch=None, delete=True):
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
        :returns: If `feature_branch` is given the global revision id of the
                  feature branch is returned, otherwise the global revision id
                  of the target branch (before any merges performed by
                  :func:`merge_up()`) is returned.
        :raises: The following exceptions can be raised:

                 - :exc:`~exceptions.TypeError` when `target_branch` and
                   :attr:`current_branch` are both :data:`None`.
                 - :exc:`~exceptions.ValueError` when the given target branch
                   doesn't exist (based on :attr:`branches`).
                 - :exc:`~executor.ExternalCommandFailed` if a command fails.

        .. note:: Automatically creates the local repository on the first run.
        """
        timer = Timer()
        was_created = self.create()
        # Validate the target branch or select the default target branch.
        if target_branch:
            if target_branch not in self.branches:
                raise ValueError("The target branch %r doesn't exist!" % target_branch)
        else:
            target_branch = self.current_branch
            if not target_branch:
                raise TypeError("You need to specify the target branch! (where merging starts)")
        # Parse the feature branch specification.
        feature_branch = coerce_feature_branch(feature_branch) if feature_branch else None
        # Make sure we start with a clean working tree.
        self.ensure_clean()
        # Make sure we're up to date with our upstream repository (if any).
        if not was_created:
            self.update()
        # Check out the target branch.
        self.checkout(revision=target_branch)
        # Get the global revision id of the release branch we're about to merge.
        revision_to_merge = self.find_revision_id(target_branch)
        # Check if we need to merge in a feature branch.
        if feature_branch:
            if feature_branch.location:
                # Pull in the feature branch.
                self.update(remote=feature_branch.location)
            # Get the global revision id of the feature branch we're about to merge.
            revision_to_merge = self.find_revision_id(feature_branch.revision)
            # Merge in the feature branch.
            self.merge(revision=feature_branch.revision)
            # Commit the merge.
            self.commit(message="Merged %s" % feature_branch.expression)
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
        logger.info("Merging up from %s to %s: %s",
                    target_branch,
                    pluralize(len(branches_to_upmerge), "branch", "branches"),
                    concatenate(branches_to_upmerge))
        # Merge the feature branch up through the selected branches.
        merge_queue = [target_branch] + branches_to_upmerge
        while len(merge_queue) >= 2:
            from_branch = merge_queue[0]
            to_branch = merge_queue[1]
            logger.info("Merging %s into %s ..", from_branch, to_branch)
            self.checkout(revision=to_branch)
            self.merge(revision=from_branch)
            self.commit(message="Merged %s" % from_branch)
            merge_queue.pop(0)
        # Check if we need to delete or close the feature branch.
        if delete and feature_branch and feature_branch.revision in self.branches:
            # Delete or close the feature branch.
            self.delete_branch(
                branch_name=feature_branch.revision,
                message="Closing feature branch %s" % feature_branch.revision,
            )
            # Update the working tree to the default branch.
            self.checkout()
        logger.info("Done! Finished merging up in %s.", timer)
        return revision_to_merge

    def add_files(self, *pathnames, **kw):
        """
        Stage new files in the working tree to be included in the next commit.

        :param pathnames: Any positional arguments are expected to be pathnames
                          relative to the root of the repository.
        :param all: If the keyword argument `all` is :data:`True` then all
                    new files are added to the repository (in this case no
                    pathnames should be given).
        :raises: The following exceptions can be raised:

                 - :exc:`~exceptions.ValueError` when pathnames are given and
                   the keyword argument `all` is also :data:`True`.

                 - :exc:`~executor.ExternalCommandFailed` if the command fails.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        add_all = kw.get('all', False)
        logger.info("Staging working tree changes to be committed in %s ..", self.local)
        if pathnames and add_all:
            raise ValueError("You can't add specific pathnames using all=True!")
        if add_all:
            execute(self.get_command(
                method_name='add_files',
                attribute_name='add_command_all',
                local=self.local,
            ))
        else:
            execute(self.get_command(
                method_name='add_files',
                attribute_name='add_command',
                local=self.local,
                filenames=pathnames,
            ))

    def commit(self, message, author=None):
        """
        Commit changes to tracked files in the working tree.

        :param message: The commit message (a string).
        :param author: Override the value of :attr:`author` (a string). If
                       :attr:`author` is :data:`None` this argument is
                       required.
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        logger.info("Committing changes in working tree of %s: %s", self.local, message)
        execute(self.get_command(
            method_name='commit',
            attribute_name='commit_command',
            local=self.local,
            message=message,
            **self.get_author(author)
        ))

    def export(self, directory, revision=None):
        """
        Export the complete tree from the local version control repository.

        :param directory: The directory where the tree should be exported (a
                          string).
        :param revision: The revision to export (a string, defaults to
                         :attr:`default_revision`).
        :raises: :exc:`~executor.ExternalCommandFailed` if the command fails.

        .. note:: Automatically creates the local repository on the first run.
        """
        self.create()
        revision = revision or self.default_revision
        logger.info("Exporting revision %s of %s to %s ..", revision, self.local, directory)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        execute(self.get_command(
            method_name='export',
            attribute_name='export_command',
            local=self.local,
            revision=revision,
            directory=directory,
        ))

    @property
    def is_bare(self):
        """
        :data:`True` if the repository is a bare checkout, :data:`False` otherwise.

        The :attr:`is_bare` property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

    @property
    def is_clean(self):
        """
        :data:`True` if the working tree is clean, :data:`False` otherwise.

        The :attr:`is_clean` property needs to be implemented by subclasses.
        """
        raise NotImplementedError()

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
            """, local=self.local))

    def find_revision_number(self, revision=None):
        """
        Find the local revision number of the given revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string, defaults to :attr:`default_revision`).
        :returns: The local revision number (an integer).

        .. note:: Automatically creates the local repository on the first run.

        The :func:`find_revision_number()` method needs to be implemented by
        subclasses.
        """
        raise NotImplementedError()

    def find_revision_id(self, revision=None):
        """
        Find the global revision id of the given revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string, defaults to :attr:`default_revision`).
        :returns: The global revision id (a hexadecimal string).

        .. note:: Automatically creates the local repository on the first run.

        The :func:`find_revision_id()` method needs to be implemented by
        subclasses.
        """
        raise NotImplementedError()

    def generate_control_field(self, revision=None):
        """
        Generate a Debian control file name/value pair for the given repository and revision.

        :param revision: A reference to a revision, most likely the name of a
                         branch (a string, defaults to :attr:`default_revision`).
        :returns: A tuple with two strings: The name of the field and the value.

        This generates a ``Vcs-Bzr`` field for Bazaar_ repositories, a
        ``Vcs-Hg`` field for Mercurial_ repositories and a ``Vcs-Git`` field
        for Git_ repositories. Here's an example based on the public git
        repository of the vcs-repo-mgr project:

        >>> from vcs_repo_mgr import coerce_repository
        >>> repository = coerce_repository('https://github.com/xolox/python-vcs-repo-mgr.git')
        >>> repository.generate_control_field()
        ('Vcs-Git', 'https://github.com/xolox/python-vcs-repo-mgr.git#b617731b6c0ca746665f597d2f24b8814b137ebc')
        """
        value = "%s#%s" % (self.remote or self.local, self.find_revision_id(revision))
        return self.control_field, value

    @property
    def branches(self):
        """
        Find information about the branches in the version control repository.

        :returns: A :class:`dict` with branch names (strings) as keys and
                  :class:`Revision` objects as values.

        .. note:: Automatically creates the local repository on the first run.

        Here's an example based on a mirror of the git project's repository:

        >>> from vcs_repo_mgr import GitRepo
        >>> from pprint import pprint
        >>> repository = GitRepo(remote='https://github.com/git/git.git')
        >>> pprint(repository.branches)
        {'maint':  Revision(repository=GitRepo(...), branch='maint',  revision_id='16018ae'),
         'master': Revision(repository=GitRepo(...), branch='master', revision_id='8440f74'),
         'next':   Revision(repository=GitRepo(...), branch='next',   revision_id='38e7071'),
         'pu':     Revision(repository=GitRepo(...), branch='pu',     revision_id='d61c1fa'),
         'todo':   Revision(repository=GitRepo(...), branch='todo',   revision_id='dea8a2d')}
        """
        self.create()
        return dict((r.branch, r) for r in self.find_branches())

    @property
    def ordered_branches(self):
        """
        Find information about the branches in the version control repository.

        :returns: An ordered :class:`list` of :class:`Revision` objects.
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

        :returns: A :class:`dict` with tag names (strings) as keys and
                  :class:`Revision` objects as values.

        .. note:: Automatically creates the local repository on the first run.

        Here's an example based on a mirror of the git project's repository:

        >>> from vcs_repo_mgr import GitRepo
        >>> from pprint import pprint
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
        self.create()
        return dict((r.tag, r) for r in self.find_tags())

    @property
    def ordered_tags(self):
        """
        Find information about the tags in the version control repository.

        :returns: An ordered :class:`list` of :class:`Revision` objects.
                  The list is ordered by performing a `natural order sort
                  <https://pypi.python.org/pypi/naturalsort>`_ of tag names
                  in ascending order (i.e. the first value is the "oldest"
                  tag and the last value is the "newest" tag).

        .. note:: Automatically creates the local repository on the first run.
        """
        return natsort(self.tags.values(), key=operator.attrgetter('tag'))

    @property
    def releases(self):
        r"""
        Find information about the releases in the version control repository.

        :returns: A :class:`dict` with release identifiers (strings) as keys
                  and :class:`Release` objects as values.

        .. note:: Automatically creates the local repository on the first run.

        Here's an example based on a mirror of the git project's repository
        which shows the last ten releases based on tags, where each release
        identifier captures a tag without its 'v' prefix:

        >>> from vcs_repo_mgr import GitRepo
        >>> from pprint import pprint
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
        pattern = self.compiled_filter
        available_releases = {}
        available_revisions = getattr(self, self.release_scheme)
        for identifier, revision in available_revisions.items():
            match = pattern.match(identifier)
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

        :returns: An ordered :class:`list` of :class:`Release` objects.
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

    def release_to_branch(self, release_id):
        """
        Shortcut to translate a release identifier to a branch name.

        :param release_id: A :attr:`Release.identifier` value (a string).
        :returns: A branch name (a string).
        :raises: :exc:`~exceptions.TypeError` when the repository is not
                 using branches as its release scheme.
        """
        if self.release_scheme != 'branches':
            raise TypeError("Repository isn't using 'branches' release scheme!")
        return self.releases[release_id].revision.branch

    def release_to_tag(self, release_id):
        """
        Shortcut to translate a release identifier to a tag name.

        :param release_id: A :attr:`Release.identifier` value (a string).
        :returns: A tag name (a string).
        :raises: :exc:`~exceptions.TypeError` when the repository is not
                 using tags as its release scheme.
        """
        if self.release_scheme != 'tags':
            raise TypeError("Repository isn't using 'tags' release scheme!")
        return self.releases[release_id].revision.tag

    def find_branches(self):
        """
        Find information about the branches in the version control repository.

        This is an internal method that is expected to be implemented by
        subclasses of :class:`Repository` and is used by
        :attr:`Repository.branches`.

        :returns: A generator of :class:`Revision` objects.
        """
        raise NotImplementedError()

    def find_tags(self):
        """
        Find information about the tags in the version control repository.

        This is an internal method that is expected to be implemented by
        subclasses of :class:`Repository` and is used by
        :attr:`Repository.tags`.

        :returns: A generator of :class:`Revision` objects.
        """
        raise NotImplementedError()

    def __repr__(self):
        """Generate a human readable representation of a repository object."""
        fields = []
        if self.local:
            fields.append("local=%r" % self.local)
        if self.remote:
            fields.append("remote=%r" % self.remote)
        return "%s(%s)" % (self.__class__.__name__, ', '.join(fields))


class Revision(object):

    """
    :class:`Revision` objects represent a specific revision in a :class:`Repository`.

    The following fields are available:

    .. py:attribute:: repository

       The :class:`Repository` object of the version control repository
       containing the revision.

    .. py:attribute:: revision_id

       A string containing a global revision id (a hexadecimal hash) comparable
       between local and remote repositories. Useful to unambiguously refer to
       a revision and its history. This field is always available.

    .. py:attribute:: revision_number

       A local revision number (an incrementing integer). Useful as a build
       number or when a simple, incrementing version number is required. Should
       not be used to unambiguously refer to a revision. If not available this
       will be ``None``.

    .. py:attribute:: branch

       The name of the branch in which the revision exists (a string). If not
       available this will be ``None``.

    .. py:attribute:: tag

       The name of the tag associated to the revision (a string). If not
       available this will be ``None``.
    """

    def __init__(self, repository, revision_id, revision_number=None, branch=None, tag=None):
        """
        Create a :class:`Revision` object.

        :param repository: A :class:`Repository` object.
        :param revision_id: A string containing a hexadecimal hash.
        :param revision_number: The revision number (an integer, optional).
        :param branch: The name of the branch (a string, optional).
        :param tag: The name of the tag (a string, optional).
        """
        self.repository = repository
        self.revision_id = revision_id
        if revision_number is not None:
            self.revision_number = revision_number
        self.branch = branch
        self.tag = tag

    @lazy_property(writable=True)
    def revision_number(self):
        """The revision number of the revision (an integer)."""
        return self.repository.find_revision_number(self.revision_id)

    def __repr__(self):
        """Generate a human readable representation of a revision object."""
        fields = ["repository=%r" % self.repository]
        if self.branch:
            fields.append("branch=%r" % self.branch)
        if self.tag:
            fields.append("tag=%r" % self.tag)
        if self.revision_number is not None:
            fields.append("revision_number=%r" % self.revision_number)
        fields.append("revision_id=%r" % self.revision_id)
        return "%s(%s)" % (self.__class__.__name__, ', '.join(fields))


class RepositoryMeta(type):

    """Metaclass for automatic registration of :class:`Repository` subclasses."""

    def __init__(cls, name, bases, dict):
        """Register a :class:`Repository` subclass as soon as its defined."""
        # Initialize super classes.
        type.__init__(cls, name, bases, dict)
        # Don't register the Repository class itself.
        if issubclass(cls, Repository):
            # Register the Repository subclass.
            REPOSITORY_TYPES.add(cls)


# Obscure syntax gymnastics to define a class with a metaclass whose
# definition is compatible with Python 2.x as well as Python 3.x.
# See also: https://wiki.python.org/moin/PortingToPy3k/BilingualQuickRef#metaclasses
Repository = RepositoryMeta('Repository', Repository.__bases__, dict(Repository.__dict__))


class Release(object):

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
    :attr:`Repository.releases` are based on :attr:`Repository.tags`, but
    using the ``release_scheme`` argument to the :class:`Repository`
    constructor you can specify that releases should be based on
    :attr:`Repository.branches` instead. Additionally you can use the
    ``release_filter`` argument to specify a regular expression that will be
    used to distinguish valid releases from other tags/branches.

    .. py:attribute:: revision

       The :class:`Revision` that the release relates to.

    .. py:attribute:: identifier

      The name of the tag or branch (a string). If a ``release_filter``
      containing a single capture group is used this identifier is set to the
      captured substring instead of the complete tag or branch name.
    """

    def __init__(self, revision, identifier):
        """
        Initialize a release.

        :param revision: The :class:`Revision` that the release relates to.
        :param identifier: The (substring of the) tag or branch name that the
                           release is based on (a string).
        """
        self.revision = revision
        self.identifier = identifier

    def __repr__(self):
        """Generate a human readable representation of a release object."""
        return "%s(%s)" % (self.__class__.__name__, ', '.join([
            "revision=%r" % self.revision,
            "identifier=%r" % self.identifier,
        ]))


class FeatureBranchSpec(PropertyManager):

    """Simple and human friendly feature branch specifications."""

    def __init__(self, expression):
        """
        Initialize a :class:`FeatureBranchSpec` object.

        :param expression: A feature branch specification (a string).

        The `expression` string is parsed as follows:

        - If `expression` contains two nonempty substrings separated by the
          character ``#`` it is split into two parts where the first part is
          used to set :attr:`location` and the second part is used to set
          :attr:`revision`.
        - Otherwise `expression` is interpreted as a revision without a
          location (in this case :attr:`location` will be :data:`None`).

        Some examples to make things more concrete:

        >>> from vcs_repo_mgr import FeatureBranchSpec
        >>> FeatureBranchSpec('https://github.com/xolox/python-vcs-repo-mgr.git#remote-feature-branch')
        FeatureBranchSpec(expression='https://github.com/xolox/python-vcs-repo-mgr.git#remote-feature-branch',
                          location='https://github.com/xolox/python-vcs-repo-mgr.git',
                          revision='remote-feature-branch')
        >>> FeatureBranchSpec('local-feature-branch')
        FeatureBranchSpec(expression='local-feature-branch',
                          location=None,
                          revision='local-feature-branch')
        """
        super(FeatureBranchSpec, self).__init__(expression=expression)

    @required_property
    def expression(self):
        """The feature branch specification provided by the user (a string)."""

    @writable_property
    def location(self):
        """
        The location of the repository that contains :attr:`revision` (a string or :data:`None`).

        The computed default value of :attr:`location` is based on the value of
        :attr:`expression` as described in the documentation of
        :func:`__init__()`.
        """
        location, _, revision = self.expression.partition('#')
        return location if location and revision else None

    @required_property
    def revision(self):
        """
        The name of the feature branch (a string).

        The computed default value of :attr:`revision` is based on the value of
        :attr:`expression` as described in the documentation of
        :func:`__init__()`.
        """
        location, _, revision = self.expression.partition('#')
        return revision if location and revision else self.expression


class HgRepo(Repository):

    """
    Version control repository interface for Mercurial_ repositories.

    .. _Mercurial: http://mercurial.selenic.com/
    """

    ALIASES = ['hg', 'mercurial']
    """A list of strings with aliases/names for Mercurial."""

    friendly_name = 'Mercurial'
    control_field = 'Vcs-Hg'
    create_command = 'hg clone --noupdate {remote} {local}'
    create_command_non_bare = 'hg clone {remote} {local}'
    update_command = 'hg -R {local} pull {remote}'
    push_command = 'hg -R {local} push --new-branch {remote}'
    checkout_command = 'hg -R {local} update --rev={revision}'
    checkout_command_clean = 'hg -R {local} update --rev={revision} --clean'
    create_branch_command = 'hg -R {local} branch {branch_name}'
    delete_branch_command = compact('''
        hg -R {local} update --rev={branch_name} &&
        hg -R {local} commit --user={author_combined} --message={message} --close-branch
    ''')
    merge_command = 'hg -R {local} merge --rev={revision}'
    add_command = 'hg --cwd {local} addremove {filenames}'
    add_command_all = 'hg --cwd {local} addremove'
    # The `hg remove --after' command is used to match the semantics of `git
    # commit --all' however `hg remove --after' is _very_ verbose (it comments
    # on every existing file in the repository) and unfortunately it ignores
    # the `--quiet' option. This explains why I've decided to silence the
    # standard error stream (though I feel I may regret this later).
    commit_command = compact('''
        hg -R {local} remove --after 2>/dev/null;
        hg -R {local} commit --user={author_combined} --message={message}
    ''')
    export_command = 'hg -R {local} archive --rev={revision} {directory}'

    @staticmethod
    def get_vcs_directory(directory):
        """
        Get the pathname of the directory containing Mercurial's metadata files.

        :param directory: The pathname of a local directory (a string). The
                          directory doesn't have to exist.
        :returns: The ``.hg`` subdirectory of the given directory (a string).
        """
        return os.path.join(directory, '.hg')

    @writable_property(cached=True)
    def author(self):
        """
        The author for commits created using :func:`~Repository.commit()` (a string).

        The :class:`HgRepo` class overrides this property to discover the
        configured username and email address using the command ``hg config
        ui.username``. This means that by default your Mercurial configuration
        will be respected, but you are still free to explicitly specify a value
        for :attr:`author`.
        """
        return execute(
            'hg', '-R', self.local, 'config', 'ui.username',
            capture=True, check=False, silent=True,
        )

    @required_property
    def default_revision(self):
        """The default revision for Mercurial repositories (a string, defaults to ``default``)."""
        return 'default'

    @property
    def current_branch(self):
        """The name of the branch that's currently checked out in the working tree (a string or :data:`None`)."""
        return execute('hg', 'branch', capture=True, check=False, directory=self.local)

    @property
    def merge_conflicts(self):
        """The filenames of any files with merge conflicts (a list of strings)."""
        listing = execute('hg', 'resolve', '--list', capture=True, directory=self.local)
        filenames = set()
        for line in listing.splitlines():
            tokens = line.split(None, 1)
            if len(tokens) == 2:
                status, name = tokens
                if status and name and status.upper() != 'R':
                    filenames.add(name)
        return sorted(filenames)

    @property
    def is_bare(self):
        """
        :data:`True` if the repository is a bare checkout, :data:`False` otherwise.

        Runs the ``hg id`` command to check whether the (special) global
        revision id ``000000000000`` is reported.
        """
        self.create()
        try:
            return int(execute('hg', '-R', self.local, 'id', capture=True)) == 0
        except Exception:
            return False

    @property
    def is_clean(self):
        """:data:`True` if the working tree is clean, :data:`False` otherwise."""
        self.create()
        listing = execute('hg', '-R', self.local, 'diff', capture=True)
        return len(listing.splitlines()) == 0

    def find_revision_number(self, revision=None):
        """
        Find the revision number of the given revision expression.

        :param revision: A Mercurial specific revision expression (a string).
        :returns: The revision number (an integer).
        """
        self.create()
        revision = revision or self.default_revision
        result = execute('hg', '-R', self.local, 'id', '--rev', revision, '--num',
                         capture=True).rstrip('+')
        assert result and result.isdigit(), \
            "Failed to find local revision number! ('hg id --num' gave unexpected output)"
        return int(result)

    def find_revision_id(self, revision=None):
        """
        Find the revision id of the given revision expression.

        :param revision: A Mercurial specific revision expression (a string).
        :returns: The revision id (a hexadecimal string).
        """
        self.create()
        revision = revision or self.default_revision
        result = execute('hg', '-R', self.local, 'id', '--rev', revision, '--debug', '--id',
                         capture=True).rstrip('+')
        assert re.match('^[A-Fa-z0-9]+$', result), \
            "Failed to find global revision id! ('hg id --id' gave unexpected output)"
        return result

    def find_branches(self):
        """
        Find the branches in the Mercurial repository.

        :returns: A generator of :class:`Revision` objects.

        .. note:: Closed branches are not included.
        """
        listing = execute('hg', '-R', self.local, 'branches', capture=True)
        for line in listing.splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and ':' in tokens[1]:
                revision_number, revision_id = tokens[1].split(':')
                yield Revision(repository=self,
                               revision_id=revision_id,
                               revision_number=int(revision_number),
                               branch=tokens[0])

    def find_tags(self):
        """
        Find the tags in the Mercurial repository.

        :returns: A generator of :class:`Revision` objects.
        """
        listing = execute('hg', '-R', self.local, 'tags', capture=True)
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

    ALIASES = ['git']
    """A list of strings with aliases/names for Git."""

    friendly_name = 'Git'
    control_field = 'Vcs-Git'
    create_command = 'git clone --bare {remote} {local}'
    create_command_non_bare = 'git clone {remote} {local}'
    update_command = 'cd {local} && git fetch {remote} +refs/heads/*:refs/heads/*'
    push_command = 'cd {local} && git push {remote} && git push --tags {remote}'
    checkout_command = 'cd {local} && git checkout {revision}'
    checkout_command_clean = 'cd {local} && git checkout . && git checkout {revision}'
    create_branch_command = 'cd {local} && git checkout -b {branch_name}'
    delete_branch_command = 'cd {local} && git branch -d {branch_name}'
    merge_command = compact('''
        cd {local} && git
            -c user.name={author_name}
            -c user.email={author_email}
            merge --no-commit --no-ff {revision}
    ''')
    add_command = 'cd {local} && git add -- {filenames}'
    add_command_all = 'cd {local} && git add --all .'
    commit_command = compact('''
        cd {local} && git
            -c user.name={author_name}
            -c user.email={author_email}
            commit --all --message {message}
    ''')
    export_command = 'cd {local} && git archive {revision} | tar --extract --directory={directory}'

    @staticmethod
    def get_vcs_directory(directory):
        """
        Get the pathname of the directory containing Git's metadata files.

        :param directory: The pathname of a local directory (a string). The
                          directory doesn't have to exist.
        :returns: The ``.git`` subdirectory of the given directory (for
                  repositories with a working tree) or the given directory
                  itself (for repositories without a working tree).
        """
        subdirectory = os.path.join(directory, '.git')
        return subdirectory if os.path.isdir(subdirectory) else directory

    @classmethod
    def contains_repository(cls, directory):
        """
        Check whether the given directory contains a local Git clone.

        :param directory: The pathname of a local directory (a string).
        :returns: :data:`True` if it looks like the directory contains a local
                  Git clone, :data:`False` otherwise.

        This static method checks whether the directory returned by
        :func:`get_vcs_directory()` contains a file called ``config``.
        """
        return os.path.isfile(os.path.join(cls.get_vcs_directory(directory), 'config'))

    @writable_property(cached=True)
    def author(self):
        """
        The author for commits created using :func:`~Repository.commit()` (a string).

        The :class:`GitRepo` class overrides this property to discover the
        configured username using the command ``git config user.name`` and
        email address using ``git config user.email``. This means that by
        default your Git configuration will be respected, but you are still
        free to explicitly specify a value for :attr:`author`.
        """
        name = execute('git', 'config', 'user.name', capture=True, check=False, directory=self.local, silent=True)
        email = execute('git', 'config', 'user.email', capture=True, check=False, directory=self.local, silent=True)
        return u"%s <%s>" % (name, email) if name and email else name

    @required_property
    def default_revision(self):
        """The default revision for Git repositories (a string, defaults to ``master``)."""
        return 'master'

    @property
    def current_branch(self):
        """The name of the branch that's currently checked out in the working tree (a string or :data:`None`)."""
        output = execute('git', 'rev-parse', '--abbrev-ref', 'HEAD', capture=True, check=False, directory=self.local)
        return output if output != 'HEAD' else None

    @property
    def merge_conflicts(self):
        """The filenames of any files with merge conflicts (a list of strings)."""
        listing = execute('git', 'ls-files', '--unmerged', '-z', capture=True, directory=self.local)
        filenames = set()
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
    def is_bare(self):
        """
        :data:`True` if the repository is a bare checkout, :data:`False` otherwise.

        Runs the ``git config --get core.bare`` command to check whether we're
        dealing with a bare checkout.
        """
        self.create()
        return coerce_boolean(execute(
            'git', 'config', '--get', 'core.bare',
            capture=True, directory=self.local,
        ))

    @property
    def is_clean(self):
        """
        :data:`True` if the working tree (and index) is clean, :data:`False` otherwise.

        The implementation of :attr:`GitRepo.is_clean` checks whether ``git
        diff`` reports any differences. This command has several variants:

        1. ``git diff`` shows the difference between the index and working
           tree.
        2. ``git diff --cached`` shows the difference between the last commit
           and index.
        3. ``git diff HEAD`` shows the difference between the last commit and
           working tree.

        The implementation of :attr:`GitRepo.is_clean` uses the third command
        (``git diff HEAD``) in an attempt to hide the existence of git's index
        from callers that are trying to write code that works with Git and
        Mercurial using the same Python API.
        """
        self.create()
        listing = execute('git', 'diff', 'HEAD', capture=True, directory=self.local)
        return len(listing.splitlines()) == 0

    def find_revision_number(self, revision=None):
        """
        Find the revision number of the given revision expression.

        :param revision: A git specific revision expression (a string).
        :returns: The revision number (an integer).
        """
        self.create()
        revision = revision or self.default_revision
        result = execute('git', 'rev-list', revision, '--count', capture=True, directory=self.local)
        assert result and result.isdigit(), \
            "Failed to find local revision number! ('git rev-list --count' gave unexpected output)"
        return int(result)

    def find_revision_id(self, revision=None):
        """
        Find the revision id of the given revision expression.

        :param revision: A git specific revision expression (a string).
        :returns: The revision id (a hexadecimal string).
        """
        self.create()
        revision = revision or self.default_revision
        result = execute('git', 'rev-parse', revision, capture=True, directory=self.local)
        assert re.match('^[A-Fa-z0-9]+$', result), \
            "Failed to find global revision id! ('git rev-parse' gave unexpected output)"
        return result

    def find_branches(self):
        """
        Find the branches in the git repository.

        :returns: A generator of :class:`Revision` objects.
        """
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
        """
        Find the tags in the git repository.

        :returns: A generator of :class:`Revision` objects.
        """
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

    ALIASES = ['bzr', 'bazaar']
    """A list of strings with aliases/names for Bazaar."""

    friendly_name = 'Bazaar'
    control_field = 'Vcs-Bzr'
    create_command = 'bzr branch --no-tree --use-existing-dir {remote} {local}'
    create_command_non_bare = 'bzr branch --use-existing-dir {remote} {local}'
    update_command = 'cd {local} && bzr pull {remote}'
    push_command = 'cd {local} && bzr push {remote}'
    export_command = 'cd {local} && bzr export --revision={revision} {directory}'

    @staticmethod
    def get_vcs_directory(directory):
        """
        Get the pathname of the directory containing Bazaar's metadata files.

        :param directory: The pathname of a local directory (a string). The
                          directory doesn't have to exist.
        :returns: The ``.bzr`` subdirectory of the given directory (a string).
        """
        return os.path.join(directory, '.bzr')

    @classmethod
    def contains_repository(cls, directory):
        """
        Check whether the given directory contains a local Bazaar clone.

        :param directory: The pathname of a local directory (a string).
        :returns: :data:`True` if it looks like the directory contains a local
                  Bazaar clone, :data:`False` otherwise.

        This method checks whether the directory returned by
        :func:`get_vcs_directory()` contains a file called ``branch-format``.
        """
        return os.path.isfile(os.path.join(cls.get_vcs_directory(directory), 'branch-format'))

    @required_property
    def default_revision(self):
        """The default revision for Bazaar repositories (a string, defaults to ``last:1``)."""
        return 'last:1'

    @property
    def is_bare(self):
        """
        :data:`True` if the repository is a bare checkout, :data:`False` otherwise.

        Checks whether the ``.bzr/checkout`` directory exists (it doesn't exist
        in Bazaar repositories created using ``bzr branch --no-tree ...``).
        """
        self.create()
        return not os.path.isdir(os.path.join(self.vcs_directory, 'checkout'))

    @property
    def is_clean(self):
        """:data:`True` if the working tree is clean, :data:`False` otherwise."""
        self.create()
        listing = execute('bzr', 'diff', check=False, capture=True, directory=self.local)
        return len(listing.splitlines()) == 0

    def find_revision_number(self, revision=None):
        """
        Find the revision number of the given revision expression.

        :param revision: A Bazaar specific revision expression (a string).
        :returns: The revision number (an integer).

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
        self.create()
        revision = revision or self.default_revision
        result = execute('bzr', 'log', '--revision=..%s' % revision, '--line', capture=True, directory=self.local)
        revision_number = len([line for line in result.splitlines() if line and not line.isspace()])
        assert revision_number > 0, "Failed to find local revision number! ('bzr log --line' gave unexpected output)"
        return revision_number

    def find_revision_id(self, revision=None):
        """
        Find the revision id of the given revision expression.

        :param revision: A Bazaar specific revision expression (a string).
        :returns: The revision id (a hexadecimal string).
        """
        self.create()
        revision = revision or self.default_revision
        result = execute('bzr', 'version-info', '--revision=%s' % revision, '--custom', '--template={revision_id}',
                         capture=True, directory=self.local)
        logger.debug("Output of 'bzr version-info' command: %s", result)
        assert result, "Failed to find global revision id! ('bzr version-info' gave unexpected output)"
        return result

    def find_branches(self):
        """
        Bazaar repository support doesn't support branches.

        This method logs a warning message and returns an empty list. Consider
        using tags instead.
        """
        logger.warning("Bazaar repository support doesn't include branches (consider using tags instead).")
        return []

    def find_tags(self):
        """
        Find the tags in the Bazaar repository.

        :returns: A generator of :class:`Revision` objects.

        .. note:: The ``bzr tags`` command reports tags pointing to
                  non-existing revisions as ``?`` but doesn't provide revision
                  ids. We can get the revision ids using the ``bzr tags
                  --show-ids`` command but this command doesn't mark tags
                  pointing to non-existing revisions. We combine the output of
                  both because we want all the information.
        """
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

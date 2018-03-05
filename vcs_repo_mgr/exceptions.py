# Version control system repository manager.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 5, 2018
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""
Custom exception types raised by the `vcs-repo-mgr` package.

When `vcs-repo-mgr` encounters known errors it will raise an exception. Most of
these exceptions have special types that capture the type of error so that the
Python :keyword:`except` statement can be used to handle different types of
errors in different ways.
"""


class VcsRepoMgrError(Exception):

    """
    Base class for exceptions directly raised by :mod:`vcs_repo_mgr`.
    """


class AmbiguousRepositoryNameError(VcsRepoMgrError):

    """
    Exception raised when an ambiguous repository name is encountered.

    Raised by :func:`~vcs_repo_mgr.find_configured_repository()` when the
    given repository name is ambiguous (i.e. it matches multiple repository
    names).
    """


class NoMatchingReleasesError(VcsRepoMgrError):

    """
    Exception raised when no matching releases are found.

    Raised by :func:`~vcs_repo_mgr.Repository.select_release()` when no
    matching releases are found in the repository.
    """


class NoSuchRepositoryError(VcsRepoMgrError):

    """
    Exception raised when a repository by the given name doesn't exist.

    Raised by :func:`~vcs_repo_mgr.find_configured_repository()` when the
    given repository name doesn't match any of the configured repositories.
    """


class UnknownRepositoryTypeError(VcsRepoMgrError):

    """
    Exception raised when a repository has an unknown type configured.

    Raised by :func:`~vcs_repo_mgr.find_configured_repository()` when it
    encounters a repository definition with an unknown type.
    """


class WorkingTreeNotCleanError(VcsRepoMgrError):

    """
    Exception raised when a working tree contains changes to tracked files.

    Raised by :func:`~vcs_repo_mgr.Repository.ensure_clean()` when it
    encounters a repository whose local working tree contains changes to
    tracked files.
    """


class MergeConflictError(VcsRepoMgrError):

    """
    Exception raised when a merge results in merge conflicts.

    Raised by :func:`~vcs_repo_mgr.Repository.merge()` when it performs a merge
    that results in merge conflicts.
    """


class MissingWorkingTreeError(VcsRepoMgrError):

    """
    Exception raised when working tree support is required but missing.

    Raised by :func:`~vcs_repo_mgr.Repository.ensure_working_tree()` when
    it finds that the local repository doesn't support a working tree.
    """

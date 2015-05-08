"""
When `vcs-repo-mgr` encounters known errors it will raise an exception. Most of
these exceptions have special types that capture the type of error so that the
Python :py:keyword:`except` statement can be used to handle different types of
errors in different ways.
"""

class VcsRepoMgrError(Exception):
    """
    Base class for exceptions directly raised by :py:mod:`vcs_repo_mgr`.
    """

class AmbiguousRepositoryNameError(VcsRepoMgrError):
    """
    Exception raised by :py:func:`~vcs_repo_mgr.find_configured_repository()`
    when the given repository name is ambiguous (i.e. it matches multiple
    repository names).
    """

class NoMatchingReleasesError(VcsRepoMgrError):
    """
    Exception raised by :py:func:`~vcs_repo_mgr.Repository.select_release()`
    when no matching releases are found in the repository.
    """

class NoSuchRepositoryError(VcsRepoMgrError):
    """
    Exception raised by :py:func:`~vcs_repo_mgr.find_configured_repository()`
    when the given repository name doesn't match any of the configured
    repositories.
    """

class UnknownRepositoryTypeError(VcsRepoMgrError):
    """
    Exception raised by :py:func:`~vcs_repo_mgr.find_configured_repository()`
    when it encounters a repository definition with an unknown type.
    """

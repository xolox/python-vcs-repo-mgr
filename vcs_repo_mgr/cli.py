# Command line interface for vcs-repo-mgr.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 10, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""
Usage: vcs-tool [OPTIONS]

Supported options:

  -r, --repository=NAME       name of configured repository
      --rev, --revision=REV   revision to export (used in combination
                              with the options -n, -i and -e)
  -d, --find-directory        print the absolute path of the local repository
  -n, --find-revision-number  find the local revision number of the revision
                              given with --rev
  -i, --find-revision-id      find the global revision id of the revision
                              given with --rev
  -u, --update                update local clone of repository by
                              pulling latest changes from remote
                              repository
  -e, --export=DIR            export contents of repository to
                              directory (used in combination
                              with --revision)
  -v, --verbose               make more noise
  -h, --help                  show this message and exit

The value of --revision defaults to `master' for git repositories and `default'
for Mercurial repositories.
"""

# Standard library modules.
import functools
import getopt
import logging
import os
import sys

# External dependencies.
import coloredlogs
from executor import execute

# Modules included in our package.
from vcs_repo_mgr import find_configured_repository

# Known configuration file locations.
USER_CONFIG_FILE = os.path.expanduser('~/.vcs-repo-mgr.ini')
SYSTEM_CONFIG_FILE = '/etc/vcs-repo-mgr.ini'

# Initialize a logger.
logger = logging.getLogger(__name__)

# Inject our logger into all execute() calls.
execute = functools.partial(execute, logger=logger)

def main():
    """
    The command line interface of the ``vcs-tool`` command.
    """
    # Initialize logging to the terminal.
    coloredlogs.install()
    # Command line option defaults.
    repository = None
    revision = None
    actions = []
    # Parse the command line arguments.
    try:
        options, arguments = getopt.gnu_getopt(sys.argv[1:], 'r:dniue:vh', [
            'repository=', 'rev=', 'revision=', 'find-directory',
            'find-revision-number', 'find-revision-id', 'update', 'export=',
            'verbose', 'help'
        ])
        for option, value in options:
            if option in ('-r', '--repository'):
                name = value.strip()
                assert name, "Please specify the name of a repository! (using -r, --repository)"
                repository = find_configured_repository(name)
            elif option in ('--rev', '--revision'):
                revision = value.strip()
                assert revision, "Please specify a nonempty revision string!"
            elif option in ('-d', '--find-directory'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_directory, repository))
            elif option in ('-n', '--find-revision-number'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_revision_number, repository, revision))
            elif option in ('-i', '--find-revision-id'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_revision_id, repository, revision))
            elif option in ('-u', '--update'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(repository.update))
            elif option in ('-e', '--export'):
                directory = value.strip()
                assert repository, "Please specify a repository first!"
                assert directory, "Please specify the directory where the revision should be exported!"
                actions.append(functools.partial(repository.export, directory, revision))
            elif option in ('-v', '--verbose'):
                coloredlogs.increase_verbosity()
            elif option in ('-h', '--help'):
                usage()
                return
        if not actions:
            usage()
            return
    except Exception as e:
        logger.error(e)
        print()
        usage()
        sys.exit(1)
    # Execute the requested action(s).
    try:
        for action in actions:
            action()
    except Exception:
        logger.exception("Failed to execute requested action(s)!")
        sys.exit(1)

def print_directory(repository):
    print(repository.local)

def print_revision_number(repository, revision):
    print(repository.find_revision_number(revision))
    
def print_revision_id(repository, revision):
    print(repository.find_revision_id(revision))

def usage():
    print(__doc__.strip())

# vim: ts=4 sw=4 et

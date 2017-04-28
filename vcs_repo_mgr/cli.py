# Command line interface for vcs-repo-mgr.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: April 29, 2017
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""
Usage: vcs-tool [OPTIONS] [ARGS]

Command line program to perform common operations (in the context of
packaging/deployment) on version control repositories. Supports Bazaar,
Mercurial and Git repositories.

Supported options:

  -r, --repository=REPOSITORY

    Select a repository to operate on by providing the name of a repository
    defined in one of the configuration files ~/.vcs-repo-mgr.ini and
    /etc/vcs-repo-mgr.ini.

    Alternatively the location of a remote repository can be given. The
    location should be prefixed by the type of the repository (with a `+' in
    between) unless the location ends in `.git' in which case the prefix is
    optional.

  --rev, --revision=REVISION

    Select a revision to operate on. Accepts any string that's supported by the
    VCS system that manages the repository, which means you can provide branch
    names, tag names, exact revision ids, etc. This option is used in
    combination with the --find-revision-number, --find-revision-id and
    --export options.

    If this option is not provided a default revision is selected: `last:1' for
    Bazaar repositories, `master' for git repositories and `default' (not
    `tip'!) for Mercurial repositories.

  --release=RELEASE_ID

    Select a release to operate on. This option works in the same way as the
    --revision option. Please refer to the vcs-repo-mgr documentation for
    details on "releases".

    Although release identifiers are based on branch or tag names they
    may not correspond literally, this is why the release identifier you
    specify here is translated to a global revision id before being passed to
    the VCS system.

  -n, --find-revision-number

    Print the local revision number (an integer) of the revision given with the
    --revision option. Revision numbers are useful as a build number or when a
    simple, incrementing version number is required. Revision numbers should
    not be used to unambiguously refer to a revision (use revision ids for that
    instead). This option is used in combination with the --repository and
    --revision options.

  -i, --find-revision-id

    Print the global revision id (a string) of the revision given with the
    --revision option. Global revision ids are useful to unambiguously refer to
    a revision. This option is used in combination with the --repository and
    --revision options.

  --list-releases

    Print the identifiers of the releases in the repository given with the
    --repository option. The release identifiers are printed on standard
    output (one per line), ordered using natural order comparison.

  --select-release=RELEASE_ID

    Print the identifier of the newest release that is not newer than
    RELEASE_ID in the repository given with the --repository option.
    The release identifier is printed on standard output.

  -s, --sum-revisions

    Print the summed revision numbers of multiple repository/revision pairs.
    The repository/revision pairs are taken from the positional arguments to
    vcs-repo-mgr.

    This is useful when you're building a package based on revisions from
    multiple VCS repositories. By taking changes in all repositories into
    account when generating version numbers you can make sure that your version
    number is bumped with every single change.

  --vcs-control-field

    Print a line containing a Debian control file field and value. The field
    name will be one of `Vcs-Bzr', `Vcs-Hg' or `Vcs-Git'. The value will be the
    repository's remote location and the selected revision (separated by a `#'
    character).

  -u, --update

    Create/update the local clone of a remote repository by pulling the latest
    changes from the remote repository. This option is used in combination with
    the --repository option.

  -m, --merge-up

    Merge a change into one or more release branches and the default branch.

    By default merging starts from the current branch. You can explicitly
    select the branch where merging should start using the --rev, --revision
    and --release options.

    You can also start by merging a feature branch into the selected release
    branch before merging the change up through later release branches and the
    default branch. To do so you pass the name of the feature branch as a
    positional argument.

    If the feature branch is located in a different repository you can prefix
    the location of the repository to the name of the feature branch with a `#'
    token in between, to delimit the location from the branch name.

  -e, --export=DIRECTORY

    Export the contents of a specific revision of a repository to a local
    directory. This option is used in combination with the --repository and
    --revision options.

  -d, --find-directory

    Print the absolute pathname of a local repository. This option is used in
    combination with the --repository option.

  -v, --verbose

    Increase logging verbosity (can be repeated).

  -q, --quiet

    Decrease logging verbosity (can be repeated).

  -h, --help

    Show this message and exit.
"""

# Standard library modules.
import functools
import getopt
import logging
import sys

# External dependencies.
import coloredlogs
from executor import execute
from humanfriendly.terminal import usage, warning

# Modules included in our package.
from vcs_repo_mgr import coerce_repository, sum_revision_numbers

# Initialize a logger.
logger = logging.getLogger(__name__)

# Inject our logger into all execute() calls.
execute = functools.partial(execute, logger=logger)


def main():
    """The command line interface of the ``vcs-tool`` program."""
    # Initialize logging to the terminal.
    coloredlogs.install()
    # Command line option defaults.
    repository = None
    revision = None
    actions = []
    # Parse the command line arguments.
    try:
        options, arguments = getopt.gnu_getopt(sys.argv[1:], 'r:dnisume:vqh', [
            'repository=', 'rev=', 'revision=', 'release=', 'find-directory',
            'find-revision-number', 'find-revision-id', 'list-releases',
            'select-release=', 'sum-revisions', 'vcs-control-field', 'update',
            'merge-up', 'export=', 'verbose', 'quiet', 'help',
        ])
        for option, value in options:
            if option in ('-r', '--repository'):
                value = value.strip()
                assert value, "Please specify the name of a repository! (using -r, --repository)"
                repository = coerce_repository(value)
            elif option in ('--rev', '--revision'):
                revision = value.strip()
                assert revision, "Please specify a nonempty revision string!"
            elif option == '--release':
                # TODO Right now --release and --merge-up cannot be combined
                #      because the following statements result in a global
                #      revision id which is immutable. If release objects had
                #      something like an optional `mutable_revision_id' it
                #      should be possible to support the combination of
                #      --release and --merge-up.
                assert repository, "Please specify a repository first!"
                release_id = value.strip()
                assert release_id in repository.releases, "The given release identifier is invalid!"
                revision = repository.releases[release_id].revision.revision_id
            elif option in ('-d', '--find-directory'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_directory, repository))
            elif option in ('-n', '--find-revision-number'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_revision_number, repository, revision))
            elif option in ('-i', '--find-revision-id'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_revision_id, repository, revision))
            elif option == '--list-releases':
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_releases, repository))
            elif option == '--select-release':
                assert repository, "Please specify a repository first!"
                release_id = value.strip()
                assert release_id, "Please specify a nonempty release identifier!"
                actions.append(functools.partial(print_selected_release, repository, release_id))
            elif option in ('-s', '--sum-revisions'):
                assert len(arguments) >= 2, "Please specify one or more repository/revision pairs!"
                actions.append(functools.partial(print_summed_revisions, arguments))
                arguments = []
            elif option == '--vcs-control-field':
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(print_vcs_control_field, repository, revision))
            elif option in ('-u', '--update'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(repository.update))
            elif option in ('-m', '--merge-up'):
                assert repository, "Please specify a repository first!"
                actions.append(functools.partial(
                    repository.merge_up,
                    target_branch=revision,
                    feature_branch=arguments[0] if arguments else None,
                ))
            elif option in ('-e', '--export'):
                directory = value.strip()
                assert repository, "Please specify a repository first!"
                assert directory, "Please specify the directory where the revision should be exported!"
                actions.append(functools.partial(repository.export, directory, revision))
            elif option in ('-v', '--verbose'):
                coloredlogs.increase_verbosity()
            elif option in ('-q', '--quiet'):
                coloredlogs.decrease_verbosity()
            elif option in ('-h', '--help'):
                usage(__doc__)
                return
        if not actions:
            usage(__doc__)
            return
    except Exception as e:
        warning("Error: %s", e)
        sys.exit(1)
    # Execute the requested action(s).
    try:
        for action in actions:
            action()
    except Exception:
        logger.exception("Failed to execute requested action(s)!")
        sys.exit(1)


def print_directory(repository):
    """Report the local directory of a repository to standard output."""
    print(repository.local)


def print_revision_number(repository, revision):
    """Report the revision number of the given revision to standard output."""
    print(repository.find_revision_number(revision))


def print_revision_id(repository, revision):
    """Report the revision id of the given revision to standard output."""
    print(repository.find_revision_id(revision))


def print_selected_release(repository, release_id):
    """Report the identifier of the given release to standard output."""
    print(repository.select_release(release_id).identifier)


def print_releases(repository):
    """Report the identifiers of all known releases of the given repository to standard output."""
    print('\n'.join(release.identifier for release in repository.ordered_releases))


def print_summed_revisions(arguments):
    """Report the summed revision numbers for the given arguments to standard output."""
    print(sum_revision_numbers(arguments))


def print_vcs_control_field(repository, revision):
    """Report the VCS control field for the given repository and revision to standard output."""
    print("%s: %s" % repository.generate_control_field(revision))

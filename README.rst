vcs-repo-mgr: Version control repository manager
================================================

.. image:: https://travis-ci.org/xolox/python-vcs-repo-mgr.svg?branch=master
   :target: https://travis-ci.org/xolox/python-vcs-repo-mgr

.. image:: https://coveralls.io/repos/xolox/python-vcs-repo-mgr/badge.png?branch=master
   :target: https://coveralls.io/r/xolox/python-vcs-repo-mgr?branch=master

The Python package `vcs-repo-mgr` provides a command line program and Python
API to perform common operations (in the context of packaging/deployment) on
`version control`_ repositories. It's currently tested on Python 2.6, 2.7, 3.4
and 3.5. Bazaar_, Mercurial_ and Git_ repositories are supported.

.. contents::
   :local:

Installation
------------

The `vcs-repo-mgr` package is available on PyPI_ which means installation
should be as simple as:

.. code-block:: sh

   $ pip install vcs-repo-mgr

There's actually a multitude of ways to install Python packages (e.g. the `per
user site-packages directory`_, `virtual environments`_ or just installing
system wide) and I have no intention of getting into that discussion here, so
if this intimidates you then read up on your options before returning to these
instructions ;-).

You will also need Bazaar_, Mercurial_ and/or Git_ installed (depending on the
type of repositories you want to work with). Here's how you install them on
Debian and Ubuntu based systems:

.. code-block:: sh

   $ sudo apt-get install bzr mercurial git-core

Usage
-----

There are two ways to use the `vcs-repo-mgr` package: As the command line
program ``vcs-tool`` and as a Python API. For details about the Python API
please refer to the API documentation available on `Read the Docs`_. The
command line interface is described below.

.. A DRY solution to avoid duplication of the `vcs-tool --help' text:
..
.. [[[cog
.. from humanfriendly.usage import inject_usage
.. inject_usage('vcs_repo_mgr.cli')
.. ]]]

**Usage:** `vcs-tool [OPTIONS] [ARGS]`

Command line program to perform common operations (in the context of packaging/deployment) on version control repositories. Supports Bazaar, Mercurial and Git repositories.

**Supported options:**

.. csv-table::
   :header: Option, Description
   :widths: 30, 70


   "``-r``, ``--repository=REPOSITORY``","Select a repository to operate on by providing the name of a repository
   defined in one of the configuration files ~/.vcs-repo-mgr.ini and
   /etc/vcs-repo-mgr.ini.
   
   Alternatively the location of a remote repository can be given. The
   location should be prefixed by the type of the repository (with a ""+"" in
   between) unless the location ends in "".git"" in which case the prefix is
   optional.
   "
   "``--rev``, ``--revision=REVISION``","Select a revision to operate on. Accepts any string that's supported by the
   VCS system that manages the repository, which means you can provide branch
   names, tag names, exact revision ids, etc. This option is used in
   combination with the ``--find-revision-number``, ``--find-revision-id`` and
   ``--export`` options.
   
   If this option is not provided a default revision is selected: ""last:1"" for
   Bazaar repositories, ""master"" for git repositories and ""default"" (not
   ""tip""!) for Mercurial repositories.
   "
   ``--release=RELEASE_ID``,"Select a release to operate on. This option works in the same way as the
   ``--revision`` option. Please refer to the vcs-repo-mgr documentation for
   details on ""releases"".
   
   Although release identifiers are based on branch or tag names they
   may not correspond literally, this is why the release identifier you
   specify here is translated to a global revision id before being passed to
   the VCS system.
   "
   "``-n``, ``--find-revision-number``","Print the local revision number (an integer) of the revision given with the
   ``--revision`` option. Revision numbers are useful as a build number or when a
   simple, incrementing version number is required. Revision numbers should
   not be used to unambiguously refer to a revision (use revision ids for that
   instead). This option is used in combination with the ``--repository`` and
   ``--revision`` options.
   "
   "``-i``, ``--find-revision-id``","Print the global revision id (a string) of the revision given with the
   ``--revision`` option. Global revision ids are useful to unambiguously refer to
   a revision. This option is used in combination with the ``--repository`` and
   ``--revision`` options.
   "
   ``--list-releases``,"Print the identifiers of the releases in the repository given with the
   ``--repository`` option. The release identifiers are printed on standard
   output (one per line), ordered using natural order comparison.
   "
   ``--select-release=RELEASE_ID``,"Print the identifier of the newest release that is not newer than
   ``RELEASE_ID`` in the repository given with the ``--repository`` option.
   The release identifier is printed on standard output.
   "
   "``-s``, ``--sum-revisions``","Print the summed revision numbers of multiple repository/revision pairs.
   The repository/revision pairs are taken from the positional arguments to
   vcs-repo-mgr.
   
   This is useful when you're building a package based on revisions from
   multiple VCS repositories. By taking changes in all repositories into
   account when generating version numbers you can make sure that your version
   number is bumped with every single change.
   "
   ``--vcs-control-field``,"Print a line containing a Debian control file field and value. The field
   name will be one of ""Vcs-Bzr"", ""Vcs-Hg"" or ""Vcs-Git"". The value will be the
   repository's remote location and the selected revision (separated by a ""#""
   character).
   "
   "``-u``, ``--update``","Create/update the local clone of a remote repository by pulling the latest
   changes from the remote repository. This option is used in combination with
   the ``--repository`` option.
   "
   "``-m``, ``--merge-up``","Merge a change into one or more release branches and the default branch.
   
   By default merging starts from the current branch. You can explicitly
   select the branch where merging should start using the ``--rev``, ``--revision``
   and ``--release`` options.
   
   You can also start by merging a feature branch into the selected release
   branch before merging the change up through later release branches and the
   default branch. To do so you pass the name of the feature branch as a
   positional argument.
   
   If the feature branch is located in a different repository you can prefix
   the location of the repository to the name of the feature branch with a ""#""
   token in between, to delimit the location from the branch name.
   "
   "``-e``, ``--export=DIRECTORY``","Export the contents of a specific revision of a repository to a local
   directory. This option is used in combination with the ``--repository`` and
   ``--revision`` options.
   "
   "``-d``, ``--find-directory``","Print the absolute pathname of a local repository. This option is used in
   combination with the ``--repository`` option.
   "
   "``-v``, ``--verbose``","Make more noise.
   "
   "``-h``, ``--help``","Show this message and exit.
   "

.. [[[end]]]

The primary way to use the ``vcs-tool`` command requires you to create a
configuration file:

.. code-block:: sh

   $ cat > ~/.vcs-repo-mgr.ini << EOF
   [coloredlogs]
   type = git
   local = /tmp/coloredlogs
   remote = git@github.com:xolox/python-coloredlogs.git
   EOF

Because the ``-r``, ``--repository`` option accepts remote repository locations
in addition to names it's not actually required to create a configuration file.
Of course this depends on your use case(s).

Below are some examples of the command line interface. If you're interested in
using the Python API please refer to the `online documentation`_.

Updating repositories
~~~~~~~~~~~~~~~~~~~~~

If the configuration file defines a local *and* remote repository and the local
repository doesn't exist yet it will be created the first time you update it:

.. code-block:: sh

   $ vcs-tool --repository coloredlogs --update
   2014-05-04 18:55:54 INFO Creating Git clone of git@github.com:xolox/python-coloredlogs.git at /tmp/coloredlogs ..
   Cloning into bare repository '/tmp/coloredlogs'...
   remote: Reusing existing pack: 96, done.
   remote: Counting objects: 5, done.
   remote: Compressing objects: 100% (5/5), done.
   remote: Total 101 (delta 0), reused 0 (delta 0)
   Receiving objects: 100% (101/101), 28.11 KiB, done.
   Resolving deltas: 100% (44/44), done.

Later runs will pull the latest changes instead of performing a full clone:

.. code-block:: sh

   $ vcs-tool --repository coloredlogs --update
   2014-05-04 18:55:56 INFO Updating Git clone of git@github.com:xolox/python-coloredlogs.git at /tmp/coloredlogs ..
   From github.com:xolox/python-coloredlogs
    * branch HEAD -> FETCH_HEAD

Finding revision numbers/ids
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Revision numbers are integer numbers that increment with every added revision.
They're very useful during packaging/deployment:

.. code-block:: sh

   $ vcs-tool --repository coloredlogs --revision master --find-revision-number
   24

Revision ids (hashes) are hexadecimal strings that uniquely identify revisions.
They are useful to unambiguously refer to a revision and its history (e.g while
building a package you can embed the revision id as a hint about the origins of
the package):

.. code-block:: sh

   $ vcs-tool --repository coloredlogs --revision master --find-revision-id
   bce75c1eea88ebd40135cd45de716fe9591e348c

Exporting revisions
~~~~~~~~~~~~~~~~~~~

By default the repositories created by `vcs-repo-mgr` do not contain a working tree,
just the version control files (in Git_ terminology this is called a "bare
repository"). This has two reasons:

1. Bare repositories help conserve disk space. This is insignificant for small
   repositories, but on large repositories it can make a noticeable difference.
   Especially if you're using a lot of them :-)

2. Bare repositories enforce the principle that the working tree shouldn't be
   used during packaging (instead you should export the tree at a specific
   revision to a temporary directory and use that). This insistence on not
   using the working tree during packaging has two reasons:

   1. The working tree can contain files which are not under version control.
      Such files should certainly *not* be included in a package
      unintentionally.

   2. If the working tree of a repository is used, this makes it impossible to
      safely perform parallel builds from the same repository (the builds can
      corrupt each other's working tree).

This means that if you want to do something with the files in the repository
you have to export a revision to a (temporary) directory:

.. code-block:: sh

   $ vcs-tool --repository coloredlogs --export /tmp/coloredlogs-snapshot
   2014-05-04 19:17:24 INFO Exporting revision master of /tmp/coloredlogs to /tmp/coloredlogs-snapshot ..

   $ ls -l /tmp/coloredlogs-snapshot
   total 28K
   drwxrwxr-x 2 peter peter 4.0K May  3 14:31 coloredlogs
   drwxrwxr-x 3 peter peter 4.0K May  3 14:31 vim
   -rw-rw-r-- 1 peter peter 1.1K May  3 14:31 LICENSE.txt
   -rw-rw-r-- 1 peter peter   56 May  3 14:31 MANIFEST.in
   -rw-rw-r-- 1 peter peter 5.4K May  3 14:31 README.rst
   -rwxrwxr-x 1 peter peter 1.1K May  3 14:31 setup.py

Future improvements
-------------------

This section is currently a "braindump" which means I haven't committed to any
of these improvements, I'm just thinking out loud ;-).

**Improve interactive repository selection**
 Two improvements for interactive usage of the ``vcs-tool`` program:

 - Automatically load a repository's configuration when a pathname is given
   that matches an entry in a configuration file (right now you need to give
   the repository's name in order to load its configuration).

 - Do the obvious thing when no repository is specified on the command line but
   the working directory matches a configured repository.

**Wildcard matching in configuration files**
 It might be interesting to support shell wildcard matching against local
 directory names to apply a default configuration to a group of repositories?

**Enable more extensive customization**
 Right now the version control commands are hard coded and not easy to
 customize for those cases where the existing API gets you 90% of where you
 want to be but makes that last 10% impossible. Technically this is already
 possible through subclassing, but a more lightweight solution would
 certainly be nice to have :-).

**Switch to executor.contexts**
 Switch to executor.contexts_ for external command execution to enable
 dependency injection of command execution contexts. I haven't really
 investigated how complex the switch will be. It might be possible to somehow
 combine the above point (enable customization) and this point (dependency
 injection) but I'm not yet sure what that would look like.

**Extend Bazaar support**
 Try to bring Bazaar_ support up to par with the features supported for Git_
 and Mercurial_ repositories. To be honest I'm not sure this is worth the
 effort, I find myself working with Bazaar repositories less and less.

**Refactor test suite**
 The test suite started out based on clones of external repositories, simply
 because I lacked the means to create new repositories and make new commits yet
 needed repositories with existing commits to test against.

 Since then I never revisited this structure and the test suite has become a
 tangled mess of methods being called in the right order, dependent on each
 other's side effects. I should definitely revisit this and attempt to isolate
 all of these tests into separate test methods that don't depend on each other.

Known issues
------------

This section documents known issues that users may run into.

Problematic dependencies
~~~~~~~~~~~~~~~~~~~~~~~~

Bazaar and Mercurial are both written in Python and available on PyPI and as
such I included them in the installation requirements of `vcs-repo-mgr`,
because I couldn't think of a good reason not to.

Adding support for Python 3 to `vcs-repo-mgr` made things more complicated
because Bazaar and Mercurial didn't support Python 3, leading to installation
errors. To cope with this problem the Bazaar and Mercurial requirements were
made conditional on the Python version:

- On Python 2 the Bazaar and Mercurial packages would be installed together
  with `vcs-repo-mgr`.

- On Python 3 the user was instead responsible for making sure that Bazaar and
  Mercurial were installed (for example using system packages).

This works fine because `vcs-repo-mgr` only invokes Bazaar and Mercurial using
the command line interfaces so it doesn't matter whether the version control
system is using the same version of Python as `vcs-repo-mgr`.

Since then the installation of the Bazaar package has started failing on PyPy,
unfortunately this time there is no reliable and backwards compatible way to
make the Bazaar dependency optional in wheel distributions `due to bugs in
setuptools <https://github.com/html5lib/html5lib-python/issues/231#issuecomment-224022399>`_.

When I investigated support for environment markers that match Python
implementations (refer to the link above) I decided that instead of writing a
setup script full of nasty and fragile hacks I'd rather just drop official
(tested) support for PyPy, as silly as the reason for it may be.

Contact
-------

The latest version of `vcs-repo-mgr` is available on PyPI_ and GitHub_. For
bug reports please create an issue on GitHub_. If you have questions,
suggestions, etc. feel free to send me an e-mail at `peter@peterodding.com`_.

License
-------

This software is licensed under the `MIT license`_.

© 2016 Peter Odding.

.. External references:
.. _Bazaar: http://bazaar.canonical.com/en/
.. _executor.contexts: http://executor.readthedocs.org/en/latest/#module-executor.contexts
.. _Git: http://git-scm.com/
.. _GitHub: https://github.com/xolox/python-vcs-repo-mgr
.. _Mercurial: http://mercurial.selenic.com/
.. _MIT license: http://en.wikipedia.org/wiki/MIT_License
.. _online documentation: https://vcs-repo-mgr.readthedocs.org/en/latest/#function-reference
.. _per user site-packages directory: https://www.python.org/dev/peps/pep-0370/
.. _peter@peterodding.com: peter@peterodding.com
.. _PyPI: https://pypi.python.org/pypi/vcs-repo-mgr
.. _Read the Docs: https://vcs-repo-mgr.readthedocs.org/en/latest/#function-reference
.. _version control: http://en.wikipedia.org/wiki/Revision_control
.. _virtual environments: http://docs.python-guide.org/en/latest/dev/virtualenvs/

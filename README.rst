vcs-repo-mgr: Version control repository manager
================================================

.. image:: https://travis-ci.org/xolox/python-vcs-repo-mgr.svg?branch=master
   :target: https://travis-ci.org/xolox/python-vcs-repo-mgr

.. image:: https://coveralls.io/repos/xolox/python-vcs-repo-mgr/badge.png?branch=master
   :target: https://coveralls.io/r/xolox/python-vcs-repo-mgr?branch=master

The Python package ``vcs-repo-mgr`` provides a command line program and Python
API to perform common operations (in the context of packaging/deployment) on
`version control`_ repositories. It's currently tested on Python 2.6, 2.7 and
3.4. Bazaar_, Mercurial_ and Git_ repositories are currently supported.

Usage
-----

To get started you have to install the package:

  .. code-block:: sh

     peter@macbook> pip install vcs-repo-mgr

You will also need Bazaar_, Mercurial_ and/or Git_ installed (depending on the
type of repositories you want to work with). Here's how you install them on
Debian/Ubuntu:

  .. code-block:: sh

     peter@macbook> sudo apt-get install bzr mercurial git-core

You now have the ``vcs-tool`` command available:

  .. code-block:: sh

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
         location should be prefixed by the type of the repository (with a '+' in
         between) unless the location ends in '.git' in which case the prefix is
         optional.

       --rev, --revision=REVISION

         Select a revision to operate on. Accepts any string that's supported by the
         VCS system that manages the repository, which means you can provide branch
         names, tag names, exact revision ids, etc. This option is used in
         combination with the --find-revision-number, --find-revision-id and
         --export options.

         If this option is not provided a default revision is selected: 'last:1' for
         Bazaar repositories, 'master' for git repositories and 'default' (not
         'tip'!) for Mercurial repositories.

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
         name will be one of 'Vcs-Bzr', 'Vcs-Hg' or 'Vcs-Git'. The value will be the
         repository's remote location and the selected revision (separated by a '#'
         character).

       -u, --update

         Create/update the local clone of a remote repository by pulling the latest
         changes from the remote repository. This option is used in combination with
         the --repository option.

       -e, --export=DIRECTORY

         Export the contents of a specific revision of a repository to a local
         directory. This option is used in combination with the --repository and
         --revision options.

       -d, --find-directory

         Print the absolute pathname of a local repository. This option is used in
         combination with the --repository option.

       -v, --verbose

         Make more noise.

       -h, --help

         Show this message and exit.

The primary way to use the ``vcs-tool`` command requires you to create a
configuration file:

  .. code-block:: sh

     peter@macbook> cat > ~/.vcs-repo-mgr.ini << EOF
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

     peter@macbook> vcs-tool --repository coloredlogs --update
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

     peter@macbook> vcs-tool --repository coloredlogs --update
     2014-05-04 18:55:56 INFO Updating Git clone of git@github.com:xolox/python-coloredlogs.git at /tmp/coloredlogs ..
     From github.com:xolox/python-coloredlogs
      * branch HEAD -> FETCH_HEAD

Finding revision numbers/ids
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Revision numbers are integer numbers that increment with every added revision.
They're very useful during packaging/deployment:

  .. code-block:: sh

     peter@macbook> vcs-tool --repository coloredlogs --revision master --find-revision-number
     24

Revision ids (hashes) are hexadecimal strings that uniquely identify revisions.
They are useful to unambiguously refer to a revision and its history (e.g while
building a package you can embed the revision id as a hint about the origins of
the package):

  .. code-block:: sh

     peter@macbook> vcs-tool --repository coloredlogs --revision master --find-revision-id
     bce75c1eea88ebd40135cd45de716fe9591e348c

Exporting revisions
~~~~~~~~~~~~~~~~~~~

The repositories created by ``vcs-repo-mgr`` do not contain a working tree,
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

     peter@macbook> vcs-tool --repository coloredlogs --export /tmp/coloredlogs-snapshot
     2014-05-04 19:17:24 INFO Exporting revision master of /tmp/coloredlogs to /tmp/coloredlogs-snapshot ..

     peter@macbook> ls -l /tmp/coloredlogs-snapshot
     total 28K
     drwxrwxr-x 2 peter peter 4.0K May  3 14:31 coloredlogs
     drwxrwxr-x 3 peter peter 4.0K May  3 14:31 vim
     -rw-rw-r-- 1 peter peter 1.1K May  3 14:31 LICENSE.txt
     -rw-rw-r-- 1 peter peter   56 May  3 14:31 MANIFEST.in
     -rw-rw-r-- 1 peter peter 5.4K May  3 14:31 README.rst
     -rwxrwxr-x 1 peter peter 1.1K May  3 14:31 setup.py

Contact
-------

The latest version of ``vcs-repo-mgr`` is available on PyPi_ and GitHub_. For
bug reports please create an issue on GitHub_. If you have questions,
suggestions, etc. feel free to send me an e-mail at `peter@peterodding.com`_.

License
-------

This software is licensed under the `MIT license`_.

© 2014 Peter Odding.

.. External references:
.. _Bazaar: http://bazaar.canonical.com/en/
.. _Git: http://git-scm.com/
.. _GitHub: https://github.com/xolox/python-vcs-repo-mgr
.. _Mercurial: http://mercurial.selenic.com/
.. _MIT license: http://en.wikipedia.org/wiki/MIT_License
.. _online documentation: https://vcs-repo-mgr.readthedocs.org/en/latest/#function-reference
.. _peter@peterodding.com: peter@peterodding.com
.. _PyPi: https://pypi.python.org/pypi/vcs-repo-mgr
.. _version control: http://en.wikipedia.org/wiki/Revision_control

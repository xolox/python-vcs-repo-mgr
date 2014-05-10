vcs-repo-mgr: Version control repository manager
================================================

.. image:: https://travis-ci.org/xolox/python-vcs-repo-mgr.svg?branch=master
   :target: https://travis-ci.org/xolox/python-vcs-repo-mgr

.. image:: https://coveralls.io/repos/xolox/python-vcs-repo-mgr/badge.png?branch=master
   :target: https://coveralls.io/r/xolox/python-vcs-repo-mgr?branch=master

The Python package ``vcs-repo-mgr`` provides a command line program and Python
API to perform common operations (in the context of packaging/deployment) on
`version control`_ repositories. It's currently tested on Python 2.6, 2.7 and
3.4. At the moment only Mercurial_ and Git_ repositories are supported.

Usage
-----

To get started you have to install the package:

  .. code-block:: sh

     peter@macbook> pip install vcs-repo-mgr

You will also need Mercurial_ and/or Git_ installed (depending on the type
of repositories you want to work with). Here's how you install them on
Debian/Ubuntu:

  .. code-block:: sh

     peter@macbook> sudo apt-get install mercurial git-core

You now have the ``vcs-tool`` command available:

  .. code-block:: sh

     peter@macbook> vcs-tool --help
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

Before you can use the ``vcs-tool`` command you have to create a configuration
file:

  .. code-block:: sh

     peter@macbook> cat > ~/.vcs-repo-mgr.ini << EOF
     [coloredlogs]
     type = git
     local = /tmp/coloredlogs
     remote = git@github.com:xolox/python-coloredlogs.git
     EOF

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
.. _Git: http://git-scm.com/
.. _GitHub: https://github.com/xolox/python-vcs-repo-mgr
.. _Mercurial: http://mercurial.selenic.com/
.. _MIT license: http://en.wikipedia.org/wiki/MIT_License
.. _online documentation: https://vcs-repo-mgr.readthedocs.org/en/latest/#function-reference
.. _peter@peterodding.com: peter@peterodding.com
.. _PyPi: https://pypi.python.org/pypi/vcs-repo-mgr
.. _version control: http://en.wikipedia.org/wiki/Revision_control

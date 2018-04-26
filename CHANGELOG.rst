Changelog
=========

The purpose of this document is to list all of the notable changes to this
project. The format was inspired by `Keep a Changelog`_. This project adheres
to `semantic versioning`_.

.. contents::
   :local:

`Release 4.2`_ (2018-04-26)
---------------------------

- Added this changelog.
- Added ``license`` key to setup script.

.. _Release 4.2: https://github.com/xolox/python-vcs-repo-mgr/compare/4.1.3...4.2

`Release 4.1.3`_ (2018-03-28)
-----------------------------

Bug fix: Restore support for exporting to directories with relative pathnames.

.. _Release 4.1.3: https://github.com/xolox/python-vcs-repo-mgr/compare/4.1.2...4.1.3

`Release 4.1.2`_ (2018-03-28)
-----------------------------

Bug fix: Make sure ``update_context()`` is called before ``is_bare()`` is invoked.

.. _Release 4.1.2: https://github.com/xolox/python-vcs-repo-mgr/compare/4.1.1...4.1.2

`Release 4.1.1`_ (2018-03-08)
-----------------------------

Bug fix: Resolve issue `#5`_ by expanding remote git branch names to be unambiguous.

.. _Release 4.1.1: https://github.com/xolox/python-vcs-repo-mgr/compare/4.1...4.1.1
.. _#5: https://github.com/xolox/python-vcs-repo-mgr/issues/5

`Release 4.1`_ (2018-03-08)
---------------------------

- Bug fix: Resolve issue `#4`_ by implementing a new approach to "git branch
  name discovery" (that works equally well for local branches as it does for
  remote branches) by switching from ``git branch --list --verbose`` to ``git
  for-each-ref``.

- Document MacOS compatibility, run MacOS tests on Travis CI. While I never
  specifically intended for vcs-repo-mgr to be used on Apple systems, a
  colleague of mine has been trying to do exactly this and has run into a
  number of issues that are probably caused by platform incompatibilities in
  vcs-repo-mgr and/or its dependencies.

.. _Release 4.1: https://github.com/xolox/python-vcs-repo-mgr/compare/4.0...4.1
.. _#4: https://github.com/xolox/python-vcs-repo-mgr/issues/4

`Release 4.0`_ (2018-03-05)
---------------------------

- Backwards incompatible: Force internal merge tool for Mercurial. After
  isolating the test suite from ``$HOME`` my ``~/.hgrc`` was ignored and the
  following setting disappeared:

  .. code-block:: ini

     [ui]
     merge = internal:merge

  Then I ran the `vcs-repo-mgr` test suite and ``meld`` popped up. Not what I
  was expecting from an automated test suite! Although it seems unlikely to me
  that someone would depend on the old behavior the introduction of ``hg
  --config ui.merge=internal:merge`` is backwards incompatible and version
  numbers are cheap, so I'm bumping the major version number :-).

  I do think the new behavior is a better default for the Mercurial backend
  given the focus of `vcs-repo-mgr` on automation, if only to make this backend
  match the behavior of the other backends.

- Isolate the test suite from ``$HOME``. I recently added the following to my
  ``~/.gitconfig``:

  .. code-block:: ini

     [commit]
     gpgsign = true

  Then I ran the `vcs-repo-mgr` test suite and I was not amused :-P. This
  should fix the underlying more generic issue.

.. _Release 4.0: https://github.com/xolox/python-vcs-repo-mgr/compare/3.0...4.0

`Release 3.0`_ (2018-03-05)
---------------------------

- Backwards incompatible: Raise an exception when a working tree is required
  but missing. This change is technically backwards incompatible in more than
  one way:

  1. Requiring subclasses to implement the ``supports_working_tree`` property
     breaks external subclasses (outside of my control).

  2. The new exception previously wasn't there and would never be raised, but
     then all of the affected operations (requiring a working tree) would
     likely end in an external command failure.

  For what it's worth: I don't expect these changes to bite any real life use
  cases.

- Merged pull request `#3`_ to improve MacOS compatibility (by replacing
  ``mkdir --parents`` with ``mkdir -p``).

- Starting from this release the files needed to generate documentation are
  included in source distributions.

- Moved the ``coerce_pattern()`` function to the humanfriendly_ package
  (because I wanted to be able to use it in qpass_ as well).

.. _Release 3.0: https://github.com/xolox/python-vcs-repo-mgr/compare/2.0.1...3.0
.. _#3: https://github.com/xolox/python-vcs-repo-mgr/pulls/3
.. _humanfriendly: https://humanfriendly.readthedocs.io/
.. _qpass: https://qpass.readthedocs.io/

`Release 2.0.1`_ (2017-08-02)
-----------------------------

Bug fix: Ignore untracked files in ``HgRepo.commit()``.

.. _Release 2.0.1: https://github.com/xolox/python-vcs-repo-mgr/compare/2.0...2.0.1

`Release 2.0`_ (2017-07-14)
---------------------------

Various changes to ``merge_up()``:

- Automatically create release branches.
- Skip merging up when target branch is default branch.
- Bug fix: Don't delete or close non-feature-branches.

.. _Release 2.0: https://github.com/xolox/python-vcs-repo-mgr/compare/1.0...2.0

`Release 1.0`_ (2017-07-03)
---------------------------

**Major rewrite: Named remotes, selective pushing, init support, etc.**

Brain dump of changes:

- What triggered me to start on a major rewrite was that I'd gotten fed up with
  the current (horrible) test suite because it depends on the cloning of remote
  public repositories which makes it slow and fragile. To underline why it is
  fragile:

  I only know of one place to find public Bazaar repositories which is
  Launchpad.net, however cloning a Bazaar repository from Launchpad fails more
  often than it works. Recently the 'more often' turned into always and the
  test coverage of the Bazaar support in `vcs-repo-mgr` basically disappeared,
  without any action from me :-(.

  To improve the test suite I wanted to add support for ``bzr init``, ``git
  init`` and ``hg init``. However that would have made the code even uglier
  than it already was and so the rewrite was triggered :-).

  Support for ``init`` has been added, by the way :-P. I've also added support
  for creating tags, otherwise I wouldn't have been able to test the support
  for tags :-).

  After the rewrite I also rewrote the test suite, it's a completely different
  beast now. Stil slow, but much more robust and with quicker feedback about
  individual tests.

- The ``push()`` and ``pull()`` methods can work with specific revisions and
  ``merge_up()`` has been changed to pull a specific revision (the feature
  branch that it merges in).

- The API between the ``Repository`` superclass and the subclasses that
  implement support for a specific version control system has been changed
  completely, in various backwards incompatible ways.

- The new API enables introspection of 'remotes' (the repositories from which
  you clone/pull and the repositories that you push to) which enables
  ``pull()`` to know whether a 'default remote' is configured for any given
  repository.

- The new API has a class to represent commit authors, enabling less ad-hoc
  communication between the superclass, its subclasses and callers.

- In the process of rewriting everything I've switched to using execution
  contexts created by ``executor.contexts``, this enables me to configure the
  working directory in two places instead of having to repeat the same thing in
  a hundred different places. This change also gives callers much more control
  over how external commands are executed (so much control that you can in
  theory run the commands on a remote system over SSH without having a version
  control system installed on your local system :-P).

- Support for specific version control systems has been extracted from the main
  ``vcs_repo_mgr`` module into separate modules under the
  ``vcs_repo_mgr.backends`` namespace. The modules in the backends namespace
  are loaded on demand.

.. _Release 1.0: https://github.com/xolox/python-vcs-repo-mgr/compare/0.34...1.0

`Release 0.34`_ (2017-04-29)
----------------------------

- Improved the command line interface.
- Added Python 3.6 to tested Python versions.
- Refactored makefile (and Travis CI and Tox configs).

.. _Release 0.34: https://github.com/xolox/python-vcs-repo-mgr/compare/0.33.1...0.34

`Release 0.33.1`_ (2016-11-30)
------------------------------

Update ``stdeb.cfg`` from ``setup.py`` (to avoid duplicate dependencies).

.. _Release 0.33.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.33...0.33.1

`Release 0.33`_ (2016-10-26)
----------------------------

- Support for pushing between repositories.
- Started publishing wheel distributions.
- Improved documentation on raised exceptions.
- Improved logging in ``Repository.update()``.
- Droped support for PyPy (refer to readme changes for details).

.. _Release 0.33: https://github.com/xolox/python-vcs-repo-mgr/compare/0.32.1...0.33

`Release 0.32.1`_ (2016-08-04)
------------------------------

- Refactor setup script to fix issue `#2`_ (``UnicodeDecodeError`` in ``setup.py`` on Python 3).
- Run test suite on Travis CI under PyPy as well (works for me with tox :-)

.. _Release 0.32.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.32...0.32.1
.. _#2: https://github.com/xolox/python-vcs-repo-mgr/issues/2

`Release 0.32`_ (2016-04-20)
----------------------------

Enable feature branch customization for ``merge_up()``.

.. _Release 0.32: https://github.com/xolox/python-vcs-repo-mgr/compare/0.31...0.32

`Release 0.31`_ (2016-04-20)
----------------------------

Support for interactive merge conflict resolution.

.. _Release 0.31: https://github.com/xolox/python-vcs-repo-mgr/compare/0.30...0.31

`Release 0.30`_ (2016-03-18)
----------------------------

Added a command line interface for the ``merge_up()`` functionality.

.. _Release 0.30: https://github.com/xolox/python-vcs-repo-mgr/compare/0.29...0.30

`Release 0.29`_ (2016-03-18)
----------------------------

Make it possible to merge changes up through release branches.

.. _Release 0.29: https://github.com/xolox/python-vcs-repo-mgr/compare/0.28...0.29

`Release 0.28`_ (2016-03-18)
----------------------------

Make it possible to add new files to repositories.

.. _Release 0.28: https://github.com/xolox/python-vcs-repo-mgr/compare/0.27.2...0.28

`Release 0.27.2`_ (2016-03-18)
------------------------------

Bug fix for previous commit (concerning the ``hg remove --after`` return code).

.. _Release 0.27.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.27.1...0.27.2

`Release 0.27.1`_ (2016-03-18)
------------------------------

Run ``hg remove --after`` before ``hg commit``.

.. _Release 0.27.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.27...0.27.1

`Release 0.27`_ (2016-03-16)
----------------------------

Expose the name of the currently checked out branch.

.. _Release 0.27: https://github.com/xolox/python-vcs-repo-mgr/compare/0.26.1...0.27

`Release 0.26.1`_ (2016-03-16)
------------------------------

Bug fix for ``hg`` command invocations, refer to the following Travis CI build
failure for details: https://travis-ci.org/xolox/python-vcs-repo-mgr/jobs/116499864.

.. _Release 0.26.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.26...0.26.1

`Release 0.26`_ (2016-03-16)
----------------------------

Make it possible to delete merged branches.

.. _Release 0.26: https://github.com/xolox/python-vcs-repo-mgr/compare/0.25...0.26

`Release 0.25`_ (2016-03-16)
----------------------------

- Automatic ``Repository`` subclass registration using metaclasses.
- Move aliases from ``repository_factory()`` to ``Repository`` subclasses.
- Transform the ``vcs_directory`` and ``exists`` properties into static methods.
- Make ``repository_factory()`` a bit more flexible.
- Make ``coerce_repository()`` infer VCS types from local directories

.. _Release 0.25: https://github.com/xolox/python-vcs-repo-mgr/compare/0.24.1...0.25

`Release 0.24.1`_ (2016-03-16)
------------------------------

Bug fix for unattended ``git merge`` support.

.. _Release 0.24.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.24...0.24.1

`Release 0.24`_ (2016-03-16)
----------------------------

Make it possible to merge between branches.

.. _Release 0.24: https://github.com/xolox/python-vcs-repo-mgr/compare/0.23.1...0.24

`Release 0.23.1`_ (2016-03-16)
------------------------------

Switch from ``git diff`` to ``git diff HEAD`` (see the inline documentation for
more details).

.. _Release 0.23.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.23...0.23.1

`Release 0.23`_ (2016-03-16)
----------------------------

Make it possible to create new branches.

.. _Release 0.23: https://github.com/xolox/python-vcs-repo-mgr/compare/0.22.3...0.23

`Release 0.22.3`_ (2016-03-16)
------------------------------

- Start using the ``@lazy_property`` decorator.
- Bug fix for git commit message author handling.
- Stop Travis CI from launching builds for tags.

.. _Release 0.22.3: https://github.com/xolox/python-vcs-repo-mgr/compare/0.22.2...0.22.3

`Release 0.22.2`_ (2016-03-16)
------------------------------

A bug fix for the test suite.

.. _Release 0.22.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.22.1...0.22.2

`Release 0.22.1`_ (2016-03-16)
------------------------------

Improve handling of commit authors.

The general idea behind the new implementation is to reconcile two opposing
forces:

- Don't rely on configuration files (I'm building a Python API after all).
- Respect the values in configuration files when available (because of the Do
  What I Mean aspect).

.. _Release 0.22.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.22...0.22.1

`Release 0.22`_ (2016-03-16)
----------------------------

- Make it possible to commit changes.
- Add Python 3.5 to supported versions.

.. _Release 0.22: https://github.com/xolox/python-vcs-repo-mgr/compare/0.21...0.22

`Release 0.21`_ (2016-03-16)
----------------------------

Make it possible to override the remote for ``create()`` and ``update()`` calls.

.. _Release 0.21: https://github.com/xolox/python-vcs-repo-mgr/compare/0.20.1...0.21

`Release 0.20.1`_ (2016-03-16)
------------------------------

Fixed a Python 3 incompatibility in the test suite.

.. _Release 0.20.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.20...0.20.1

`Release 0.20`_ (2016-03-16)
----------------------------

Enable updating of the working tree to different revisions.

.. _Release 0.20: https://github.com/xolox/python-vcs-repo-mgr/compare/0.19...0.20

`Release 0.19`_ (2016-03-16)
----------------------------

- Start switching to property-manager_.
- Force Read the Docs to install with ``pip`` instead of ``python setup.py install``.

.. _Release 0.19: https://github.com/xolox/python-vcs-repo-mgr/compare/0.18.2...0.19
.. _property-manager: https://property-manager.readthedocs.io/

`Release 0.18.2`_ (2016-03-15)
------------------------------

Enable ``bare=None`` in ``find_configured_repository()``.

.. _Release 0.18.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.18.1...0.18.2

`Release 0.18.1`_ (2016-03-15)
------------------------------

- Make preference for (non-)bare repositories more flexible.
- Give readme & documentation some much needed love.

.. _Release 0.18.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.18...0.18.1

`Release 0.18`_ (2016-03-15)
----------------------------

Make it possible to check whether a working tree is clean.

.. _Release 0.18: https://github.com/xolox/python-vcs-repo-mgr/compare/0.17...0.18

`Release 0.17`_ (2016-03-15)
----------------------------

Enable clones with working trees (non-bare clones).

.. _Release 0.17: https://github.com/xolox/python-vcs-repo-mgr/compare/0.16...0.17

`Release 0.16`_ (2016-03-15)
----------------------------

- Make it possible to check for bare checkouts
- Document existing CONSTANTS, make ``known_release_schemes`` a documented constant as well.
- Implement and enforce PEP-8 and PEP-257 compliance.

.. _Release 0.16: https://github.com/xolox/python-vcs-repo-mgr/compare/0.15.1...0.16

`Release 0.15.1`_ (2015-08-19)
------------------------------

Bug fix: Make sure ``git fetch`` *always* updates local branches.

To be honest I'm not sure why I never ran into this before, I've been
using this functionality for months and updates always came in just
fine based on the same version of git. Nevertheless the new ``git fetch``
command is the proper, documented way to do what I want ``git`` to do so
here we go :-).

Detailed explanation: http://stackoverflow.com/a/10697486

.. _Release 0.15.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.15...0.15.1

`Release 0.15`_ (2015-06-25)
----------------------------

- Expand ``~/`` and ``$HOME`` in configuration file (issue `#1`_).
- Improve documentation of ``find_configured_repository()``.
- Improve documentation on how ``limit_vcs_updates`` works.

.. _Release 0.15: https://github.com/xolox/python-vcs-repo-mgr/compare/0.14...0.15
.. _#1: https://github.com/xolox/python-vcs-repo-mgr/issues/1

`Release 0.14`_ (2015-05-08)
----------------------------

- Move exceptions to separate module.
- Various documentation improvements.

.. _Release 0.14: https://github.com/xolox/python-vcs-repo-mgr/compare/0.13...0.14

`Release 0.13`_ (2015-05-08)
----------------------------

Shortcuts to translate release identifiers to branches/tags (also got test
coverage back up to +/- 97%).

.. _Release 0.13: https://github.com/xolox/python-vcs-repo-mgr/compare/0.12...0.13

`Release 0.12`_ (2015-03-16)
----------------------------

Expose release specific functionality in CLI (listing & selection).

.. _Release 0.12: https://github.com/xolox/python-vcs-repo-mgr/compare/0.11...0.12

`Release 0.11`_ (2015-03-16)
----------------------------

- Expose release selection in CLI (similar to revision selection).
- Fix RST format typo in ``find_configured_repository()`` docstring.

.. _Release 0.11: https://github.com/xolox/python-vcs-repo-mgr/compare/0.10...0.11

`Release 0.10`_ (2015-02-19)
----------------------------

- Don't construct duplicate ``Repository`` objects (when possible to avoid).
- Improve argument validation in ``Repository`` initializer.
- Move autovivification of local clones to ``Repository`` initializer.
- ``make install`` should install 'dynamic dependencies' as well.

.. _Release 0.10: https://github.com/xolox/python-vcs-repo-mgr/compare/0.9...0.10

`Release 0.9`_ (2015-02-19)
---------------------------

Changed release querying API, added "release selection" API.

.. _Release 0.9: https://github.com/xolox/python-vcs-repo-mgr/compare/0.8...0.9

`Release 0.8`_ (2015-02-19)
---------------------------

Experimental support for "releases" (can be based on tags or branches).

.. _Release 0.8: https://github.com/xolox/python-vcs-repo-mgr/compare/0.7...0.8

`Release 0.7`_ (2014-11-02)
---------------------------

Auto vivification of VCS repositories.

.. _Release 0.7: https://github.com/xolox/python-vcs-repo-mgr/compare/0.6.4...0.7

`Release 0.6.4`_ (2014-09-14)
-----------------------------

Support for generating Debian control file ``Vcs-*`` fields.

.. _Release 0.6.4: https://github.com/xolox/python-vcs-repo-mgr/compare/0.6.3...0.6.4

`Release 0.6.3`_ (2014-09-14)
-----------------------------

Another bug fix for Python 3.x compatibility in test suite.

.. _Release 0.6.3: https://github.com/xolox/python-vcs-repo-mgr/compare/0.6.2...0.6.3

`Release 0.6.2`_ (2014-09-14)
-----------------------------

Bug fix to make test suite compatible with Python 3.x.
See https://travis-ci.org/xolox/python-vcs-repo-mgr/jobs/35273703.

.. _Release 0.6.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.6.1...0.6.2

`Release 0.6.1`_ (2014-09-14)
-----------------------------

Support for summing revision numbers from multiple repositories.

.. _Release 0.6.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.6...0.6.1

`Release 0.6`_ (2014-09-14)
---------------------------

Support for Bazaar repositories.

.. _Release 0.6: https://github.com/xolox/python-vcs-repo-mgr/compare/0.5...0.6

`Release 0.5`_ (2014-09-14)
---------------------------

Support for tags (also rewrote the test suite and increased test coverage).

.. _Release 0.5: https://github.com/xolox/python-vcs-repo-mgr/compare/0.4...0.5

`Release 0.4`_ (2014-06-25)
---------------------------

Rename ``limit_repo_updates`` to ``limit_vcs_updates`` (backwards incompatible).

.. _Release 0.4: https://github.com/xolox/python-vcs-repo-mgr/compare/0.3.2...0.4

`Release 0.3.2`_ (2014-06-22)
-----------------------------

Try to unbreak Python 3.x tests on Travis CI.

.. _Release 0.3.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.3.1...0.3.2

`Release 0.3.1`_ (2014-06-22)
-----------------------------

Bug fix for 'rate limiting' of repository updates.

.. _Release 0.3.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.3...0.3.1

`Release 0.3`_ (2014-06-19)
---------------------------

Support 'rate limiting' of repository updates.

.. _Release 0.3: https://github.com/xolox/python-vcs-repo-mgr/compare/0.2.4...0.3

`Release 0.2.4`_ (2014-05-31)
-----------------------------

- Change Mercurial from Debian dependency to Python dependency.
- Improve test coverage by testing command line interface.

.. _Release 0.2.4: https://github.com/xolox/python-vcs-repo-mgr/compare/0.2.3...0.2.4

`Release 0.2.3`_ (2014-05-11)
-----------------------------

- Automatically create local repositories on the first run.
- Bump humanfriendly requirement due to Python 3 compatibility.

.. _Release 0.2.3: https://github.com/xolox/python-vcs-repo-mgr/compare/0.2.2...0.2.3

`Release 0.2.2`_ (2014-05-11)
-----------------------------

Removed dead code and increased test coverage.

.. _Release 0.2.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.2.1...0.2.2

`Release 0.2.1`_ (2014-05-10)
-----------------------------

- Bug fix for ``Revision.revision_number``.
- Improved test coverage, started using Coveralls.io.

.. _Release 0.2.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.2...0.2.1

`Release 0.2`_ (2014-05-10)
---------------------------

- Document supported Python versions (2.6, 2.7 & 3.4).
- Switch git clone in tests to use HTTPS instead of SSH
- Start using Travis CI.

.. _Release 0.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.1.5...0.2

`Release 0.1.5`_ (2014-05-05)
-----------------------------

Bug fix: Include ``stdeb.cfg`` in source distributions (via ``MANIFEST.in``).

.. _Release 0.1.5: https://github.com/xolox/python-vcs-repo-mgr/compare/0.1.4...0.1.5

`Release 0.1.4`_ (2014-05-05)
-----------------------------

- Document the dependency on ``git`` and ``hg`` executables.
- Document dependencies on Debian system packages in ``stdeb.cfg``.

.. _Release 0.1.4: https://github.com/xolox/python-vcs-repo-mgr/compare/0.1.3...0.1.4

`Release 0.1.3`_ (2014-05-04)
-----------------------------

Add the usage message of the ``vcs-tool`` program to the documentation.

.. _Release 0.1.3: https://github.com/xolox/python-vcs-repo-mgr/compare/0.1.2...0.1.3

`Release 0.1.2`_ (2014-05-04)
-----------------------------

Added support for ``vcs-tool --find-directory`` option.

.. _Release 0.1.2: https://github.com/xolox/python-vcs-repo-mgr/compare/0.1.1...0.1.2

`Release 0.1.1`_ (2014-05-04)
-----------------------------

Bug fix: Added missing ``humanfriendly`` dependency.

.. _Release 0.1.1: https://github.com/xolox/python-vcs-repo-mgr/compare/0.1...0.1.1

`Release 0.1`_ (2014-05-04)
---------------------------

The initial commit with support for cloning repositories, pulling updates,
exporting revisions, querying revision ids and numbers for Git and Mercurial
repositories.

.. _Release 0.1: https://github.com/xolox/python-vcs-repo-mgr/tree/0.1

.. _Keep a Changelog: http://keepachangelog.com/
.. _semantic versioning: http://semver.org/

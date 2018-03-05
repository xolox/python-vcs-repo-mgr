#!/usr/bin/env python

# Setup script for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 5, 2018
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""
Setup script for the `vcs-repo-mgr` package.

**python setup.py install**
  Install from the working directory into the current Python environment.

**python setup.py sdist**
  Build a source distribution archive.

**python setup.py bdist_wheel**
  Build a wheel distribution archive.
"""

# Standard library modules.
import codecs
import os
import re
import sys

# De-facto standard solution for Python packaging.
from setuptools import find_packages, setup

PY2 = (sys.version_info[0] == 2)
""":data:`True` on Python 2, :data:`False` otherwise."""


def get_contents(*args):
    """Get the contents of a file relative to the source distribution directory."""
    with codecs.open(get_absolute_path(*args), 'r', 'UTF-8') as handle:
        return handle.read()


def get_version(*args):
    """Extract the version number from a Python module."""
    contents = get_contents(*args)
    metadata = dict(re.findall('__([a-z]+)__ = [\'"]([^\'"]+)', contents))
    return metadata['version']


def get_install_requires():
    """Add conditional dependencies (when creating source distributions)."""
    install_requires = get_requirements('requirements.txt')
    if 'bdist_wheel' not in sys.argv:
        if sys.version_info[0] == 2:
            # On Python 2.6 and 2.7 we pull in Bazaar.
            install_requires.append('bzr >= 2.6.0')
        if sys.version_info[2:] == (2, 6):
            # On Python 2.6 we have to stick to versions of Mercurial below 4.3
            # because 4.3 drops support for Python 2.6, see the change log:
            # https://www.mercurial-scm.org/wiki/WhatsNew
            install_requires.append('mercurial >= 2.9, < 4.3')
        elif (2, 6) < sys.version_info[:2] < (3, 0):
            # On Python 2.7 we pull in Mercurial.
            install_requires.append('mercurial >= 2.9')
    return sorted(install_requires)


def get_extras_require():
    """Add conditional dependencies (when creating wheel distributions)."""
    extras_require = {}
    if have_environment_marker_support():
        extras_require[':python_version == "2.6"'] = ['bzr >= 2.6.0', 'mercurial >= 2.9, < 4.3']
        extras_require[':python_version == "2.7"'] = ['bzr >= 2.6.0', 'mercurial >= 2.9']
    return extras_require


def get_requirements(*args):
    """Get requirements from pip requirement files."""
    requirements = set()
    with open(get_absolute_path(*args)) as handle:
        for line in handle:
            # Strip comments.
            line = re.sub(r'^#.*|\s#.*', '', line)
            # Ignore empty lines
            if line and not line.isspace():
                requirements.add(re.sub(r'\s+', '', line))
    return sorted(requirements)


def get_absolute_path(*args):
    """Transform relative pathnames into absolute pathnames."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *args)


def have_environment_marker_support():
    """
    Check whether setuptools has support for PEP-426 environment marker support.

    Based on the ``setup.py`` script of the ``pytest`` package:
    https://bitbucket.org/pytest-dev/pytest/src/default/setup.py
    """
    try:
        from pkg_resources import parse_version
        from setuptools import __version__
        return parse_version(__version__) >= parse_version('0.7.2')
    except Exception:
        return False


# When our installation requirements include Bazaar and Mercurial it is silly
# to also require the Bazaar and Mercurial system packages through stdeb.cfg
# so we overwrite the file to remove these dependencies.
if PY2:
    with open(get_absolute_path('stdeb.cfg'), 'w') as handle:
        handle.write('[vcs-repo-mgr]\n')
        handle.write('Depends: git | git-core\n')


setup(name='vcs-repo-mgr',
      version=get_version('vcs_repo_mgr', '__init__.py'),
      description="Version control repository manager",
      long_description=get_contents('README.rst'),
      url='https://github.com/xolox/python-vcs-repo-mgr',
      author="Peter Odding",
      author_email='peter@peterodding.com',
      packages=find_packages(),
      entry_points=dict(console_scripts=[
          'vcs-tool = vcs_repo_mgr.cli:main',
      ]),
      install_requires=get_install_requires(),
      extras_require=get_extras_require(),
      test_suite='vcs_repo_mgr.tests',
      classifiers=[
          'Development Status :: 5 - Production/Stable',
          'Environment :: Console',
          'Intended Audience :: Developers',
          'Intended Audience :: Information Technology',
          'Intended Audience :: System Administrators',
          'License :: OSI Approved :: MIT License',
          'Operating System :: POSIX',
          'Operating System :: Unix',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 2.6',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.4',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Topic :: Software Development :: Libraries :: Python Modules',
          'Topic :: Software Development :: Version Control',
          'Topic :: System :: Archiving :: Packaging',
          'Topic :: System :: Software Distribution',
          'Topic :: System :: Systems Administration',
          'Topic :: Utilities',
      ])

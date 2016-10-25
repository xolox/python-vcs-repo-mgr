#!/usr/bin/env python

# Setup script for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 25, 2016
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

PYTHON_TWO_DEPS = ['bzr >= 2.6.0', 'mercurial >= 2.9']
"""
The `vcs-repo-mgr` package depends on Bazaar and Mercurial which don't support
Python 3 (at the time of writing) while `vcs-repo-mgr` does support Python 3.

On the one hand it's nice to pull in recent versions of these dependencies as
installation requirements when possible, it definitely shouldn't make it
impossible to install `vcs-repo-mgr` under Python 3. Because of this the Bazaar
and Mercurial dependencies are conditional; users that are running Python 3 are
expected to install Bazaar and/or Mercurial via e.g. their system package
manager.
"""


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
    """Add conditional dependencies for Python 2 (when creating source distributions)."""
    install_requires = get_requirements('requirements.txt')
    if 'bdist_wheel' not in sys.argv:
        if sys.version_info[0] == 2:
            install_requires.extend(PYTHON_TWO_DEPS)
    return sorted(install_requires)


def get_extras_require():
    """Add conditional dependencies for Python 2 (when creating wheel distributions)."""
    extras_require = {}
    if have_environment_marker_support():
        expression = ':python_version == "2.6" or python_version == "2.7"'
        extras_require[expression] = list(PYTHON_TWO_DEPS)
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
          'Topic :: Software Development :: Libraries :: Python Modules',
          'Topic :: Software Development :: Version Control',
          'Topic :: System :: Archiving :: Packaging',
          'Topic :: System :: Software Distribution',
          'Topic :: System :: Systems Administration',
          'Topic :: Utilities',
      ])

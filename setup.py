#!/usr/bin/env python

# Setup script for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: August 4, 2016
# URL: https://github.com/xolox/python-vcs-repo-mgr

"""
Setup script for the ``vcs-repo-mgr`` package.

**python setup.py install**
  Install from the working directory into the current Python environment.

**python setup.py sdist**
  Build a source distribution archive.
"""

# Standard library modules.
import codecs
import os
import re
import sys

# De-facto standard solution for Python packaging.
from setuptools import find_packages, setup


def get_contents(*args):
    """Get the contents of a file relative to the source distribution directory."""
    with codecs.open(get_absolute_path(*args), 'r', 'UTF-8') as handle:
        return handle.read()


def get_version(*args):
    """Extract the version number from a Python module."""
    contents = get_contents(*args)
    metadata = dict(re.findall('__([a-z]+)__ = [\'"]([^\'"]+)', contents))
    return metadata['version']


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


# Fill in the "install_requires" field based on requirements.txt.
requirements = get_requirements('requirements.txt')

# The vcs-repo-mgr package depends on Mercurial however Mercurial doesn't
# support Python 3.x while vcs-repo-mgr does support Python 3.x. Because most
# users will be using Python 2.x in the foreseeable future I've decided to be
# pragmatic about things and turn Mercurial into a conditional dependency.
# See also: http://mercurial.selenic.com/wiki/SupportedPythonVersions
#
# TODO Make this compatible with binary wheels.
if sys.version_info[0] == 2:
    requirements.append('bzr >= 2.6.0')
    requirements.append('mercurial >= 2.9')
else:
    # If Mercurial is not included in the Python requirements then it should at
    # least be included in the Debian package dependencies.
    with open(get_absolute_path('stdeb.cfg'), 'w') as handle:
        handle.write('[vcs-repo-mgr]\n')
        handle.write('Depends: bzr, git | git-core, mercurial\n')
        handle.write('XS-Python-Version: >= 2.6\n')

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
      install_requires=get_requirements('requirements.txt'),
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
          'Programming Language :: Python :: Implementation :: CPython',
          'Programming Language :: Python :: Implementation :: PyPy',
          'Topic :: Software Development :: Libraries :: Python Modules',
          'Topic :: Software Development :: Version Control',
          'Topic :: System :: Archiving :: Packaging',
          'Topic :: System :: Software Distribution',
          'Topic :: System :: Systems Administration',
          'Topic :: Utilities',
      ])

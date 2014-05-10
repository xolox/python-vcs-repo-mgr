#!/usr/bin/env python

# Setup script for the `vcs-repo-mgr' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 10, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

import re
from os.path import abspath, dirname, join
from setuptools import setup, find_packages

# Find the directory where the source distribution was unpacked.
source_directory = dirname(abspath(__file__))

# Find the current version.
module = join(source_directory, 'vcs_repo_mgr', '__init__.py')
for line in open(module, 'r'):
    match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']$', line)
    if match:
        version_string = match.group(1)
        break
else:
    raise Exception("Failed to extract version from %s!" % module)

# Fill in the long description (for the benefit of PyPi)
# with the contents of README.rst (rendered by GitHub).
readme_file = join(source_directory, 'README.rst')
readme_text = open(readme_file, 'r').read()

# Fill in the "install_requires" field based on requirements.txt.
requirements = [l.strip() for l in open(join(source_directory, 'requirements.txt'), 'r') if not l.startswith('#')]

setup(name='vcs-repo-mgr',
      version=version_string,
      description='Version control repository manager',
      long_description=readme_text,
      url='https://github.com/xolox/python-vcs-repo-mgr',
      author='Peter Odding',
      author_email='peter@peterodding.com',
      packages=find_packages(),
      entry_points={'console_scripts': ['vcs-tool = vcs_repo_mgr.cli:main']},
      install_requires=requirements,
      test_suite='vcs_repo_mgr.tests')

# vim: ts=4 sw=4

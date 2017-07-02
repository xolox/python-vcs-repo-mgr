#!/bin/bash -e

# Make sure apt-get's package lists are up-to-date.
sudo apt-get update -qq

# Make sure git is installed.
sudo apt-get install --yes git

# Install up-to-date versions of Bazaar and Mercurial
# (using Python packaging instead of Debian packaging).
if python -c 'import sys; sys.exit(1 if sys.version_info[0] == 2 else 0)'; then
  sudo apt-get install --yes python-pip
  sudo pip install --upgrade bzr mercurial
fi

# Install the required Python packages.
pip install pip-accel
pip-accel install coveralls
pip-accel install --requirement=requirements.txt
pip-accel install --requirement=requirements-checks.txt
pip-accel install --requirement=requirements-tests.txt

# Install the project itself, making sure that potential character encoding
# and/or decoding errors in the setup script are caught as soon as possible.
LC_ALL=C pip-accel install .

#!/bin/bash -e

# On Linux workers we need to install some requirements.
if [ "$TRAVIS_OS_NAME" = linux ]; then
  # Make sure apt-get's package lists are up-to-date.
  sudo apt-get update -qq
  # Make sure git is installed.
  sudo DEBIAN_FRONTEND=noninteractive apt-get install --yes git
  # Install up-to-date versions of Bazaar and Mercurial
  # (using Python packaging instead of Debian packaging).
  if python -c 'import sys; sys.exit(1 if sys.version_info[0] == 2 else 0)'; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install --yes python-pip
    sudo pip install --upgrade bzr mercurial
  fi
fi

# On Mac OS X workers we are responsible for creating the Python virtual
# environment, because we set `language: generic' in the Travis CI build
# configuration file (to bypass the lack of Python runtime support).
if [ "$TRAVIS_OS_NAME" = osx ]; then
  VIRTUAL_ENV="$HOME/virtualenv/python2.7"
  if [ ! -x "$VIRTUAL_ENV/bin/python" ]; then
    virtualenv "$VIRTUAL_ENV"
  fi
  source "$VIRTUAL_ENV/bin/activate"
fi

# Install the required Python packages.
pip install --requirement=requirements-travis.txt

# Install the project itself, making sure that potential character encoding
# and/or decoding errors in the setup script are caught as soon as possible.
LC_ALL=C pip install .

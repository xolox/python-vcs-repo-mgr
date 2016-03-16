# Makefile for vcs-repo-mgr.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 16, 2016
# URL: https://github.com/xolox/python-vcs-repo-mgr

WORKON_HOME ?= $(HOME)/.virtualenvs
VIRTUAL_ENV ?= $(WORKON_HOME)/vcs-repo-mgr
ACTIVATE = . "$(VIRTUAL_ENV)/bin/activate"

default:
	@echo 'Makefile for vcs-repo-mgr'
	@echo
	@echo 'Usage:'
	@echo
	@echo '    make install    install the package in a virtual environment'
	@echo '    make test       run the test suite and report coverage'
	@echo '    make check      check the coding style'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

install:
	test -d "$(VIRTUAL_ENV)" || virtualenv --no-site-packages "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/pip" || ($(ACTIVATE) && easy_install pip)
	test -x "$(VIRTUAL_ENV)/bin/pip-accel" || ($(ACTIVATE) && pip install --quiet pip-accel)
	$(ACTIVATE) && pip uninstall --quiet --yes vcs-repo-mgr || true
	$(ACTIVATE) && pip-accel install --quiet --editable .

test: install
	test -x "$(VIRTUAL_ENV)/bin/py.test" || ($(ACTIVATE) && pip-accel install --quiet pytest pytest-cov)
	$(ACTIVATE) && py.test --cov --exitfirst --verbose
	$(ACTIVATE) && coverage html

check: install
	test -x "$(VIRTUAL_ENV)/bin/flake8" || ($(ACTIVATE) && pip-accel install --quiet flake8-pep257)
	$(ACTIVATE) && flake8

readme:
	test -x "$(VIRTUAL_ENV)/bin/cog.py" || ($(ACTIVATE) && pip-accel install --quiet cogapp)
	$(ACTIVATE) && cog.py -r README.rst

docs: install
	test -x "$(VIRTUAL_ENV)/bin/sphinx-build" || ($(ACTIVATE) && pip-accel install --quiet sphinx)
	cd docs && make html

publish:
	git push origin && git push --tags origin
	make clean && python setup.py sdist upload

clean:
	rm -Rf build dist docs/build *.egg-info htmlcov

.PHONY: default install test check readme docs publish clean

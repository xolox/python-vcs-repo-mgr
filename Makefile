# Makefile for vcs-repo-mgr.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: September 14, 2014
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
	@echo '    make test       run the test suite'
	@echo '    make coverage   run the tests, report coverage'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

install:
	test -d "$(VIRTUAL_ENV)" || virtualenv --no-site-packages "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/pip-accel" || ($(ACTIVATE) && easy_install pip-accel)
	$(ACTIVATE) && pip-accel install -r requirements.txt
	$(ACTIVATE) && pip uninstall -y vcs-repo-mgr || true
	$(ACTIVATE) && pip install --no-deps .

test: install
	test -x "$(VIRTUAL_ENV)/bin/py.test" || ($(ACTIVATE) && pip-accel install pytest)
	$(ACTIVATE) && py.test --exitfirst --capture=no vcs_repo_mgr/tests.py

coverage: install
	test -x "$(VIRTUAL_ENV)/bin/coverage" || ($(ACTIVATE) && pip-accel install coverage)
	$(ACTIVATE) && coverage run --source=vcs_repo_mgr setup.py test
	$(ACTIVATE) && coverage html --omit=vcs_repo_mgr/tests.py
	if [ "`whoami`" != root ] && which gnome-open >/dev/null 2>&1; then gnome-open htmlcov/index.html; fi

docs: install
	test -x "$(VIRTUAL_ENV)/bin/sphinx-build" || ($(ACTIVATE) && pip-accel install sphinx)
	cd docs && make html
	if which gnome-open >/dev/null 2>&1; then \
		gnome-open "docs/build/html/index.html"; \
	fi

publish:
	git push origin && git push --tags origin
	make clean && python setup.py sdist upload

clean:
	rm -Rf build dist docs/build *.egg-info

.PHONY: default install test docs publish clean

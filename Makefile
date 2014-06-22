# Makefile for vcs-repo-mgr.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: June 22, 2014
# URL: https://github.com/xolox/python-vcs-repo-mgr

WORKON_HOME ?= $(HOME)/.virtualenvs
VIRTUAL_ENV ?= $(WORKON_HOME)/vcs-repo-mgr

default:
	@echo 'Makefile for vcs-repo-mgr'
	@echo
	@echo 'Usage:'
	@echo
	@echo '    make install    install the package in a virtual environment'
	@echo '    make test       run the test suite'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

install:
	test -d "$(VIRTUAL_ENV)" || virtualenv --no-site-packages "$(VIRTUAL_ENV)"
	test -x "$(VIRTUAL_ENV)/bin/pip-accel" || "$(VIRTUAL_ENV)/bin/easy_install" pip-accel
	"$(VIRTUAL_ENV)/bin/pip-accel" install -r requirements.txt
	"$(VIRTUAL_ENV)/bin/pip" uninstall -y vcs-repo-mgr || true
	"$(VIRTUAL_ENV)/bin/pip" install --no-deps .

test:
	"$(VIRTUAL_ENV)/bin/python" setup.py test

docs: install
	"$(VIRTUAL_ENV)/bin/pip-accel" install sphinx
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

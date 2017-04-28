# -*- coding: utf-8 -*-

"""Documentation build configuration file for the `vcs-repo-mgr` package."""

import os
import sys

# Add the 'vcs-repo-mgr' source distribution's root directory to the module path.
sys.path.insert(0, os.path.abspath('..'))

# -- General configuration -----------------------------------------------------

# Sphinx extension module names.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.doctest',
    'sphinx.ext.intersphinx',
    'sphinx.ext.viewcode',
    'humanfriendly.sphinx',
]

# Configuration for the `autodoc' extension.
autodoc_member_order = 'bysource'

# Paths that contain templates, relative to this directory.
templates_path = ['templates']

# The suffix of source filenames.
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'vcs-repo-mgr'
copyright = u'2017, Peter Odding'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.

# Find the package version and make it the release.
from vcs_repo_mgr import __version__ as vcs_repo_mgr_version  # noqa

# The short X.Y version.
version = '.'.join(vcs_repo_mgr_version.split('.')[:2])

# The full version, including alpha/beta/rc tags.
release = vcs_repo_mgr_version

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
language = 'en'

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns = ['build']

# If true, '()' will be appended to :func: etc. cross-reference text.
add_function_parentheses = True

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# Refer to the Python standard library.
# From: http://twistedmatrix.com/trac/ticket/4582.
intersphinx_mapping = {
    'python': ('https://docs.python.org', None),
    'executor': ('https://executor.readthedocs.org/en/latest', None),
    'propertymanager': ('https://property-manager.readthedocs.org/en/latest', None),
}

# -- Options for HTML output ---------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
html_theme = 'default'

# Output file base name for HTML help builder.
htmlhelp_basename = 'vcsrepomgrdoc'


def setup(app):
    """Based on http://stackoverflow.com/a/5599712/788200."""
    app.connect('autodoc-skip-member', (lambda app, what, name, obj, skip, options:
                                        False if name == '__init__' else skip))

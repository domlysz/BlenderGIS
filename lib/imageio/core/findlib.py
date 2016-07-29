# -*- coding: utf-8 -*-
# Copyright (c) 2015, imageio contributors
# Copyright (C) 2013, Zach Pincus, Almar Klein and others

""" This module contains generic code to find and load a dynamic library.
"""

from __future__ import absolute_import, print_function, division

import os
import sys
import ctypes


LOCALDIR = os.path.abspath(os.path.dirname(__file__))


# More generic:
# def get_local_lib_dirs(*libdirs):
#     """ Get a list of existing directories that end with one of the given
#     subdirs, and that are in the (sub)package that this modules is part of.
#     """
#     dirs = []
#     parts = __name__.split('.')
#     for i in reversed(range(len(parts))):
#         package_name = '.'.join(parts[:i])
#         package = sys.modules.get(package_name, None)
#         if package:
#             dirs.append(os.path.abspath(os.path.dirname(package.__file__)))
#     dirs = [os.path.join(d, sub) for sub in libdirs for d in dirs]
#     return [d for d in dirs if os.path.isdir(d)]


def looks_lib(fname):
    """ Returns True if the given filename looks like a dynamic library.
    Based on extension, but cross-platform and more flexible. 
    """
    fname = fname.lower()
    if sys.platform.startswith('win'):
        return fname.endswith('.dll')
    elif sys.platform.startswith('darwin'):
        return fname.endswith('.dylib')
    else:
        return fname.endswith('.so') or '.so.' in fname


def generate_candidate_libs(lib_names, lib_dirs=None):
    """ Generate a list of candidate filenames of what might be the dynamic
    library corresponding with the given list of names.
    Returns (lib_dirs, lib_paths)
    """
    lib_dirs = lib_dirs or []
    
    # Get system dirs to search
    sys_lib_dirs = ['/lib', 
                    '/usr/lib', 
                    '/usr/lib/x86_64-linux-gnu',
                    '/usr/local/lib', 
                    '/opt/local/lib', ]
    
    # Get Python dirs to search (shared if for Pyzo)
    py_sub_dirs = ['lib', 'DLLs', 'Library/bin', 'shared']    
    py_lib_dirs = [os.path.join(sys.prefix, d) for d in py_sub_dirs]
    if hasattr(sys, 'base_prefix'):
        py_lib_dirs += [os.path.join(sys.base_prefix, d) for d in py_sub_dirs]
    
    # Get user dirs to search (i.e. HOME)
    home_dir = os.path.expanduser('~')
    user_lib_dirs = [os.path.join(home_dir, d) for d in ['lib']]
    
    # Select only the dirs for which a directory exists, and remove duplicates
    potential_lib_dirs = lib_dirs + sys_lib_dirs + py_lib_dirs + user_lib_dirs
    lib_dirs = []
    for ld in potential_lib_dirs:
        if os.path.isdir(ld) and ld not in lib_dirs:
            lib_dirs.append(ld)
    
    # Now attempt to find libraries of that name in the given directory
    # (case-insensitive)
    lib_paths = []
    for lib_dir in lib_dirs:
        # Get files, prefer short names, last version
        files = os.listdir(lib_dir)
        files = reversed(sorted(files))
        files = sorted(files, key=len)
        for lib_name in lib_names:
            # Test all filenames for name and ext
            for fname in files:
                if fname.lower().startswith(lib_name) and looks_lib(fname):
                    lib_paths.append(os.path.join(lib_dir, fname))
    
    # Return (only the items which are files)
    lib_paths = [lp for lp in lib_paths if os.path.isfile(lp)]
    return lib_dirs, lib_paths


def load_lib(exact_lib_names, lib_names, lib_dirs=None):
    """ load_lib(exact_lib_names, lib_names, lib_dirs=None)
    
    Load a dynamic library. 
    
    This function first tries to load the library from the given exact
    names. When that fails, it tries to find the library in common
    locations. It searches for files that start with one of the names
    given in lib_names (case insensitive). The search is performed in
    the given lib_dirs and a set of common library dirs.
    
    Returns ``(ctypes_library, library_path)``
    """
    
    # Checks
    assert isinstance(exact_lib_names, list)
    assert isinstance(lib_names, list)
    if lib_dirs is not None:
        assert isinstance(lib_dirs, list)
    exact_lib_names = [n for n in exact_lib_names if n]
    lib_names = [n for n in lib_names if n]
    
    # Get reference name (for better messages)
    if lib_names:
        the_lib_name = lib_names[0]
    elif exact_lib_names:
        the_lib_name = exact_lib_names[0]
    else:
        raise ValueError("No library name given.")
    
    # Collect filenames of potential libraries
    # First try a few bare library names that ctypes might be able to find
    # in the default locations for each platform. 
    lib_dirs, lib_paths = generate_candidate_libs(lib_names, lib_dirs)
    lib_paths = exact_lib_names + lib_paths
    
    # Select loader 
    if sys.platform.startswith('win'):
        loader = ctypes.windll
    else:
        loader = ctypes.cdll
    
    # Try to load until success
    the_lib = None
    errors = []
    for fname in lib_paths:
        try:
            the_lib = loader.LoadLibrary(fname)
            break
        except Exception:
            # Don't record errors when it couldn't load the library from an
            # exact name -- this fails often, and doesn't provide any useful
            # debugging information anyway, beyond "couldn't find library..."
            if fname not in exact_lib_names:
                # Get exception instance in Python 2.x/3.x compatible manner
                e_type, e_value, e_tb = sys.exc_info()
                del e_tb
                errors.append((fname, e_value))
    
    # No success ...
    if the_lib is None:
        if errors:
            # No library loaded, and load-errors reported for some
            # candidate libs
            err_txt = ['%s:\n%s' % (l, str(e)) for l, e in errors]
            msg = ('One or more %s libraries were found, but ' + 
                   'could not be loaded due to the following errors:\n%s')
            raise OSError(msg % (the_lib_name, '\n\n'.join(err_txt)))
        else:
            # No errors, because no potential libraries found at all!
            msg = 'Could not find a %s library in any of:\n%s'
            raise OSError(msg % (the_lib_name, '\n'.join(lib_dirs)))
    
    # Done
    return the_lib, fname

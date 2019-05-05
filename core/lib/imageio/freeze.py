""" 
Helper functions for freezing imageio.
"""

import sys


def get_includes():
    if sys.version_info[0] == 3:
        urllib = ['email', 'urllib.request', ]
    else:
        urllib = ['urllib2']
    return urllib + ['numpy', 'zipfile', 'io']


def get_excludes():
    return []

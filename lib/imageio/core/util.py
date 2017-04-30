# -*- coding: utf-8 -*-
# Copyright (c) 2015, imageio contributors
# imageio is distributed under the terms of the (new) BSD License.

""" 
Various utilities for imageio
"""

from __future__ import absolute_import, print_function, division

import re
import os
import sys
import time
import struct
from warnings import warn

import numpy as np

IS_PYPY = '__pypy__' in sys.builtin_module_names
THIS_DIR = os.path.abspath(os.path.dirname(__file__))

# Taken from six.py
PY3 = sys.version_info[0] == 3
if PY3:
    string_types = str,
    text_type = str
    binary_type = bytes
else:  # pragma: no cover
    string_types = basestring,  # noqa
    text_type = unicode  # noqa
    binary_type = str


def urlopen(*args, **kwargs):
    """ Compatibility function for the urlopen function. Raises an
    RuntimeError if urlopen could not be imported (which can occur in
    frozen applications.
    """ 
    try:
        from urllib2 import urlopen
    except ImportError:
        try:
            from urllib.request import urlopen  # Py3k
        except ImportError:
            raise RuntimeError('Could not import urlopen.')
    return urlopen(*args, **kwargs)


def image_as_uint(im, bitdepth=None):
    """ Convert the given image to uint (default: uint8)
    
    If the dtype already matches the desired format, it is returned
    as-is. If the image is float, and all values are between 0 and 1,
    the values are multiplied by np.power(2.0, bitdepth). In all other
    situations, the values are scaled such that the minimum value
    becomes 0 and the maximum value becomes np.power(2.0, bitdepth)-1
    (255 for 8-bit and 65535 for 16-bit).
    """
    if not bitdepth:
        bitdepth = 8
    if not isinstance(im, np.ndarray):
        raise ValueError('Image must be a numpy array')
    if bitdepth == 8:
        out_type = np.uint8
    elif bitdepth == 16:
        out_type = np.uint16
    else:
        raise ValueError('Bitdepth must be either 8 or 16')
    dtype_str = str(im.dtype)
    if ((im.dtype == np.uint8 and bitdepth == 8) or
       (im.dtype == np.uint16 and bitdepth == 16)):
        # Already the correct format? Return as-is
        return im
    if (dtype_str.startswith('float') and
       np.nanmin(im) >= 0 and np.nanmax(im) <= 1):
        warn('Lossy conversion from {0} to {1}, range [0, 1]'.format(
             dtype_str, out_type.__name__))
        im = im.astype(np.float64) * (np.power(2.0, bitdepth)-1)
    elif im.dtype == np.uint16 and bitdepth == 8:
        warn('Lossy conversion from uint16 to uint8, '
             'loosing 8 bits of resolution')
        im = np.right_shift(im, 8)
    elif im.dtype == np.uint32:
        warn('Lossy conversion from uint32 to {0}, '
             'loosing {1} bits of resolution'.format(out_type.__name__,
                                                     32-bitdepth))
        im = np.right_shift(im, 32-bitdepth)
    elif im.dtype == np.uint64:
        warn('Lossy conversion from uint64 to {0}, '
             'loosing {1} bits of resolution'.format(out_type.__name__,
                                                     64-bitdepth))
        im = np.right_shift(im, 64-bitdepth)
    else:
        mi = np.nanmin(im)
        ma = np.nanmax(im)
        if not np.isfinite(mi):
            raise ValueError('Minimum image value is not finite')
        if not np.isfinite(ma):
            raise ValueError('Maximum image value is not finite')
        if ma == mi:
            raise ValueError('Max value == min value, ambiguous given dtype')
        warn('Conversion from {0} to {1}, '
             'range [{2}, {3}]'.format(dtype_str, out_type.__name__, mi, ma))
        # Now make float copy before we scale
        im = im.astype('float64')
        # Scale the values between 0 and 1 then multiply by the max value
        im = (im - mi) / (ma - mi) * (np.power(2.0, bitdepth)-1)
    assert np.nanmin(im) >= 0
    assert np.nanmax(im) < np.power(2.0, bitdepth)
    return im.astype(out_type)


# currently not used ... the only use it to easily provide the global meta info
class ImageList(list):
    def __init__(self, meta=None):
        list.__init__(self)
        # Check
        if not (meta is None or isinstance(meta, dict)):
            raise ValueError('ImageList expects meta data to be a dict.')
        # Convert and return
        self._meta = meta if meta is not None else {}
    
    @property
    def meta(self):
        """ The dict with the meta data of this image.
        """ 
        return self._meta


class Image(np.ndarray):
    """ Image(array, meta=None)
    
    A subclass of np.ndarray that has a meta attribute.
    Following scikit-image, we leave this as a normal numpy array as much 
    as we can.
    """
    
    def __new__(cls, array, meta=None):
        # Check
        if not isinstance(array, np.ndarray):
            raise ValueError('Image expects a numpy array.')
        if not (meta is None or isinstance(meta, dict)):
            raise ValueError('Image expects meta data to be a dict.')
        # Convert and return
        meta = meta if meta is not None else {}
        try:
            ob = array.view(cls)
        except AttributeError:  # pragma: no cover
            # Just return the original; no metadata on the array in Pypy!
            return array
        ob._copy_meta(meta)
        return ob
    
    def _copy_meta(self, meta):
        """ Make a 2-level deep copy of the meta dictionary.
        """
        self._meta = Dict()
        for key, val in meta.items():
            if isinstance(val, dict):
                val = Dict(val)  # Copy this level
            self._meta[key] = val
    
    @property
    def meta(self):
        """ The dict with the meta data of this image.
        """ 
        return self._meta
    
    def __array_finalize__(self, ob):
        """ So the meta info is maintained when doing calculations with
        the array. 
        """
        if isinstance(ob, Image):
            self._copy_meta(ob.meta)
        else:
            self._copy_meta({})
    
    def __array_wrap__(self, out, context=None):
        """ So that we return a native numpy array (or scalar) when a
        reducting ufunc is applied (such as sum(), std(), etc.)
        """
        if not out.shape:
            return out.dtype.type(out)  # Scalar
        elif out.shape != self.shape:
            return out.view(type=np.ndarray)
        else:
            return out  # Type Image


def asarray(a):
    """ Pypy-safe version of np.asarray. Pypy's np.asarray consumes a
    *lot* of memory if the given array is an ndarray subclass. This
    function does not.
    """
    if isinstance(a, np.ndarray):
        if IS_PYPY:  # pragma: no cover 
            a = a.copy()  # pypy has issues with base views
        plain = a.view(type=np.ndarray)
        return plain
    return np.asarray(a)


try:
    from collections import OrderedDict as _dict
except ImportError:
    _dict = dict


class Dict(_dict):
    """ A dict in which the keys can be get and set as if they were
    attributes. Very convenient in combination with autocompletion.
    
    This Dict still behaves as much as possible as a normal dict, and
    keys can be anything that are otherwise valid keys. However, 
    keys that are not valid identifiers or that are names of the dict
    class (such as 'items' and 'copy') cannot be get/set as attributes.
    """
    
    __reserved_names__ = dir(_dict())  # Also from OrderedDict
    __pure_names__ = dir(dict())
    
    def __getattribute__(self, key):
        try:
            return object.__getattribute__(self, key)
        except AttributeError:
            if key in self:
                return self[key]
            else:
                raise
    
    def __setattr__(self, key, val):
        if key in Dict.__reserved_names__:
            # Either let OrderedDict do its work, or disallow
            if key not in Dict.__pure_names__:
                return _dict.__setattr__(self, key, val)
            else:
                raise AttributeError('Reserved name, this key can only ' +
                                     'be set via ``d[%r] = X``' % key)
        else:
            # if isinstance(val, dict): val = Dict(val) -> no, makes a copy!
            self[key] = val
    
    def __dir__(self):
        isidentifier = lambda x: bool(re.match(r'[a-z_]\w*$', x, re.I))
        names = [k for k in self.keys() if 
                 (isinstance(k, string_types) and isidentifier(k))]
        return Dict.__reserved_names__ + names

    
class BaseProgressIndicator:
    """ BaseProgressIndicator(name)
    
    A progress indicator helps display the progres of a task to the
    user. Progress can be pending, running, finished or failed.
    
    Each task has:
      * a name - a short description of what needs to be done.
      * an action - the current action in performing the task (e.g. a subtask)
      * progress - how far the task is completed
      * max - max number of progress units. If 0, the progress is indefinite
      * unit - the units in which the progress is counted
      * status - 0: pending, 1: in progress, 2: finished, 3: failed
    
    This class defines an abstract interface. Subclasses should implement
    _start, _stop, _update_progress(progressText), _write(message).
    """
    
    def __init__(self, name):
        self._name = name
        self._action = ''
        self._unit = ''
        self._max = 0
        self._status = 0
        self._last_progress_update = 0
    
    def start(self,  action='', unit='', max=0):
        """ start(action='', unit='', max=0)
        
        Start the progress. Optionally specify an action, a unit,
        and a maxium progress value.
        """
        if self._status == 1:
            self.finish() 
        self._action = action
        self._unit = unit
        self._max = max
        #
        self._progress = 0 
        self._status = 1
        self._start()
    
    def status(self):
        """ status()
        
        Get the status of the progress - 0: pending, 1: in progress,
        2: finished, 3: failed
        """
        return self._status
    
    def set_progress(self, progress=0, force=False):
        """ set_progress(progress=0, force=False)
        
        Set the current progress. To avoid unnecessary progress updates
        this will only have a visual effect if the time since the last
        update is > 0.1 seconds, or if force is True.
        """
        self._progress = progress
        # Update or not?
        if not (force or (time.time() - self._last_progress_update > 0.1)):
            return
        self._last_progress_update = time.time()
        # Compose new string
        unit = self._unit or ''
        progressText = ''
        if unit == '%':
            progressText = '%2.1f%%' % progress
        elif self._max > 0:
            percent = 100 * float(progress) / self._max
            progressText = '%i/%i %s (%2.1f%%)' % (progress, self._max, unit, 
                                                   percent)
        elif progress > 0:
            if isinstance(progress, float):
                progressText = '%0.4g %s' % (progress, unit)
            else:
                progressText = '%i %s' % (progress, unit)
        # Update
        self._update_progress(progressText)
    
    def increase_progress(self, extra_progress):
        """ increase_progress(extra_progress)
        
        Increase the progress by a certain amount.
        """
        self.set_progress(self._progress + extra_progress)
    
    def finish(self, message=None):
        """ finish(message=None)
        
        Finish the progress, optionally specifying a message. This will
        not set the progress to the maximum.
        """
        self.set_progress(self._progress, True)  # fore update
        self._status = 2
        self._stop()
        if message is not None:
            self._write(message)
    
    def fail(self, message=None):
        """ fail(message=None)
        
        Stop the progress with a failure, optionally specifying a message.
        """
        self.set_progress(self._progress, True)  # fore update
        self._status = 3
        self._stop()
        message = 'FAIL ' + (message or '')
        self._write(message)
    
    def write(self, message):
        """ write(message)
        
        Write a message during progress (such as a warning).
        """
        if self.__class__ == BaseProgressIndicator:
            # When this class is used as a dummy, print explicit message
            print(message)
        else:
            return self._write(message)
    
    # Implementing classes should implement these
    
    def _start(self):
        pass
        
    def _stop(self):
        pass
    
    def _update_progress(self, progressText):
        pass
    
    def _write(self, message):
        pass


class StdoutProgressIndicator(BaseProgressIndicator):
    """ StdoutProgressIndicator(name)
    
    A progress indicator that shows the progress in stdout. It
    assumes that the tty can appropriately deal with backspace
    characters.
    """
    def _start(self):
        self._chars_prefix, self._chars = '', ''
        # Write message
        if self._action:
            self._chars_prefix = '%s (%s): ' % (self._name, self._action)
        else:
            self._chars_prefix = '%s: ' % self._name
        sys.stdout.write(self._chars_prefix)
        sys.stdout.flush()
    
    def _update_progress(self, progressText):
        # If progress is unknown, at least make something move
        if not progressText:
            i1, i2, i3, i4 = '-\\|/'
            M = {i1: i2, i2: i3, i3: i4, i4: i1}
            progressText = M.get(self._chars, i1)
        # Store new string and write
        delChars = '\b'*len(self._chars)
        self._chars = progressText
        sys.stdout.write(delChars+self._chars)
        sys.stdout.flush()
    
    def _stop(self):
        self._chars = self._chars_prefix = ''
        sys.stdout.write('\n')
        sys.stdout.flush()
    
    def _write(self, message):
        # Write message
        delChars = '\b'*len(self._chars_prefix+self._chars)
        sys.stdout.write(delChars+'  '+message+'\n')
        # Reprint progress text
        sys.stdout.write(self._chars_prefix+self._chars)
        sys.stdout.flush()


# From pyzolib/paths.py (https://bitbucket.org/pyzo/pyzolib/src/tip/paths.py)
def appdata_dir(appname=None, roaming=False):
    """ appdata_dir(appname=None, roaming=False)
    
    Get the path to the application directory, where applications are allowed
    to write user specific files (e.g. configurations). For non-user specific
    data, consider using common_appdata_dir().
    If appname is given, a subdir is appended (and created if necessary). 
    If roaming is True, will prefer a roaming directory (Windows Vista/7).
    """
    
    # Define default user directory
    userDir = os.path.expanduser('~')
    if not os.path.isdir(userDir):  # pragma: no cover
        userDir = '/var/tmp'  # issue #54
    
    # Get system app data dir
    path = None
    if sys.platform.startswith('win'):
        path1, path2 = os.getenv('LOCALAPPDATA'), os.getenv('APPDATA')
        path = (path2 or path1) if roaming else (path1 or path2)
    elif sys.platform.startswith('darwin'):
        path = os.path.join(userDir, 'Library', 'Application Support')
    # On Linux and as fallback
    if not (path and os.path.isdir(path)):
        path = userDir
    
    # Maybe we should store things local to the executable (in case of a 
    # portable distro or a frozen application that wants to be portable)
    prefix = sys.prefix
    if getattr(sys, 'frozen', None):
        prefix = os.path.abspath(os.path.dirname(sys.path[0]))
    for reldir in ('settings', '../settings'):
        localpath = os.path.abspath(os.path.join(prefix, reldir))
        if os.path.isdir(localpath):  # pragma: no cover
            try:
                open(os.path.join(localpath, 'test.write'), 'wb').close()
                os.remove(os.path.join(localpath, 'test.write'))
            except IOError:
                pass  # We cannot write in this directory
            else:
                path = localpath
                break
    
    # Get path specific for this app
    if appname:
        if path == userDir:
            appname = '.' + appname.lstrip('.')  # Make it a hidden directory
        path = os.path.join(path, appname)
        if not os.path.isdir(path):  # pragma: no cover
            os.mkdir(path)
    
    # Done
    return path


def resource_dirs():
    """ resource_dirs()
    
    Get a list of directories where imageio resources may be located.
    The first directory in this list is the "resources" directory in
    the package itself. The second directory is the appdata directory
    (~/.imageio on Linux). The list further contains the application
    directory (for frozen apps), and may include additional directories
    in the future.
    """
    dirs = []
    # Resource dir baked in the package
    dirs.append(os.path.abspath(os.path.join(THIS_DIR, '..', 'resources')))
    # Appdata directory
    try:
        dirs.append(appdata_dir('imageio'))
    except Exception:  # pragma: no cover
        pass  # The home dir may not be writable
    # Directory where the app is located (mainly for frozen apps)
    if sys.path and sys.path[0]:
        # Get the path. If frozen, sys.path[0] is the name of the executable,
        # otherwise it is the path to the directory that contains the script.
        thepath = sys.path[0]
        if getattr(sys, 'frozen', None):
            thepath = os.path.dirname(thepath)
        dirs.append(os.path.abspath(thepath))
    return dirs


def get_platform():
    """ get_platform()
    
    Get a string that specifies the platform more specific than
    sys.platform does. The result can be: linux32, linux64, win32,
    win64, osx32, osx64. Other platforms may be added in the future.
    """
    # Get platform
    if sys.platform.startswith('linux'):
        plat = 'linux%i'
    elif sys.platform.startswith('win'):
        plat = 'win%i'
    elif sys.platform.startswith('darwin'):
        plat = 'osx%i'
    else:  # pragma: no cover
        return None
    
    return plat % (struct.calcsize('P') * 8)  # 32 or 64 bits


def has_module(module_name):
    """Check to see if a python module is available.
    """
    if sys.version_info > (3, ):
        import importlib
        return importlib.find_loader(module_name) is not None
    else:  # pragma: no cover
        import imp
        try:
            imp.find_module(module_name)
        except ImportError:
            return False
        return True

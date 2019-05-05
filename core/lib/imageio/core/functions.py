# -*- coding: utf-8 -*-
# Copyright (c) 2015, imageio contributors
# imageio is distributed under the terms of the (new) BSD License.

""" 
These functions represent imageio's main interface for the user. They
provide a common API to read and write image data for a large
variety of formats. All read and write functions accept keyword
arguments, which are passed on to the format that does the actual work.
To see what keyword arguments are supported by a specific format, use
the :func:`.help` function.

Functions for reading:

  * :func:`.imread` - read an image from the specified uri
  * :func:`.mimread` - read a series of images from the specified uri
  * :func:`.volread` - read a volume from the specified uri
  * :func:`.mvolread` - read a series of volumes from the specified uri

Functions for saving:

  * :func:`.imwrite` - write an image to the specified uri
  * :func:`.mimwrite` - write a series of images to the specified uri
  * :func:`.volwrite` - write a volume to the specified uri
  * :func:`.mvolwrite` - write a series of volumes to the specified uri

More control:

For a larger degree of control, imageio provides functions
:func:`.get_reader` and :func:`.get_writer`. They respectively return an
:class:`.Reader` and an :class:`.Writer` object, which can
be used to read/write data and meta data in a more controlled manner.
This also allows specific scientific formats to be exposed in a way
that best suits that file-format.


.. note::
    
    Some of these functions were renamed in v1.1 to realize a more clear
    and consistent API. The old functions are still available for
    backward compatibility (and will be in the foreseeable future).

"""

from __future__ import absolute_import, print_function, division

import numpy as np

from . import Request
from .. import formats


def help(name=None):
    """ help(name=None)
    
    Print the documentation of the format specified by name, or a list
    of supported formats if name is omitted. 
    
    Parameters
    ----------
    name : str
        Can be the name of a format, a filename extension, or a full
        filename. See also the :doc:`formats page <formats>`.
    """
    if not name:
        print(formats)
    else:
        print(formats[name])


## Base functions that return a reader/writer


def get_reader(uri, format=None, mode='?', **kwargs):
    """ get_reader(uri, format=None, mode='?', **kwargs)
    
    Returns a :class:`.Reader` object which can be used to read data
    and meta data from the specified file.
    
    Parameters
    ----------
    uri : {str, bytes, file}
        The resource to load the image from. This can be a normal
        filename, a file in a zipfile, an http/ftp address, a file
        object, or the raw bytes.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    mode : {'i', 'I', 'v', 'V', '?'}
        Used to give the reader a hint on what the user expects (default "?"):
        "i" for an image, "I" for multiple images, "v" for a volume,
        "V" for multiple volumes, "?" for don't care.
    kwargs : ...
        Further keyword arguments are passed to the reader. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Create request object
    request = Request(uri, 'r' + mode, **kwargs)
    
    # Get format
    if format is not None:
        format = formats[format]
    else:
        format = formats.search_read_format(request)
    if format is None:
        raise ValueError('Could not find a format to read the specified file '
                         'in mode %r' % mode)
    
    # Return its reader object
    return format.get_reader(request)


def get_writer(uri, format=None, mode='?', **kwargs):
    """ get_writer(uri, format=None, mode='?', **kwargs)
    
    Returns a :class:`.Writer` object which can be used to write data
    and meta data to the specified file.
    
    Parameters
    ----------
    uri : {str, file}
        The resource to write the image to. This can be a normal
        filename, a file in a zipfile, a file object, or
        ``imageio.RETURN_BYTES``, in which case the raw bytes are
        returned.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename.
    mode : {'i', 'I', 'v', 'V', '?'}
        Used to give the writer a hint on what the user expects (default '?'):
        "i" for an image, "I" for multiple images, "v" for a volume,
        "V" for multiple volumes, "?" for don't care.
    kwargs : ...
        Further keyword arguments are passed to the writer. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Create request object
    request = Request(uri, 'w' + mode, **kwargs)
    
    # Get format
    if format is not None:
        format = formats[format]
    else:
        format = formats.search_write_format(request)
    if format is None:
        raise ValueError('Could not find a format to write the specified file '
                         'in mode %r' % mode)
    
    # Return its writer object
    return format.get_writer(request)


## Images

def imread(uri, format=None, **kwargs):
    """ imread(uri, format=None, **kwargs)
    
    Reads an image from the specified file. Returns a numpy array, which
    comes with a dict of meta data at its 'meta' attribute.
    
    Note that the image data is returned as-is, and may not always have
    a dtype of uint8 (and thus may differ from what e.g. PIL returns).
    
    Parameters
    ----------
    uri : {str, bytes, file}
        The resource to load the image from. This can be a normal
        filename, a file in a zipfile, an http/ftp address, a file
        object, or the raw bytes.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the reader. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Get reader and read first
    reader = read(uri, format, 'i', **kwargs)
    with reader:
        return reader.get_data(0)


def imwrite(uri, im, format=None, **kwargs):
    """ imwrite(uri, im, format=None, **kwargs)
    
    Write an image to the specified file.
    
    Parameters
    ----------
    uri : {str, file}
        The resource to write the image to. This can be a normal
        filename, a file in a zipfile, a file object, or
        ``imageio.RETURN_BYTES``, in which case the raw bytes are
        returned.
    im : numpy.ndarray
        The image data. Must be NxM, NxMx3 or NxMx4.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the writer. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Test image
    if isinstance(im, np.ndarray):
        if im.ndim == 2:
            pass
        elif im.ndim == 3 and im.shape[2] in [1, 3, 4]:
            pass
        else:
            raise ValueError('Image must be 2D (grayscale, RGB, or RGBA).')
    else:
        raise ValueError('Image must be a numpy array.')
    
    # Get writer and write first
    writer = get_writer(uri, format, 'i', **kwargs)
    with writer:
        writer.append_data(im)
    
    # Return a result if there is any
    return writer.request.get_result()


## Multiple images

def mimread(uri, format=None, **kwargs):
    """ mimread(uri, format=None, **kwargs)
    
    Reads multiple images from the specified file. Returns a list of
    numpy arrays, each with a dict of meta data at its 'meta' attribute.
    
    Parameters
    ----------
    uri : {str, bytes, file}
        The resource to load the images from. This can be a normal
        filename, a file in a zipfile, an http/ftp address, a file
        object, or the raw bytes.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the reader. See :func:`.help`
        to see what arguments are available for a particular format.
    
    Memory consumption
    ------------------
    This function will raise a RuntimeError when the read data consumes
    over 256 MB of memory. This is to protect the system using so much
    memory that it needs to resort to swapping, and thereby stall the
    computer. E.g. ``mimread('hunger_games.avi')``.
    """ 
    
    # Get reader
    reader = read(uri, format, 'I', **kwargs)
    
    # Read
    ims = []
    nbytes = 0
    for im in reader:
        ims.append(im)
        # Memory check
        nbytes += im.nbytes
        if nbytes > 256 * 1024 * 1024:
            ims[:] = []  # clear to free the memory
            raise RuntimeError('imageio.mimread() has read over 256 MiB of '
                               'image data.\nStopped to avoid memory problems.'
                               ' Use imageio.get_reader() instead.')
    
    return ims


def mimwrite(uri, ims, format=None, **kwargs):
    """ mimwrite(uri, ims, format=None, **kwargs)
    
    Write multiple images to the specified file.
    
    Parameters
    ----------
    uri : {str, file}
        The resource to write the images to. This can be a normal
        filename, a file in a zipfile, a file object, or
        ``imageio.RETURN_BYTES``, in which case the raw bytes are
        returned.
    ims : sequence of numpy arrays
        The image data. Each array must be NxM, NxMx3 or NxMx4.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the writer. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Get writer
    writer = get_writer(uri, format, 'I', **kwargs)
    with writer:
        
        # Iterate over images (ims may be a generator)
        for im in ims:
            
            # Test image
            if isinstance(im, np.ndarray):
                if im.ndim == 2:
                    pass
                elif im.ndim == 3 and im.shape[2] in [1, 3, 4]:
                    pass
                else:
                    raise ValueError('Image must be 2D '
                                     '(grayscale, RGB, or RGBA).')
            else:
                raise ValueError('Image must be a numpy array.')
            
            # Add image
            writer.append_data(im)
    
    # Return a result if there is any
    return writer.request.get_result()


## Volumes

def volread(uri, format=None, **kwargs):
    """ volread(uri, format=None, **kwargs)
    
    Reads a volume from the specified file. Returns a numpy array, which
    comes with a dict of meta data at its 'meta' attribute.
    
    Parameters
    ----------
    uri : {str, bytes, file}
        The resource to load the volume from. This can be a normal
        filename, a file in a zipfile, an http/ftp address, a file
        object, or the raw bytes.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the reader. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Get reader and read first
    reader = read(uri, format, 'v', **kwargs)
    with reader:
        return reader.get_data(0)


def volwrite(uri, im, format=None, **kwargs):
    """ volwrite(uri, vol, format=None, **kwargs)
    
    Write a volume to the specified file.
    
    Parameters
    ----------
    uri : {str, file}
        The resource to write the image to. This can be a normal
        filename, a file in a zipfile, a file object, or
        ``imageio.RETURN_BYTES``, in which case the raw bytes are
        returned.
    vol : numpy.ndarray
        The image data. Must be NxMxL (or NxMxLxK if each voxel is a tuple).
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the writer. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Test image
    if isinstance(im, np.ndarray):
        if im.ndim == 3:
            pass
        elif im.ndim == 4 and im.shape[3] < 32:  # How large can a tuple be?
            pass
        else:
            raise ValueError('Image must be 3D, or 4D if each voxel is '
                             'a tuple.')
    else:
        raise ValueError('Image must be a numpy array.')
    
    # Get writer and write first
    writer = get_writer(uri, format, 'v', **kwargs)
    with writer:
        writer.append_data(im)
    
    # Return a result if there is any
    return writer.request.get_result()


## Multiple volumes

def mvolread(uri, format=None, **kwargs):
    """ mvolread(uri, format=None, **kwargs)
    
    Reads multiple volumes from the specified file. Returns a list of
    numpy arrays, each with a dict of meta data at its 'meta' attribute.
    
    Parameters
    ----------
    uri : {str, bytes, file}
        The resource to load the volumes from. This can be a normal
        filename, a file in a zipfile, an http/ftp address, a file
        object, or the raw bytes.
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the reader. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Get reader and read all
    reader = read(uri, format, 'V', **kwargs)
    
    ims = []
    nbytes = 0
    for im in reader:
        ims.append(im)
        # Memory check
        nbytes += im.nbytes
        if nbytes > 1024 * 1024 * 1024:  # pragma: no cover
            ims[:] = []  # clear to free the memory
            raise RuntimeError('imageio.mvolread() has read over 1 GiB of '
                               'image data.\nStopped to avoid memory problems.'
                               ' Use imageio.get_reader() instead.')
    
    return ims


def mvolwrite(uri, ims, format=None, **kwargs):
    """ mvolwrite(uri, vols, format=None, **kwargs)
    
    Write multiple volumes to the specified file.
    
    Parameters
    ----------
    uri : {str, file}
        The resource to write the volumes to. This can be a normal
        filename, a file in a zipfile, a file object, or
        ``imageio.RETURN_BYTES``, in which case the raw bytes are
        returned.
    ims : sequence of numpy arrays
        The image data. Each array must be NxMxL (or NxMxLxK if each
        voxel is a tuple).
    format : str
        The format to use to read the file. By default imageio selects
        the appropriate for you based on the filename and its contents.
    kwargs : ...
        Further keyword arguments are passed to the writer. See :func:`.help`
        to see what arguments are available for a particular format.
    """ 
    
    # Get writer
    writer = get_writer(uri, format, 'V', **kwargs)
    with writer:
        
        # Iterate over images (ims may be a generator)
        for im in ims:
            
            # Test image
            if isinstance(im, np.ndarray):
                if im.ndim == 3:
                    pass
                elif im.ndim == 4 and im.shape[3] < 32:
                    pass  # How large can a tuple be?
                else:
                    raise ValueError('Image must be 3D, or 4D if each voxel is'
                                     'a tuple.')
            else:
                raise ValueError('Image must be a numpy array.')
            
            # Add image
            writer.append_data(im)
    
    # Return a result if there is any
    return writer.request.get_result()


## Aliases

read = get_reader
save = get_writer
imsave = imwrite
mimsave = mimwrite
volsave = volwrite
mvolsave = mvolwrite

# -*- coding: utf-8 -*-
# Copyright (c) 2015, imageio contributors
# imageio is distributed under the terms of the (new) BSD License.

""" 

.. note::
    imageio is under construction, some details with regard to the 
    Reader and Writer classes may change. 

These are the main classes of imageio. They expose an interface for
advanced users and plugin developers. A brief overview:
  
  * imageio.FormatManager - for keeping track of registered formats.
  * imageio.Format - representation of a file format reader/writer
  * imageio.Format.Reader - object used during the reading of a file.
  * imageio.Format.Writer - object used during saving a file.
  * imageio.Request - used to store the filename and other info.

Plugins need to implement a Format class and register
a format object using ``imageio.formats.add_format()``.

"""

from __future__ import absolute_import, print_function, division

# todo: do we even use the known extensions?

# Some notes:
#
# The classes in this module use the Request object to pass filename and
# related info around. This request object is instantiated in
# imageio.get_reader and imageio.get_writer.

from __future__ import with_statement

import os

import numpy as np

from . import Image, asarray
from . import string_types, text_type, binary_type  # noqa


class Format:
    """ Represents an implementation to read/write a particular file format
    
    A format instance is responsible for 1) providing information about
    a format; 2) determining whether a certain file can be read/written
    with this format; 3) providing a reader/writer class.
    
    Generally, imageio will select the right format and use that to
    read/write an image. A format can also be explicitly chosen in all
    read/write functions. Use ``print(format)``, or ``help(format_name)``
    to see its documentation.
    
    To implement a specific format, one should create a subclass of
    Format and the Format.Reader and Format.Writer classes. see
    :doc:`plugins` for details.
    
    Parameters
    ----------
    name : str
        A short name of this format. Users can select a format using its name.
    description : str
        A one-line description of the format.
    extensions : str | list | None
        List of filename extensions that this format supports. If a
        string is passed it should be space or comma separated. The
        extensions are used in the documentation and to allow users to
        select a format by file extension. It is not used to determine
        what format to use for reading/saving a file.
    modes : str
        A string containing the modes that this format can handle ('iIvV').
        This attribute is used in the documentation and to select the
        formats when reading/saving a file.
    """
    
    def __init__(self, name, description, extensions=None, modes=None):
        
        # Store name and description
        self._name = name.upper()
        self._description = description
        
        # Store extensions, do some effort to normalize them.
        # They are stored as a list of lowercase strings without leading dots.
        if extensions is None:
            extensions = []
        elif isinstance(extensions, string_types):
            extensions = extensions.replace(',', ' ').split(' ')
        #
        if isinstance(extensions, (tuple, list)):
            self._extensions = tuple(['.' + e.strip('.').lower() 
                                      for e in extensions if e])
        else:
            raise ValueError('Invalid value for extensions given.')
        
        # Store mode
        self._modes = modes or ''
        if not isinstance(self._modes, string_types):
            raise ValueError('Invalid value for modes given.')
        for m in self._modes:
            if m not in 'iIvV?':
                raise ValueError('Invalid value for mode given.')
    
    def __repr__(self):
        # Short description
        return '<Format %s - %s>' % (self.name, self.description)
    
    def __str__(self):
        return self.doc
    
    @property
    def doc(self):
        """ The documentation for this format (name + description + docstring).
        """
        # Our docsring is assumed to be indented by four spaces. The
        # first line needs special attention.
        return '%s - %s\n\n    %s\n' % (self.name, self.description, 
                                        self.__doc__.strip())
    
    @property
    def name(self):
        """ The name of this format.
        """
        return self._name
    
    @property
    def description(self):
        """ A short description of this format.
        """ 
        return self._description
    
    @property
    def extensions(self):
        """ A list of file extensions supported by this plugin.
        These are all lowercase with a leading dot.
        """
        return self._extensions
    
    @property
    def modes(self):
        """ A string specifying the modes that this format can handle.
        """
        return self._modes
    
    def get_reader(self, request):
        """ get_reader(request)
        
        Return a reader object that can be used to read data and info
        from the given file. Users are encouraged to use
        imageio.get_reader() instead.
        """
        select_mode = request.mode[1] if request.mode[1] in 'iIvV' else ''
        if select_mode not in self.modes:
            raise RuntimeError('Format %s cannot read in mode %r' % 
                               (self.name, select_mode))
        return self.Reader(self, request)
    
    def get_writer(self, request):
        """ get_writer(request)
        
        Return a writer object that can be used to write data and info
        to the given file. Users are encouraged to use
        imageio.get_writer() instead.
        """
        select_mode = request.mode[1] if request.mode[1] in 'iIvV' else ''
        if select_mode not in self.modes:
            raise RuntimeError('Format %s cannot write in mode %r' % 
                               (self.name, select_mode))
        return self.Writer(self, request)
    
    def can_read(self, request):
        """ can_read(request)
        
        Get whether this format can read data from the specified uri.
        """
        return self._can_read(request)
    
    def can_write(self, request):
        """ can_write(request)
        
        Get whether this format can write data to the speciefed uri.
        """
        return self._can_write(request)
    
    def _can_read(self, request):  # pragma: no cover
        return None  # Plugins must implement this
    
    def _can_write(self, request):  # pragma: no cover
        return None  # Plugins must implement this

    # -----
    
    class _BaseReaderWriter(object):
        """ Base class for the Reader and Writer class to implement common 
        functionality. It implements a similar approach for opening/closing
        and context management as Python's file objects.
        """
        
        def __init__(self, format, request):
            self.__closed = False
            self._BaseReaderWriter_last_index = -1
            self._format = format
            self._request = request
            # Open the reader/writer
            self._open(**self.request.kwargs.copy())
        
        @property
        def format(self):
            """ The :class:`.Format` object corresponding to the current
            read/write operation.
            """
            return self._format
        
        @property
        def request(self):
            """ The :class:`.Request` object corresponding to the
            current read/write operation.
            """
            return self._request
        
        def __enter__(self):
            self._checkClosed()
            return self
        
        def __exit__(self, type, value, traceback):
            if value is None:
                # Otherwise error in close hide the real error.
                self.close() 
        
        def __del__(self):
            try:
                self.close()
            except Exception:  # pragma: no cover
                pass  # Supress noise when called during interpreter shutdown
        
        def close(self):
            """ Flush and close the reader/writer.
            This method has no effect if it is already closed.
            """
            if self.__closed:
                return
            self.__closed = True
            self._close()
            # Process results and clean request object
            self.request.finish()
        
        @property
        def closed(self):
            """ Whether the reader/writer is closed.
            """
            return self.__closed
        
        def _checkClosed(self, msg=None):
            """Internal: raise an ValueError if reader/writer is closed
            """
            if self.closed:
                what = self.__class__.__name__
                msg = msg or ("I/O operation on closed %s." % what)
                raise RuntimeError(msg)
        
        # To implement
        
        def _open(self, **kwargs):
            """ _open(**kwargs)
            
            Plugins should probably implement this.
            
            It is called when reader/writer is created. Here the
            plugin can do its initialization. The given keyword arguments
            are those that were given by the user at imageio.read() or
            imageio.write().
            """ 
            raise NotImplementedError()
        
        def _close(self):
            """ _close()
            
            Plugins should probably implement this.
            
            It is called when the reader/writer is closed. Here the plugin
            can do a cleanup, flush, etc.
            
            """ 
            raise NotImplementedError()
    
    # -----
    
    class Reader(_BaseReaderWriter):
        """
        The purpose of a reader object is to read data from an image
        resource, and should be obtained by calling :func:`.get_reader`. 
        
        A reader can be used as an iterator to read multiple images,
        and (if the format permits) only reads data from the file when
        new data is requested (i.e. streaming). A reader can also be
        used as a context manager so that it is automatically closed.
        
        Plugins implement Reader's for different formats. Though rare,
        plugins may provide additional functionality (beyond what is
        provided by the base reader class).
        """
        
        def get_length(self):
            """ get_length()
            
            Get the number of images in the file. (Note: you can also
            use ``len(reader_object)``.)
            
            The result can be:
                * 0 for files that only have meta data
                * 1 for singleton images (e.g. in PNG, JPEG, etc.)
                * N for image series
                * inf for streams (series of unknown length)
            """ 
            return self._get_length()
        
        def get_data(self, index, **kwargs):
            """ get_data(index, **kwargs)
            
            Read image data from the file, using the image index. The
            returned image has a 'meta' attribute with the meta data.
            
            Some formats may support additional keyword arguments. These are
            listed in the documentation of those formats.
            """
            self._checkClosed()
            self._BaseReaderWriter_last_index = index
            im, meta = self._get_data(index, **kwargs)
            return Image(im, meta)  # Image tests im and meta 
        
        def get_next_data(self, **kwargs):
            """ get_next_data(**kwargs)
            
            Read the next image from the series.
            
            Some formats may support additional keyword arguments. These are
            listed in the documentation of those formats.
            """
            return self.get_data(self._BaseReaderWriter_last_index+1, **kwargs)
        
        def get_meta_data(self, index=None):
            """ get_meta_data(index=None)
            
            Read meta data from the file. using the image index. If the
            index is omitted or None, return the file's (global) meta data.
            
            Note that ``get_data`` also provides the meta data for the returned
            image as an atrribute of that image.
            
            The meta data is a dict, which shape depends on the format.
            E.g. for JPEG, the dict maps group names to subdicts and each
            group is a dict with name-value pairs. The groups represent
            the different metadata formats (EXIF, XMP, etc.).
            """
            self._checkClosed()
            meta = self._get_meta_data(index)
            if not isinstance(meta, dict):
                raise ValueError('Meta data must be a dict, not %r' % 
                                 meta.__class__.__name__)
            return meta
        
        def iter_data(self):
            """ iter_data()
            
            Iterate over all images in the series. (Note: you can also
            iterate over the reader object.)
            
            """ 
            self._checkClosed()
            i, n = 0, self.get_length()
            while i < n:
                try:
                    im, meta = self._get_data(i)
                except IndexError:
                    if n == float('inf'):
                        return
                    raise
                yield Image(im, meta)
                i += 1
        
        # Compatibility
        
        def __iter__(self):
            return self.iter_data()
        
        def __len__(self):
            return self.get_length()
        
        # To implement
        
        def _get_length(self):
            """ _get_length()
            
            Plugins must implement this.
            
            The retured scalar specifies the number of images in the series.
            See Reader.get_length for more information.
            """ 
            raise NotImplementedError() 
        
        def _get_data(self, index):
            """ _get_data()
            
            Plugins must implement this, but may raise an IndexError in
            case the plugin does not support random access.
            
            It should return the image and meta data: (ndarray, dict).
            """ 
            raise NotImplementedError() 
        
        def _get_meta_data(self, index):
            """ _get_meta_data(index)
            
            Plugins must implement this. 
            
            It should return the meta data as a dict, corresponding to the
            given index, or to the file's (global) meta data if index is
            None.
            """ 
            raise NotImplementedError() 
    
    # -----
    
    class Writer(_BaseReaderWriter):
        """ 
        The purpose of a writer object is to write data to an image
        resource, and should be obtained by calling :func:`.get_writer`. 
        
        A writer will (if the format permits) write data to the file
        as soon as new data is provided (i.e. streaming). A writer can
        also be used as a context manager so that it is automatically
        closed.
        
        Plugins implement Writer's for different formats. Though rare,
        plugins may provide additional functionality (beyond what is
        provided by the base writer class).
        """
        
        def append_data(self, im, meta=None):
            """ append_data(im, meta={})
            
            Append an image (and meta data) to the file. The final meta
            data that is used consists of the meta data on the given
            image (if applicable), updated with the given meta data.
            """ 
            self._checkClosed()
            # Check image data
            if not isinstance(im, np.ndarray):
                raise ValueError('append_data requires ndarray as first arg')
            # Get total meta dict
            total_meta = {}
            if hasattr(im, 'meta') and isinstance(im.meta, dict):
                total_meta.update(im.meta)
            if meta is None:
                pass
            elif not isinstance(meta, dict):
                raise ValueError('Meta must be a dict.')
            else:
                total_meta.update(meta)        
            
            # Decouple meta info
            im = asarray(im)
            # Call
            return self._append_data(im, total_meta)
        
        def set_meta_data(self, meta):
            """ set_meta_data(meta)
            
            Sets the file's (global) meta data. The meta data is a dict which
            shape depends on the format. E.g. for JPEG the dict maps
            group names to subdicts, and each group is a dict with
            name-value pairs. The groups represents the different
            metadata formats (EXIF, XMP, etc.). 
            
            Note that some meta formats may not be supported for
            writing, and individual fields may be ignored without
            warning if they are invalid.
            """ 
            self._checkClosed()
            if not isinstance(meta, dict):
                raise ValueError('Meta must be a dict.')
            else:
                return self._set_meta_data(meta)
        
        # To implement
        
        def _append_data(self, im, meta):
            # Plugins must implement this
            raise NotImplementedError() 
        
        def _set_meta_data(self, meta):
            # Plugins must implement this
            raise NotImplementedError() 


class FormatManager:
    """ 
    There is exactly one FormatManager object in imageio: ``imageio.formats``.
    Its purpose it to keep track of the registered formats.
    
    The format manager supports getting a format object using indexing (by 
    format name or extension). When used as an iterator, this object
    yields all registered format objects.
    
    See also :func:`.help`.
    """
    
    def __init__(self):
        self._formats = []
    
    def __repr__(self):
        return '<imageio.FormatManager with %i registered formats>' % len(self)
    
    def __iter__(self):
        return iter(self._formats)
    
    def __len__(self):
        return len(self._formats)
    
    def __str__(self):
        ss = []
        for format in self._formats: 
            ext = ', '.join(format.extensions)
            s = '%s - %s [%s]' % (format.name, format.description, ext)
            ss.append(s)
        return '\n'.join(ss)
    
    def __getitem__(self, name):
        # Check
        if not isinstance(name, string_types):
            raise ValueError('Looking up a format should be done by name '
                             'or by extension.')
        
        # Test if name is existing file
        if os.path.isfile(name):
            from . import Request
            format = self.search_read_format(Request(name, 'r?'))
            if format is not None:
                return format
        
        if '.' in name:
            # Look for extension
            e1, e2 = os.path.splitext(name.lower())
            name = e2 or e1
            # Search for format that supports this extension
            for format in self._formats:
                if name in format.extensions:
                    return format
        else:
            # Look for name
            name = name.upper()
            for format in self._formats:
                if name == format.name:
                    return format
            else:
                # Maybe the user meant to specify an extension
                return self['.'+name.lower()]
        
        # Nothing found ...
        raise IndexError('No format known by name %s.' % name)
    
    def add_format(self, format, overwrite=False):
        """ add_format(format, overwrite=False)
        
        Register a format, so that imageio can use it. If a format with the
        same name already exists, an error is raised, unless overwrite is True,
        in which case the current format is replaced.
        """
        if not isinstance(format, Format):
            raise ValueError('add_format needs argument to be a Format object')
        elif format in self._formats:
            raise ValueError('Given Format instance is already registered')
        elif format.name in self.get_format_names():
            if overwrite:
                self._formats.remove(self[format.name])
            else:
                raise ValueError('A Format named %r is already registered, use'
                                 ' overwrite=True to replace.' % format.name)
        self._formats.append(format)
    
    def search_read_format(self, request):
        """ search_read_format(request)
        
        Search a format that can read a file according to the given request.
        Returns None if no appropriate format was found. (used internally)
        """
        select_mode = request.mode[1] if request.mode[1] in 'iIvV' else ''
        select_ext = request.filename.lower()
        
        # Select formats that seem to be able to read it
        selected_formats = []
        for format in self._formats:
            if select_mode in format.modes:
                if select_ext.endswith(format.extensions):
                    selected_formats.append(format)
        
        # Select the first that can
        for format in selected_formats:
            if format.can_read(request):
                return format
        
        # If no format could read it, it could be that file has no or
        # the wrong extension. We ask all formats again.
        for format in self._formats:
            if format not in selected_formats:
                if format.can_read(request):
                    return format
    
    def search_write_format(self, request):
        """ search_write_format(request)
        
        Search a format that can write a file according to the given request. 
        Returns None if no appropriate format was found. (used internally)
        """
        select_mode = request.mode[1] if request.mode[1] in 'iIvV' else ''
        select_ext = request.filename.lower()
        
        # Select formats that seem to be able to write it
        selected_formats = []
        for format in self._formats:
            if select_mode in format.modes:
                if select_ext.endswith(format.extensions):
                    selected_formats.append(format)
        
        # Select the first that can
        for format in selected_formats:
            if format.can_write(request):
                return format
        
        # If none of the selected formats could write it, maybe another
        # format can still write it. It might prefer a different mode,
        # or be able to handle more formats than it says by its extensions.
        for format in self._formats:
            if format not in selected_formats:
                if format.can_write(request):
                    return format
    
    def get_format_names(self):
        """ Get the names of all registered formats.
        """
        return [f.name for f in self._formats]
    
    def show(self):
        """ Show a nicely formatted list of available formats
        """
        print(self)

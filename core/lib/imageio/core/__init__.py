# -*- coding: utf-8 -*-
# Copyright (c) 2015, imageio contributors
# Distributed under the (new) BSD License. See LICENSE.txt for more info.

""" This subpackage provides the core functionality of imageio
(everything but the plugins).
"""

from .util import Image, Dict, asarray, image_as_uint, urlopen  # noqa
from .util import BaseProgressIndicator, StdoutProgressIndicator  # noqa
from .util import string_types, text_type, binary_type, IS_PYPY  # noqa
from .util import get_platform, appdata_dir, resource_dirs, has_module  # noqa
from .findlib import load_lib  # noqa
from .fetching import get_remote_file, InternetNotAllowedError  # noqa
from .request import Request, read_n_bytes, RETURN_BYTES  # noqa
from .format import Format, FormatManager  # noqa

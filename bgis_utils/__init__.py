# -*- coding:utf-8 -*-

#  ***** GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#  ***** GPL LICENSE BLOCK *****

bl_info = {
	'name': '[bgis] Utilities',
	'description': 'Various operators for BlenderGIS',
	'author': 'domLysz',
	'license': 'GPL',
	'deps': '',
	'version': (2, 0),
	'blender': (2, 7, 6),
	'location': 'View3D > Tools > GIS',
	'warning': '',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': '',
	'link': '',
	'support': 'COMMUNITY',
	'category': '3D View'
	}

import bpy
import addon_utils

try:
	import geoscene
except:
	raise ImportError("Geoscene addon isn't installed.")

from .view3d_setGeorefCam import *


def checkAddon(addon_name):
	'''Check is an addon is installed and enable it if needed'''
	addon_utils.modules_refresh()
	if addon_name not in addon_utils.addons_fake_modules:
		raise ImportError("%s addon not installed." % addon_name)
	else:
		default, enable = addon_utils.check(addon_name)
		#>>Warning: addon-module 'geoscene' found module but without __addon_enabled__ field, possible name collision
		if not enable:
			addon_utils.enable(addon_name, default_set=True, persistent=False)
			#>>module changed on disk: \geoscene\__init__.py reloading...

def register():
	checkAddon("geoscene")
	bpy.utils.register_module(__name__)

def unregister():
	bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
	register()

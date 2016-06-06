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
	'name': '[bgis] Import raster georeferenced with world file',
	'author': 'domLysz',
	'license': 'GPL',
	'deps': 'Numpy, Gdal, Tyf',
	'version': (3, 0),
	'blender': (2, 7, 6),#min version = 2.67
	'location': 'File > Import > Georeferenced raster',
	'description': 'Import georeferenced raster',
	'warning': '',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': '',
	'link': '',
	'support': 'COMMUNITY',
	'category': 'Import-Export',
	}

import bpy
import addon_utils

try:
	import geoscene
except:
	raise ImportError("Geoscene addon isn't installed.")

from .op_import_georaster import IMPORT_GEORAST

def checkAddon(addon_name):
	'''Check is an addon is installed and enable it if needed'''
	addon_utils.modules_refresh()
	addon_utils.modules_refresh()
	if addon_name not in addon_utils.addons_fake_modules:
		raise ImportError("%s addon not installed." % addon_name)
	else:
		default, enable = addon_utils.check(addon_name)
		#>>Warning: addon-module 'geoscene' found module but without __addon_enabled__ field, possible name collision
		if not enable:
			addon_utils.enable(addon_name, default_set=True, persistent=False)
			#>>module changed on disk: \geoscene\__init__.py reloading...

# Register in File > Import menu
def menu_func_import(self, context):
	self.layout.operator(IMPORT_GEORAST.bl_idname, text="Georeferenced raster")

def register():
	checkAddon("geoscene")
	#bpy.utils.register_class(IMPORT_GEORAST)
	bpy.utils.register_module(__name__)
	bpy.types.INFO_MT_file_import.append(menu_func_import)

def unregister():
	#bpy.utils.unregister_class(IMPORT_GEORAST)
	bpy.utils.unregister_module(__name__)
	bpy.types.INFO_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
	register()

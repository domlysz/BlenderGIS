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
	'name': 'Import/export from ESRI shapefile file format (.shp)',
	'author': 'domLysz',
	'license': 'GPL',
	'deps': 'pyShp',
	'version': (1, 6),
	'blender': (2, 7, 0),
	'location': 'File > Import | Export > Shapefile (.shp)',
	'description': 'Import/export from ESRI shapefile file format (.shp)',
	'warning': '',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': '',
	'link': '',
	'support': 'COMMUNITY',
	'category': 'Import-Export',
	}

import bpy
from .op_import_shp import IMPORT_SHP
from .op_export_shp import EXPORT_SHP

# Register in File > Import menu
def menu_func_import(self, context):
	self.layout.operator(IMPORT_SHP.bl_idname, text="Shapefile (.shp)")

def menu_func_export(self, context):
	self.layout.operator(EXPORT_SHP.bl_idname, text="Shapefile (.shp)")

def register():
	bpy.utils.register_class(IMPORT_SHP)
	bpy.types.INFO_MT_file_import.append(menu_func_import)
	bpy.utils.register_class(EXPORT_SHP)
	bpy.types.INFO_MT_file_export.append(menu_func_export)

def unregister():
	bpy.utils.unregister_class(IMPORT_SHP)
	bpy.types.INFO_MT_file_import.remove(menu_func_import)
	bpy.utils.unregister_class(EXPORT_SHP)
	bpy.types.INFO_MT_file_export.append(menu_func_export)

if __name__ == "__main__":
	register()

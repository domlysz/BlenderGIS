# -*- coding:Latin-1 -*-
bl_info = {
	'name': 'Import/export from ESRI shapefile file format (.shp)',
	'author': 'domLysz',
	'version': (1, 6),
	'blender': (2, 6, 9),
	'location': 'File > Import | Export > Shapefile (.shp)',
	'description': 'Import/export from ESRI shapefile file format (.shp)',
	'warning': '',
	'wiki_url': '',
	'tracker_url': '',
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

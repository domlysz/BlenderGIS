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
	'name': 'BlenderGIS',
	'description': 'Various tools for handle geodata',
	'author': 'domlysz',
	'license': 'GPL',
	'deps': '',
	'version': (1, 0),
	'blender': (2, 7, 7),
	'location': 'View3D > Tools > GIS',
	'warning': '',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': 'https://github.com/domlysz/BlenderGIS/issues',
	'link': '',
	'support': 'COMMUNITY',
	'category': '3D View'
	}

import bpy


#Import all modules which contains classes that must be registed (classes derived from bpy.types.*)
from . import prefs
from . import geoscene
from .basemaps import mapviewer
from .misc import view3d_setGeorefCam
from .misc import view3d_setCursorGeorefFromExif
from .delaunay_voronoi import delaunayVoronoiBlender
from .io_georaster import op_import_georaster
from .io_shapefile import op_export_shp, op_import_shp
from .osm import op_import_osm
from .terrain_analysis import nodes_builder, reclassify


# Register in File > Import menu
def menu_func_import(self, context):
	self.layout.operator('importgis.georaster', text="Georeferenced raster")
	self.layout.operator('importgis.shapefile_file_dialog', text="Shapefile (.shp)")
	self.layout.operator('importgis.osm_file', text="Open Street Map xml (.osm)")

def menu_func_export(self, context):
	self.layout.operator('exportgis.shapefile', text="Shapefile (.shp)")


def register():

	reclassify.register() #this module has its own register function because it contains PropertyGroup that must be specifically registered
	bpy.utils.register_module(__name__)

	bpy.types.INFO_MT_file_import.append(menu_func_import)
	bpy.types.INFO_MT_file_export.append(menu_func_export)

	wm = bpy.context.window_manager
	km = wm.keyconfigs.active.keymaps['3D View']
	kmi = km.keymap_items.new(idname='view3d.map_start', value='PRESS', type='NUMPAD_ASTERIX', ctrl=False, alt=False, shift=False, oskey=False)

def unregister():

	bpy.types.INFO_MT_file_import.remove(menu_func_import)
	bpy.types.INFO_MT_file_export.append(menu_func_export)

	wm = bpy.context.window_manager
	km = wm.keyconfigs.active.keymaps['3D View']
	kmi = km.keymap_items.remove(km.keymap_items['view3d.map_start'])
	#>>cause warnings prints : "search for unknown operator 'VIEW3D_OT_map_start', 'VIEW3D_OT_map_start' "

	reclassify.unregister()
	bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
	register()

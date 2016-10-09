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
	'blender': (2, 7, 8),
	'location': 'View3D > Tools > GIS',
	'warning': '',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': 'https://github.com/domlysz/BlenderGIS/issues',
	'link': '',
	'support': 'COMMUNITY',
	'category': '3D View'
	}

import bpy, os

from .checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_PIL, HAS_IMGIO

#Import all modules which contains classes that must be registed (classes derived from bpy.types.*)
from . import prefs
from . import geoscene
from .basemaps import mapviewer
from .misc import view3d_setGeorefCam, view3d_setCamFromExif
from .delaunay_voronoi import delaunayVoronoiBlender
from .io_georaster import op_import_georaster
from .io_shapefile import op_export_shp, op_import_shp
from .osm import op_import_osm
from .terrain_analysis import nodes_builder, reclassify


import bpy.utils.previews as iconsLib
icons_dict = {}

class bgisPanel(bpy.types.Panel):
	bl_category = "GIS"
	bl_label = "BlenderGIS"
	bl_space_type = "VIEW_3D"
	bl_context = "objectmode"
	bl_region_type = "TOOLS"

	def draw(self, context):
		layout = self.layout
		scn = context.scene

		layout.operator("bgis.pref_show", icon='PREFERENCES')

		col = layout.column(align=True)
		col.label('Geodata:')

		row = col.row(align=True)
		row.operator("view3d.map_start", icon_value=icons_dict["layers"].icon_id)
		#row.operator("bgis.pref_show", icon='SCRIPTWIN', text='')

		row = col.row(align=True)
		row.operator("importgis.osm_query", icon_value=icons_dict["osm"].icon_id)
		#row.operator("bgis.pref_show", icon='SCRIPTWIN', text='')

		row = layout.row(align=True)
		row.label('Import:')#, icon='LIBRARY_DATA_DIRECT')
		row.operator("importgis.shapefile_file_dialog", icon_value=icons_dict["shp"].icon_id, text='')
		row.operator("importgis.georaster", icon_value=icons_dict["raster"].icon_id, text='')
		row.operator("importgis.osm_file", icon_value=icons_dict["osm_xml"].icon_id, text='')
		#row.operator("importgis.lidar_las", icon_value=icons_dict["lidar"].icon_id, text='')

		col = layout.column(align=True)
		col.label('Camera creation:')
		col.operator("camera.georender", icon_value=icons_dict["georefCam"].icon_id, text='Georender')
		row = col.row(align=True)
		row.operator("camera.geophotos", icon_value=icons_dict["exifCam"].icon_id, text='Geophotos')
		row.operator("camera.geophotos_setactive", icon='FILE_REFRESH', text='')

		col = layout.column(align=True)
		col.label('Mesh:')
		col.operator("tesselation.delaunay", icon_value=icons_dict["delaunay"].icon_id, text='Delaunay')
		col.operator("tesselation.voronoi", icon_value=icons_dict["voronoi"].icon_id, text='Voronoi')

		col = layout.column(align=True)
		col.label('Analysis:')
		col.operator("analysis.nodes", icon_value=icons_dict["terrain"].icon_id, text='Terrain')



# Register in File > Import menu
def menu_func_import(self, context):
	self.layout.operator('importgis.georaster', text="Georeferenced raster")
	self.layout.operator('importgis.shapefile_file_dialog', text="Shapefile (.shp)")
	self.layout.operator('importgis.osm_file', text="Open Street Map xml (.osm)")

def menu_func_export(self, context):
	self.layout.operator('exportgis.shapefile', text="Shapefile (.shp)")


def register():

	global icons_dict
	icons_dict = iconsLib.new()
	icons_dir = os.path.join(os.path.dirname(__file__), "icons")
	for icon in os.listdir(icons_dir):
		name, ext = os.path.splitext(icon)
		icons_dict.load(name, os.path.join(icons_dir, icon), 'IMAGE')

	reclassify.register() #this module has its own register function because it contains PropertyGroup that must be specifically registered
	bpy.utils.register_module(__name__)

	bpy.types.INFO_MT_file_import.append(menu_func_import)
	bpy.types.INFO_MT_file_export.append(menu_func_export)

	wm = bpy.context.window_manager
	km = wm.keyconfigs.active.keymaps['3D View']
	kmi = km.keymap_items.new(idname='view3d.map_start', value='PRESS', type='NUMPAD_ASTERIX', ctrl=False, alt=False, shift=False, oskey=False)

def unregister():

	global icons_dict
	iconsLib.remove(icons_dict)

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

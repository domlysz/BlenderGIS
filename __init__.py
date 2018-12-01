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

#Modules
CAM_GEOPHOTO = True
CAM_GEOREF = True
EXPORT_SHP = True
GET_SRTM = True
IMPORT_GEORASTER = True
IMPORT_OSM = True
IMPORT_SHP = True
IMPORT_ASC = True
DELAUNAY = True
TERRAIN_NODES = True
TERRAIN_RECLASS = True
BASEMAPS = True
DROP = True

import bpy, os

from .core.checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_PIL, HAS_IMGIO
from .core.settings import getSettings, setSettings

#Import all modules which contains classes that must be registed (classes derived from bpy.types.*)
from . import prefs
from . import geoscene
#from .operators import * #see operators/__init__/__all__

if CAM_GEOPHOTO:
	from .operators import add_camera_exif
if CAM_GEOREF:
	from .operators import add_camera_georef
if EXPORT_SHP:
	from .operators import io_export_shp
if GET_SRTM:
	from .operators import io_get_srtm
if IMPORT_GEORASTER:
	from .operators import io_import_georaster
if IMPORT_OSM:
	from .operators import io_import_osm
if IMPORT_SHP:
	from .operators import io_import_shp
if IMPORT_ASC:
	from .operators import io_import_asc
if DELAUNAY:
	from .operators import mesh_delaunay_voronoi
if TERRAIN_NODES:
	from .operators import nodes_terrain_analysis_builder
if TERRAIN_RECLASS:
	from .operators import nodes_terrain_analysis_reclassify
if BASEMAPS:
	from .operators import view3d_mapviewer
if DROP:
	from .operators import object_drop


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

		if BASEMAPS:
			row = col.row(align=True)
			row.operator("view3d.map_start", icon_value=icons_dict["layers"].icon_id)

		row = col.row(align=True)
		if IMPORT_OSM:
			row.operator("importgis.osm_query", icon_value=icons_dict["osm"].icon_id)
		if GET_SRTM:
			row.operator("importgis.srtm_query")


		row = layout.row(align=True)
		row.label('Import:')#, icon='LIBRARY_DATA_DIRECT')
		if IMPORT_SHP:
			row.operator("importgis.shapefile_file_dialog", icon_value=icons_dict["shp"].icon_id, text='')
		if IMPORT_GEORASTER:
			row.operator("importgis.georaster", icon_value=icons_dict["raster"].icon_id, text='')
		if IMPORT_OSM:
			row.operator("importgis.osm_file", icon_value=icons_dict["osm_xml"].icon_id, text='')
		#row.operator("importgis.asc_file", icon_value=icons_dict["asc"].icon_id, text='')
		#row.operator("importgis.lidar_las", icon_value=icons_dict["lidar"].icon_id, text='')

		col = layout.column(align=True)
		col.label('Camera creation:')
		if CAM_GEOREF:
			col.operator("camera.georender", icon_value=icons_dict["georefCam"].icon_id, text='Georender')
		if CAM_GEOPHOTO:
			row = col.row(align=True)
			row.operator("camera.geophotos", icon_value=icons_dict["exifCam"].icon_id, text='Geophotos')
			row.operator("camera.geophotos_setactive", icon='FILE_REFRESH', text='')

		if DELAUNAY:
			col = layout.column(align=True)
			col.label('Mesh:')
			col.operator("tesselation.delaunay", icon_value=icons_dict["delaunay"].icon_id, text='Delaunay')
			col.operator("tesselation.voronoi", icon_value=icons_dict["voronoi"].icon_id, text='Voronoi')

		if DROP:
			col = layout.column(align=True)
			col.label('Object:')
			col.operator("object.drop", icon_value=icons_dict["drop"].icon_id, text='Drop')

		if TERRAIN_NODES:
			col = layout.column(align=True)
			col.label('Analysis:')
			col.operator("analysis.nodes", icon_value=icons_dict["terrain"].icon_id, text='Terrain')



# Register in File > Import menu
def menu_func_import(self, context):
	if IMPORT_GEORASTER:
		self.layout.operator('importgis.georaster', text="Georeferenced raster")
	if IMPORT_SHP:
		self.layout.operator('importgis.shapefile_file_dialog', text="Shapefile (.shp)")
	if IMPORT_OSM:
		self.layout.operator('importgis.osm_file', text="Open Street Map xml (.osm)")
	if IMPORT_ASC:
		self.layout.operator('importgis.asc_file', text="ESRI ASCII Grid (.asc)")

def menu_func_export(self, context):
	if EXPORT_SHP:
		self.layout.operator('exportgis.shapefile', text="Shapefile (.shp)")


def register():

	#icons
	global icons_dict
	icons_dict = iconsLib.new()
	icons_dir = os.path.join(os.path.dirname(__file__), "icons")
	for icon in os.listdir(icons_dir):
		name, ext = os.path.splitext(icon)
		icons_dict.load(name, os.path.join(icons_dir, icon), 'IMAGE')

	#operators
	if TERRAIN_RECLASS:
		nodes_terrain_analysis_reclassify.register() #this module has its own register function because it contains PropertyGroup that must be specifically registered
	bpy.utils.register_module(__name__) #register all imported operators of the current module

	#menus
	bpy.types.INFO_MT_file_import.append(menu_func_import)
	bpy.types.INFO_MT_file_export.append(menu_func_export)

	#shortcuts
	wm = bpy.context.window_manager
	kc =  wm.keyconfigs.active
	if kc is not None: #no keyconfig when Blender from commandline with background flag
		km = kc.keymaps['3D View']
		if BASEMAPS:
			kmi = km.keymap_items.new(idname='view3d.map_start', value='PRESS', type='NUMPAD_ASTERIX', ctrl=False, alt=False, shift=False, oskey=False)
	#config core settings
	prefs = bpy.context.user_preferences.addons[__package__].preferences
	cfg = getSettings()
	cfg['proj_engine'] = prefs.projEngine
	cfg['img_engine'] = prefs.imgEngine
	setSettings(cfg)


def unregister():

	global icons_dict
	iconsLib.remove(icons_dict)

	bpy.types.INFO_MT_file_import.remove(menu_func_import)
	bpy.types.INFO_MT_file_export.append(menu_func_export)
	try: #windows manager may be unavailable (for example whne running Blender command line)
		wm = bpy.context.window_manager
		km = wm.keyconfigs.active.keymaps['3D View']
		if BASEMAPS:
			kmi = km.keymap_items.remove(km.keymap_items['view3d.map_start'])
			#>>cause warnings prints : "search for unknown operator 'VIEW3D_OT_map_start', 'VIEW3D_OT_map_start' "
	except:
		pass
	if TERRAIN_RECLASS:
		nodes_terrain_analysis_reclassify.unregister()
	bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
	register()

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

import bpy

bl_info = {
	'name': 'BlenderGIS',
	'description': 'Various tools for handle geodata',
	'author': 'domlysz',
	'license': 'GPL',
	'deps': '',
	'version': (2, 2, 6),
	'blender': (2, 83, 0),
	'location': 'View3D > Tools > GIS',
	'warning': 'development version',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': 'https://github.com/domlysz/BlenderGIS/issues',
	'link': '',
	'support': 'COMMUNITY',
	'category': '3D View'
	}

class BlenderVersionError(Exception):
	pass

if bl_info['blender'] > bpy.app.version:
	raise BlenderVersionError(f"This addon requires Blender >= {bl_info['blender']}")

#Modules
CAM_GEOPHOTO = True
CAM_GEOREF = True
EXPORT_SHP = True
GET_DEM = True
IMPORT_GEORASTER = True
IMPORT_OSM = True
IMPORT_SHP = True
IMPORT_ASC = True
DELAUNAY = True
TERRAIN_NODES = True
TERRAIN_RECLASS = True
BASEMAPS = True
DROP = True
EARTH_SPHERE = True

import os, sys, tempfile
from datetime import datetime

def getAppData():
	home = os.path.expanduser('~')
	loc = os.path.join(home, '.bgis')
	if not os.path.exists(loc):
		os.mkdir(loc)
	return loc

APP_DATA = getAppData()

import logging
from logging.handlers import RotatingFileHandler
#temporary set log level, will be overriden reading addon prefs
#logsFormat = "%(levelname)s:%(name)s:%(lineno)d:%(message)s"
logsFormat = '{levelname}:{name}:{lineno}:{message}'
logsFileName = 'bgis.log'
try:
	#logsFilePath = os.path.join(os.path.dirname(__file__), logsFileName)
	logsFilePath = os.path.join(APP_DATA, logsFileName)
	#logging.basicConfig(level=logging.getLevelName('DEBUG'), format=logsFormat, style='{', filename=logsFilePath, filemode='w')
	logHandler = RotatingFileHandler(logsFilePath, mode='a', maxBytes=512000, backupCount=1)
except PermissionError:
	#logsFilePath = os.path.join(bpy.app.tempdir, logsFileName)
	logsFilePath = os.path.join(tempfile.gettempdir(), logsFileName)
	logHandler = RotatingFileHandler(logsFilePath, mode='a', maxBytes=512000, backupCount=1)
logHandler.setFormatter(logging.Formatter(logsFormat, style='{'))
logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.DEBUG)
logger.info('###### Starting new Blender session : {}'.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

def _excepthook(exc_type, exc_value, exc_traceback):
	if 'BlenderGIS' in exc_traceback.tb_frame.f_code.co_filename:
		logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
	sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = _excepthook #warn, this is a global variable, can be overrided by another addon

####
'''
Workaround for `sys.excepthook` thread
https://stackoverflow.com/questions/1643327/sys-excepthook-and-threading
'''
import threading

init_original = threading.Thread.__init__

def init(self, *args, **kwargs):

	init_original(self, *args, **kwargs)
	run_original = self.run

	def run_with_except_hook(*args2, **kwargs2):
		try:
			run_original(*args2, **kwargs2)
		except Exception:
			sys.excepthook(*sys.exc_info())

	self.run = run_with_except_hook

threading.Thread.__init__ = init

####


import ssl
if (not os.environ.get('PYTHONHTTPSVERIFY', '') and
	getattr(ssl, '_create_unverified_context', None)):
	ssl._create_default_https_context = ssl._create_unverified_context

#from .core.checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_PIL, HAS_IMGIO
from .core.settings import settings

#Import all modules which contains classes that must be registed (classes derived from bpy.types.*)
from . import prefs
from . import geoscene

if CAM_GEOPHOTO:
	from .operators import add_camera_exif
if CAM_GEOREF:
	from .operators import add_camera_georef
if EXPORT_SHP:
	from .operators import io_export_shp
if GET_DEM:
	from .operators import io_get_dem
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
if EARTH_SPHERE:
	from .operators import mesh_earth_sphere


import bpy.utils.previews as iconsLib
icons_dict = {}


class BGIS_OT_logs(bpy.types.Operator):
	bl_idname = "bgis.logs"
	bl_description = 'Display BlenderGIS logs'
	bl_label = "Logs"

	def execute(self, context):
		if logsFileName in bpy.data.texts:
			logs = bpy.data.texts[logsFileName]
		else:
			logs = bpy.data.texts.load(logsFilePath)
		bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
		area = bpy.context.area
		area.type = 'TEXT_EDITOR'
		area.spaces[0].text = logs
		bpy.ops.text.reload()
		return {'FINISHED'}


class VIEW3D_MT_menu_gis_import(bpy.types.Menu):
	bl_label = "Import"
	def draw(self, context):
		if IMPORT_SHP:
			self.layout.operator("importgis.shapefile_file_dialog", icon_value=icons_dict["shp"].icon_id, text='Shapefile (.shp)')
		if IMPORT_GEORASTER:
			self.layout.operator("importgis.georaster", icon_value=icons_dict["raster"].icon_id, text="Georeferenced raster (.tif .jpg .jp2 .png)")
		if IMPORT_OSM:
			self.layout.operator("importgis.osm_file", icon_value=icons_dict["osm"].icon_id, text="Open Street Map xml (.osm)")
		if IMPORT_ASC:
			self.layout.operator('importgis.asc_file', icon_value=icons_dict["asc"].icon_id, text="ESRI ASCII Grid (.asc)")

class VIEW3D_MT_menu_gis_export(bpy.types.Menu):
	bl_label = "Export"
	def draw(self, context):
		if EXPORT_SHP:
			self.layout.operator('exportgis.shapefile', text="Shapefile (.shp)", icon_value=icons_dict["shp"].icon_id)

class VIEW3D_MT_menu_gis_webgeodata(bpy.types.Menu):
	bl_label = "Web geodata"
	def draw(self, context):
		if BASEMAPS:
			self.layout.operator("view3d.map_start", icon_value=icons_dict["layers"].icon_id)
		if IMPORT_OSM:
			self.layout.operator("importgis.osm_query", icon_value=icons_dict["osm"].icon_id)
		if GET_DEM:
			self.layout.operator("importgis.dem_query", icon_value=icons_dict["raster"].icon_id)

class VIEW3D_MT_menu_gis_camera(bpy.types.Menu):
	bl_label = "Camera"
	def draw(self, context):
		if CAM_GEOREF:
			self.layout.operator("camera.georender", icon_value=icons_dict["georefCam"].icon_id, text='Georender')
		if CAM_GEOPHOTO:
			self.layout.operator("camera.geophotos", icon_value=icons_dict["exifCam"].icon_id, text='Geophotos')
			self.layout.operator("camera.geophotos_setactive", icon='FILE_REFRESH')

class VIEW3D_MT_menu_gis_mesh(bpy.types.Menu):
	bl_label = "Mesh"
	def draw(self, context):
		if DELAUNAY:
			self.layout.operator("tesselation.delaunay", icon_value=icons_dict["delaunay"].icon_id, text='Delaunay')
			self.layout.operator("tesselation.voronoi", icon_value=icons_dict["voronoi"].icon_id, text='Voronoi')
		if EARTH_SPHERE:
			self.layout.operator("earth.sphere", icon="WORLD", text='lonlat to sphere')
			#self.layout.operator("earth.curvature", icon="SPHERECURVE", text='Earth curvature correction')
			self.layout.operator("earth.curvature", icon_value=icons_dict["curve"].icon_id, text='Earth curvature correction')

class VIEW3D_MT_menu_gis_object(bpy.types.Menu):
	bl_label = "Object"
	def draw(self, context):
		if DROP:
			self.layout.operator("object.drop", icon_value=icons_dict["drop"].icon_id, text='Drop')

class VIEW3D_MT_menu_gis_nodes(bpy.types.Menu):
	bl_label = "Nodes"
	def draw(self, context):
		if TERRAIN_NODES:
			self.layout.operator("analysis.nodes", icon_value=icons_dict["terrain"].icon_id, text='Terrain analysis')

class VIEW3D_MT_menu_gis(bpy.types.Menu):
	bl_label = "GIS"
	# Set the menu operators and draw functions
	def draw(self, context):
		layout = self.layout
		layout.operator("bgis.pref_show", icon='PREFERENCES')
		layout.separator()
		layout.menu('VIEW3D_MT_menu_gis_webgeodata', icon="URL")
		layout.menu('VIEW3D_MT_menu_gis_import', icon='IMPORT')
		layout.menu('VIEW3D_MT_menu_gis_export', icon='EXPORT')
		layout.menu('VIEW3D_MT_menu_gis_camera', icon='CAMERA_DATA')
		layout.menu('VIEW3D_MT_menu_gis_mesh', icon='MESH_DATA')
		layout.menu('VIEW3D_MT_menu_gis_object', icon='CUBE')
		layout.menu('VIEW3D_MT_menu_gis_nodes', icon='NODETREE')
		layout.separator()
		layout.operator("bgis.logs", icon='TEXT')

menus = [
VIEW3D_MT_menu_gis,
VIEW3D_MT_menu_gis_webgeodata,
VIEW3D_MT_menu_gis_import,
VIEW3D_MT_menu_gis_export,
VIEW3D_MT_menu_gis_camera,
VIEW3D_MT_menu_gis_mesh,
VIEW3D_MT_menu_gis_object,
VIEW3D_MT_menu_gis_nodes
]


def add_gis_menu(self, context):
	if context.mode == 'OBJECT':
		self.layout.menu('VIEW3D_MT_menu_gis')


def register():
	#icons
	global icons_dict
	icons_dict = iconsLib.new()
	icons_dir = os.path.join(os.path.dirname(__file__), "icons")
	for icon in os.listdir(icons_dir):
		name, ext = os.path.splitext(icon)
		icons_dict.load(name, os.path.join(icons_dir, icon), 'IMAGE')

	#operators
	prefs.register()
	geoscene.register()

	for menu in menus:
		try:
			bpy.utils.register_class(menu)
		except ValueError as e:
			logger.warning('{} is already registered, now unregister and retry... '.format(menu))
			bpy.utils.unregister_class(menu)
			bpy.utils.register_class(menu)

	bpy.utils.register_class(BGIS_OT_logs)

	if BASEMAPS:
		view3d_mapviewer.register()
	if IMPORT_GEORASTER:
		io_import_georaster.register()
	if IMPORT_SHP:
		io_import_shp.register()
	if EXPORT_SHP:
		io_export_shp.register()
	if IMPORT_OSM:
		io_import_osm.register()
	if IMPORT_ASC:
		io_import_asc.register()
	if DELAUNAY:
		mesh_delaunay_voronoi.register()
	if DROP:
		object_drop.register()
	if GET_DEM:
		io_get_dem.register()
	if CAM_GEOPHOTO:
		add_camera_exif.register()
	if CAM_GEOREF:
		add_camera_georef.register()
	if TERRAIN_NODES:
		nodes_terrain_analysis_builder.register()
	if TERRAIN_RECLASS:
		nodes_terrain_analysis_reclassify.register()
	if EARTH_SPHERE:
		mesh_earth_sphere.register()

	#menus
	bpy.types.VIEW3D_MT_editor_menus.append(add_gis_menu)

	#shortcuts
	if not bpy.app.background: #no ui when running as background
		wm = bpy.context.window_manager
		kc =  wm.keyconfigs.active
		if '3D View' in kc.keymaps:
			km = kc.keymaps['3D View']
			if BASEMAPS:
				kmi = km.keymap_items.new(idname='view3d.map_start', type='NUMPAD_ASTERIX', value='PRESS')

	#Setup prefs
	preferences = bpy.context.preferences.addons[__package__].preferences
	logger.setLevel(logging.getLevelName(preferences.logLevel)) #will affect all child logger

	#update core settings according to addon prefs
	settings.proj_engine = preferences.projEngine
	settings.img_engine = preferences.imgEngine


def unregister():

	global icons_dict
	iconsLib.remove(icons_dict)

	if not bpy.app.background: #no ui when running as background
		wm = bpy.context.window_manager
		if '3D View' in  wm.keyconfigs.active.keymaps:
			km = wm.keyconfigs.active.keymaps['3D View']
			if BASEMAPS:
				if 'view3d.map_start' in km.keymap_items:
					kmi = km.keymap_items.remove(km.keymap_items['view3d.map_start'])

	bpy.types.VIEW3D_MT_editor_menus.remove(add_gis_menu)

	for menu in menus:
		bpy.utils.unregister_class(menu)

	bpy.utils.unregister_class(BGIS_OT_logs)

	prefs.unregister()
	geoscene.unregister()
	if BASEMAPS:
		view3d_mapviewer.unregister()
	if IMPORT_GEORASTER:
		io_import_georaster.unregister()
	if IMPORT_SHP:
		io_import_shp.unregister()
	if EXPORT_SHP:
		io_export_shp.unregister()
	if IMPORT_OSM:
		io_import_osm.unregister()
	if IMPORT_ASC:
		io_import_asc.unregister()
	if DELAUNAY:
		mesh_delaunay_voronoi.unregister()
	if DROP:
		object_drop.unregister()
	if GET_DEM:
		io_get_dem.unregister()
	if CAM_GEOPHOTO:
		add_camera_exif.unregister()
	if CAM_GEOREF:
		add_camera_georef.unregister()
	if TERRAIN_NODES:
		nodes_terrain_analysis_builder.unregister()
	if TERRAIN_RECLASS:
		nodes_terrain_analysis_reclassify.unregister()
	if EARTH_SPHERE:
		mesh_earth_sphere.unregister()

if __name__ == "__main__":
	register()

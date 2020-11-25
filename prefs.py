import json
import logging
log = logging.getLogger(__name__)
import sys, os

import bpy
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty
from bpy.types import Operator, Panel, AddonPreferences
import addon_utils

from . import bl_info
from .core.proj.reproj import EPSGIO
from .core.proj.srs import SRS
from .core.checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_PIL, HAS_IMGIO
from .core import settings

PKG = __package__

def getAppData():
	home = os.path.expanduser('~')
	loc = os.path.join(home, '.bgis')
	if not os.path.exists(loc):
		os.mkdir(loc)
	return loc

APP_DATA = getAppData()

'''
Default Enum properties contents (list of tuple (value, label, tootip))
Theses properties are automatically filled from a serialized json string stored in a StringProperty
This is workaround to have an editable EnumProperty (ie the user can add, remove or edit an entry)
because the Blender Python API does not provides built in functions for these tasks.
To edit the content of these enum, we just need to write new operators which will simply update the json string
As the json backend is stored in addon preferences, the property will be saved and restored for the next blender session
'''


DEFAULT_CRS = [
	('EPSG:3857', 'Web Mercator', 'Worldwide projection, high distortions, not suitable for precision modelling'),
	('EPSG:4326', 'WGS84 latlon', 'Longitude and latitude in degrees, DO NOT USE AS SCENE CRS (this system is defined only for reprojection tasks')
]


DEFAULT_DEM_SERVER = [
	("https://portal.opentopography.org/API/globaldem?demtype=SRTMGL1&west={W}&east={E}&south={S}&north={N}&outputFormat=GTiff", 'OpenTopography SRTM 30m', 'OpenTopography.org web service for SRTM 30m global DEM'),
	("https://portal.opentopography.org/API/globaldem?demtype=SRTMGL3&west={W}&east={E}&south={S}&north={N}&outputFormat=GTiff", 'OpenTopography SRTM 90m', 'OpenTopography.org web service for SRTM 90m global DEM'),
	("http://www.gmrt.org/services/GridServer?west={W}&east={E}&south={S}&north={N}&layer=topo&format=geotiff&resolution=high", 'Marine-geo.org GMRT', 'Marine-geo.org web service for GMRT global DEM (terrestrial (ASTER) and bathymetry)')
]

DEFAULT_OVERPASS_SERVER =  [
	("https://lz4.overpass-api.de/api/interpreter", 'overpass-api.de', 'Main Overpass API instance'),
	("http://overpass.openstreetmap.fr/api/interpreter", 'overpass.openstreetmap.fr', 'French Overpass API instance'),
	("https://overpass.kumi.systems/api/interpreter", 'overpass.kumi.systems', 'Kumi Systems Overpass Instance')
]

#default filter tags for OSM import
DEFAULT_OSM_TAGS = [
	'building',
	'highway',
	'landuse',
	'leisure',
	'natural',
	'railway',
	'waterway'
]



class BGIS_OT_pref_show(Operator):

	bl_idname = "bgis.pref_show"
	bl_description = 'Display BlenderGIS addons preferences'
	bl_label = "Preferences"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		addon_utils.modules_refresh()
		context.preferences.active_section = 'ADDONS'
		bpy.data.window_managers["WinMan"].addon_search = bl_info['name']
		#bpy.ops.wm.addon_expand(module=PKG)
		mod = addon_utils.addons_fake_modules.get(PKG)
		mod.bl_info['show_expanded'] = True
		bpy.ops.screen.userpref_show('INVOKE_DEFAULT')
		return {'FINISHED'}



class BGIS_PREFS(AddonPreferences):

	bl_idname = PKG

	################
	#Predefined Spatial Ref. Systems

	def listPredefCRS(self, context):
		return [tuple(elem) for elem in json.loads(self.predefCrsJson)]

	#store crs preset as json string into addon preferences
	predefCrsJson: StringProperty(default=json.dumps(DEFAULT_CRS))

	predefCrs: EnumProperty(
		name = "Predefinate CRS",
		description = "Choose predefinite Coordinate Reference System",
		#default = 1, #possible only since Blender 2.90
		items = listPredefCRS
		)

	################
	#proj engine

	def getProjEngineItems(self, context):
		items = [ ('AUTO', 'Auto detect', 'Auto select the best library for reprojection tasks') ]
		if HAS_GDAL:
			items.append( ('GDAL', 'GDAL', 'Force GDAL as reprojection engine') )
		if HAS_PYPROJ:
			items.append( ('PYPROJ', 'pyProj', 'Force pyProj as reprojection engine') )
		#if EPSGIO.ping(): #too slow
		#	items.append( ('EPSGIO', 'epsg.io', '') )
		items.append( ('EPSGIO', 'epsg.io', 'Force epsg.io as reprojection engine') )
		items.append( ('BUILTIN', 'Built in', 'Force reprojection through built in Python functions') )
		return items

	def updateProjEngine(self, context):
		settings.proj_engine = self.projEngine

	projEngine: EnumProperty(
		name = "Projection engine",
		description = "Select projection engine",
		items = getProjEngineItems,
		update = updateProjEngine
		)

	################
	#img engine

	def getImgEngineItems(self, context):
		items = [ ('AUTO', 'Auto detect', 'Auto select the best imaging library') ]
		if HAS_GDAL:
			items.append( ('GDAL', 'GDAL', 'Force GDAL as image processing engine') )
		if HAS_IMGIO:
			items.append( ('IMGIO', 'ImageIO', 'Force ImageIO as image processing  engine') )
		if HAS_PIL:
			items.append( ('PIL', 'PIL', 'Force PIL as image processing  engine') )
		return items

	def updateImgEngine(self, context):
		settings.img_engine = self.imgEngine

	imgEngine: EnumProperty(
		name = "Image processing engine",
		description = "Select image processing engine",
		items = getImgEngineItems,
		update = updateImgEngine
		)

	################
	#OSM

	osmTagsJson: StringProperty(default=json.dumps(DEFAULT_OSM_TAGS)) #just a serialized list of tags

	def listOsmTags(self, context):
		prefs = context.preferences.addons[PKG].preferences
		tags = json.loads(prefs.osmTagsJson)
		#put each item in a tuple (key, label, tooltip)
		return [ (tag, tag, tag) for tag in tags]

	osmTags: EnumProperty(
		name = "OSM tags",
		description = "List of registered OSM tags",
		items = listOsmTags
		)

	################
	#Basemaps

	def getCacheFolder(self):
		return bpy.path.abspath(self.get("cacheFolder", ''))

	def setCacheFolder(self, value):
		if os.access(value, os.X_OK | os.W_OK):
			self["cacheFolder"] = value
		else:
			log.error("The selected cache folder has no write access")
			self["cacheFolder"] = "The selected folder has no write access"

	cacheFolder: StringProperty(
		name = "Cache folder",
		default = APP_DATA, #Does not works !?
		description = "Define a folder where to store Geopackage SQlite db",
		subtype = 'DIR_PATH',
		get = getCacheFolder,
		set = setCacheFolder
		)

	synchOrj: BoolProperty(
		name="Synch. lat/long",
		description='Keep geo origin synchronized with crs origin. Can be slow with remote reprojection services',
		default=True)

	zoomToMouse: BoolProperty(name="Zoom to mouse", description='Zoom towards the mouse pointer position', default=True)

	lockOrigin: BoolProperty(name="Lock origin", description='Do not move scene origin when panning map', default=False)
	lockObj: BoolProperty(name="Lock objects", description='Retain objects geolocation when moving map origin', default=True)

	resamplAlg: EnumProperty(
		name = "Resampling method",
		description = "Choose GDAL's resampling method used for reprojection",
		items = [ ('NN', 'Nearest Neighboor', ''), ('BL', 'Bilinear', ''), ('CB', 'Cubic', ''), ('CBS', 'Cubic Spline', ''), ('LCZ', 'Lanczos', '') ]
		)

	################
	#Network

	def listOverpassServer(self, context):
		return [tuple(entry) for entry in json.loads(self.overpassServerJson)]

	#store crs preset as json string into addon preferences
	overpassServerJson: StringProperty(default=json.dumps(DEFAULT_OVERPASS_SERVER))

	overpassServer: EnumProperty(
		name = "Overpass server",
		description = "Select an overpass server",
		#default = 0,
		items = listOverpassServer
		)

	def listDemServer(self, context):
		return [tuple(entry) for entry in json.loads(self.demServerJson)]

	#store crs preset as json string into addon preferences
	demServerJson: StringProperty(default=json.dumps(DEFAULT_DEM_SERVER))

	demServer: EnumProperty(
		name = "Elevation server",
		description = "Select a server that provides Digital Elevation Model datasource",
		#default = 0,
		items = listDemServer
		)

	################
	#IO options
	mergeDoubles: BoolProperty(
		name = "Merge duplicate vertices",
		description = 'Merge shared vertices between features when importing vector data',
		default = False)
	adjust3Dview: BoolProperty(
		name = "Adjust 3D view",
		description = "Update 3d view grid size and clip distances according to the new imported object's size",
		default = True)
	forceTexturedSolid: BoolProperty(
		name = "Force textured solid shading",
		description = "Update shading mode to display raster's texture",
		default = True)

	################
	#System
	def updateLogLevel(self, context):
		logger = logging.getLogger(PKG)
		logger.setLevel(logging.getLevelName(self.logLevel))

	logLevel: EnumProperty(
		name = "Logging level",
		description = "Select the logging level",
		items = [('DEBUG', 'Debug', ''), ('INFO', 'Info', ''), ('WARNING', 'Warning', ''), ('ERROR', 'Error', ''), ('CRITICAL', 'Critical', '')],
		update = updateLogLevel,
		default = 'DEBUG'
		)

	################
	def draw(self, context):
		layout = self.layout

		#SRS
		box = layout.box()
		box.label(text='Spatial Reference Systems')
		row = box.row().split(factor=0.5)
		row.prop(self, "predefCrs", text='')
		row.operator("bgis.add_predef_crs", icon='ADD')
		row.operator("bgis.edit_predef_crs", icon='PREFERENCES')
		row.operator("bgis.rmv_predef_crs", icon='REMOVE')
		row.operator("bgis.reset_predef_crs", icon='PLAY_REVERSE')

		#Basemaps
		box = layout.box()
		box.label(text='Basemaps')
		box.prop(self, "cacheFolder")
		row = box.row()
		row.prop(self, "zoomToMouse")
		row.prop(self, "lockObj")
		row.prop(self, "lockOrigin")
		row.prop(self, "synchOrj")
		row = box.row()
		row.prop(self, "resamplAlg")

		#IO
		box = layout.box()
		box.label(text='Import/Export')
		row = box.row().split(factor=0.5)
		split = row.split(factor=0.9, align=True)
		split.prop(self, "osmTags")
		split.operator("wm.url_open", icon='INFO').url = "http://wiki.openstreetmap.org/wiki/Map_Features"
		row.operator("bgis.add_osm_tag", icon='ADD')
		row.operator("bgis.edit_osm_tag", icon='PREFERENCES')
		row.operator("bgis.rmv_osm_tag", icon='REMOVE')
		row.operator("bgis.reset_osm_tags", icon='PLAY_REVERSE')
		row = box.row()
		row.prop(self, "mergeDoubles")
		row.prop(self, "adjust3Dview")
		row.prop(self, "forceTexturedSolid")

		#Network
		box = layout.box()
		box.label(text='Remote datasource')
		row = box.row().split(factor=0.5)
		row.prop(self, "overpassServer")
		row.operator("bgis.add_overpass_server", icon='ADD')
		row.operator("bgis.edit_overpass_server", icon='PREFERENCES')
		row.operator("bgis.rmv_overpass_server", icon='REMOVE')
		row.operator("bgis.reset_overpass_server", icon='PLAY_REVERSE')
		row = box.row().split(factor=0.5)
		row.prop(self, "demServer")
		row.operator("bgis.add_dem_server", icon='ADD')
		row.operator("bgis.edit_dem_server", icon='PREFERENCES')
		row.operator("bgis.rmv_dem_server", icon='REMOVE')
		row.operator("bgis.reset_dem_server", icon='PLAY_REVERSE')

		#System
		box = layout.box()
		box.label(text='System')
		box.prop(self, "projEngine")
		box.prop(self, "imgEngine")
		box.prop(self, "logLevel")

#######################

class PredefCRS():

	'''
	Collection of utility methods (callable at class level) to deal with predefined CRS dictionary
	Can be used by others operators that need to fill their own crs enum
	'''

	@staticmethod
	def getData():
		'''Load the json string'''
		prefs = bpy.context.preferences.addons[PKG].preferences
		return json.loads(prefs.predefCrsJson)

	@classmethod
	def getName(cls, key):
		'''Return the convenient name of a given srid or None if this crs does not exist in the list'''
		data = cls.getData()
		try:
			return [entry[1] for entry in data if entry[0] == key][0]
		except IndexError:
			return None

	@classmethod
	def getEnumItems(cls):
		'''Return a list of predefined crs usable to fill a bpy EnumProperty'''
		return [tuple(entry) for entry in cls.getData()]


#################
# Collection of operators to manage predefined CRS

class BGIS_OT_add_predef_crs(Operator):
	bl_idname = "bgis.add_predef_crs"
	bl_description = 'Add predefinate CRS'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	crs: StringProperty(name = "Definition",  description = "Specify EPSG code or Proj4 string definition for this CRS")
	name: StringProperty(name = "Description", description = "Choose a convenient name for this CRS")
	desc: StringProperty(name = "Description", description = "Add a description or comment about this CRS")

	def check(self, context):
		return True

	def search(self, context):
		if not EPSGIO.ping():
			self.report({'ERROR'}, "Cannot request epsg.io website")
		else:
			results = EPSGIO.search(self.query)
			self.results = json.dumps(results)
			if results:
				self.crs = 'EPSG:' + results[0]['code']
				self.name = results[0]['name']

	def updEnum(self, context):
		crsItems = []
		if self.results != '':
			for result in json.loads(self.results):
				srid = 'EPSG:' + result['code']
				crsItems.append( (result['code'], result['name'], srid) )
		return crsItems

	def fill(self, context):
		if self.results != '':
			crs = [crs for crs in json.loads(self.results) if crs['code'] == self.crsEnum][0]
			self.crs = 'EPSG:' + crs['code']
			self.desc = crs['name']

	query: StringProperty(name='Query', description='Hit enter to process the search', update=search)

	results: StringProperty()

	crsEnum: EnumProperty(name='Results', description='Select the desired CRS', items=updEnum, update=fill)

	search: BoolProperty(name='Search', description='Search for coordinate system into EPSG database', default=False)

	save: BoolProperty(name='Save to addon preferences',  description='Save Blender user settings after the addition', default=False)

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)#, width=300)

	def draw(self, context):
		layout = self.layout
		layout.prop(self, 'search')
		if self.search:
			layout.prop(self, 'query')
			layout.prop(self, 'crsEnum')
			layout.separator()
		layout.prop(self, 'crs')
		layout.prop(self, 'name')
		layout.prop(self, 'desc')
		#layout.prop(self, 'save') #sincce Blender2.8 prefs are autosaved

	def execute(self, context):
		if not SRS.validate(self.crs):
			self.report({'ERROR'}, 'Invalid CRS')
		if self.crs.isdigit():
			self.crs = 'EPSG:' + self.crs
		#append the new crs def to json string
		prefs = context.preferences.addons[PKG].preferences
		data = json.loads(prefs.predefCrsJson)
		data.append((self.crs, self.name, self.desc))
		prefs.predefCrsJson = json.dumps(data)
		#change enum index to new added crs and redraw
		#prefs.predefCrs = self.crs
		context.area.tag_redraw()
		#end
		if self.save:
			bpy.ops.wm.save_userpref()
		return {'FINISHED'}

class BGIS_OT_rmv_predef_crs(Operator):

	bl_idname = "bgis.rmv_predef_crs"
	bl_description = 'Remove predefinate CRS'
	bl_label = "Remove"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.predefCrs
		if key != '':
			data = json.loads(prefs.predefCrsJson)
			data = [e for e in data if e[0] != key]
			prefs.predefCrsJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_reset_predef_crs(Operator):

	bl_idname = "bgis.reset_predef_crs"
	bl_description = 'Reset predefinate CRS'
	bl_label = "Reset"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		prefs.predefCrsJson = json.dumps(DEFAULT_CRS)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_edit_predef_crs(Operator):

	bl_idname = "bgis.edit_predef_crs"
	bl_description = 'Edit predefinate CRS'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	crs: StringProperty(name = "EPSG code or Proj4 string",  description = "Specify EPSG code or Proj4 string definition for this CRS")
	name: StringProperty(name = "Description", description = "Choose a convenient name for this CRS")
	desc: StringProperty(name = "Name", description = "Add a description or comment about this CRS")

	def invoke(self, context, event):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.predefCrs
		if key == '':
			return {'CANCELLED'}
		data = json.loads(prefs.predefCrsJson)
		entry = [entry for entry in data if entry[0] == key][0]
		self.crs, self.name, self.desc = entry
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.predefCrs
		data = json.loads(prefs.predefCrsJson)

		if SRS.validate(self.crs):
			data = [entry for entry in data if entry[0] != key] #deleting
			data.append((self.crs, self.name, self.desc))
			prefs.predefCrsJson = json.dumps(data)
			context.area.tag_redraw()
		else:
			self.report({'ERROR'}, 'Invalid CRS')

		return {'FINISHED'}


#################
# Collection of operators to manage predefinates OSM Tags

class BGIS_OT_add_osm_tag(Operator):
	bl_idname = "bgis.add_osm_tag"
	bl_description = 'Add new predefinate OSM filter tag'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	tag: StringProperty(name = "Tag",  description = "Specify the tag (examples : 'building', 'landuse=forest' ...)")

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)#, width=300)

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		tags = json.loads(prefs.osmTagsJson)
		tags.append(self.tag)
		prefs.osmTagsJson = json.dumps(tags)
		prefs.osmTags = self.tag #update current idx
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_rmv_osm_tag(Operator):

	bl_idname = "bgis.rmv_osm_tag"
	bl_description = 'Remove predefinate OSM filter tag'
	bl_label = "Remove"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		tag = prefs.osmTags
		if tag != '':
			tags = json.loads(prefs.osmTagsJson)
			del tags[tags.index(tag)]
			prefs.osmTagsJson = json.dumps(tags)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_reset_osm_tags(Operator):

	bl_idname = "bgis.reset_osm_tags"
	bl_description = 'Reset predefinate OSM filter tag'
	bl_label = "Reset"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		prefs.osmTagsJson = json.dumps(DEFAULT_OSM_TAGS)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_edit_osm_tag(Operator):

	bl_idname = "bgis.edit_osm_tag"
	bl_description = 'Edit predefinate OSM filter tag'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	tag: StringProperty(name = "Tag",  description = "Specify the tag (examples : 'building', 'landuse=forest' ...)")

	def invoke(self, context, event):
		prefs = context.preferences.addons[PKG].preferences
		self.tag = prefs.osmTags
		if self.tag == '':
			return {'CANCELLED'}
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		tag = prefs.osmTags
		tags = json.loads(prefs.osmTagsJson)
		del tags[tags.index(tag)]
		tags.append(self.tag)
		prefs.osmTagsJson = json.dumps(tags)
		prefs.osmTags = self.tag #update current idx
		context.area.tag_redraw()
		return {'FINISHED'}

#################
# Collection of operators to manage DEM server urls

class BGIS_OT_add_dem_server(Operator):
	bl_idname = "bgis.add_dem_server"
	bl_description = 'Add new topography web service'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	url: StringProperty(name = "Url template",  description = "Define url template string. Bounding box varaibles are {W}, {E}, {S} and {N}")
	name: StringProperty(name = "Description", description = "Choose a convenient name for this server")
	desc: StringProperty(name = "Description", description = "Add a description or comment about this remote datasource")

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)#, width=300)

	def execute(self, context):
		templates = ['{W}', '{E}', '{S}', '{N}']
		if all([t in self.url for t in templates]):
			prefs = context.preferences.addons[PKG].preferences
			data = json.loads(prefs.demServerJson)
			data.append( (self.url, self.name, self.desc) )
			prefs.demServerJson = json.dumps(data)
			context.area.tag_redraw()
		else:
			self.report({'ERROR'}, 'Invalid URL')
		return {'FINISHED'}

class BGIS_OT_rmv_dem_server(Operator):

	bl_idname = "bgis.rmv_dem_server"
	bl_description = 'Remove a given topography web service'
	bl_label = "Remove"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.demServer
		if key != '':
			data = json.loads(prefs.demServerJson)
			data = [e for e in data if e[0] != key]
			prefs.demServerJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_reset_dem_server(Operator):

	bl_idname = "bgis.reset_dem_server"
	bl_description = 'Reset default topographic web server'
	bl_label = "Reset"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		prefs.demServerJson = json.dumps(DEFAULT_DEM_SERVER)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_edit_dem_server(Operator):

	bl_idname = "bgis.edit_dem_server"
	bl_description = 'Edit a topographic web server'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	url: StringProperty(name = "Url template",  description = "Define url template string. Bounding box varaibles are {W}, {E}, {S} and {N}")
	name: StringProperty(name = "Description", description = "Choose a convenient name for this server")
	desc: StringProperty(name = "Description", description = "Add a description or comment about this remote datasource")

	def invoke(self, context, event):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.demServer
		if key == '':
			return {'CANCELLED'}
		data = json.loads(prefs.demServerJson)
		entry = [entry for entry in data if entry[0] == key][0]
		self.url, self.name, self.desc = entry
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.demServer
		data = json.loads(prefs.demServerJson)
		templates = ['{W}', '{E}', '{S}', '{N}']
		if all([t in self.url for t in templates]):
			data = [entry for entry in data if entry[0] != key] #deleting
			data.append((self.url, self.name, self.desc))
			prefs.demServerJson = json.dumps(data)
			context.area.tag_redraw()
		else:
			self.report({'ERROR'}, 'Invalid URL')
		return {'FINISHED'}

#################

class EditEnum():
	'''
	Helper to deal with an enum property that use a serialized json backend
	Can be used by others operators to edit and EnumProperty
	WORK IN PROGRESS
	'''

	def __init__(self, enumName):
		self.prefs = bpy.context.preferences.addons[PKG].preferences
		self.enumName = enumName
		self.jsonName = enumName + 'Json'

	def getData(self):
		'''Load the json string'''
		data = json.loads(getattr(self.prefs, self.jsonName))
		return [tuple(entry) for entry in data]

	def append(self, value, label, tooltip, check=lambda x: True):
		if not check(value):
			return
		data = self.getData()
		data.append((value, label, tooltip))
		setattr(self.prefs, self.jsonName, json.dumps(data))

	def remove(self, key):
		if key != '':
			data = self.getData()
			data = [e for e in data if e[0] != key]
			setattr(self.prefs, self.jsonName, json.dumps(data))

	def edit(self, key, value, label, tooltip):
		self.remove(key)
		self.append(value, label, tooltip)

	def reset(self):
		setattr(self.prefs, self.jsonName, json.dumps(DEFAULT_OVERPASS_SERVER))

#################
# Collection of operators to manage Overpass server urls

class BGIS_OT_add_overpass_server(Operator):
	bl_idname = "bgis.add_overpass_server"
	bl_description = 'Add new OSM overpass server url'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	url: StringProperty(name = "Url template",  description = "Define the url end point of the overpass server")
	name: StringProperty(name = "Description", description = "Choose a convenient name for this server")
	desc: StringProperty(name = "Description", description = "Add a description or comment about this remote server")

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)#, width=300)

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		data = json.loads(prefs.overpassServerJson)
		data.append( (self.url, self.name, self.desc) )
		prefs.overpassServerJson = json.dumps(data)
		#EditEnum('overpassServer').append(self.url, self.name, self.desc, check=lambda url: url.startswith('http'))
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_rmv_overpass_server(Operator):

	bl_idname = "bgis.rmv_overpass_server"
	bl_description = 'Remove a given overpass server'
	bl_label = "Remove"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.overpassServer
		if key != '':
			data = json.loads(prefs.overpassServerJson)
			data = [e for e in data if e[0] != key]
			prefs.overpassServerJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_reset_overpass_server(Operator):

	bl_idname = "bgis.reset_overpass_server"
	bl_description = 'Reset default overpass server'
	bl_label = "Rest"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		prefs.overpassServerJson = json.dumps(DEFAULT_OVERPASS_SERVER)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_edit_overpass_server(Operator):

	bl_idname = "bgis.edit_overpass_server"
	bl_description = 'Edit an overpass server url'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	url: StringProperty(name = "Url template",  description = "Define the url end point of the overpass server")
	name: StringProperty(name = "Description", description = "Choose a convenient name for this server")
	desc: StringProperty(name = "Description", description = "Add a description or comment about this remote server")

	def invoke(self, context, event):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.overpassServer
		if key == '':
			return {'CANCELLED'}
		data = json.loads(prefs.overpassServerJson)
		entry = [entry for entry in data if entry[0] == key][0]
		self.url, self.name, self.desc = entry
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.overpassServer
		data = json.loads(prefs.overpassServerJson)
		data = [entry for entry in data if entry[0] != key] #deleting
		data.append((self.url, self.name, self.desc))
		prefs.overpassServerJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}


classes = [
BGIS_OT_pref_show,
BGIS_PREFS,
BGIS_OT_add_predef_crs,
BGIS_OT_rmv_predef_crs,
BGIS_OT_reset_predef_crs,
BGIS_OT_edit_predef_crs,
BGIS_OT_add_osm_tag,
BGIS_OT_rmv_osm_tag,
BGIS_OT_reset_osm_tags,
BGIS_OT_edit_osm_tag,
BGIS_OT_add_dem_server,
BGIS_OT_rmv_dem_server,
BGIS_OT_reset_dem_server,
BGIS_OT_edit_dem_server,
BGIS_OT_add_overpass_server,
BGIS_OT_rmv_overpass_server,
BGIS_OT_reset_overpass_server,
BGIS_OT_edit_overpass_server
]

def register():
	for cls in classes:
		try:
			bpy.utils.register_class(cls)
		except ValueError as e:
			#log.error('Cannot register {}'.format(cls), exc_info=True)
			log.warning('{} is already registered, now unregister and retry... '.format(cls))
			bpy.utils.unregister_class(cls)
			bpy.utils.register_class(cls)

	# set default cache folder
	prefs = bpy.context.preferences.addons[PKG].preferences
	if prefs.cacheFolder == '':
		prefs.cacheFolder = APP_DATA


def unregister():
	for cls in classes:
		bpy.utils.unregister_class(cls)

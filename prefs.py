import json
import logging
log = logging.getLogger(__name__)
import sys

import bpy
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty
from bpy.types import Operator, Panel, AddonPreferences
import addon_utils

from . import bl_info
from .core.proj.reproj import EPSGIO
from .core.proj.srs import SRS
from .core.checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_PIL, HAS_IMGIO
from .core.settings import getSetting, getSettings, setSettings

PKG = __package__

#default predefinate crs
PREDEF_CRS = {
	'EPSG:4326' : 'WGS84 latlon',
	'EPSG:3857' : 'Web Mercator'
}

#default filter tags for OSM import
OSM_TAGS = [
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
	#Predefinate Spatial Ref. Systems

	def listPredefCRS(self, context):
		return PredefCRS.getEnumItems()

	#store crs preset as json string into addon preferences
	predefCrsJson: StringProperty(default=json.dumps(PREDEF_CRS))

	predefCrs: EnumProperty(
		name = "Predefinate CRS",
		description = "Choose predefinite Coordinate Reference System",
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
		prefs = getSettings()
		prefs['proj_engine'] = self.projEngine
		setSettings(prefs)

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
		prefs = getSettings()
		prefs['img_engine'] = self.imgEngine
		setSettings(prefs)

	imgEngine: EnumProperty(
		name = "Image processing engine",
		description = "Select image processing engine",
		items = getImgEngineItems,
		update = updateImgEngine
		)

	################
	#OSM

	osmTagsJson: StringProperty(default=json.dumps(OSM_TAGS)) #just a serialized list of tags

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

	overpassServer: EnumProperty(
		name = "Overpass server",
		description = "Select an overpass server",
		default = "https://lz4.overpass-api.de/api/interpreter",
		items = [
			("https://lz4.overpass-api.de/api/interpreter", 'overpass-api.de', 'Main Overpass API instance'),
			("http://overpass.openstreetmap.fr/api/interpreter", 'overpass.openstreetmap.fr', 'French Overpass API instance'),
			("https://overpass.kumi.systems/api/interpreter", 'overpass.kumi.systems', 'Kumi Systems Overpass Instance')
			#("https://overpass.nchc.org.tw", 'overpass.nchc.org.tw', 'Taiwan Overpass API')
			]
		)

	################
	#Basemaps

	def getCacheFolder(self):
		return bpy.path.abspath(self.get("cacheFolder", ''))

	def setCacheFolder(self, value):
		self["cacheFolder"] = value

	cacheFolder: StringProperty(
		name = "Cache folder",
		default = "",
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
	#DEM options
	srtmServer: EnumProperty(
		name = "SRTM server",
		description = "Select an overpass server",
		items = [
			("http://opentopo.sdsc.edu/otr/getdem?demtype=SRTMGL3&west={W}&east={E}&south={S}&north={N}&outputFormat=GTiff", 'OpenTopography', 'OpenTopography.org web service'),
			("http://www.marine-geo.org/services/GridServer?west={W}&east={E}&south={S}&north={N}&layer=topo&format=geotiff&resolution=high", 'Marine-geo.org', 'Marine-geo.org web service')
			]
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
		box.prop(self, "projEngine")
		box.prop(self, "imgEngine")

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
		row.prop(self, "overpassServer")
		row.prop(self, "srtmServer")
		row = box.row()
		row.prop(self, "mergeDoubles")
		row.prop(self, "adjust3Dview")
		row.prop(self, "forceTexturedSolid")

		#System
		box = layout.box()
		box.label(text='System')
		box.prop(self, "logLevel")

#######################

class PredefCRS():

	'''Collection of methods (callable at class level) to deal with predefined CRS dictionary'''

	@staticmethod
	def getData():
		'''Load the json string'''
		prefs = bpy.context.preferences.addons[PKG].preferences
		return json.loads(prefs.predefCrsJson)

	@staticmethod
	def getSelected():
		'''Return the current crs selected in the enum stored in addon preferences'''
		prefs = bpy.context.preferences.addons[PKG].preferences
		return prefs.predefCrs

	@classmethod
	def getName(cls, key):
		'''Return the name of a given srid or None if this crs does not exist in predef list'''
		data = cls.getData()
		return data.get(key, None)

	@classmethod
	def getEnumItems(cls):
		'''Return a list of predefined crs usable to fill a bpy EnumProperty'''
		crsItems = []
		data = cls.getData()
		for srid, name in data.items():
			#put each item in a tuple (key, label, tooltip)
			crsItems.append( (srid, name, srid) )
		return crsItems


#################
# Collection of operators to manage predefinates CRS

class BGIS_OT_add_predef_crs(Operator):
	bl_idname = "bgis.add_predef_crs"
	bl_description = 'Add predefinate CRS'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	crs: StringProperty(name = "Definition",  description = "Specify EPSG code or Proj4 string definition for this CRS")
	desc: StringProperty(name = "Description", description = "Choose a convenient name for this CRS")

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
				self.desc = results[0]['name']

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
		layout.prop(self, 'desc')
		layout.prop(self, 'save')

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		#append the new crs def to json string
		data = json.loads(prefs.predefCrsJson)
		if not SRS.validate(self.crs):
			self.report({'ERROR'}, 'Invalid CRS')
		if self.crs.isdigit():
			self.crs = 'EPSG:' + self.crs
		data[self.crs] = self.desc
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
			del data[key]
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
		prefs.predefCrsJson = json.dumps(PREDEF_CRS)
		context.area.tag_redraw()
		return {'FINISHED'}

class BGIS_OT_edit_predef_crs(Operator):

	bl_idname = "bgis.edit_predef_crs"
	bl_description = 'Edit predefinate CRS'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	desc: StringProperty(name = "Name", description = "Choose a convenient name for this CRS")
	crs: StringProperty(name = "EPSG code or Proj4 string",  description = "Specify EPSG code or Proj4 string definition for this CRS")

	def invoke(self, context, event):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.predefCrs
		if key == '':
			return {'CANCELLED'}
		data = json.loads(prefs.predefCrsJson)
		self.crs = key
		self.desc = data[key]
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.preferences.addons[PKG].preferences
		key = prefs.predefCrs
		data = json.loads(prefs.predefCrsJson)

		if SRS.validate(self.crs):
			del data[key]
			data[self.crs] = self.desc
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
		prefs.osmTagsJson = json.dumps(OSM_TAGS)
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
BGIS_OT_edit_osm_tag
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


def unregister():
	for cls in classes:
		bpy.utils.unregister_class(cls)

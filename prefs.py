import json

import bpy
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty
from bpy.types import Operator, Panel, AddonPreferences
import addon_utils

from . import bl_info
from .utils.proj import SRS, EPSGIO #classes
from .checkdeps import HAS_GDAL, HAS_PYPROJ

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


class BGIS_PREFS_SHOW(bpy.types.Operator):

	bl_idname = "bgis.pref_show"
	bl_description = 'Display BlenderGIS addons preferences'
	bl_label = "Preferences"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		addon_utils.modules_refresh()
		bpy.context.user_preferences.active_section = 'ADDONS'
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
	predefCrsJson = StringProperty(default=json.dumps(PREDEF_CRS))

	predefCrs = EnumProperty(
		name = "Predefinate CRS",
		description = "Choose predefinite Coordinate Reference System",
		items = listPredefCRS
		)

	def getProjEngine(self, context):
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

	projEngine = EnumProperty(
		name = "Projection engine",
		description = "Select projection engine",
		items = getProjEngine
		)

	################
	#OSM

	osmTagsJson = StringProperty(default=json.dumps(OSM_TAGS)) #just a serialized list of tags

	def listOsmTags(self, context):
		prefs = bpy.context.user_preferences.addons[PKG].preferences
		tags = json.loads(prefs.osmTagsJson)
		#put each item in a tuple (key, label, tooltip)
		return [ (tag, tag, tag) for tag in tags]

	osmTags = EnumProperty(
		name = "OSM tags",
		description = "List of registered OSM tags",
		items = listOsmTags
		)

	################
	#Basemaps

	cacheFolder = StringProperty(
		name = "Cache folder",
		default = "",
		description = "Define a folder where to store Geopackage SQlite db",
		subtype = 'DIR_PATH'
		)

	fontColor = FloatVectorProperty(
		name="Font color",
		subtype='COLOR',
		min=0, max=1,
		size=4,
		default=(0, 0, 0, 1)
		)

	zoomToMouse = BoolProperty(name="Zoom to mouse", description='Zoom towards the mouse pointer position', default=True)

	lockOrigin = BoolProperty(name="Lock origin", description='Do not move scene origin when panning map', default=False)
	lockObj = BoolProperty(name="Lock objects", description='Retain objects geolocation when moving map origin', default=True)

	resamplAlg = EnumProperty(
		name = "Resampling method",
		description = "Choose GDAL's resampling method used for reprojection",
		items = [ ('NN', 'Nearest Neighboor', ''), ('BL', 'Bilinear', ''), ('CB', 'Cubic', ''), ('CBS', 'Cubic Spline', ''), ('LCZ', 'Lanczos', '') ]
		)



	def draw(self, context):
		layout = self.layout

		#SRS
		box = layout.box()
		box.label('Spatial Reference Systems')
		row = box.row().split(percentage=0.5)
		row.prop(self, "predefCrs", text='')
		row.operator("bgis.add_predef_crs", icon='ZOOMIN')
		row.operator("bgis.edit_predef_crs", icon='SCRIPTWIN')
		row.operator("bgis.rmv_predef_crs", icon='ZOOMOUT')
		row.operator("bgis.reset_predef_crs", icon='PLAY_REVERSE')
		box.prop(self, "projEngine")

		#Basemaps
		box = layout.box()
		box.label('Basemaps')
		box.prop(self, "cacheFolder")
		row = box.row()
		row.prop(self, "zoomToMouse")
		row.prop(self, "lockObj")
		row.prop(self, "lockOrigin")
		row.label('Font color:')
		row.prop(self, "fontColor", text='')
		row = box.row()
		row.prop(self, "resamplAlg")

		#IO
		box = layout.box()
		box.label('Import/Export')
		row = box.row().split(percentage=0.5)
		split = row.split(percentage=0.9, align=True)
		split.prop(self, "osmTags")
		split.operator("wm.url_open", icon='INFO').url = "http://wiki.openstreetmap.org/wiki/Map_Features"
		row.operator("bgis.add_osm_tag", icon='ZOOMIN')
		row.operator("bgis.edit_osm_tag", icon='SCRIPTWIN')
		row.operator("bgis.rmv_osm_tag", icon='ZOOMOUT')
		row.operator("bgis.reset_osm_tags", icon='PLAY_REVERSE')


#######################

class PredefCRS():

	'''Collection of methods (callable at class level) to deal with predefinates CRS dictionnary'''

	@staticmethod
	def getData():
		'''Load the json string'''
		prefs = bpy.context.user_preferences.addons[PKG].preferences
		return json.loads(prefs.predefCrsJson)

	@staticmethod
	def getSelected():
		'''Return the current crs selected in the enum stored in addon preferences'''
		prefs = bpy.context.user_preferences.addons[PKG].preferences
		return prefs.predefCrs

	@classmethod
	def getName(cls, key):
		'''Return the name of a given srid or None if this crs does not exist in predef list'''
		data = cls.getData()
		return data.get(key, None)

	@classmethod
	def getEnumItems(cls):
		'''Return a list of predefinate crs usable to fill a bpy EnumProperty'''
		crsItems = []
		data = cls.getData()
		for srid, name in data.items():
			#put each item in a tuple (key, label, tooltip)
			crsItems.append( (srid, name, srid) )
		return crsItems


#################
# Collection of operators to manage predefinates CRS

class PREDEF_CRS_ADD(Operator):
	bl_idname = "bgis.add_predef_crs"
	bl_description = 'Add predefinate CRS'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	crs = StringProperty(name = "Definition",  description = "Specify EPSG code or Proj4 string definition for this CRS")
	desc = StringProperty(name = "Description", description = "Choose a convenient name for this CRS")

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

	query = StringProperty(name='Query', description='Hit enter to process the search', update=search)

	results = StringProperty()

	crsEnum = EnumProperty(name='Results', description='Select the desired CRS', items=updEnum, update=fill)

	search = BoolProperty(name='Search', description='Search for coordinate system into EPSG database', default=False)

	save = BoolProperty(name='Save to addon preferences',  description='Save Blender user settings after the addition', default=False)

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
		prefs = context.user_preferences.addons[PKG].preferences
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


class PREDEF_CRS_RMV(Operator):

	bl_idname = "bgis.rmv_predef_crs"
	bl_description = 'Remove predefinate CRS'
	bl_label = "Remove"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.user_preferences.addons[PKG].preferences
		key = prefs.predefCrs
		if key != '':
			data = json.loads(prefs.predefCrsJson)
			del data[key]
			prefs.predefCrsJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}

class PREDEF_CRS_RESET(Operator):

	bl_idname = "bgis.reset_predef_crs"
	bl_description = 'Reset predefinate CRS'
	bl_label = "Reset"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.user_preferences.addons[PKG].preferences
		prefs.predefCrsJson = json.dumps(PREDEF_CRS)
		context.area.tag_redraw()
		return {'FINISHED'}

class PREDEF_CRS_EDIT(Operator):

	bl_idname = "bgis.edit_predef_crs"
	bl_description = 'Edit predefinate CRS'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	desc = StringProperty(name = "Name", description = "Choose a convenient name for this CRS")
	crs = StringProperty(name = "EPSG code or Proj4 string",  description = "Specify EPSG code or Proj4 string definition for this CRS")

	def invoke(self, context, event):
		prefs = context.user_preferences.addons[PKG].preferences
		key = prefs.predefCrs
		if key == '':
			return {'FINISHED'}
		data = json.loads(prefs.predefCrsJson)
		self.crs = key
		self.desc = data[key]
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.user_preferences.addons[PKG].preferences
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

class OSM_TAG_ADD(Operator):
	bl_idname = "bgis.add_osm_tag"
	bl_description = 'Add new predefinate OSM filter tag'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	tag = StringProperty(name = "Tag",  description = "Specify the tag (examples : 'building', 'landuse=forest' ...)")

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)#, width=300)

	def execute(self, context):
		prefs = bpy.context.user_preferences.addons[PKG].preferences
		tags = json.loads(prefs.osmTagsJson)
		tags.append(self.tag)
		prefs.osmTagsJson = json.dumps(tags)
		prefs.osmTags = self.tag #update current idx
		context.area.tag_redraw()
		return {'FINISHED'}


class OSM_TAG_RMV(Operator):

	bl_idname = "bgis.rmv_osm_tag"
	bl_description = 'Remove predefinate OSM filter tag'
	bl_label = "Remove"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.user_preferences.addons[PKG].preferences
		tag = prefs.osmTags
		if tag != '':
			tags = json.loads(prefs.osmTagsJson)
			del tags[tags.index(tag)]
			prefs.osmTagsJson = json.dumps(tags)
		context.area.tag_redraw()
		return {'FINISHED'}

class OSM_TAGS_RESET(Operator):

	bl_idname = "bgis.reset_osm_tags"
	bl_description = 'Reset predefinate OSM filter tag'
	bl_label = "Reset"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.user_preferences.addons[PKG].preferences
		prefs.osmTagsJson = json.dumps(OSM_TAGS)
		context.area.tag_redraw()
		return {'FINISHED'}

class OSM_TAG_EDIT(Operator):

	bl_idname = "bgis.edit_osm_tag"
	bl_description = 'Edit predefinate OSM filter tag'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	tag = StringProperty(name = "Tag",  description = "Specify the tag (examples : 'building', 'landuse=forest' ...)")

	def invoke(self, context, event):
		prefs = context.user_preferences.addons[PKG].preferences
		self.tag = prefs.osmTags
		if self.tag == '':
			return {'FINISHED'}
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.user_preferences.addons[PKG].preferences
		tag = prefs.osmTags
		tags = json.loads(prefs.osmTagsJson)
		del tags[tags.index(tag)]
		tags.append(self.tag)
		prefs.osmTagsJson = json.dumps(tags)
		prefs.osmTags = self.tag #update current idx
		context.area.tag_redraw()
		return {'FINISHED'}

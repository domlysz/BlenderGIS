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


import json
import bpy
import addon_utils
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty

from .geoscn import GeoScene, SK
from .proj import reprojPt, EPSGIO, search_EPSGio

################
# store crs preset as json string into addon preferences
#default predef crs json

PREDEF_CRS = {
	'EPSG:4326' : 'WGS84 latlon',
	'EPSG:3857' : 'Web Mercator',
}



class PredefCRS():

	'''Collection of methods (callable at class level) to deal with predefinates CRS dictionnary'''

	@staticmethod
	def getData():
		'''Load the json string'''
		prefs = bpy.context.user_preferences.addons[__package__].preferences
		return json.loads(prefs.predefCrsJson)

	@staticmethod
	def getSelected():
		'''Return the current crs selected in the enum stored in addon preferences'''
		prefs = bpy.context.user_preferences.addons[__package__].preferences
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


################

class GEOSCENE_PREFS(AddonPreferences):

	bl_idname = __package__
	#bl_idname = __name__

	def listPredefCRS(self, context):
		return PredefCRS.getEnumItems()

	#json string
	predefCrsJson = StringProperty(default=json.dumps(PREDEF_CRS))

	predefCrs = EnumProperty(
		name = "Predefinate CRS",
		description = "Choose predefinite Coordinate Reference System",
		items = listPredefCRS
		)

	#hidden props used as display options in georef manager panel
	displayOriginGeo = BoolProperty(name='Geo', description='Display longitude and latitude of scene origin')
	displayOriginPrj = BoolProperty(name='Proj', description='Display coordinates of scene origin in CRS space')
	toogleCrsEdit = BoolProperty(name='Switch scene CRS', description='Enable scene CRS selection', default=False)

	def draw(self, context):
		layout = self.layout
		row = layout.row().split(percentage=0.5)
		row.prop(self, "predefCrs")
		row.operator("geoscene.add_predef_crs", icon='ZOOMIN')
		row.operator("geoscene.edit_predef_crs", icon='SCRIPTWIN')
		row.operator("geoscene.rmv_predef_crs", icon='ZOOMOUT')
		row.operator("geoscene.reset_predef_crs", icon='PLAY_REVERSE')


class GEOSCENE_PREFS_SHOW(Operator):

	bl_idname = "geoscene.show_pref"
	bl_description = 'Display geoscene addon preferences'
	bl_label = "Preferences"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		addonName = __package__
		addon_utils.modules_refresh()
		bpy.context.user_preferences.active_section = 'ADDONS'
		bpy.data.window_managers["WinMan"].addon_search = addonName
		#bpy.ops.wm.addon_expand(module=addonName)
		mod = addon_utils.addons_fake_modules.get(addonName)
		mod.bl_info['show_expanded'] = True
		bpy.ops.screen.userpref_show('INVOKE_DEFAULT')
		return {'FINISHED'}


class PREDEF_CRS_ADD(Operator):
	bl_idname = "geoscene.add_predef_crs"
	bl_description = 'Add predefinate CRS'
	bl_label = "Add"
	bl_options = {'INTERNAL'}

	crs = StringProperty(name = "Definition",  description = "Specify EPSG code or Proj4 string definition for this CRS")
	desc = StringProperty(name = "Description", description = "Choose a convenient name for this CRS")

	def check(self, context):
		return True

	def search(self, context):
		if not EPSGIO:
			self.report({'ERROR'}, "Cannot request epsg.io website")
		else:
			results = search_EPSGio(self.query)
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
		prefs = context.user_preferences.addons[ __package__].preferences
		#append the new crs def to json string
		data = json.loads(prefs.predefCrsJson)
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

	bl_idname = "geoscene.rmv_predef_crs"
	bl_description = 'Remove predefinate CRS'
	bl_label = "Remove"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.user_preferences.addons[__package__].preferences
		key = prefs.predefCrs
		if key != '':
			data = json.loads(prefs.predefCrsJson)
			del data[key]
			prefs.predefCrsJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}

class PREDEF_CRS_RESET(Operator):

	bl_idname = "geoscene.reset_predef_crs"
	bl_description = 'Reset predefinate CRS'
	bl_label = "Reset"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		prefs = context.user_preferences.addons[__package__].preferences
		prefs.predefCrsJson = json.dumps(PREDEF_CRS)
		context.area.tag_redraw()
		return {'FINISHED'}

class PREDEF_CRS_EDIT(Operator):

	bl_idname = "geoscene.edit_predef_crs"
	bl_description = 'Edit predefinate CRS'
	bl_label = "Edit"
	bl_options = {'INTERNAL'}

	crs = StringProperty(name = "EPSG code or Proj4 string",  description = "Specify EPSG code or Proj4 string definition for this CRS")
	desc = StringProperty(name = "Description", description = "Choose a convenient name for this CRS")

	def invoke(self, context, event):
		prefs = context.user_preferences.addons[__package__].preferences
		key = prefs.predefCrs
		if key == '':
			return {'FINISHED'}
		data = json.loads(prefs.predefCrsJson)
		self.crs = key
		self.desc = data[key]
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		prefs = context.user_preferences.addons[__package__].preferences
		data = json.loads(prefs.predefCrsJson)
		data[self.crs] = self.desc
		prefs.predefCrsJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}




###############


class GEOSCENE_SET_CRS(Operator):
	'''
	use the enum of predefinates crs defined in addon prefs
	to select and switch scene crs definition
	'''

	bl_idname = "geoscene.set_crs"
	bl_description = 'Switch scene crs'
	bl_label = "Switch"
	bl_options = {'INTERNAL', 'UNDO'}

	"""
	#to avoid conflict, make a distinct predef crs enum
	#instead of reuse the one defined in addon pref

	def listPredefCRS(self, context):
		return PredefCRS.getEnumItems()

	crsEnum = EnumProperty(
		name = "Predefinate CRS",
		description = "Choose predefinite Coordinate Reference System",
		items = listPredefCRS
		)
	"""

	def draw(self,context):
		prefs = context.user_preferences.addons[__package__].preferences
		layout = self.layout
		row = layout.row(align=True)
		#row.prop(self, "crsEnum", text='')
		row.prop(prefs, "predefCrs", text='')
		#row.operator("geoscene.show_pref", text='', icon='PREFERENCES')
		row.operator("geoscene.add_predef_crs", text='', icon='ZOOMIN')

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self, width=200)

	def execute(self, context):
		geoscn = GeoScene()
		prefs = context.user_preferences.addons[__package__].preferences
		try:
			#geoscn.crs = self.crsEnum
			geoscn.crs = prefs.predefCrs
		except Exception as err:
			self.report({'ERROR'}, 'Cannot update crs. '+str(err))
		#
		context.area.tag_redraw() #does not work if context is a popup...
		prefs.toogleCrsEdit = False
		return {'FINISHED'}


class GEOSCENE_UPD_ORG_GEO(Operator):

	bl_idname = "geoscene.upd_org_geo"
	bl_description = 'Update scene origin lat long'
	bl_label = "Update geo"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene()
		if geoscn.hasOriginPrj and geoscn.hasCRS:
			try:
				geoscn.lon, geoscn.lat = reprojPt(geoscn.crs, 4326, geoscn.crsx, geoscn.crsy)
			except Exception as err:
				self.report({'ERROR'}, str(err))
		else:
			self.report({'ERROR'}, 'No enough infos')
		return {'FINISHED'}


class GEOSCENE_UPD_ORG_PRJ(Operator):

	bl_idname = "geoscene.upd_org_prj"
	bl_description = 'Update scene origin in crs space'
	bl_label = "Update prj"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene()
		if geoscn.hasOriginGeo and geoscn.hasCRS:
			try:
				geoscn.crsx, geoscn.crsy = reprojPt(4326, geoscn.crs, geoscn.lon, geoscn.lat)
			except Exception as err:
				self.report({'ERROR'}, str(err))
		else:
			self.report({'ERROR'}, 'No enough infos')
		return {'FINISHED'}


class GEOSCENE_CLEAR_ORG(Operator):

	bl_idname = "geoscene.clear_org"
	bl_description = 'Clear scene origin coordinates'
	bl_label = "Clear origin"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene()
		geoscn.delOrigin()
		return {'FINISHED'}

class GEOSCENE_CLEAR_GEOREF(Operator):

	bl_idname = "geoscene.clear_georef"
	bl_description = 'Clear all georef infos'
	bl_label = "Clear georef"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene()
		geoscn.delOrigin()
		del geoscn.crs
		return {'FINISHED'}

################

class GEOSCENE_PANEL(Panel):
	bl_category = "GIS"
	bl_label = "Geoscene"
	bl_space_type = "VIEW_3D"
	bl_context = "objectmode"
	bl_region_type = "TOOLS"#"UI"


	def draw(self, context):
		layout = self.layout
		scn = context.scene
		geoscn = GeoScene()

		prefs = context.user_preferences.addons[__package__].preferences
		layout.operator("geoscene.show_pref")#, icon='PREFERENCES')

		georefManagerLayout(self, context)



def georefManagerLayout(self, context):
	'''Use this method to extend a panel with georef managment tools'''
	layout = self.layout
	scn = context.scene
	geoscn = GeoScene()

	geoscnPrefs = context.user_preferences.addons['geoscene'].preferences

	if geoscn.isBroken:
		layout.alert = True

	row = layout.row(align=True)
	row.label('Scene georeferencing :')
	if geoscn.hasCRS:
		row.operator("geoscene.clear_georef", text='', icon='CANCEL')

	#CRS
	row = layout.row(align=True)
	#row.alignment = 'LEFT'
	#row.label(icon='EMPTY_DATA')
	split = row.split(percentage=0.25)
	if geoscn.hasCRS:
		split.label(icon='PROP_ON', text='CRS:')
	elif not geoscn.hasCRS and (geoscn.hasOriginGeo or geoscn.hasOriginPrj):
		split.label(icon='ERROR', text='CRS:')
	else:
		split.label(icon='PROP_OFF', text='CRS:')

	if geoscn.hasCRS:
		##col = split.column(align=True)
		##col.enabled = False
		##col.prop(scn, '["'+SK.CRS+'"]', text='')
		crs = scn[SK.CRS]
		name = PredefCRS.getName(crs)
		if name is not None:
			split.label(name)
		else:
			split.label(crs)
	else:
		split.label("Not set")

	#row.operator("geoscene.set_crs", text='', icon='SCRIPTWIN')
	row.prop(geoscnPrefs, 'toogleCrsEdit', text='', icon='SCRIPTWIN', toggle=True)
	if geoscnPrefs.toogleCrsEdit:
		row = layout.row(align=True)
		row.prop(geoscnPrefs, 'predefCrs', text='Switch to')
		row.operator("geoscene.add_predef_crs", text='', icon='ZOOMIN')
		col = row.column(align=True)
		col.operator_context = 'EXEC_DEFAULT' #do not display props popup dialog
		col.operator("geoscene.set_crs", text='', icon='FILE_TICK')

	#Origin
	row = layout.row(align=True)
	#row.alignment = 'LEFT'
	#row.label(icon='CURSOR')
	split = row.split(percentage=0.25, align=True)
	if not geoscn.hasOriginGeo and not geoscn.hasOriginPrj:
		split.label(icon='PROP_OFF', text="Origin:")
	elif not geoscn.hasOriginGeo and geoscn.hasOriginPrj:
		split.label(icon='PROP_CON', text="Origin:")
	elif geoscn.hasOriginGeo and geoscn.hasOriginPrj:
		split.label(icon='PROP_ON', text="Origin:")
	elif geoscn.hasOriginGeo and not geoscn.hasOriginPrj:
		split.label(icon='ERROR', text="Origin:")

	col = split.column(align=True)
	if not geoscn.hasOriginGeo:
		col.enabled = False
	col.prop(geoscnPrefs, 'displayOriginGeo', toggle=True)

	col = split.column(align=True)
	if not geoscn.hasOriginPrj:
		col.enabled = False
	col.prop(geoscnPrefs, 'displayOriginPrj', toggle=True)

	if geoscn.hasOriginGeo or geoscn.hasOriginPrj:
		if geoscn.hasCRS and not geoscn.hasOriginPrj:
			row.operator("geoscene.upd_org_prj", text="", icon='CONSTRAINT')
		if geoscn.hasCRS and not geoscn.hasOriginGeo:
			row.operator("geoscene.upd_org_geo", text="", icon='CONSTRAINT')
		row.operator("geoscene.clear_org", text="", icon='ZOOMOUT')

	if geoscn.hasOriginGeo and geoscnPrefs.displayOriginGeo:
		row = layout.row()
		row.enabled = False
		row.prop(scn, '["'+SK.LON+'"]', text='Lon')
		row.prop(scn, '["'+SK.LAT+'"]', text='Lat')

	if  geoscn.hasOriginPrj and geoscnPrefs.displayOriginPrj:
		row = layout.row()
		row.enabled = False
		row.prop(scn, '["'+SK.CRSX+'"]', text='X')
		row.prop(scn, '["'+SK.CRSY+'"]', text='Y')

	if geoscn.hasScale:
		row = layout.row()
		row.label('Map scale:')
		col = row.column()
		col.enabled = False
		col.prop(scn, '["'+SK.SCALE+'"]', text='')

	#if geoscn.hasZoom:
	#	layout.prop(scn, '["'+SK.ZOOM+'"]', text='Zoom level', slider=True)

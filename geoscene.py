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
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty
from bpy.types import Operator, Panel

from .prefs import PredefCRS
from .utils.proj import reprojPt, SRS


PKG = __package__


class SK():
	"""Alias to Scene Keys used to store georef infos"""
	# latitude and longitude of scene origin in decimal degrees
	LAT = "latitude"
	LON = "longitude"
	#Spatial Reference System Identifier
	# can be directly an EPSG code or formated following the template "AUTH:4326"
	# or a proj4 string definition of Coordinate Reference System (CRS)
	CRS = "SRID"
	# Coordinates of scene origin in CRS space
	CRSX = "crs x"
	CRSY = "crs y"
	# General scale denominator of the map (1:x)
	SCALE = "scale"
	# Current zoom level in the Tile Matrix Set
	ZOOM = "zoom"



class GeoScene():

	def __init__(self, scn=None):
		if scn is None:
			self.scn = bpy.context.scene
		else:
			self.scn = scn
		self.SK = SK()

	@property
	def _rna_ui(self):
		# get or init the dictionary containing IDprops settings
		rna_ui = self.scn.get('_RNA_UI', None)
		if rna_ui is None:
			self.scn['_RNA_UI'] = {}
			rna_ui = self.scn['_RNA_UI']
		return rna_ui

	@property
	def hasCRS(self):
		return SK.CRS in self.scn

	@property
	def hasValidCRS(self):
		if not self.hasCRS:
			return False
		return SRS.validate(self.crs)

	@property
	def isGeoref(self):
		'''A scene is georef if at least a valid CRS is defined and
		the coordinates of scene's origin in this CRS space is set'''
		return self.hasValidCRS and self.hasOriginPrj

	@property
	def isFullyGeoref(self):
		return self.hasValidCRS and self.hasOriginPrj and self.hasOriginGeo

	@property
	def isPartiallyGeoref(self):
		return self.hasCRS or self.hasOriginPrj or self.hasOriginGeo

	@property
	def isBroken(self):
		"""partial georef infos make the geoscene unusuable and broken"""
		return (self.hasCRS and not self.hasValidCRS) \
		or (not self.hasCRS and (self.hasOriginPrj or self.hasOriginGeo)) \
		or (self.hasCRS and self.hasOriginGeo and not self.hasOriginPrj)

	@property
	def hasOriginGeo(self):
		return SK.LAT in self.scn and SK.LON in self.scn

	@property
	def hasOriginPrj(self):
		return SK.CRSX in self.scn and SK.CRSY in self.scn

	def setOriginGeo(self, lon, lat):
		self.lon, self.lat = lon, lat
		try:
			self.crsx, self.crsy = reprojPt(4326, self.crs, lon, lat)
		except Exception as e:
			if self.hasOriginPrj:
				self.delOriginPrj()
				print('Warning, origin proj has been deleted because the property could not be updated. ' + str(e))

	def setOriginPrj(self, x, y):
		self.crsx, self.crsy = x, y
		try:
			self.lon, self.lat = reprojPt(self.crs, 4326, x, y)
		except Exception as e:
			if self.hasOriginGeo:
				self.delOriginGeo()
				print('Warning, origin geo has been deleted because the property could not be updated. ' + str(e))

	def updOriginPrj(self, x, y, updObjLoc=True, updBkgImg=True):
		'''Update/move scene origin passing absolute coordinates'''
		if not self.hasOriginPrj:
			raise Exception("Cannot update an unset origin.")
		dx = x - self.crsx
		dy = y - self.crsy
		self.setOriginPrj(x, y)
		if updObjLoc:
			self._moveObjLoc(dx, dy)
		if updBkgImg:
			self._moveBkgImg(dx, dy)

	def updOriginGeo(self, lon, lat, updObjLoc=True, updBkgImg=True):
		if not self.isGeoref:
			raise Exception("Cannot update geo origin of an ungeoref scene.")
		x, y = reprojPt(4326, self.crs, lon, lat)
		self.updOriginPrj(x, y)
		dx = x - self.crsx
		dy = y - self.crsy
		self.crsx, self.crsy = x, y
		self.lon, self.lat = lon ,lat
		if updObjLoc:
			self._moveObjLoc(dx, dy)
		if updBkgImg:
			self._moveBkgImg(dx, dy)

	def moveOriginGeo(self, dx, dy, updObjLoc=True, updBkgImg=True):
		if not self.hasOriginGeo:
			raise Exception("Cannot move an unset origin.")
		x = self.lon + dx
		y = self.lat + dy
		self.updOriginGeo(x, y, updObjLoc=updObjLoc, updBkgImg=updBkgImg)


	def moveOriginPrj(self, dx, dy, useScale=True, updObjLoc=True, updBkgImg=True):
		'''Move scene origin passing relative deltas'''
		if not self.hasOriginPrj:
			raise Exception("Cannot move an unset origin.")

		if useScale:
			self.setOriginPrj(self.crsx + dx * self.scale, self.crsy + dy * self.scale)
		else:
			self.setOriginPrj(self.crsx + dx, self.crsy + dy)

		if updObjLoc:
			self._moveObjLoc(dx, dy)
		if updBkgImg:
			self._moveBkgImg(dx, dy)


	def _moveObjLoc(self, dx, dy):
		topParents = [obj for obj in self.scn.objects if not obj.parent]
		for obj in topParents:
			obj.location.x -= dx
			obj.location.y -= dy

	def _moveBkgImg(self, dx, dy):
		space = bpy.context.area.spaces.active
		if space.type == 'VIEW_3D':
			for bkg in space.background_images:
				img = bkg.image
				if img is not None and bkg.view_axis == 'TOP':
					try:
						#this statement can fails if source image is not readable (e.g. deleted file)
						ratio = img.size[0] / img.size[1]
					except:
						pass
					else:
						bkg.offset_x -= dx
						bkg.offset_y -= dy * ratio

	def getOriginGeo(self):
		return self.lon, self.lat

	def getOriginPrj(self):
		return self.crsx, self.crsy

	def delOriginGeo(self):
		del self.lat
		del self.lon

	def delOriginPrj(self):
		del self.crsx
		del self.crsy

	def delOrigin(self):
		self.delOriginGeo()
		self.delOriginPrj()

	@property
	def crs(self):
		return self.scn.get(SK.CRS, None) #always string
	@crs.setter
	def crs(self, v):
		#Make sure input value is a valid crs string representation
		crs = str(SRS(v)) #will raise an error if the crs is not valid
		#Reproj existing origin. New CRS will not be set if updating existing origin is not possible
		# try first to reproj from origin geo because self.crs can be empty or broken
		if self.hasOriginGeo:
			self.crsx, self.crsy = reprojPt(4326, crs, self.lon, self.lat)
		elif self.hasOriginPrj and self.hasCRS:
			if self.hasValidCRS:
				# will raise an error is current crs is empty or invalid
				self.crsx, self.crsy = reprojPt(self.crs, crs, self.crsx, self.crsy)
			else:
				raise Exception("Scene origin coordinates cannot be updated because current CRS is invalid.")
		#Set ID prop
		if SK.CRS not in self.scn:
			self._rna_ui[SK.CRS] = {"description": "Map Coordinate Reference System", "default": ''}
		self.scn[SK.CRS] = crs
	@crs.deleter
	def crs(self):
		if SK.CRS in self.scn:
			del self.scn[SK.CRS]


	@property
	def lat(self):
		return self.scn.get(SK.LAT, None)
	@lat.setter
	def lat(self, v):
		if SK.LAT not in self.scn:
			self._rna_ui[SK.LAT] = {"description": "Scene origin latitude", "default": 0.0, "min":-90.0, "max":90.0}
		if -90 <= v <= 90:
			self.scn[SK.LAT] = v
		else:
			raise ValueError('Wrong latitude value '+str(v))
	@lat.deleter
	def lat(self):
		if SK.LAT in self.scn:
			del self.scn[SK.LAT]

	@property
	def lon(self):
		return self.scn.get(SK.LON, None)
	@lon.setter
	def lon(self, v):
		if SK.LON not in self.scn:
			self._rna_ui[SK.LON] = {"description": "Scene origin longitude", "default": 0.0, "min":-180.0, "max":180.0}
		if -180 <= v <= 180:
			self.scn[SK.LON] = v
		else:
			raise ValueError('Wrong longitude value '+str(v))
	@lon.deleter
	def lon(self):
		if SK.LON in self.scn:
			del self.scn[SK.LON]

	@property
	def crsx(self):
		return self.scn.get(SK.CRSX, None)
	@crsx.setter
	def crsx(self, v):
		if SK.CRSX not in self.scn:
			self._rna_ui[SK.CRSX] = {"description": "Scene x origin in CRS space", "default": 0.0}
		if isinstance(v, (int, float)):
			self.scn[SK.CRSX] = v
		else:
			raise ValueError('Wrong x origin value '+str(v))
	@crsx.deleter
	def crsx(self):
		if SK.CRSX in self.scn:
			del self.scn[SK.CRSX]

	@property
	def crsy(self):
		return self.scn.get(SK.CRSY, None)
	@crsy.setter
	def crsy(self, v):
		if SK.CRSY not in self.scn:
			self._rna_ui[SK.CRSY] = {"description": "Scene y origin in CRS space", "default": 0.0}
		if isinstance(v, (int, float)):
			self.scn[SK.CRSY] = v
		else:
			raise ValueError('Wrong y origin value '+str(v))
	@crsy.deleter
	def crsy(self):
		if SK.CRSY in self.scn:
			del self.scn[SK.CRSY]

	@property
	def scale(self):
		return self.scn.get(SK.SCALE, 1)
	@scale.setter
	def scale(self, v):
		if SK.SCALE not in self.scn:
			self._rna_ui[SK.SCALE] = {"description": "Map scale denominator", "default": 1, "min": 1}
		self.scn[SK.SCALE] = v
	@scale.deleter
	def scale(self):
		if SK.SCALE in self.scn:
			del self.scn[SK.SCALE]

	@property
	def zoom(self):
		return self.scn.get(SK.ZOOM, None)
	@zoom.setter
	def zoom(self, v):
		if SK.ZOOM not in self.scn:
			self._rna_ui[SK.ZOOM] = {"description": "Basemap zoom level", "default": 1, "min": 0, "max":25}
		self.scn[SK.ZOOM] = v
	@zoom.deleter
	def zoom(self):
		if SK.ZOOM in self.scn:
			del self.scn[SK.ZOOM]

	@property
	def hasScale(self):
		#return self.scale is not None
		return SK.SCALE in self.scn

	@property
	def hasZoom(self):
		return self.zoom is not None


################


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
		prefs = context.user_preferences.addons[PKG].preferences
		layout = self.layout
		row = layout.row(align=True)
		#row.prop(self, "crsEnum", text='')
		row.prop(prefs, "predefCrs", text='')
		#row.operator("geoscene.show_pref", text='', icon='PREFERENCES')
		row.operator("bgis.add_predef_crs", text='', icon='ZOOMIN')

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self, width=200)

	def execute(self, context):
		geoscn = GeoScene(context.scene)
		prefs = context.user_preferences.addons[PKG].preferences
		try:
			geoscn.crs = prefs.predefCrs
		except Exception as err:
			self.report({'ERROR'}, 'Cannot update crs. '+str(err))
		#
		context.area.tag_redraw() #does not work if context is a popup...
		bpy.context.window_manager.toogleCrsEdit = False
		return {'FINISHED'}

class GEOSCENE_INIT_ORG(Operator):

	bl_idname = "geoscene.init_org"
	bl_description = 'Init scene origin custom props at location 0,0'
	bl_label = "Init origin"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene(context.scene)
		if geoscn.hasOriginGeo or geoscn.hasOriginPrj:
			print('Warning, cannot init scene origin because it already exist')
			return {'FINISHED'}
		else:
			geoscn.lon, geoscn.lat = 0, 0
			geoscn.crsx, geoscn.crsy = 0, 0
		return {'FINISHED'}

class GEOSCENE_EDIT_ORG_GEO(Operator):

	bl_idname = "geoscene.edit_org_geo"
	bl_description = 'Edit scene origin longitude/latitude'
	bl_label = "Edit origin geo"
	bl_options = {'INTERNAL', 'UNDO'}

	lon = FloatProperty()
	lat = FloatProperty()

	def invoke(self, context, event):
		geoscn = GeoScene(context.scene)
		if geoscn.isBroken:
			self.report({'ERROR'}, "Scene georef is broken")
			return {'CANCELLED'}
		self.lon, self.lat = geoscn.getOriginGeo()
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		geoscn = GeoScene(context.scene)
		if geoscn.hasOriginGeo:
			geoscn.updOriginGeo(self.lon, self.lat)
		else:
			geoscn.setOriginGeo(self.lon, self.lat)
		return {'FINISHED'}

class GEOSCENE_EDIT_ORG_PRJ(Operator):

	bl_idname = "geoscene.edit_org_prj"
	bl_description = 'Edit scene origin in projected system'
	bl_label = "Edit origin proj"
	bl_options = {'INTERNAL', 'UNDO'}

	x = FloatProperty()
	y = FloatProperty()

	def invoke(self, context, event):
		geoscn = GeoScene(context.scene)
		if geoscn.isBroken:
			self.report({'ERROR'}, "Scene georef is broken")
			return {'CANCELLED'}
		self.x, self.y = geoscn.getOriginPrj()
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		geoscn = GeoScene(context.scene)
		if geoscn.hasOriginPrj:
			geoscn.updOriginPrj(self.x, self.y)
		else:
			geoscn.setOriginPrj(self.x, self.y)
		return {'FINISHED'}

class GEOSCENE_LINK_ORG_GEO(Operator):

	bl_idname = "geoscene.link_org_geo"
	bl_description = 'Link scene origin lat long'
	bl_label = "Link geo"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene(context.scene)
		if geoscn.hasOriginPrj and geoscn.hasCRS:
			try:
				geoscn.lon, geoscn.lat = reprojPt(geoscn.crs, 4326, geoscn.crsx, geoscn.crsy)
			except Exception as err:
				self.report({'ERROR'}, str(err))
		else:
			self.report({'ERROR'}, 'No enough infos')
		return {'FINISHED'}


class GEOSCENE_LINK_ORG_PRJ(Operator):

	bl_idname = "geoscene.link_org_prj"
	bl_description = 'Link scene origin in crs space'
	bl_label = "Link prj"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene(context.scene)
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
		geoscn = GeoScene(context.scene)
		geoscn.delOrigin()
		return {'FINISHED'}

class GEOSCENE_CLEAR_GEOREF(Operator):

	bl_idname = "geoscene.clear_georef"
	bl_description = 'Clear all georef infos'
	bl_label = "Clear georef"
	bl_options = {'INTERNAL', 'UNDO'}

	def execute(self, context):
		geoscn = GeoScene(context.scene)
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
		geoscn = GeoScene(scn)

		#layout.operator("bgis.pref_show", icon='PREFERENCES')

		georefManagerLayout(self, context)


#hidden props used as display options in georef manager panel
bpy.types.WindowManager.displayOriginGeo = BoolProperty(name='Geo', description='Display longitude and latitude of scene origin')
bpy.types.WindowManager.displayOriginPrj = BoolProperty(name='Proj', description='Display coordinates of scene origin in CRS space')
bpy.types.WindowManager.toogleCrsEdit = BoolProperty(name='Switch scene CRS', description='Enable scene CRS selection', default=False)

def getLon(self):
	geoscn = GeoScene()
	return geoscn.lon

def getLat(self):
	geoscn = GeoScene()
	return geoscn.lat

def setLon(self, lon):
	geoscn = GeoScene()
	if geoscn.hasOriginGeo:
		geoscn.updOriginGeo(lon, geoscn.lat)
	else:
		geoscn.setOriginGeo(lon, geoscn.lat)

def setLat(self, lat):
	geoscn = GeoScene()
	if geoscn.hasOriginGeo:
		geoscn.updOriginGeo(geoscn.lon, lat)
	else:
		geoscn.setOriginGeo(geoscn.lon, lat)

bpy.types.WindowManager.lon = FloatProperty(get=getLon, set=setLon)
bpy.types.WindowManager.lat = FloatProperty(get=getLat, set=setLat)

def getCrsx(self):
	geoscn = GeoScene()
	return geoscn.crsx

def getCrsy(self):
	geoscn = GeoScene()
	return geoscn.crsy

def setCrsx(self, x):
	geoscn = GeoScene()
	if geoscn.hasOriginPrj:
		geoscn.updOriginPrj(x, geoscn.crsy)
	else:
		geoscn.setOriginPrj(x, geoscn.crsy)

def setCrsy(self, y):
	geoscn = GeoScene()
	if geoscn.hasOriginPrj:
		geoscn.updOriginPrj(geoscn.crsx, y)
	else:
		geoscn.setOriginPrj(geoscn.crsx, y)

bpy.types.WindowManager.crsx = FloatProperty(get=getCrsx, set=setCrsx)
bpy.types.WindowManager.crsy = FloatProperty(get=getCrsy, set=setCrsy)


def georefManagerLayout(self, context):
	'''Use this method to extend a panel with georef managment tools'''
	layout = self.layout
	scn = context.scene
	wm = bpy.context.window_manager
	geoscn = GeoScene(scn)

	prefs = context.user_preferences.addons[PKG].preferences

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
	row.prop(wm, 'toogleCrsEdit', text='', icon='SCRIPTWIN', toggle=True)
	if wm.toogleCrsEdit:
		row = layout.row(align=True)
		row.prop(prefs, 'predefCrs', text='Switch to')
		row.operator("bgis.add_predef_crs", text='', icon='ZOOMIN')
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
	col.prop(wm, 'displayOriginGeo', toggle=True)

	col = split.column(align=True)
	if not geoscn.hasOriginPrj:
		col.enabled = False
	col.prop(wm, 'displayOriginPrj', toggle=True)

	if geoscn.hasOriginGeo or geoscn.hasOriginPrj:
		if geoscn.hasCRS and not geoscn.hasOriginPrj:
			row.operator("geoscene.link_org_prj", text="", icon='CONSTRAINT')
		if geoscn.hasCRS and not geoscn.hasOriginGeo:
			row.operator("geoscene.link_org_geo", text="", icon='CONSTRAINT')
		row.operator("geoscene.clear_org", text="", icon='ZOOMOUT')

	if not geoscn.hasOriginGeo and not geoscn.hasOriginPrj:
		row.operator("geoscene.init_org", text="", icon='ZOOMIN')

	if geoscn.hasOriginGeo and wm.displayOriginGeo:
		row = layout.row()
		row.prop(wm, 'lon', text='Lon')
		row.prop(wm, 'lat', text='Lat')
		'''
		row.enabled = False
		row.prop(scn, '["'+SK.LON+'"]', text='Lon')
		row.prop(scn, '["'+SK.LAT+'"]', text='Lat')
		'''

	if  geoscn.hasOriginPrj and wm.displayOriginPrj:
		row = layout.row()
		row.prop(wm, 'crsx', text='X')
		row.prop(wm, 'crsy', text='Y')
		'''
		row.enabled = False
		row.prop(scn, '["'+SK.CRSX+'"]', text='X')
		row.prop(scn, '["'+SK.CRSY+'"]', text='Y')
		'''

	if geoscn.hasScale:
		row = layout.row()
		row.label('Map scale:')
		col = row.column()
		col.enabled = False
		col.prop(scn, '["'+SK.SCALE+'"]', text='')

	#if geoscn.hasZoom:
	#	layout.prop(scn, '["'+SK.ZOOM+'"]', text='Zoom level', slider=True)

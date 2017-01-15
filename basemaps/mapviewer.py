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

#built-in imports
import math
import os
import threading

#bpy imports
import bpy
from mathutils import Vector
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_vector_3d
import addon_utils
import blf, bgl

#addon import
from .servicesDefs import GRIDS, SOURCES
from .mapservice import MapService

#bgis imports
from ..checkdeps import HAS_GDAL, HAS_PIL, HAS_IMGIO
from ..geoscene import GeoScene, SK, georefManagerLayout
from ..prefs import PredefCRS
from ..utils.proj import reprojPt, reprojBbox, dd2meters, meters2dd
from ..utils.geom import BBOX
#for export to mesh tool
from ..utils.bpu import adjust3Dview, showTextures
from ..io_georaster.op_import_georaster import rasterExtentToMesh, placeObj, geoRastUVmap, addTexture

#OSM Nominatim API module
#https://github.com/damianbraun/nominatim
from ..osm.nominatim import Nominatim


PKG, SUBPKG = __package__.split('.') #blendergis.basemaps

####################

class BaseMap(GeoScene):

	"""Handle a map as background image in Blender"""

	def __init__(self, context, srckey, laykey, grdkey=None):

		#Get context
		self.context = context
		self.scn = context.scene
		GeoScene.__init__(self, self.scn)
		self.area = context.area
		self.area3d = [r for r in self.area.regions if r.type == 'WINDOW'][0]
		self.view3d = self.area.spaces.active
		self.reg3d = self.view3d.region_3d

		#Get cache destination folder in addon preferences
		prefs = context.user_preferences.addons[PKG].preferences
		cacheFolder = prefs.cacheFolder

		#Get resampling algo preference and set the constant
		MapService.RESAMP_ALG = prefs.resamplAlg

		#Init MapService class
		self.srv = MapService(srckey, cacheFolder)

		#Set destination tile matrix
		if grdkey is None:
			grdkey = self.srv.srcGridKey
		if grdkey == self.srv.srcGridKey:
			self.tm = self.srv.srcTms
		else:
			#Define destination grid in map service
			self.srv.setDstGrid(grdkey)
			self.tm = self.srv.dstTms

		#Init some geoscene props if needed
		if not self.hasCRS:
			self.crs = self.tm.CRS
		if not self.hasOriginPrj:
			self.setOriginPrj(0, 0)
		if not self.hasScale:
			self.scale = 1
		if not self.hasZoom:
			self.zoom = 0

		#Set path to tiles mosaic used as background image in Blender
		#We need a format that support transparency so jpg is exclude
		#Writing to tif is generally faster than writing to png
		if bpy.data.is_saved:
			folder = os.path.dirname(bpy.data.filepath) + os.sep
			##folder = bpy.path.abspath("//"))
		else:
			##folder = bpy.context.user_preferences.filepaths.temporary_directory
			#Blender crease a sub-directory within the temp directory, for each session, which is cleared on exit
			folder = bpy.app.tempdir
		self.imgPath = folder + srckey + '_' + laykey + '_' + grdkey + ".tif"

		#Get layer def obj
		self.layer = self.srv.layers[laykey]

		#map keys
		self.srckey = srckey
		self.laykey = laykey
		self.grdkey = grdkey

		#Thread attributes
		self.thread = None
		#Background image attributes
		self.img = None #bpy image
		self.bkg = None #bpy background
		self.viewDstZ = None #view 3d z distance
		#Store previous request
		#TODO


	def get(self):
		'''Launch run() function in a new thread'''
		self.stop()
		self.srv.running = True
		self.thread = threading.Thread(target=self.run)
		self.thread.start()

	def stop(self):
		'''Stop actual thread'''
		if self.srv.running:
			self.srv.running = False
			self.thread.join()

	def run(self):
		"""thread method"""
		self.mosaic = self.request()
		if self.srv.running and self.mosaic is not None:
			#save image
			self.mosaic.save(self.imgPath)
		if self.srv.running:
			#Place background image
			self.place()

	def view3dToProj(self, dx, dy):
		'''Convert view3d coords to crs coords'''
		x = self.crsx + dx * self.scale
		y = self.crsy + dy * self.scale
		return x, y

	def moveOrigin(self, dx, dy, useScale=True, updObjLoc=True, updBkgImg=True):
		'''Move scene origin and update props'''
		self.moveOriginPrj(dx, dy, useScale, updObjLoc, updBkgImg) #geoscene function

	def request(self):
		'''Request map service to build a mosaic of required tiles to cover view3d area'''
		#Get area dimension
		#w, h = self.area.width, self.area.height
		w, h = self.area3d.width, self.area3d.height

		#Get area bbox coords in destination tile matrix crs (map origin is bottom lelf)

		#Method 1 : Get bbox coords in scene crs and then reproject the bbox if needed
		res = self.tm.getRes(self.zoom)
		if self.crs == 'EPSG:4326':
			res = meters2dd(res)
		dx, dy, dz = self.reg3d.view_location
		ox = self.crsx + (dx * self.scale)
		oy = self.crsy + (dy * self.scale)
		xmin = ox - w/2 * res * self.scale
		ymax = oy + h/2 * res * self.scale
		xmax = ox + w/2 * res * self.scale
		ymin = oy - h/2 * res * self.scale
		bbox = (xmin, ymin, xmax, ymax)
		#reproj bbox to destination grid crs if scene crs is different
		if self.crs != self.tm.CRS:
			bbox = reprojBbox(self.crs, self.tm.CRS, bbox)

		'''
		#Method 2
		bbox = BBOX.fromTopView(self.context) #ERROR context is None ????
		bbox = bbox.toGeo(geoscn=self)
		if self.crs != self.tm.CRS:
			bbox = reprojBbox(self.crs, self.tm.CRS, bbox)
		'''

		#Stop thread if the request is same as previous
		#TODO

		if self.srv.srcGridKey == self.grdkey:
			toDstGrid = False
		else:
			toDstGrid = True

		mosaic = self.srv.getImage(self.laykey, bbox, self.zoom, toDstGrid, outCRS=self.crs)

		return mosaic


	def place(self):
		'''Set map as background image'''

		#Get or load bpy image
		try:
			self.img = [img for img in bpy.data.images if img.filepath == self.imgPath and len(img.packed_files) == 0][0]
		except:
			self.img = bpy.data.images.load(self.imgPath)

		#Activate view3d background
		self.view3d.show_background_images = True

		#Hide all existing background
		for bkg in self.view3d.background_images:
			if bkg.view_axis == 'TOP':
				bkg.show_background_image = False

		#Get or load background image
		bkgs = [bkg for bkg in self.view3d.background_images if bkg.image is not None]
		try:
			self.bkg = [bkg for bkg in bkgs if bkg.image.filepath == self.imgPath and len(bkg.image.packed_files) == 0][0]
		except:
			self.bkg = self.view3d.background_images.new()
			self.bkg.image = self.img

		#Set some background props
		self.bkg.show_background_image = True
		self.bkg.view_axis = 'TOP'
		self.bkg.opacity = 1

		#Get some image props
		img_ox, img_oy = self.mosaic.origin
		img_w, img_h = self.mosaic.size
		res = self.mosaic.res
		#res = self.tm.getRes(self.zoom)

		#Set background size
		sizex = img_w * res / self.scale
		self.bkg.size = sizex #since blender > 2.74 else = sizex/2

		#Set background offset (image origin does not match scene origin)
		dx = (self.crsx - img_ox) / self.scale
		dy = (self.crsy - img_oy) / self.scale
		self.bkg.offset_x = -dx
		ratio = img_w / img_h
		self.bkg.offset_y = -dy * ratio #https://developer.blender.org/T48034

		#Compute view3d z distance
		#in ortho view, view_distance = max(view3d dst x, view3d dist y) / 2
		dst =  max( [self.area3d.width, self.area3d.height] )
		dst = dst * res / self.scale
		dst /= 2
		self.reg3d.view_distance = dst
		self.viewDstZ = dst

		#Update image drawing
		self.bkg.image.reload()




####################################


def drawInfosText(self, context):
	"""Draw map infos on 3dview"""

	#Get contexts
	scn = context.scene
	area = context.area
	area3d = [reg for reg in area.regions if reg.type == 'WINDOW'][0]
	view3d = area.spaces.active
	reg3d = view3d.region_3d

	#Get area3d dimensions
	w, h = area3d.width, area3d.height
	cx = w/2 #center x

	#Get map props stored in scene
	geoscn = GeoScene(scn)
	zoom = geoscn.zoom
	scale = geoscn.scale

	#Set text police and color
	font_id = 0  # ???
	prefs = context.user_preferences.addons[PKG].preferences
	fontColor = prefs.fontColor
	bgl.glColor4f(*fontColor) #rgba

	#Draw title
	blf.position(font_id, cx-25, 70, 0) #id, x, y, z
	blf.size(font_id, 15, 72) #id, point size, dpi
	blf.draw(font_id, "Map view")

	#Draw other texts
	blf.size(font_id, 12, 72)
	# thread progress and service status
	blf.position(font_id, cx-45, 90, 0)
	blf.draw(font_id, self.progress)
	# zoom and scale values
	blf.position(font_id, cx-50, 50, 0)
	blf.draw(font_id, "Zoom " + str(zoom) + " - Scale 1:" + str(int(scale)))
	# view3d distance
	dst = reg3d.view_distance
	if dst > 1000:
		dst /= 1000
		unit = 'km'
	else:
		unit = 'm'
	blf.position(font_id, cx-50, 30, 0)
	blf.draw(font_id, '3D View distance ' + str(int(dst)) + ' ' + unit)
	# cursor crs coords
	blf.position(font_id, cx-45, 10, 0)
	blf.draw(font_id, str((int(self.posx), int(self.posy))))



def drawZoomBox(self, context):

	bgl.glEnable(bgl.GL_BLEND)
	bgl.glColor4f(0, 0, 0, 0.5)
	bgl.glLineWidth(2)

	if self.zoomBoxMode and not self.zoomBoxDrag:
		# before selection starts draw infinite cross
		bgl.glBegin(bgl.GL_LINES)

		px, py = self.zb_xmax, self.zb_ymax

		bgl.glVertex2i(0, py)
		bgl.glVertex2i(context.area.width, py)

		bgl.glVertex2i(px, 0)
		bgl.glVertex2i(px, context.area.height)

		bgl.glEnd()

	elif self.zoomBoxMode and self.zoomBoxDrag:
		# when selecting draw dashed line box
		bgl.glEnable(bgl.GL_LINE_STIPPLE)
		bgl.glLineStipple(2, 0x3333)
		bgl.glBegin(bgl.GL_LINE_LOOP)

		bgl.glVertex2i(self.zb_xmin, self.zb_ymin)
		bgl.glVertex2i(self.zb_xmin, self.zb_ymax)
		bgl.glVertex2i(self.zb_xmax, self.zb_ymax)
		bgl.glVertex2i(self.zb_xmax, self.zb_ymin)

		bgl.glEnd()

		bgl.glDisable(bgl.GL_LINE_STIPPLE)


	# restore opengl defaults
	bgl.glLineWidth(1)
	bgl.glDisable(bgl.GL_BLEND)
	bgl.glColor4f(0.0, 0.0, 0.0, 1.0)

###############

class MAP_START(bpy.types.Operator):

	bl_idname = "view3d.map_start"
	bl_description = 'Toggle 2d map navigation'
	bl_label = "Basemap"
	bl_options = {'REGISTER'}

	#special function to auto redraw an operator popup called through invoke_props_dialog
	def check(self, context):
		return True

	def listSources(self, context):
		srcItems = []
		for srckey, src in SOURCES.items():
			#put each item in a tuple (key, label, tooltip)
			srcItems.append( (srckey, src['name'], src['description']) )
		return srcItems

	def listGrids(self, context):
		grdItems = []
		src = SOURCES[self.src]
		for gridkey, grd in GRIDS.items():
			#put each item in a tuple (key, label, tooltip)
			if gridkey == src['grid']:
				#insert at first position
				grdItems.insert(0, (gridkey, grd['name']+' (source)', grd['description']) )
			else:
				grdItems.append( (gridkey, grd['name'], grd['description']) )
		return grdItems

	def listLayers(self, context):
		layItems = []
		src = SOURCES[self.src]
		for laykey, lay in src['layers'].items():
			#put each item in a tuple (key, label, tooltip)
			layItems.append( (laykey, lay['name'], lay['description']) )
		return layItems


	src = EnumProperty(
				name = "Map",
				description = "Choose map service source",
				items = listSources
				)

	grd = EnumProperty(
				name = "Grid",
				description = "Choose cache tiles matrix",
				items = listGrids
				)

	lay = EnumProperty(
				name = "Layer",
				description = "Choose layer",
				items = listLayers
				)


	dialog = StringProperty(default='MAP') # 'MAP', 'SEARCH', 'OPTIONS'

	query = StringProperty(name="Go to")

	zoom = IntProperty(name='Zoom level', min=0, max=25)

	recenter = BoolProperty(name='Center to existing objects')

	def draw(self, context):
		addonPrefs = context.user_preferences.addons[PKG].preferences
		scn = context.scene
		layout = self.layout

		if self.dialog == 'SEARCH':
				layout.prop(self, 'query')
				layout.prop(self, 'zoom', slider=True)

		elif self.dialog == 'OPTIONS':
			layout.prop(addonPrefs, "fontColor")
			#viewPrefs = context.user_preferences.view
			#layout.prop(viewPrefs, "use_zoom_to_mouse")
			layout.prop(addonPrefs, "zoomToMouse")
			layout.prop(addonPrefs, "lockObj")
			layout.prop(addonPrefs, "lockOrigin")

		elif self.dialog == 'MAP':
			layout.prop(self, 'src', text='Source')
			layout.prop(self, 'lay', text='Layer')
			col = layout.column()
			if not HAS_GDAL:
				col.enabled = False
				col.label('(No raster reprojection support)')
			col.prop(self, 'grd', text='Tile matrix set')

			#srcCRS = GRIDS[SOURCES[self.src]['grid']]['CRS']
			grdCRS = GRIDS[self.grd]['CRS']
			row = layout.row()
			#row.alignment = 'RIGHT'
			desc = PredefCRS.getName(grdCRS)
			if desc is not None:
				row.label('CRS: ' + desc)
			else:
				row.label('CRS: ' + grdCRS)

			row = layout.row()
			row.prop(self, 'recenter')

			geoscn = GeoScene(scn)
			if geoscn.isPartiallyGeoref:
				#layout.separator()
				georefManagerLayout(self, context)

			#row = layout.row()
			#row.label('Map scale:')
			#row.prop(scn, '["'+SK.SCALE+'"]', text='')


	def invoke(self, context, event):

		if not HAS_PIL and not HAS_GDAL and not HAS_IMGIO:
			self.report({'ERROR'}, "No imaging library available. Please install Python GDAL or Pillow module")
			return {'CANCELLED'}

		if not context.area.type == 'VIEW_3D':
			self.report({'WARNING'}, "View3D not found, cannot run operator")
			return {'CANCELLED'}

		#Update zoom
		geoscn = GeoScene(context.scene)
		if geoscn.hasZoom:
			self.zoom = geoscn.zoom

		#Display dialog
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		scn = context.scene
		geoscn = GeoScene(scn)
		prefs = context.user_preferences.addons[PKG].preferences

		#check cache folder
		folder = prefs.cacheFolder
		if folder == "" or not os.path.exists(folder):
			self.report({'ERROR'}, "Please define a valid cache folder path")
			return {'FINISHED'}

		if self.dialog == 'MAP':
			grdCRS = GRIDS[self.grd]['CRS']
			if geoscn.isBroken:
				self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
				return {'FINISHED'}
			#set scene crs as grid crs
			#if not geoscn.hasCRS:
				#geoscn.crs = grdCRS
			#Check if raster reproj is needed
			if geoscn.hasCRS and geoscn.crs != grdCRS and not HAS_GDAL:
				self.report({'ERROR'}, "Please install gdal to enable raster reprojection support")
				return {'FINISHED'}

		#Move scene origin to the researched place
		if self.dialog == 'SEARCH':
			geoscn.zoom = self.zoom
			bpy.ops.view3d.map_search('EXEC_DEFAULT', query=self.query)

		#Start map viewer operator
		self.dialog = 'MAP' #reinit dialog type
		bpy.ops.view3d.map_viewer('INVOKE_DEFAULT', srckey=self.src, laykey=self.lay, grdkey=self.grd, recenter=self.recenter)

		return {'FINISHED'}





###############


class MAP_VIEWER(bpy.types.Operator):

	bl_idname = "view3d.map_viewer"
	bl_description = 'Toggle 2d map navigation'
	bl_label = "Map viewer"
	bl_options = {'INTERNAL'}

	srckey = StringProperty()

	grdkey = StringProperty()

	laykey = StringProperty()

	recenter = BoolProperty()

	@classmethod
	def poll(cls, context):
		return context.area.type == 'VIEW_3D'


	def __del__(self):
		if getattr(self, 'restart', False):
			bpy.ops.view3d.map_start('INVOKE_DEFAULT', src=self.srckey, lay=self.laykey, grd=self.grdkey, dialog=self.dialog)


	def invoke(self, context, event):

		self.restart = False
		self.dialog = 'MAP' # dialog name for MAP_START >> string in  ['MAP', 'SEARCH', 'OPTIONS']

		self.moveFactor = 0.1

		self.prefs = context.user_preferences.addons[PKG].preferences
		#Option to adjust or not objects location when panning
		self.updObjLoc = self.prefs.lockObj #if georef if locked then we need to adjust object location after each pan

		#Add draw callback to view space
		args = (self, context)
		self._drawTextHandler = bpy.types.SpaceView3D.draw_handler_add(drawInfosText, args, 'WINDOW', 'POST_PIXEL')
		self._drawZoomBoxHandler = bpy.types.SpaceView3D.draw_handler_add(drawZoomBox, args, 'WINDOW', 'POST_PIXEL')

		#Add modal handler and init a timer
		context.window_manager.modal_handler_add(self)
		self.timer = context.window_manager.event_timer_add(0.05, context.window)

		#Switch to top view ortho (center to origin)
		view3d = context.area.spaces.active
		bpy.ops.view3d.viewnumpad(type='TOP')
		view3d.region_3d.view_perspective = 'ORTHO'
		view3d.cursor_location = (0, 0, 0)
		if not self.prefs.lockOrigin:
			#bpy.ops.view3d.view_center_cursor()
			view3d.region_3d.view_location = (0, 0, 0)

		#Init some properties
		# tag if map is currently drag
		self.inMove = False
		# mouse crs coordinates reported in draw callback
		self.posx, self.posy = 0, 0
		# thread progress infos reported in draw callback
		self.progress = ''
		# Zoom box
		self.zoomBoxMode = False
		self.zoomBoxDrag = False
		self.zb_xmin, self.zb_xmax = 0, 0
		self.zb_ymin, self.zb_ymax = 0, 0

		#Get map
		self.map = BaseMap(context, self.srckey, self.laykey, self.grdkey)

		if self.recenter and len(context.scene.objects) > 0:
			scnBbox = BBOX.fromScn(context.scene).to2D()
			w, h = scnBbox.dimensions
			px_diag = math.sqrt(context.area.width**2 + context.area.height**2)
			dst_diag = math.sqrt( w**2 + h**2 )
			targetRes = dst_diag / px_diag
			z = self.map.tm.getNearestZoom(targetRes, rule='lower')
			resFactor = self.map.tm.getFromToResFac(self.map.zoom, z)
			context.region_data.view_distance *= resFactor
			x, y = scnBbox.center
			if self.prefs.lockOrigin:
				context.region_data.view_location = (x, y, 0)
			else:
				self.map.moveOrigin(x, y)
			self.map.zoom = z

		self.map.get()

		return {'RUNNING_MODAL'}



	def mouseTo3d(self, context, x, y):
		'''Convert event.mouse_region to world coordinates'''
		coords = (x, y)
		reg = context.region
		reg3d = context.region_data
		vec = region_2d_to_vector_3d(reg, reg3d, coords)
		loc = region_2d_to_location_3d(reg, reg3d, coords, vec)
		return loc


	def modal(self, context, event):

		context.area.tag_redraw()
		scn = bpy.context.scene

		if event.type == 'TIMER':
			#report thread progression
			self.progress = self.map.srv.report
			return {'PASS_THROUGH'}


		if event.type in ['WHEELUPMOUSE', 'NUMPAD_PLUS']:

			if event.value == 'PRESS':

				if event.alt:
					# map scale up
					self.map.scale *= 10
					self.map.place()
					#Scale existing objects
					for obj in scn.objects:
						obj.location /= 10
						obj.scale /= 10

				elif event.ctrl:
					# view3d zoom up
					dst = context.region_data.view_distance
					context.region_data.view_distance -= dst * self.moveFactor
					if self.prefs.zoomToMouse:
						mouseLoc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
						viewLoc = context.region_data.view_location
						deltaVect = (mouseLoc - viewLoc) * self.moveFactor
						viewLoc += deltaVect
				else:
					# map zoom up
					if self.map.zoom < self.map.layer.zmax and self.map.zoom < self.map.tm.nbLevels-1:
						self.map.zoom += 1
						resFactor = self.map.tm.getNextResFac(self.map.zoom)
						if not self.prefs.zoomToMouse:
							context.region_data.view_distance *= resFactor
						else:
							#Progressibly zoom to cursor
							dst = context.region_data.view_distance
							dst2 = dst * resFactor
							context.region_data.view_distance = dst2
							mouseLoc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
							viewLoc = context.region_data.view_location
							moveFactor = (dst - dst2) / dst
							deltaVect = (mouseLoc - viewLoc) * moveFactor
							if self.prefs.lockOrigin:
								viewLoc += deltaVect
							else:
								dx, dy, dz = deltaVect
								self.map.moveOrigin(dx, dy, updObjLoc=self.updObjLoc)
						self.map.get()


		if event.type in ['WHEELDOWNMOUSE', 'NUMPAD_MINUS']:

			if event.value == 'PRESS':

				if event.alt:
					#map scale down
					s = self.map.scale / 10
					if s < 1: s = 1
					self.map.scale = s
					self.map.place()
					#Scale existing objects
					for obj in scn.objects:
						obj.location *= 10
						obj.scale *= 10

				elif event.ctrl:
					#view3d zoom down
					dst = context.region_data.view_distance
					context.region_data.view_distance += dst * self.moveFactor
					if self.prefs.zoomToMouse:
						mouseLoc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
						viewLoc = context.region_data.view_location
						deltaVect = (mouseLoc - viewLoc) * self.moveFactor
						viewLoc -= deltaVect
				else:
					#map zoom down
					if self.map.zoom > self.map.layer.zmin and self.map.zoom > 0:
						self.map.zoom -= 1
						resFactor = self.map.tm.getPrevResFac(self.map.zoom)
						if not self.prefs.zoomToMouse:
							context.region_data.view_distance *= resFactor
						else:
							#Progressibly zoom to cursor
							dst = context.region_data.view_distance
							dst2 = dst * resFactor
							context.region_data.view_distance = dst2
							mouseLoc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
							viewLoc = context.region_data.view_location
							moveFactor = (dst - dst2) / dst
							deltaVect = (mouseLoc - viewLoc) * moveFactor
							if self.prefs.lockOrigin:
								viewLoc += deltaVect
							else:
								dx, dy, dz = deltaVect
								self.map.moveOrigin(dx, dy, updObjLoc=self.updObjLoc)
						self.map.get()



		if event.type == 'MOUSEMOVE':

			#Report mouse location coords in projeted crs
			loc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
			self.posx, self.posy = self.map.view3dToProj(loc.x, loc.y)

			if self.zoomBoxMode:
				self.zb_xmax, self.zb_ymax = event.mouse_region_x, event.mouse_region_y

			#Drag background image (edit its offset values)
			if self.inMove:
				loc1 = self.mouseTo3d(context, self.x1, self.y1)
				loc2 = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
				dlt = loc1 - loc2
				if event.ctrl or self.prefs.lockOrigin:
					context.region_data.view_location = self.viewLoc1 + dlt
				else:
					#Move background image
					if self.map.bkg is not None:
						ratio = self.map.img.size[0] / self.map.img.size[1]
						self.map.bkg.offset_x = self.offx1 - dlt.x
						self.map.bkg.offset_y = self.offy1 - (dlt.y * ratio)
					#Move existing objects (only top level parent)
					if self.updObjLoc:
						topParents = [obj for obj in scn.objects if not obj.parent]
						for i, obj in enumerate(topParents):
							loc1 = self.objsLoc1[i]
							obj.location.x = loc1.x - dlt.x
							obj.location.y = loc1.y - dlt.y


		if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'}:

			if event.value == 'PRESS' and not self.zoomBoxMode:
				#Get click mouse position and background image offset (if exist)
				self.x1, self.y1 = event.mouse_region_x, event.mouse_region_y
				self.viewLoc1 = context.region_data.view_location.copy()
				if not event.ctrl:
					#Stop thread now, because we don't know when the mouse click will be released
					self.map.stop()
					if not self.prefs.lockOrigin:
						if self.map.bkg is not None:
							self.offx1 = self.map.bkg.offset_x
							self.offy1 = self.map.bkg.offset_y
						#Store current location of each objects (only top level parent)
						self.objsLoc1 = [obj.location.copy() for obj in scn.objects if not obj.parent]
				#Tag that map is currently draging
				self.inMove = True

			if event.value == 'RELEASE' and not self.zoomBoxMode:
				self.inMove = False
				if not event.ctrl:
					if not self.prefs.lockOrigin:
						#Compute final shift
						loc1 = self.mouseTo3d(context, self.x1, self.y1)
						loc2 = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
						dlt = loc1 - loc2
						#Update map
						self.map.moveOrigin(dlt.x, dlt.y, updObjLoc=False, updBkgImg=False)
					self.map.get()


			if event.value == 'PRESS' and self.zoomBoxMode:
				self.zoomBoxDrag = True
				self.zb_xmin, self.zb_ymin = event.mouse_region_x, event.mouse_region_y

			if event.value == 'RELEASE' and self.zoomBoxMode:
				#Get final zoom box
				xmax = max(event.mouse_region_x, self.zb_xmin)
				ymax = max(event.mouse_region_y, self.zb_ymin)
				xmin = min(event.mouse_region_x, self.zb_xmin)
				ymin = min(event.mouse_region_y, self.zb_ymin)
				#Exit zoom box mode
				self.zoomBoxDrag = False
				self.zoomBoxMode = False
				context.window.cursor_set('DEFAULT')
				#Compute the move to box origin
				w = xmax - xmin
				h = ymax - ymin
				cx = xmin + w/2
				cy = ymin + h/2
				loc = self.mouseTo3d(context, cx, cy)
				#Compute target resolution
				px_diag = math.sqrt(context.area.width**2 + context.area.height**2)
				mapRes = self.map.tm.getRes(self.map.zoom)
				dst_diag = math.sqrt( (w*mapRes)**2 + (h*mapRes)**2)
				targetRes = dst_diag / px_diag
				z = self.map.tm.getNearestZoom(targetRes, rule='lower')
				resFactor = self.map.tm.getFromToResFac(self.map.zoom, z)
				#Preview
				context.region_data.view_distance *= resFactor
				if self.prefs.lockOrigin:
					context.region_data.view_location = loc
				else:
					self.map.moveOrigin(loc.x, loc.y, updObjLoc=self.updObjLoc)
				self.map.zoom = z
				self.map.get()


		if event.type in ['LEFT_CTRL', 'RIGHT_CTRL']:

			if event.value == 'PRESS':
				self._viewDstZ = context.region_data.view_distance
				self._viewLoc = context.region_data.view_location.copy()

			if event.value == 'RELEASE':
				#restore view 3d distance and location
				context.region_data.view_distance = self._viewDstZ
				context.region_data.view_location = self._viewLoc


		#NUMPAD MOVES (3D VIEW or MAP)
		if event.value == 'PRESS' and event.type in ['NUMPAD_2', 'NUMPAD_4', 'NUMPAD_6', 'NUMPAD_8']:
			delta = self.map.bkg.size * self.moveFactor
			if event.type == 'NUMPAD_4':
				if event.ctrl or self.prefs.lockOrigin:
					context.region_data.view_location += Vector( (-delta, 0, 0) )
				else:
					self.map.moveOrigin(-delta, 0, updObjLoc=self.updObjLoc)
			if event.type == 'NUMPAD_6':
				if event.ctrl or self.prefs.lockOrigin:
					context.region_data.view_location += Vector( (delta, 0, 0) )
				else:
					self.map.moveOrigin(delta, 0, updObjLoc=self.updObjLoc)
			if event.type == 'NUMPAD_2':
				if event.ctrl or self.prefs.lockOrigin:
					context.region_data.view_location += Vector( (0, -delta, 0) )
				else:
					self.map.moveOrigin(0, -delta, updObjLoc=self.updObjLoc)
			if event.type == 'NUMPAD_8':
				if event.ctrl or self.prefs.lockOrigin:
					context.region_data.view_location += Vector( (0, delta, 0) )
				else:
					self.map.moveOrigin(0, delta, updObjLoc=self.updObjLoc)
			if not event.ctrl:
				self.map.get()

		#SWITCH LAYER
		if event.type == 'SPACE':
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			self.restart = True
			return {'FINISHED'}

		#GO TO
		if event.type == 'G':
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			self.restart = True
			self.dialog = 'SEARCH'
			return {'FINISHED'}

		#OPTIONS
		if event.type == 'O':
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			self.restart = True
			self.dialog = 'OPTIONS'
			return {'FINISHED'}

		#ZOOM BOX
		if event.type == 'B' and event.value == 'PRESS':
			self.map.stop()
			self.zoomBoxMode = True
			self.zb_xmax, self.zb_ymax = event.mouse_region_x, event.mouse_region_y
			context.window.cursor_set('CROSSHAIR')

		#EXPORT
		if event.type == 'E' and event.value == 'PRESS':
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')

			#Get geoimage and bpyimage
			rast = self.map.mosaic
			bpyImg = self.map.img

			#Copy image to new datablock
			bpyImg = bpy.data.images.load(bpyImg.filepath)
			name = 'EXPORT_' + self.map.srckey + '_' + self.map.laykey + '_' + self.map.grdkey
			bpyImg.name = name
			bpyImg.pack()

			#Add new attribute to geoImg class (like GeoRaster class)
			setattr(rast, 'bpyImg', bpyImg)

			#Create Mesh
			dx, dy = self.map.getOriginPrj()
			mesh = rasterExtentToMesh(name, rast, dx, dy, pxLoc='CORNER')

			#Create object
			obj = placeObj(mesh, name)

			#UV mapping
			uvTxtLayer = mesh.uv_textures.new('rastUVmap')# Add UV map texture layer
			geoRastUVmap(obj, uvTxtLayer, rast, dx, dy)

			#Create material
			mat = bpy.data.materials.new('rastMat')
			obj.data.materials.append(mat)
			addTexture(mat, self.map.img, uvTxtLayer)

			#Adjust 3d view and display textures
			adjust3Dview(context, BBOX.fromObj(obj))
			showTextures(context)

			return {'FINISHED'}

		#EXIT
		if event.type == 'ESC' and event.value == 'PRESS':
			if self.zoomBoxMode:
				self.zoomBoxDrag = False
				self.zoomBoxMode = False
				context.window.cursor_set('DEFAULT')
			else:
				self.map.stop()
				bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
				bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
				return {'CANCELLED'}

		"""
		#FINISH
		if event.type in {'RET'}:
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			return {'FINISHED'}
		"""

		return {'RUNNING_MODAL'}



####################################

class MAP_SEARCH(bpy.types.Operator):

	bl_idname = "view3d.map_search"
	bl_description = 'Search for a place and move scene origin to it'
	bl_label = "Map search"
	bl_options = {'INTERNAL'}

	query = StringProperty(name="Go to")

	def invoke(self, context, event):
		geoscn = GeoScene(context.scene)
		if geoscn.isBroken:
			self.report({'ERROR'}, "Scene georef is broken")
			return {'CANCELLED'}
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		geoscn = GeoScene(context.scene)
		prefs = context.user_preferences.addons[PKG].preferences
		geocoder = Nominatim(base_url="http://nominatim.openstreetmap.org", referer="bgis")
		results = geocoder.query(self.query)
		if len(results) >= 1:
			result = results[0]
			lat, lon = float(result['lat']), float(result['lon'])
			if geoscn.isGeoref:
				geoscn.updOriginGeo(lon, lat, updObjLoc=prefs.lockObj)
			else:
				geoscn.setOriginGeo(lon, lat)
		return {'FINISHED'}

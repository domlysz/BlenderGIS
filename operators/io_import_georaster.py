# -*- coding:utf-8 -*-

# This file is part of BlenderGIS

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
import bmesh
import os
import math
from mathutils import Vector
import numpy as np#Ship with Blender since 2.70

from ..geoscene import GeoScene, georefManagerLayout
from ..prefs import PredefCRS

from .utils import bpyGeoRaster as GeoRaster
from .utils import placeObj, adjust3Dview, showTextures, addTexture, getBBOX
from .utils import rasterExtentToMesh, geoRastUVmap, setDisplacer

from ..core import HAS_GDAL
if HAS_GDAL:
	from osgeo import gdal

from ..core import XY as xy
from ..core.errors import OverlapError
from ..core.proj import Reproj

from bpy_extras.io_utils import ImportHelper #helper class defines filename and invoke() function which calls the file selector
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator

PKG, SUBPKG = __package__.split('.', maxsplit=1)

class IMPORT_GEORAST(Operator, ImportHelper):
	"""Import georeferenced raster (need world file)"""
	bl_idname = "importgis.georaster"  # important since its how bpy.ops.importgis.georaster is constructed (allows calling operator from python console or another script)
	#bl_idname rules: must contain one '.' (dot) charactere, no capital letters, no reserved words (like 'import')
	bl_description = 'Import raster georeferenced with world file'
	bl_label = "Import georaster"
	bl_options = {"UNDO"}

	def listObjects(self, context):
		#Function used to update the objects list (obj_list) used by the dropdown box.
		objs = [] #list containing tuples of each object
		for index, object in enumerate(bpy.context.scene.objects): #iterate over all objects
			if object.type == 'MESH':
				objs.append((str(index), object.name, "Object named " +object.name)) #put each object in a tuple (key, label, tooltip) and add this to the objects list
		return objs

	# ImportHelper class properties
	filter_glob = StringProperty(
			default="*.tif;*.jpg;*.jpeg;*.png;*.bmp",
			options={'HIDDEN'},
			)

	# Raster CRS definition
	def listPredefCRS(self, context):
		return PredefCRS.getEnumItems()
	rastCRS = EnumProperty(
		name = "Raster CRS",
		description = "Choose a Coordinate Reference System",
		items = listPredefCRS,
		)

	# List of operator properties, the attributes will be assigned
	# to the class instance from the operator settings before calling.
	importMode = EnumProperty(
			name="Mode",
			description="Select import mode",
			items=[ ('PLANE', 'On plane', "Place raster texture on new plane mesh"),
			('BKG', 'As background', "Place raster as background image"),
			('MESH', 'On mesh', "UV map raster on an existing mesh"),
			('DEM', 'As DEM', "Use DEM raster GRID to wrap an existing mesh"),
			('DEM_RAW', 'Raw DEM', "Import a DEM as pixels points cloud")]
			)
	#
	objectsLst = EnumProperty(attr="obj_list", name="Objects", description="Choose object to edit", items=listObjects)
	#
	#Subdivise (as DEM option)
	subdivision = EnumProperty(
			name="Subdivision",
			description="How to subdivise the plane (dispacer needs vertex to work with)",
			items=[ ('subsurf', 'Subsurf', "Add a subsurf modifier"),
			('mesh', 'Mesh', "Edit the mesh to subdivise the plane according to the number of DEM pixels which overlay the plane"),
			('none', 'None', "No subdivision")]
			)
	#
	demOnMesh = BoolProperty(
			name="Apply on existing mesh",
			description="Use DEM as displacer for an existing mesh",
			default=False
			)
	#
	clip = BoolProperty(
			name="Clip to working extent",
			description="Use the reference bounding box to clip the DEM",
			default=False
			)
	#
	fillNodata = BoolProperty(
			name="Fill nodata values",
			description="Interpolate existing nodata values to get an usuable displacement texture",
			default=False
			)
	#
	step = IntProperty(name = "Step", default=1, description="Pixel step", min=1)

	def draw(self, context):
		#Function used by blender to draw the panel.
		layout = self.layout
		layout.prop(self, 'importMode')
		scn = bpy.context.scene
		geoscn = GeoScene(scn)
		#
		if self.importMode == 'PLANE':
			pass
		#
		if self.importMode == 'BKG':
			pass
		#
		if self.importMode == 'MESH':
			if geoscn.isGeoref and len(self.objectsLst) > 0:
				layout.prop(self, 'objectsLst')
			else:
				layout.label("There isn't georef mesh to UVmap on")
		#
		if self.importMode == 'DEM':
			layout.prop(self, 'demOnMesh')
			if self.demOnMesh:
				if geoscn.isGeoref and len(self.objectsLst) > 0:
					layout.prop(self, 'objectsLst')
					layout.prop(self, 'clip')
				else:
					layout.label("There isn't georef mesh to apply on")
			layout.prop(self, 'subdivision')
			layout.prop(self, 'fillNodata')
		#
		if self.importMode == 'DEM_RAW':
			layout.prop(self, 'step')
			layout.prop(self, 'clip')
			if self.clip:
				if geoscn.isGeoref and len(self.objectsLst) > 0:
					layout.prop(self, 'objectsLst')
				else:
					layout.label("There isn't georef mesh to refer")
		#
		row = layout.row(align=True)
		#row.prop(self, "rastCRS", text='CRS')
		split = row.split(percentage=0.35, align=True)
		split.label('CRS:')
		split.prop(self, "rastCRS", text='')
		row.operator("bgis.add_predef_crs", text='', icon='ZOOMIN')
		if geoscn.isPartiallyGeoref:
			georefManagerLayout(self, context)


	def err(self, msg):
		'''Report error throught a Blender's message box'''
		self.report({'ERROR'}, msg)
		return {'FINISHED'}

	def execute(self, context):
		prefs = bpy.context.user_preferences.addons[PKG].preferences
		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass
		bpy.ops.object.select_all(action='DESELECT')
		#Get scene and some georef data
		scn = bpy.context.scene
		geoscn = GeoScene(scn)
		if geoscn.isBroken:
			self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
			return {'FINISHED'}
		if geoscn.isGeoref:
			dx, dy = geoscn.getOriginPrj()
		scale = geoscn.scale #TODO
		if not geoscn.hasCRS:
			try:
				geoscn.crs = self.rastCRS
			except Exception as e:
				self.report({'ERROR'}, str(e))
				return {'FINISHED'}

		#Raster reprojection throught UV mapping
		#build reprojector objects
		if geoscn.crs != self.rastCRS:
			rprj = True
			rprjToRaster = Reproj(geoscn.crs, self.rastCRS)
			rprjToScene = Reproj(self.rastCRS, geoscn.crs)
		else:
			rprj = False
			rprjToRaster = None
			rprjToScene = None

		#Path
		filePath = self.filepath
		name = os.path.basename(filePath)[:-4]

		######################################
		if self.importMode == 'PLANE':#on plane
			#Load raster
			try:
				rast = GeoRaster(filePath)
			except IOError as e:
				return self.err(str(e))
			#Get or set georef dx, dy
			if not geoscn.isGeoref:
				dx, dy = rast.center.x, rast.center.y
				if rprj:
					dx, dy = rprjToScene.pt(dx, dy)
				geoscn.setOriginPrj(dx, dy)
			#create a new mesh from raster extent
			mesh = rasterExtentToMesh(name, rast, dx, dy, reproj=rprjToScene)
			#place obj
			obj = placeObj(mesh, name)
			#UV mapping
			uvTxtLayer = mesh.uv_textures.new('rastUVmap')# Add UV map texture layer
			geoRastUVmap(obj, uvTxtLayer, rast, dx, dy, reproj=rprjToRaster)
			# Create material
			mat = bpy.data.materials.new('rastMat')
			# Add material to current object
			obj.data.materials.append(mat)
			# Add texture to material
			addTexture(mat, rast.bpyImg, uvTxtLayer, name='rastText')

		######################################
		if self.importMode == 'BKG':#background
			if rprj:
				return self.err("Raster reprojection not possible in background mode") #TODO, do gdal true reproj
			#Load raster
			try:
				rast = GeoRaster(filePath)
			except IOError as e:
				return self.err(str(e))
			#Check pixel size and rotation
			if rast.rotation.xy != [0,0]:
				return self.err("Cannot rotate background image")
			if abs(round(rast.pxSize.x, 3)) != abs(round(rast.pxSize.y, 3)):
				return self.err("Background image needs equal pixel size in map units in both x ans y axis")
			#
			trueSizeX = rast.geoSize.x
			trueSizeY = rast.geoSize.y
			ratio = rast.size.x / rast.size.y
			if geoscn.isGeoref:
				offx, offy = rast.center.x - dx, rast.center.y - dy
			else:
				dx, dy = rast.center.x, rast.center.y
				geoscn.setOriginPrj(dx, dy)
				offx, offy = 0, 0
			areas = bpy.context.screen.areas
			for area in areas:
				if area.type == 'VIEW_3D':
					space = area.spaces.active
					space.show_background_images=True
					bckImg = space.background_images.new()
					bckImg.image = rast.bpyImg
					bckImg.view_axis = 'TOP'
					bckImg.opacity = 1
					bckImg.size = trueSizeX #since Blender 2.75
					bckImg.offset_x = offx
					bckImg.offset_y = offy * ratio

		######################################
		if self.importMode == 'MESH':
			if not geoscn.isGeoref or len(self.objectsLst) == 0:
				return self.err("There isn't georef mesh to apply on")
			# Get choosen object
			obj = scn.objects[int(self.objectsLst)]
			# Select and active this obj
			obj.select = True
			scn.objects.active = obj
			# Compute projeted bbox (in geographic coordinates system)
			subBox = getBBOX.fromObj(obj).toGeo(geoscn)
			if rprj:
				subBox = rprjToRaster.bbox(subBox)
			#Load raster
			try:
				rast = GeoRaster(filePath, subBoxGeo=subBox)
			except (IOError, OverlapError) as e:
				return self.err(str(e))
			# Add UV map texture layer
			mesh = obj.data
			uvTxtLayer = mesh.uv_textures.new('rastUVmap')
			# UV mapping
			geoRastUVmap(obj, uvTxtLayer, rast, dx, dy, reproj=rprjToRaster)
			# Add material and texture
			mat = bpy.data.materials.new('rastMat')
			obj.data.materials.append(mat)
			addTexture(mat, rast.bpyImg, uvTxtLayer, name='rastText')

		######################################
		if self.importMode == 'DEM':

			# Get reference plane
			if self.demOnMesh:
				if not geoscn.isGeoref or len(self.objectsLst) == 0:
					return self.err("There isn't georef mesh to apply on")
				# Get choosen object
				obj = scn.objects[int(self.objectsLst)]
				mesh = obj.data
				# Select and active this obj
				obj.select = True
				scn.objects.active = obj
				# Compute projeted bbox (in geographic coordinates system)
				subBox = getBBOX.fromObj(obj).toGeo(geoscn)
				if rprj:
					subBox = rprjToRaster.bbox(subBox)
			else:
				subBox = None

			# Load raster
			try:
				grid = GeoRaster(filePath, subBoxGeo=subBox, clip=self.clip, fillNodata=self.fillNodata, useGDAL=HAS_GDAL)
			except (IOError, OverlapError) as e:
				return self.err(str(e))

			# If no reference, create a new plane object from raster extent
			if not self.demOnMesh:
				if not geoscn.isGeoref:
					dx, dy = grid.center.x, grid.center.y
					if rprj:
						dx, dy = rprjToScene.pt(dx, dy)
					geoscn.setOriginPrj(dx, dy)
				mesh = rasterExtentToMesh(name, grid, dx, dy, pxLoc='CENTER', reproj=rprjToScene) #use pixel center to avoid displacement glitch
				obj = placeObj(mesh, name)
				subBox = getBBOX.fromObj(obj).toGeo(geoscn)

			# Add UV map texture layer
			previousUVmapIdx = mesh.uv_textures.active_index
			uvTxtLayer = mesh.uv_textures.new('demUVmap')
			#UV mapping
			geoRastUVmap(obj, uvTxtLayer, grid, dx, dy, reproj=rprjToRaster)
			#Restore previous uv map
			if previousUVmapIdx != -1:
				mesh.uv_textures.active_index = previousUVmapIdx
			#Make subdivision
			if self.subdivision == 'mesh':#Mesh cut
				#if len(mesh.polygons) == 1:
				bpy.ops.object.mode_set(mode='EDIT')
				bpy.ops.mesh.select_all(action='SELECT')
				#nbCuts = int(max(grid.size.xy))
				#bpy.ops.mesh.subdivide(number_cuts=nbCuts)
				#WIP make a better sudivision : we need one vertex / pixel
				ul = grid.georef.pxFromGeo(*subBox.ul)
				ul = grid.georef.geoFromPx(ul.x+1, ul.y+1)
				bpy.ops.mesh.loopcut(number_cuts = grid.size.x - 1, edge_index = 1)
				bpy.ops.mesh.loopcut(number_cuts = grid.size.y - 1, edge_index = 2)
				bpy.ops.object.mode_set(mode='OBJECT')
			elif self.subdivision == 'subsurf':#Add subsurf modifier
				if not 'SUBSURF' in [mod.type for mod in obj.modifiers]:
					subsurf = obj.modifiers.new('DEM', type='SUBSURF')
					subsurf.subdivision_type = 'SIMPLE'
					subsurf.levels = 6
					subsurf.render_levels = 6
			elif self.subdivision == 'None':
				pass
			#Set displacer
			dsp = setDisplacer(obj, grid, uvTxtLayer)

		######################################
		if self.importMode == 'DEM_RAW':

			# Get reference plane
			subBox = None
			if self.clip:
				if not geoscn.isGeoref or len(self.objectsLst) == 0:
					return self.err("No working extent")
				# Get choosen object
				obj = scn.objects[int(self.objectsLst)]
				subBox = getBBOX.fromObj(obj).toGeo(geoscn)
				if rprj:
					subBox = rprjToRaster.bbox(subBox)

			# Load raster
			try:
				grid = GeoRaster(filePath, subBoxGeo=subBox, clip=self.clip, useGDAL=HAS_GDAL)
			except (IOError, OverlapError) as e:
				return self.err(str(e))

			if not geoscn.isGeoref:
				dx, dy = grid.center.x, grid.center.y
				if rprj:
					dx, dy = rprjToScene.pt(dx, dy)
				geoscn.setOriginPrj(dx, dy)
			mesh = grid.exportAsMesh(dx, dy, self.step, reproj=rprjToScene)
			obj = placeObj(mesh, name)
			grid.unload()

		######################################
		#Flag is a new object as been created...
		if self.importMode == 'PLANE' or (self.importMode == 'DEM' and not self.demOnMesh) or self.importMode == 'DEM_RAW':
			newObjCreated = True
		else:
			newObjCreated = False

		#...if so, maybee we need to adjust 3d view settings to it
		if newObjCreated and prefs.adjust3Dview:
			bb = getBBOX.fromObj(obj)
			adjust3Dview(context, bb)

		#Force view mode with textures
		if prefs.forceTexturedSolid:
			showTextures(context)


		return {'FINISHED'}

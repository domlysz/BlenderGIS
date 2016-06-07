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

try:
	from osgeo import gdal
	GDAL = True
except:
	GDAL = False

#For debug
#GDAL = False

from .utils import xy, bbox, OverlapError
from .georaster import GeoRaster, GeoRasterGDAL

from geoscene.geoscn import GeoScene
from geoscene.addon import PredefCRS, georefManagerLayout
from geoscene.proj import reprojPt, Reproj

#------------------------------------------------------------------------
def getBBox(obj, applyTransform = True, applyDeltas=False):
	'''Compute bbox of a given object'''
	if applyTransform:
		boundPts = [obj.matrix_world * Vector(corner) for corner in obj.bound_box]
	else:
		boundPts = obj.bound_box
	xmin = min([pt[0] for pt in boundPts])
	xmax = max([pt[0] for pt in boundPts])
	ymin = min([pt[1] for pt in boundPts])
	ymax = max([pt[1] for pt in boundPts])
	if applyDeltas:
		#Get georef deltas stored as scene properties
		geoscn = GeoScene()
		dx, dy = geoscn.getOriginPrj()
		return bbox(xmin+dx, xmax+dx, ymin+dy, ymax+dy)
	else:
		return bbox(xmin, xmax, ymin, ymax)

def rasterExtentToMesh(name, rast, dx, dy, pxLoc='CORNER'):
	'''Build a new mesh that represent a georaster extent'''
	#create mesh
	bm = bmesh.new()
	if pxLoc == 'CORNER':
		pts = [(pt.x-dx, pt.y-dy) for pt in rast.corners]#shift coords
	elif pxLoc == 'CENTER':
		pts = [(pt.x-dx, pt.y-dy) for pt in rast.cornersCenter]
	z = 0
	pts = [bm.verts.new((pt[0], pt[1], z)) for pt in pts]#upper left to botton left (clockwise)
	pts.reverse()#bottom left to upper left (anticlockwise --> face up)
	bm.faces.new(pts)
	#Create mesh from bmesh
	mesh = bpy.data.meshes.new(name)
	bm.to_mesh(mesh)
	bm.free()
	return mesh

def placeObj(mesh, objName):
	'''Build and add a new object from a given mesh'''
	bpy.ops.object.select_all(action='DESELECT')
	#create an object with that mesh
	obj = bpy.data.objects.new(objName, mesh)
	# Link object to scene
	bpy.context.scene.objects.link(obj)
	bpy.context.scene.objects.active = obj
	obj.select = True
	#bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
	return obj

def geoRastUVmap(obj, uvTxtLayer, rast, dx, dy):
	'''uv map a georaster texture on a given mesh'''
	uvTxtLayer.active = True
	# Assign image texture for every face
	mesh = obj.data
	for idx, pg in enumerate(mesh.polygons):
		uvTxtLayer.data[idx].image = rast.bpyImg
	#Get UV loop layer
	uvLoopLayer = mesh.uv_layers.active
	#Assign uv coords
	loc = obj.location
	for pg in mesh.polygons:
		for i in pg.loop_indices:
			vertIdx = mesh.loops[i].vertex_index
			pt = list(mesh.vertices[vertIdx].co)
			#adjust coords against object location and shift values to retrieve original point coords
			pt = (pt[0] + loc.x + dx, pt[1] + loc.y + dy)
			#Compute UV coords --> pourcent from image origin (bottom left)
			dx_px, dy_px = rast.pxFromGeo(pt[0], pt[1], reverseY=True, round2Floor=False)
			u = dx_px / rast.size[0]
			v = dy_px / rast.size[1]
			#Assign coords
			uvLoop = uvLoopLayer.data[i]
			uvLoop.uv = [u,v]

def setDisplacer(obj, rast, uvTxtLayer, mid=0):
	#Config displacer
	displacer = obj.modifiers.new('DEM', type='DISPLACE')
	demTex = bpy.data.textures.new('demText', type = 'IMAGE')
	demTex.image = rast.bpyImg
	demTex.use_interpolation = False
	demTex.extension = 'CLIP'
	demTex.use_clamp = False #Needed to get negative displacement with float32 texture
	displacer.texture = demTex
	displacer.texture_coords = 'UV'
	displacer.uv_layer = uvTxtLayer.name
	displacer.mid_level = mid #Texture values below this value will result in negative displacement
	#Setting the displacement strength :
	#displacement = (texture value - Midlevel) * Strength
	#>> Strength = displacement / texture value (because mid=0)
	#If DEM non scaled then
	#	*displacement = alt max - alt min = delta Z
	#	*texture value = delta Z / (2^depth-1)
	#		(because in Blender, pixel values are normalized between 0.0 and 1.0)
	#>> Strength = delta Z / (delta Z / (2^depth-1))
	#>> Strength = 2^depth-1
	if rast.depth < 32:
		#8 or 16 bits unsigned values (signed int16 must be converted to float to be usuable)
		displacer.strength = 2**rast.depth-1
	else:
		#32 bits values
		#with float raster, blender give directly raw float values(non normalied)
		#so a texture value of 100 simply give a displacement of 100
		displacer.strength = 1
	bpy.ops.object.shade_smooth()
	return displacer

def addTexture(mat, img, uvLay):
	'''Set a new image texture for a given material'''
	engine = bpy.context.scene.render.engine
	mat.use_nodes = True
	node_tree = mat.node_tree
	node_tree.nodes.clear()
	#
	#CYCLES
	bpy.context.scene.render.engine = 'CYCLES' #force Cycles render
	# create uv map node
	uvMapNode = node_tree.nodes.new('ShaderNodeUVMap')
	uvMapNode.uv_map = uvLay.name
	uvMapNode.location = (-400, 200)
	# create image texture node
	textureNode = node_tree.nodes.new('ShaderNodeTexImage')
	textureNode.image = img
	textureNode.extension = 'CLIP'
	textureNode.show_texture = True
	textureNode.location = (-200, 200)
	# Create BSDF diffuse node
	diffuseNode = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
	diffuseNode.location = (0, 200)
	# Create output node
	outputNode = node_tree.nodes.new('ShaderNodeOutputMaterial')
	outputNode.location = (200, 200)
	# Connect the nodes
	node_tree.links.new(uvMapNode.outputs['UV'] , textureNode.inputs['Vector'])
	node_tree.links.new(textureNode.outputs['Color'] , diffuseNode.inputs['Color'])
	node_tree.links.new(diffuseNode.outputs['BSDF'] , outputNode.inputs['Surface'])
	#
	#BLENDER_RENDER
	bpy.context.scene.render.engine = 'BLENDER_RENDER'
	# Create image texture from image
	imgTex = bpy.data.textures.new('rastText', type = 'IMAGE')
	imgTex.image = img
	imgTex.extension = 'CLIP'
	# Add texture slot
	mtex = mat.texture_slots.add()
	mtex.texture = imgTex
	mtex.texture_coords = 'UV'
	mtex.uv_layer = uvLay.name
	mtex.mapping = 'FLAT'
	# Add material node
	matNode = node_tree.nodes.new('ShaderNodeMaterial')
	matNode.material = mat
	matNode.location = (-100, -100)
	# Add output node
	outNode = node_tree.nodes.new('ShaderNodeOutput')
	outNode.location = (100, -100)
	# Connect the nodes
	node_tree.links.new(matNode.outputs['Color'] , outNode.inputs['Color'])
	#
	# restore initial engine
	bpy.context.scene.render.engine = engine



#------------------------------------------------------------------------

from bpy_extras.io_utils import ImportHelper #helper class defines filename and invoke() function which calls the file selector
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator


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
		row.operator("geoscene.add_predef_crs", text='', icon='ZOOMIN')
		if geoscn.isPartiallyGeoref:
			georefManagerLayout(self, context)


	def err(self, msg):
		'''Report error throught a Blender's message box'''
		self.report({'ERROR'}, msg)
		return {'FINISHED'}

	def execute(self, context):
		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass
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
		elif geoscn.crs != self.rastCRS:
			self.report({'ERROR'}, "Cannot reproj raster")
			return {'FINISHED'}
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
				geoscn.setOriginPrj(dx, dy)
			#create a new mesh from raster extent
			mesh = rasterExtentToMesh(name, rast, dx, dy)
			#place obj
			obj = placeObj(mesh, name)
			#UV mapping
			uvTxtLayer = mesh.uv_textures.new('rastUVmap')# Add UV map texture layer
			geoRastUVmap(obj, uvTxtLayer, rast, dx, dy)
			# Create material
			mat = bpy.data.materials.new('rastMat')
			# Add material to current object
			obj.data.materials.append(mat)
			# Add texture to material
			addTexture(mat, rast.bpyImg, uvTxtLayer)

		######################################
		if self.importMode == 'BKG':#background
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
			subBox = getBBox(obj, applyDeltas=True)
			#Load raster
			try:
				rast = GeoRaster(filePath, subBox=subBox)
			except (IOError, OverlapError) as e:
				return self.err(str(e))
			# Add UV map texture layer
			mesh = obj.data
			uvTxtLayer = mesh.uv_textures.new('rastUVmap')
			# UV mapping
			geoRastUVmap(obj, uvTxtLayer, rast, dx, dy)
			# Add material and texture
			mat = bpy.data.materials.new('rastMat')
			obj.data.materials.append(mat)
			addTexture(mat, rast.bpyImg, uvTxtLayer)

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
				subBox = getBBox(obj, applyDeltas=True)
			else:
				subBox = None

			# Load raster
			if not GDAL:
				try:
					grid = GeoRaster(filePath, subBox=subBox, clip=self.clip, fillNodata=self.fillNodata)
				except (IOError, OverlapError) as e:
					return self.err(str(e))
			else:
				try:
					grid = GeoRasterGDAL(filePath, subBox=subBox, clip=self.clip, fillNodata=self.fillNodata)
				except (IOError, OverlapError) as e:
					return self.err(str(e))

			# If no reference, create a new plane object from raster extent
			if not self.demOnMesh:
				if not geoscn.isGeoref:
					dx, dy = grid.center.x, grid.center.y
					geoscn.setOriginPrj(dx, dy)
				mesh = rasterExtentToMesh(name, grid, dx, dy, pxLoc='CENTER') #use pixel center to avoid displacement glitch
				obj = placeObj(mesh, name)

			# Add UV map texture layer
			previousUVmapIdx = mesh.uv_textures.active_index
			uvTxtLayer = mesh.uv_textures.new('demUVmap')
			#UV mapping
			geoRastUVmap(obj, uvTxtLayer, grid, dx, dy)
			#Restore previous uv map
			if previousUVmapIdx != -1:
				mesh.uv_textures.active_index = previousUVmapIdx
			#Make subdivision
			if self.subdivision == 'mesh':#Mesh cut
				#if len(mesh.polygons) == 1: #controler que le mesh n'a qu'une face
				nbCuts = int(max(grid.size.xy))#Estimate better subdivise cuts number
				bpy.ops.object.mode_set(mode='EDIT')
				bpy.ops.mesh.select_all(action='SELECT')
				bpy.ops.mesh.subdivide(number_cuts=nbCuts)
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
				subBox = getBBox(obj, applyDeltas=True)

			# Load raster
			if not GDAL:
				try:
					grid = GeoRaster(filePath, subBox=subBox, clip=self.clip)
				except (IOError, OverlapError) as e:
					return self.err(str(e))
			else:
				try:
					grid = GeoRasterGDAL(filePath, subBox=subBox, clip=self.clip)
				except (IOError, OverlapError) as e:
					return self.err(str(e))

			if not geoscn.isGeoref:
				dx, dy = grid.center.x, grid.center.y
				geoscn.setOriginPrj(dx, dy)
			mesh = grid.exportAsMesh(dx, dy, self.step)
			obj = placeObj(mesh, name)
			grid.unload()

		######################################
		#Flag is a new object as been created...
		if self.importMode == 'PLANE' or (self.importMode == 'DEM' and not self.demOnMesh) or self.importMode == 'DEM_RAW':
			newObjCreated = True
		else:
			newObjCreated = False

		#...if so, maybee we need to adjust 3d view settings to it
		if newObjCreated:
			bb = getBBox(obj)
			dstMax = round(max(abs(bb.xmax), abs(bb.xmin), abs(bb.ymax), abs(bb.ymin)))*2
			nbDigit = len(str(dstMax))
			scale = 10**(nbDigit-2)#1 digits --> 0.1m, 2 --> 1m, 3 --> 10m, 4 --> 100m, , 5 --> 1000m
			nbLines = round(dstMax/scale)
			targetDst = nbLines*scale

		#update 3d view settings
		areas = bpy.context.screen.areas
		for area in areas:
			if area.type == 'VIEW_3D':
				space = area.spaces.active
				#Force view mode with textures
				space.show_textured_solid = True
				if scn.render.engine == 'CYCLES':
					area.spaces.active.viewport_shade = 'TEXTURED'
				elif scn.render.engine == 'BLENDER_RENDER':
					area.spaces.active.viewport_shade = 'SOLID'
				#
				if newObjCreated:
					#Adjust floor grid and clip distance if the new obj is largest the actual settings
					if space.grid_lines*space.grid_scale < targetDst:
						space.grid_lines = nbLines
						space.grid_scale = scale
						space.clip_end = targetDst*10#10x more than necessary
					#Zoom to selected
					overrideContext = {'area': area, 'region':area.regions[-1]}
					bpy.ops.view3d.view_selected(overrideContext)

		return {'FINISHED'}

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

import os
import numpy as np
import bpy, bmesh

from ...core.georaster import GeoRaster


def rasterExtentToMesh(name, rast, dx, dy, pxLoc='CORNER', reproj=None, subdivise=False):
	'''Build a new mesh that represent a georaster extent'''
	#create mesh
	bm = bmesh.new()
	if pxLoc == 'CORNER':
		pts = [(pt[0], pt[1]) for pt in rast.corners]#shift coords
	elif pxLoc == 'CENTER':
		pts = [(pt[0], pt[1]) for pt in rast.cornersCenter]
	#Reprojection
	if reproj is not None:
		pts = reproj.pts(pts)
	#build shifted flat 3d vertices
	pts = [bm.verts.new((pt[0]-dx, pt[1]-dy, 0)) for pt in pts]#upper left to botton left (clockwise)
	pts.reverse()#bottom left to upper left (anticlockwise --> face up)
	bm.faces.new(pts)
	#Create mesh from bmesh
	mesh = bpy.data.meshes.new(name)
	bm.to_mesh(mesh)
	bm.free()
	return mesh

def geoRastUVmap(obj, uvTxtLayer, rast, dx, dy, reproj=None):
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
			if reproj is not None:
				pt = reproj.pt(*pt)
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


#########################################

class bpyGeoRaster(GeoRaster):

	def __init__(self, path, subBoxGeo=None, useGDAL=False, clip=False, fillNodata=False):

		#First init parent class
		GeoRaster.__init__(self, path, subBoxGeo=subBoxGeo, useGDAL=useGDAL)

		#Before open the raster into blender we need to assert that the file can be correctly loaded and exploited
		#- it must be in a file format supported by Blender (jpeg, tiff, png, bmp, or jpeg2000) and not a GIS specific format
		#- it must not be coded in int16 because this datatype cannot be correctly handle as displacement texture (issue with negatives values)
		#- it must not be too large or it will overflow Blender memory
		#- it must does not contain nodata values because nodata is coded with a large value that will cause huge unwanted displacement
		if self.format not in ['GTiff', 'TIFF', 'BMP', 'PNG', 'JPEG', 'JPEG2000'] \
		or (clip and self.subBoxGeo is not None) \
		or fillNodata \
		or self.ddtype == 'int16':

			#Open the raster as numpy array (read only a subset if we want to clip it)
			if clip:
				img = self.readAsNpArray(subset=True)
			else:
				img = self.readAsNpArray()

			#always cast to float because it's the more convenient datatype for displace texture
			#(will not be normalized from 0.0 to 1.0 in Blender)
			img.cast2float()

			#replace nodata with interpolated values
			if fillNodata:
				img.fillNodata()

			#save to a new tiff file on disk
			filepath = os.path.splitext(self.path)[0] + '_bgis.tif'
			img.save(filepath)

			#reinit the parent class
			GeoRaster.__init__(self, filepath, useGDAL=useGDAL)

		#Open the file into Blender
		self._load()


	def _load(self, pack=False):
		'''Load the georaster in Blender'''
		try:
			self.bpyImg = bpy.data.images.load(self.path)
		except:
			raise IOError("Unable to open raster")
		if pack:
			self.bpyImg.pack()
		# Set image color space, it's very important because only
		# Linear, Non Color and Raw color spaces will return raw values...
		self.bpyImg.colorspace_settings.name = 'Non-Color'

	def unload(self):
		self.bpyImg.user_clear()
		bpy.data.images.remove(self.bpyImg)
		self.bpyImg = None

	@property
	def isLoaded(self):
		'''Flag if the image has been loaded in Blender'''
		if self.bpyImg is not None:
			return True
		else:
			return False
	@property
	def isPacked(self):
		'''Flag if the image has been packed in Blender'''
		if self.bpyImg is not None:
			if len(self.bpyImg.packed_files) == 0:
				return False
			else:
				return True
		else:
			return False


	def exportAsMesh(self, dx=0, dy=0, step=1, subset=False, reproj=None):
		if subset and self.subBoxGeo is None:
			subset = False

		img = self.readAsNpArray(subset=subset)
		#TODO raise error if multiband
		data = img.data
		x0, y0 = self.origin

		#Avoid using bmesh because it's very slow with large mesh
		#use from_pydata instead
		#bm = bmesh.new()
		verts = []
		for px in range(0, self.size.x, step):
			for py in range(0, self.size.y, step):
				x = x0 + (self.pxSize.x * px)
				y = y0 +(self.pxSize.y * py)

				if reproj is not None:
					x, y = reproj.pt(x, y)

				#shift
				x -= dx
				y -= dy

				z = data[py, px]
				if z != self.noData:
					#bm.verts.new((x, y, z))
					verts.append((x, y, z))

		mesh = bpy.data.meshes.new("DEM")
		#bm.to_mesh(mesh)
		#bm.free()
		mesh.from_pydata(verts, [], [])
		mesh.update()

		return mesh

	###############################################
	# Old methods that use bpy.image.pixels and numpy, keeped here as history
	# depreciated because bpy is too slow and we need to process the image before load it in Blender
	###############################################

	def toBitDepth(self, a):
		"""
		Convert Blender pixel intensity value (from 0.0 to 1.0)
		in true pixel value in initial image bit depth range
		"""
		return a * (2**self.depth - 1)

	def fromBitDepth(self, a):
		"""
		Convert true pixel value in initial image bit depth range
		to Blender pixel intensity value (from 0.0 to 1.0)
		"""
		return a / (2**self.depth - 1)

	def getPixelsArray(self, bandIdx=None, subset=False):
		'''
		Use bpy to extract pixels values as numpy array
		In numpy fist dimension of a 2D matrix represents rows (y) and second dimension represents cols (x)
		so to get pixel value at a specified location be careful not confusing axes: data[row, column]
		It's possible to swap axes if you prefere accessing values with [x,y] indices instead of [y,x]: data.swapaxes(0,1)
		Array origin is top left
		'''
		if not self.isLoaded:
			raise IOError("Can read only image opened in Blender")
		if self.ddtype is None:
			raise IOError("Undefined data type")
		if subset and self.subBoxGeo is None:
			return None
		nbBands = self.bpyImg.channels #Blender will return 4 channels even with a one band tiff
		# Make a first Numpy array in one dimension
		a = np.array(self.bpyImg.pixels[:])#[r,g,b,a,r,g,b,a,r,g,b,a, ... ] counting from bottom to up and left to right
		# Regroup rgba values
		a = a.reshape(len(a)/nbBands, nbBands)#[[r,g,b,a],[r,g,b,a],[r,g,b,a],[r,g,b,a]...]
		# Build 2 dimensional array (In numpy first dimension represents rows (y) and second dimension represents cols (x))
		a = a.reshape(self.size.y, self.size.x, nbBands)# [ [[rgba], [rgba]...], [lines2], [lines3]...]
		# Change origin to top left
		a = np.flipud(a)
		# Swap axes to access pixels with [x,y] indices instead of [y,x]
		##a = a.swapaxes(0,1)
		# Extract the requested band
		if bandIdx is not None:
			a = a[:,:,bandIdx]
		# In blender, non float raster pixels values are normalized from 0.0 to 1.0
		if not self.isFloat:
			# Multiply by 2**depth - 1 to get raw values
			a = self.toBitDepth(a)
			# Round the result to nearest int and cast to orginal data type
			# when cast signed 16 bits dataset, the negatives values are correctly interpreted by numpy
			a = np.rint(a).astype(self.ddtype)
			# Get the negatives values from signed int16 raster
			# This part is no longer needed because previous numpy's cast already did the job
			'''
			if self.ddtype == 'int16':
				#16 bits allows coding values from 0 to 65535 (with 65535 == 2**depth / 2 - 1 )
				#positives value are coded from 0 to 32767 (from 0.0 to 0.5 in Blender)
				#negatives values are coded in reverse order from 65535 to 32768 (1.0 to 0.5 in Blender)
				#corresponding to a range from -1 to -32768
				a = np.where(a > 32767, -(65536-a), a)
			'''
		if not subset:
			return a
		else:
			# Get overlay extent (in pixels)
			subBoxPx = self.subBoxPx
			# Get subset data (min and max pixel number are both include)
			a = a[subBoxPx.ymin:subBoxPx.ymax+1, subBoxPx.xmin:subBoxPx.xmax+1] #topleft to bottomright
			return a


	def flattenPixelsArray(self, px):
		'''
		Flatten a 3d array of pixels to match the shape of bpy.pixels
		[ [[rgba], [rgba]...], [lines2], [lines3]...] >> [r,g,b,a,r,g,b,a,r,g,b,a, ... ]
		If the submited array contains only one band, then the band will be duplicate
		and an alpha band will be added to get all rgba values.
		'''
		shape = px.shape
		if len(shape) == 2:
			px = np.expand_dims(px, axis=2)
			px = np.repeat(px, 3, axis=2)
			alpha = np.ones(shape)
			alpha = np.expand_dims(alpha, axis=2)
			px = np.append(px, alpha, axis=2)
		#px = px.swapaxes(0,1)
		px = np.flipud(px)
		px = px.flatten()
		return px

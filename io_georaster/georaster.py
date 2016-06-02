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
import math
import bpy
#import bmesh
import numpy as np
from . import Tyf #geotags reader
from .utils import xy, GRS80, bbox, overlap, OverlapError
from .utils import getImgFormat, getImgDim
from .utils import replace_nans #inpainting function (ie fill nodata)

try:
	from osgeo import gdal
	GDAL_PY = True
except:
	GDAL_PY = False


class GeoRaster():
	'''A class to represent and load a georaster in Blender'''

	def initPropsModel(self):
		'''Properties model'''
		## Path infos
		self.path = None
		self.format = None #image file format (jpeg, tiff, png ...)
		self.wfPath = None
		## Data infos
		self.size = None #raster dimension (width, height) in pixel
		self.depth = None #8, 16, 32
		self.dtype = None #int, uint, float
		self.nbBands = None
		self.noData = None
		## Georef infos
		self.origin = None #upper left geo coords of pixel center
		self.pxSize = None #dimension of a pixel in map units (x scale, y scale)
		#   (y scale is negative because image origin is upper-left whereas map origin is lower-left)
		self.rotation = None #rotation terms (xrot, yrot) <--> (yskew, xskew)
		## Subbox (a bbox object that define the working extent of a subdataset)
		self.subBox = None
		## Stats
		self.min, self.max = None, None
		self.submin, self.submax = None, None
		## Flags
		self.angCoords = False #flag if raster coordinate system uses anglular units (lonlat)
		self.bpyImg = None #a pointer to bpy loaded image



	def __init__(self, path, angCoords=False, subBox=None, clip=False, fillNodata=False):
		'''
		The main purpose of this initialization step is to get a loaded image in Blender
		with all needed infos (georef, data type ...). If the data source must be edited to be
		fully usuable in Blender (like format conversion, raster calculation ...) then we must
		launch these process from here. Image will be packed only if it has been edited.
		'''
		#init properties model
		self.initPropsModel()
		
		#Get infos from path
		self.path = path
		self.format = getImgFormat(path)
		if self.format not in ['TIFF', 'BMP', 'PNG', 'JPEG', 'JPEG2000']:
			raise IOError("Unsupported format")
		self.wfPath = self.getWfPath()

		#Try to get georef infos
		self.getGeoref()
		# convert angulars coords to meters if needed
		self.angCoords = angCoords
		if self.angCoords:
			self.degrees2meters()

		# Try to get the raster size
		self.getRasterSize()

		# Assign subBox (will check if the box overlap the raster extent)
		# define a subbox at init is optionnal, we can also do it later 
		if subBox is not None:
			self.setSubBox(subBox)

		# Get data type infos from tiff tags
		# Other format aren't supported, so some functions will only works with tiff
		if self.isTiff:
			self.getDataType()

		# Now open the file in Blender
		self.load()
		
		# Create a new image if we need to clip or fill nodata
		# Also, we assume int16 raster always contains some negatives values (if not it must be uint16...)
		# to make signed 16 bits raster usuable as displacement texture the best way is to cast it to float
		# so create a copy in this case too (copy will always be cast to float)
		if (clip and self.subBox is not None) or fillNodata or self.ddtype == 'int16':
			self.copy(clip=clip, fillNodata=fillNodata)


	############################################
	# Helpers for initialization process
	############################################


	def load(self, pack=False):
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

	def getRasterSize(self):
		if self.isLoaded:
			# use bpy reader to get raster size
			self.size = xy(self.bpyImg.size[0], self.bpyImg.size[1])
		elif self.isTiff:
			# read size in tiff tags
			tif = Tyf.open(self.path)[0]
			self.size = xy(tif['ImageWidth'], tif['ImageLength'])
		else:
			# Try to read header
			w, h = getImgDim(self.path)
			if w is None and h is None:
				raise IOError("Unable to read raster size")
			else:
				self.size = xy(w, h)


	def getGeoref(self):
		'''
		Try to get geotransformation parameters
		Search first for a worldfile, if it not exists try to read geotiff tags
		'''
		if self.wfPath is not None:
			self.readWf()
		if not self.isGeoref and self.isTiff:
			self.readGeoTags()
		if not self.isGeoref:
			raise IOError("Unable to read georef infos from worldfile or geotiff tags")


	def getWfPath(self):
		'''Try to find a worlfile path for this raster'''
		ext = self.path[-3:].lower()
		extTest = []
		extTest.append(ext[0] + ext[2] +'w')#tif --> tfw, jpg --> jgw, bmp --> bpw, png --> pgw ...
		extTest.append(extTest[0]+'x')#tif --> tfwx, jpg --> jgwx, bmp --> bpwx, png --> pgwx ...
		extTest.append(ext+'w')#tif --> tifw, jpg --> jpgw, bmp --> bmpw, png --> pngw ...
		extTest.append('wld')#*.wld
		extTest.extend( [ext.upper() for ext in extTest] )
		for wfExt in extTest:
			pathTest = self.path[0:len(self.path)-3] + wfExt
			if os.path.isfile(pathTest):
				return pathTest
		return None


	def readWf(self):
		'''Extract geotransformation parameters from a worldfile'''
		try:
			f = open(self.wfPath,'r')
			wfParams = f.readlines()
			f.close()
			self.pxSize = xy(float(wfParams[0].replace(',','.')), float(wfParams[3].replace(',','.')))
			self.rotation = xy(float(wfParams[1].replace(',','.')), float(wfParams[2].replace(',','.')))
			#upper left pixel center
			self.origin = xy(float(wfParams[4].replace(',','.')), float(wfParams[5].replace(',','.')))
		except:
			raise IOError("Unable to read worldfile")


	def getDataType(self):
		'''Extract data type infos from tiff tags'''
		if not self.isTiff or not self.fileExists:
			return
		tif = Tyf.open(self.path)[0]
		self.nbBands = tif['SamplesPerPixel']
		self.depth = tif['BitsPerSample']
		if self.nbBands > 1:
			self.depth = self.depth[0]
		sampleFormatMap = {1:'uint', 2:'int', 3:'float', None:'uint', 6:'complex'}
		try:
			self.dtype = sampleFormatMap[tif['SampleFormat']]
		except:
			self.dtype = 'uint'
		try:
			self.noData = float(tif['GDAL_NODATA'])
		except:
			self.noData = None


	def readGeoTags(self):
		'''Extract geo transformation parameters from a geotiff tags'''
		if not self.isTiff or not self.fileExists:
			return
		tif = Tyf.open(self.path)[0]
		#First search for a matrix transfo
		try:
			#34264: ("ModelTransformation", "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p")
			# 4x4 transform matrix in 3D space
			transfoMatrix = tif['ModelTransformation']
			a,b,c,d,
			e,f,g,h,
			m,n,o,p = transfoMatrix
			#get only 2d affine parameters
			self.origin = xy(d, h)
			self.pxSize = xy(a, f)
			self.rotation = xy(e, b)
		except:
			#If no matrix, search for upper left coord and pixel scales
			try:
				#33922: ("ModelTiepoint", "I,J,K,X,Y,Z")
				modelTiePoint = tif['ModelTiepointTag']
				#33550 ("ModelPixelScale", "ScaleX, ScaleY, ScaleZ")
				modelPixelScale = tif['ModelPixelScaleTag']
				self.origin = xy(*modelTiePoint[3:5])
				self.pxSize = xy(*modelPixelScale[0:2])
				self.pxSize[1] = -self.pxSize.y #make negative value
				self.rotation = xy(0, 0)
			except:
				raise IOError("Unable to read geotags")
		#Instead of worldfile, topleft geotag is at corner, so adjust it to pixel center
		self.origin[0] += abs(self.pxSize.x/2)
		self.origin[1] -= abs(self.pxSize.y/2)


	def degrees2meters(self):
		"""
		Use equirectangular projection to convert angular units to meters
		True at equator only, horizontal distortions will increase according to distance from it
		"""
		k = GRS80.perimeter/360
		self.pxSize = xy(*[v*k for v in self.pxSize])
		self.origin = xy(*[v*k for v in self.origin])



	#######################################
	# Dynamic properties
	#######################################
	@property
	def fileExists(self):
		'''Test if the file exists on disk'''
		return os.path.isfile(self.path)
	@property
	def baseName(self):
		if self.path is not None:
			folder, fileName = os.path.split(self.path)
			baseName, ext = os.path.splitext(fileName)
			return baseName
	@property
	def isTiff(self):
		'''Flag if the image format is TIFF'''
		if self.format == 'TIFF' or self.format == 'GTiff':
			return True
		else:
			return False
	@property
	def isGeoref(self):
		'''Flag if georef parameters have been extracted'''
		if self.origin is not None and self.pxSize is not None and self.rotation is not None:
			return True
		else:
			return False
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
	@property
	def isOneBand(self):
		return self.nbBands == 1
	@property
	def isFloat(self):
		return self.dtype in ['Float', 'float']
	@property
	def ddtype(self):
		'''
		Get data type and depth in a concatenate string like
		'int8', 'int16', 'uint16', 'int32', 'uint32', 'float32' ...
		Can be used to define numpy or gdal data type
		'''
		if self.dtype is None or self.depth is None:
			return None
		else:
			return self.dtype + str(self.depth)
	@property
	def cornersCenter(self):
		'''
		(x,y) geo coordinates of image corners (upper left, upper right, bottom right, bottom left)
		(pt1, pt2, pt3, pt4) <--> (upper left, upper right, bottom right, bottom left)
		The coords are located at the pixel center
		'''
		xPxRange = self.size.x-1#number of pixels is range from 0 (not 1)
		yPxRange = self.size.y-1
		#pixel center
		pt1 = self.geoFromPx(0, yPxRange, True)#upperLeft
		pt2 = self.geoFromPx(xPxRange, yPxRange, True)#upperRight
		pt3 = self.geoFromPx(xPxRange, 0, True)#bottomRight
		pt4 = self.geoFromPx(0, 0, True)#bottomLeft
		return (pt1, pt2, pt3, pt4)
	@property
	def corners(self):
		'''
		(x,y) geo coordinates of image corners (upper left, upper right, bottom right, bottom left)
		(pt1, pt2, pt3, pt4) <--> (upper left, upper right, bottom right, bottom left)
		Represent the true corner location (upper left for pt1, upper right for pt2 ...)
		'''
		#get corners at center
		pt1, pt2, pt3, pt4 = self.cornersCenter
		#pixel center offset
		xOffset = abs(self.pxSize.x/2)
		yOffset = abs(self.pxSize.y/2)
		pt1 = xy(pt1.x - xOffset, pt1.y + yOffset)
		pt2 = xy(pt2.x + xOffset, pt2.y + yOffset)
		pt3 = xy(pt3.x + xOffset, pt3.y - yOffset)
		pt4 = xy(pt4.x - xOffset, pt4.y - yOffset)
		return (pt1, pt2, pt3, pt4)
	@property
	def bbox(self):
		'''Return a bbox class object'''
		xmin = min([pt.x for pt in self.corners])
		xmax = max([pt.x for pt in self.corners])
		ymin = min([pt.y for pt in self.corners])
		ymax = max([pt.y for pt in self.corners])
		return bbox(xmin, xmax, ymin, ymax)
	@property
	def center(self):
		'''(x,y) geo coordinates of image center'''
		return xy(self.corners[0].x + self.geoSize.x/2, self.corners[0].y - self.geoSize.y/2)
	@property
	def geoSize(self):
		'''raster dimensions (width, height) in map units'''
		return xy(self.size.x * abs(self.pxSize.x), self.size.y * abs(self.pxSize.y))
	@property
	def orthoGeoSize(self):
		'''ortho geo size when affine transfo applied a rotation'''
		pxWidth = math.sqrt(self.pxSize.x**2 + self.rotation.x**2)
		pxHeight = math.sqrt(self.pxSize.y**2 + self.rotation.y**2)
		return xy(self.size.x*pxWidth, self.size.y*pxHeight)
	@property
	def orthoPxSize(self):
		'''ortho pixels size when affine transfo applied a rotation'''
		pxWidth = math.sqrt(self.pxSize.x**2 + self.rotation.x**2)
		pxHeight = math.sqrt(self.pxSize.y**2 + self.rotation.y**2)
		return xy(pxWidth, pxHeight)
	@property
	def subBoxPx(self):
		'''xmin, xmax, ymin, ymax of the subbox in pixels coordinates space'''
		return self.bbox2Px(self.subBox, reverseY=False)
	@property
	def subBoxSize(self):
		'''dimension of the subbox in pixels'''
		if self.subBox is None:
			return None
		bbpx = self.subBoxPx
		w, h = bbpx.xmax - bbpx.xmin, bbpx.ymax - bbpx.ymin
		#min and max pixel number are both include 
		#so we must add 1 to get the correct size
		return xy(w+1, h+1)
	@property
	def subBoxGeoSize(self):
		'''dimension of the subbox in map units'''
		subsize = self.subBoxSize
		if subsize is not None:
			return xy(subsize.x * abs(self.pxSize.x), subsize.y * abs(self.pxSize.y))
	@property
	def subBoxOrigin(self):	
		subBoxPx = self.subBoxPx
		return self.geoFromPx(subBoxPx.xmin, subBoxPx.ymin) #px center


	def __str__(self):
		'''Brute force print...'''
		print('------------')
		print('* Paths infos :')
		print(' path %s' %self.path)
		print(' worldfile %s' %self.wfPath)
		print(' format %s' %self.format)
		#
		print('* Data infos :')
		print(' size %s' %self.size)
		print(' depth %s' %(self.depth,))
		print(' dtype %s' %self.dtype)
		print(' number of bands %i' %self.nbBands)
		print(' nodata value %s' %self.noData)
		#
		print('* Georefs infos')
		print(' is georef %s' %self.isGeoref)
		print(' origin %s' %self.origin)
		print(' pixel size %s' %self.pxSize)
		print(' rotation %s' %self.rotation)
		print(' angular %s' %self.angCoords)
		#
		print('* Statistics')
		print(' min max %s' %((self.min, self.max), ))
		print(' submin submax %s' %( (self.submin, self.submax), ))
		#
		print('* State in Blender')
		print(' is loaded %s' %self.isLoaded)
		print(' is packed %s' %self.isPacked)
		#
		print('* Geometry')
		print(' bbox %s' %self.bbox)
		print(' geoSize %s' %self.geoSize)
		#print('	orthoGeoSize %s' %self.orthoGeoSize)
		#print('	orthoPxSize %s' %self.orthoPxSize)  
		#print('	corners %s' %([p.xy for p in self.corners],))
		#print('	center %s' %self.center)
		print(' subbox (geo space) %s' %self.subBox)
		print(' subbox (px space) %s' %self.subBoxPx)
		print(' sub geoSize %s' %self.subBoxGeoSize)
		print(' sub pxSize %s' %self.subBoxSize)
		return "------------"

	#######################################
	# Methods
	#######################################

	def geoFromPx(self, xPx, yPx, reverseY=False):
		"""
		Affine transformation (cf. ESRI WorldFile spec.)
		Return geo coords of the center of an given pixel
		xPx = the column number of the pixel in the image counting from left
		yPx = the row number of the pixel in the image counting from top
		use reverseY option is yPx is counting from bottom
		Number of pixels is range from 0 (not 1)
		"""
		if reverseY:#the users given y pixel in the image counting from bottom
			yPxRange = self.size.y - 1
			yPx = yPxRange - yPx
		#
		x = self.pxSize.x * xPx + self.rotation.y * yPx + self.origin.x
		y = self.pxSize.y * yPx + self.rotation.x * xPx + self.origin.y
		return xy(x, y)


	def pxFromGeo(self, x, y, reverseY=False, round2Floor=False):
		"""
		Affine transformation (cf. ESRI WorldFile spec.)
		Return pixel position of given geographic coords
		use reverseY option to get y pixels counting from bottom
		Pixels position is range from 0 (not 1)
		"""
		# aliases for more readability
		pxSizex, pxSizey = self.pxSize
		rotx, roty = self.rotation
		offx, offy = self.origin
		#
		xPx  = (pxSizey*x - rotx*y + rotx*offy - pxSizey*offx) / (pxSizex*pxSizey - rotx*roty)
		yPx = (-roty*x + pxSizex*y + roty*offx - pxSizex*offy) / (pxSizex*pxSizey - rotx*roty)
		if reverseY:#the users want y pixel position counting from bottom
			yPxRange = self.size.y - 1#number of pixels is range from 0 (not 1)
			yPx = yPxRange - yPx
		#offset the result of 1/2 px to get the good value
		xPx += 0.5
		yPx += 0.5
		#round to floor
		if round2Floor:
			xPx, yPx = math.floor(xPx), math.floor(yPx)
		return xy(xPx, yPx)

	def bbox2Px(self, bb, reverseY=False):
		'''
		Convert a bounding box from geo coords to pixels coords
		input: a bbox class object that represent an extent in geo coords
		output: a bbox class object that represent the extent converted in pixels coords
		if needed, pixels coords are adjusted to avoid being outside raster size
		use reverseY option to get y pixels counting from bottom
		'''
		xmin, ymax = self.pxFromGeo(bb.xmin, bb.ymin, round2Floor=True)#y pixels counting from top
		xmax, ymin = self.pxFromGeo(bb.xmax, bb.ymax, round2Floor=True)#idem
		if reverseY:#y pixels counting from bottom
			ymin, ymax = ymax, ymin
		# adjust bounds of bbox against raster size
		# warn, we count pixel number from 0 but size represents total number of pixel (counting from 1)
		# so we must use size-1
		sizex, sizey = self.size
		if xmin < 0: xmin = 0
		if xmax > sizex: xmax = sizex - 1
		if ymin < 0: ymin = 0
		if ymax > sizey: ymax = sizey - 1
		return bbox(xmin, xmax, ymin, ymax)#xmax and ymax include


	def setSubBox(self, subBox):
		'''Before set the property, ensure that the desired subbox overlap the raster extent'''
		if not self.isGeoref:
			raise IOError("Not georef")
		if not overlap(self.bbox, subBox):
			raise OverlapError()
		elif subBox.xmin <= self.bbox.xmin and subBox.xmax >= self.bbox.xmax and subBox.ymin <= self.bbox.ymin and subBox.ymax >= self.bbox.ymax:
			#Ignore because subbox is greater than raster extent
			return
		else:
			self.subBox = subBox


	def exportAsMesh(self, dx=0, dy=0, step=1, subset=False):
		if subset and self.subBox is None:
			subset = False
		
		data = self.readAsNpArray(0, subset)
		x0, y0 = self.origin
		x0 -= dx
		y0 -= dy
		
		#Avoid using bmesh because it's very slow with large mesh
		#use from-pydata instead
		#bm = bmesh.new()
		verts = []
		for px in range(0, self.size.x, step):
			for py in range(0, self.size.y, step):
				x = x0 + (self.pxSize.x * px)
				y = y0 +(self.pxSize.y * py)
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
	# Methods that use bpy.image.pixels and numpy
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

	def fillNodata(self, data):
		'''
		Call the inpainting function on an given array
		return an array with nodata filled
		'''
		# Mask noData
		data =  np.ma.masked_array(data, data == self.noData)
		# Fill mask with NaN (warning NaN is a special value for float arrays only)
		if not self.isFloat:
			data = data.astype('float32')
		data =  np.ma.filled(data, np.NaN)
		# Inpainting
		data = replace_nans(data, max_iter=5, tolerance=0.5, kernel_size=2, method='localmean')
		return data

	def readAsNpArray(self, bandIdx=None, subset=False):
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
		if subset and self.subBox is None:
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


	def getStats(self):
		'''
		Use Numpy to compute min and max stats of a one band tiff (use the first band only)
		if a sub working extent is defined, it will also compute stats for this subset
		'''
		# Check some asserts
		if self.ddtype is None:
			raise IOError("Undefined data type")
		if self.ddtype not in ['int8', 'int16', 'uint16', 'int32', 'uint32', 'float32']:
			raise IOError("Unsupported data type")
		if not self.isLoaded:
			raise IOError("Can compute stats only for image open in Blender")
		if not self.isOneBand:
			raise IOError("Can compute stats only for one band raster")
		# Get data from first band
		band = self.readAsNpArray(0)
		# Mask noData before compute stats
		if self.noData is not None:
			band =  np.ma.masked_array(band, band == self.noData)
		# Set whole stats properties
		self.min, self.max = band.min(), band.max()
		# Set sub stats
		if self.subBox is not None:
			subBoxPx = self.subBoxPx
			subSet = band[subBoxPx.ymin:subBoxPx.ymax+1, subBoxPx.xmin:subBoxPx.xmax+1]
			self.submin, self.submax = subSet.min(), subSet.max()


	def copy(self, clip=False, fillNodata=False):
		'''
		Use bpy and numpy to create directly in Blender a new copy of the raster.
		
		This method provides some usefull options:
		
		* clip : will clip the raster according to the working extent define in subBox property.
		
		* fillNodata : use an inpainting method based on numpy to fill nodata values. Nodata is generally
		representent with a very high or low value. It's why using raster that contains nodata as displacement 
		texture can give huge unwanted glitch. Fill nodata help to get smooth results.
		
		This function always force data type to float32. For our purpose, float raster are easiest to use 
		because, instead of integer data, they will not be normalized from 0.0 to 1.0 in Blender.
		Also, signed 16bits raster that contains negatives must be cast to float to be usuable
		as displacement texture.
		'''
		# Check some assert
		if self.ddtype is None:
			raise IOError("Undefined data type")
		if self.ddtype not in ['int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'float32']:
			raise IOError("Unsupported data type")
		if not self.isLoaded:
			raise IOError("Copy() available only for image loaded in Blender")
		# Get data
		if self.isOneBand:
			bandIdx = 0
		else:
			bandIdx = None
		if clip and self.subBox is not None:
			# Get subset data from first band
			data = self.readAsNpArray(bandIdx, subset=True)	
		else:
			data = self.readAsNpArray(bandIdx)
			clip = False #force clip to false
		#Fill nodata
		if fillNodata and self.noData is not None:
			if self.noData in data:
				data = self.fillNodata(data)
		# Create a new image in Blender
		height, width = data.shape
		img = bpy.data.images.new(self.baseName, width, height, alpha=False, float_buffer=True)
		# Write pixels values to it
		img.pixels = self.flattenPixelsArray(data)
		# Save/pack
		img.pack(as_png=True) #as_png needed for generated images
		# Remove old image
		self.bpyImg.user_clear()
		bpy.data.images.remove(self.bpyImg)
		# Update class properties
		self.path = None
		self.bpyImg = img
		self.dtype = 'float'
		self.depth = 32
		if clip:
			self.size = xy(*img.size)
			self.origin = self.subBoxOrigin
			self.min, self.max = self.submin, self.submax
			self.subBox = None

		return True



#------------------------------------------------------------------------


class GeoRasterGDAL(GeoRaster):
	'''
	A subclass of GeoRaster that use GDAL to override some methods.
	
	Reading pixels is now performed through GDAL API and does not use 
	bpy.image.pixels method anymore.
	
	All overriden functions which required reading pixels now operate 
	directly on source file and before the image is loaded in Blender. 
	
	This way prevents memory overflow when trying to open and clip a 
	large dataset.
	'''

	def __init__(self, path, angCoords=False, subBox=None, clip=False, fillNodata=False):
		
		if not GDAL_PY:
			raise ImportError('GDAL Python binding is not installed')
		
		# Init properties model
		self.initPropsModel()

		# Get infos from path
		self.path = path

		# Get data and georef infos
		self.getGdalInfos()

		# Convert angulars coords to meters if needed
		self.angCoords = angCoords
		if self.angCoords:
			self.degrees2meters()

		# Define subbox
		if subBox is not None:
			self.setSubBox(subBox)

		# If needed, convert to a format readable by Blender
		# and/or clip to the subbox extent / fill nodata values / cast to float32
		if self.format not in ['BMP', 'GTiff', 'JPEG', 'PNG', 'JPEG2000'] or (clip and self.subBox is not None) or fillNodata or self.ddtype == 'int16':
			self.copy(clip=clip, fillNodata=fillNodata)
		else:
			self.load()



	#overrides
	def getRasterSize(self):
		self.getGdalInfos()
	def getDataType(self):
		self.getGdalInfos()
	def getGeoref(self):
		self.getGdalInfos()


	def getGdalInfos(self):
		'''Extract data type infos'''
		if self.path is None or not self.fileExists:
			raise IOError("Cannot find file on disk")
		# Open dataset
		ds = gdal.Open(self.path, gdal.GA_ReadOnly)
		# Get raster size
		self.size = xy(ds.RasterXSize, ds.RasterYSize)
		# Get format
		self.format = ds.GetDriver().ShortName
		if self.format in ['JP2OpenJPEG', 'JP2ECW', 'JP2KAK', 'JP2MrSID'] :
			self.format = 'JPEG2000'
		# Get band
		self.nbBands = ds.RasterCount
		b1 = ds.GetRasterBand(1) #first band (band index does not count from 0)
		self.noData = b1.GetNoDataValue()
		# Get data type
		ddtype = gdal.GetDataTypeName(b1.DataType)#Byte, UInt16, Int16, UInt32, Int32, Float32, Float64
		if ddtype == "Byte":
			self.dtype = 'uint'
			self.depth = 8
		else:
			self.dtype = ddtype[0:len(ddtype)-2].lower()
			self.depth = int(ddtype[-2:])
		#Get Georef	
		params = ds.GetGeoTransform()
		if params is not None:
			topleftx, pxsizex, rotx, toplefty, roty, pxsizey = params
			#instead of worldfile, topleft geotag is at corner, so adjust it to pixel center
			topleftx += abs(pxsizex/2)
			toplefty -= abs(pxsizey/2)
			#assign to class properties
			self.origin = xy(topleftx, toplefty)
			self.pxSize = xy(pxsizex, pxsizey)
			self.rotation = xy(rotx, roty)
		#Close (gdal haven't garbage collector)
		ds, b1 = None, None


	#override
	def getStats(self):
		if self.path is None or not self.fileExists:
			if self.isLoaded:
				return super().getStats()
			else:
				raise IOError("Cannot find raster on disk or in Blender data")
		ds = gdal.Open(self.path, gdal.GA_ReadOnly)
		b1 = ds.GetRasterBand(1) #first band (band index does not count from 0)
		min, max = b1.GetMinimum(), b1.GetMaximum()
		if min is None or max is None:
			min, max = b1.ComputeRasterMinMax()
		self.min, self.max = min, max
		if self.subBox:
			#use gdal readAsArray method to get the subset in a numpy array
			#origin of the raster is top left
			subBoxPx = self.subBoxPx
			startx, starty = subBoxPx.xmin, subBoxPx.ymin
			width =  subBoxPx.xmax - subBoxPx.xmin
			height = subBoxPx.ymax - subBoxPx.ymin
			subSet = b1.ReadAsArray(startx, starty, width, height).astype(self.ddtype)
			# mask noData
			if self.noData is not None:
				subSet =  np.ma.masked_array(subSet, subSet == self.noData)
			self.submin, self.submax = subSet.min(), subSet.max()
		ds, b1 = None, None


	#override
	def readAsNpArray(self, bandIdx=None, subset=False):
		'''
		Use gdal to extract pixels values as numpy array
		In numpy fist dimension of a 2D matrix represents rows (y) and second dimension represents cols (x)
		so be careful not confusing axes and use syntax like data[row, column]
		Array origin is top left
		'''
		
		#GDAL need a file on disk, but in some case init() will create a new altered copy directly in Blender.
		#In this case the class does not refer anymore to the file on disk but to the image in Blender data
		#and so, we must call the method of the parent class which use bpy to access pixels values
		if self.path is None or not self.fileExists:
			if self.isLoaded:
				return super().readAsNpArray(bandIdx, subset)
			else:
				raise IOError("Cannot find raster on disk or in Blender data")

		#ReadAsArray was implemented at both Dataset and Band levels
		#so when a raster has more than 1 band, it can be read as a 3D array
		ds = gdal.Open(self.path, gdal.GA_ReadOnly)
		if bandIdx is not None:
			b = ds.GetRasterBand(bandIdx+1) #band index does not count from 0
		#
		if not subset:
			if bandIdx is None:
				data = ds.ReadAsArray()
			else:
				data = b.ReadAsArray()
		else:
			if self.subBox is None:
				data = None
			else:
				subBoxPx = self.subBoxPx
				startx, starty = subBoxPx.xmin, subBoxPx.ymin
				width, height = self.subBoxSize
				#
				if bandIdx is None:
					data = ds.ReadAsArray(startx, starty, width, height)
				else:
					data = b.ReadAsArray(startx, starty, width, height)
		#Close and return
		if bandIdx is not None: b = None
		ds = None
		return data


	#override
	def fillNodata(self, data):
		'''
		Call gdal fillnodata function on an given np array
		return an array with nodata filled
		'''
		# gdal.FillNodata need a band object to apply on
		# so we create a memory datasource (1 band, float)
		height, width = data.shape
		ds = gdal.GetDriverByName('MEM').Create('', width, height, 1, gdal.GetDataTypeByName('float32'))
		b = ds.GetRasterBand(1)
		b.SetNoDataValue(self.noData)
		b.WriteArray(data)
		gdal.FillNodata(targetBand=b, maskBand=None, maxSearchDist=max(self.size.xy), smoothingIterations=0)
		data = b.ReadAsArray()
		ds, b = None, None
		return data


	#override
	def copy(self, clip=False, fillNodata=False):
		'''
		Use gdal and numpy to create directly in Blender a new copy of the raster.
		Data type is always cast to float32.
		
		This method provides some usefull options:
		* clip : will clip the raster according to the working extent define in subBox property.
		* fillNodata : use gdal fillnodata function.
		'''
		
		# Check some assert
		if self.path is None or not self.fileExists:
			raise IOError("Cannot find file on disk")

		# Get data
		if self.isOneBand:
			bandIdx = 0
		else:
			bandIdx = None

		if clip and self.subBox is not None:
			data = self.readAsNpArray(bandIdx, subset=True)
		else:
			data = self.readAsNpArray(bandIdx)
			clip = False #force clip to False

		#fill nodata
		if fillNodata and self.noData is not None:
			if self.noData in data:
				data = self.fillNodata(data)

		# Create a new float image in Blender
		height, width = data.shape
		img = bpy.data.images.new(self.baseName, width, height, alpha=False, float_buffer=True)
		# Write pixels values to it
		img.pixels = self.flattenPixelsArray(data)
		# Save/pack
		img.pack(as_png=True) #as_png needed for generated images)  

		# Update class properties
		self.path = None
		self.bpyImg = img
		self.dtype = 'float'
		self.depth = 32
		if clip:
			self.size = xy(*img.size)
			self.origin = self.subBoxOrigin
			self.min, self.max = self.submin, self.submax
			self.subBox = None

		return True

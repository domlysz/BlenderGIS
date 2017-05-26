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
import io
import random

import numpy as np

import bpy #TODO split georaster_bpy from core

from ..lib import Tyf #geotags reader
from .utils import replace_nans #inpainting function (ie fill nodata)

from ..utils.proj import reprojPt, reprojBbox, SRS
from ..utils.geom import XY as xy, BBOX
from ..utils.errors import OverlapError
from ..utils.img import getImgFormat, getImgDim

from ..checkdeps import HAS_GDAL, HAS_PIL, HAS_IMGIO

if HAS_PIL:
	from PIL import Image

if HAS_GDAL:
	from osgeo import gdal

if HAS_IMGIO:
	from ..lib import imageio


###
import imghdr
def isValidStream(data):
	if data is None:
		return False
	format = imghdr.what(None, data)
	if format is None:
		return False
	return True

###


class GeoRef():
	'''
	Represents georefencing informations of a raster image
	Note : image origin is upper-left whereas map origin is lower-left
	'''

	def __init__(self, rSize, pxSize, origin, rot=xy(0,0), pxCenter=True, subBoxGeo=None, crs=None):
		'''
		rSize : dimensions of the raster in pixels (width, height) tuple
		pxSize : dimension of a pixel in map units (x scale, y scale) tuple. y is always negative
		origin : upper left geo coords of pixel center, (x, y) tuple
		pxCenter : set it to True is the origin anchor point is located at pixel center
			or False if it's lolcated at pixel corner
		rotation : rotation terms (xrot, yrot) <--> (yskew, xskew)
		subBoxGeo : a BBOX object that define the working extent (subdataset) in geographic coordinate space
		'''
		self.rSize = xy(*rSize)
		self.origin = xy(*origin)
		self.pxSize = xy(*pxSize)
		if not pxCenter:
			#adjust topleft coord to pixel center
			self.origin[0] += abs(self.pxSize.x/2)
			self.origin[1] -= abs(self.pxSize.y/2)
		self.rotation = xy(*rot)
		if subBoxGeo is not None:
			# Define a subbox at init is optionnal, we can also do it later
			# Setting the subBox will check if the box overlap the raster extent
			self.setSubBoxGeo(subBoxGeo)
		else:
			self.subBoxGeo = None
		if crs is not None:
			if isinstance(crs, SRS):
				self.crs = crs
			else:
				raise IOError("CRS must be SRS() class object not " + str(type(crs)))
		else:
			self.crs = crs

	############################################
	# Alternative constructors
	############################################

	@classmethod
	def fromGDAL(cls, ds):
		'''init from gdal dataset instance'''
		geoTrans = ds.GetGeoTransform()
		if geoTrans is not None:
			xmin, resx, rotx, ymax, roty, resy = geoTrans
			w, h = ds.RasterXSize, ds.RasterYSize
			try:
				crs = SRS.fromGDAL(ds)
			except Exception as e:
				crs = None
			return cls((w, h), (resx, resy), (xmin, ymax), rot=(rotx, roty), pxCenter=False, crs=crs)
		else:
			return None

	@classmethod
	def fromWorldFile(cls, wfPath, rasterSize):
		'''init from a worldfile'''
		try:
			with open(wfPath,'r') as f:
				wf = f.readlines()
			pxSize = xy(float(wf[0].replace(',','.')), float(wf[3].replace(',','.')))
			rotation = xy(float(wf[1].replace(',','.')), float(wf[2].replace(',','.')))
			origin = xy(float(wf[4].replace(',','.')), float(wf[5].replace(',','.')))
			return cls(rasterSize, pxSize, origin, rot=rotation, pxCenter=True, crs=None)
		except:
			raise IOError("Unable to read worldfile")

	@classmethod
	def fromTyf(cls, tif):
		'''read geotags from Tyf instance'''
		w, h = tif['ImageWidth'], tif['ImageLength']
		#First search for a matrix transfo
		try:
			#34264: ("ModelTransformation", "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p")
			# 4x4 transform matrix in 3D space
			transfoMatrix = tif['ModelTransformationTag']
			a,b,c,d, \
			e,f,g,h, \
			i,j,k,l, \
			m,n,o,p = transfoMatrix
			#get only 2d affine parameters
			origin = xy(d, h)
			pxSize = xy(a, f)
			rotation = xy(e, b)
		except:
			#If no matrix, search for upper left coord and pixel scales
			try:
				#33922: ("ModelTiepoint", "I,J,K,X,Y,Z")
				modelTiePoint = tif['ModelTiepointTag']
				#33550 ("ModelPixelScale", "ScaleX, ScaleY, ScaleZ")
				modelPixelScale = tif['ModelPixelScaleTag']
				origin = xy(*modelTiePoint[3:5])
				pxSize = xy(*modelPixelScale[0:2])
				pxSize[1] = -pxSize.y #make negative value
				rotation = xy(0, 0)
			except:
				raise IOError("Unable to read geotags")
		#Define anchor point for top left coord
		#	http://www.remotesensing.org/geotiff/spec/geotiff2.5.html#2.5.2
		#	http://www.remotesensing.org/geotiff/spec/geotiff6.html#6.3.1.2
		# >> 1 = area (cell anchor = top left corner)
		# >> 2 = point (cell anchor = center)
		#geotags = Tyf.gkd.Gkd(tif)
		#cellAnchor = geotags['GTRasterTypeGeoKey']
		geotags = tif['GeoKeyDirectoryTag']
		try:
			#get GTRasterTypeGeoKey value
			cellAnchor = geotags[geotags.index(1025)+3] #http://www.remotesensing.org/geotiff/spec/geotiff2.4.html
		except:
			cellAnchor = 1 #if this key is missing then RasterPixelIsArea is the default
		if cellAnchor == 1:
			#adjust topleft coord to pixel center
			origin[0] += abs(pxSize.x/2)
			origin[1] -= abs(pxSize.y/2)
		#TODO extract crs (transcript geokeys to proj4 string)
		return cls((w, h), pxSize, origin, rot=rotation, pxCenter=True, crs=None)

	############################################
	# Export
	############################################

	def toGDAL(self):
		'''return a tuple of georef parameters ordered to define geotransformation of a gdal datasource'''
		xmin, ymax = self.corners[0]
		xres, yres = self.pxSize
		xrot, yrot = self.rotation
		return (xmin, xres, xrot, ymax, yrot, yres)

	def toWorldFile(self, path):
		'''export geo transformation to a worldfile'''
		xmin, ymax = self.origin
		xres, yres = self.pxSize
		xrot, yrot = self.rotation
		wf = (xres, xrot, yrot, yres, xmin, ymax)
		f = open(path,'w')
		f.write( '\n'.join(list(map(str, wf))) )
		f.close()

	############################################
	# Dynamic properties
	############################################

	@property
	def hasCRS(self):
		return self.crs is not None

	@property
	def hasRotation(self):
		return self.rotation.x != 0 or self.rotation.y != 0

	#TODO
	#def getCorners(self, center=True):
	#def getUL(self, center=True)

	"""
	@property
	def ul(self):
		'''upper left corner'''
		return self.geoFromPx(0, yPxRange, True)
	@property
	def ur(self):
		'''upper right corner'''
		return self.geoFromPx(xPxRange, yPxRange, True)
	@property
	def bl(self):
		'''bottom left corner'''
		return self.geoFromPx(0, 0, True)
	@property
	def br(self):
		'''bottom right corner'''
		return self.geoFromPx(xPxRange, 0, True)
	"""

	@property
	def cornersCenter(self):
		'''
		(x,y) geo coordinates of image corners (upper left, upper right, bottom right, bottom left)
		(pt1, pt2, pt3, pt4) <--> (upper left, upper right, bottom right, bottom left)
		The coords are located at the pixel center
		'''
		xPxRange = self.rSize.x-1#number of pixels is range from 0 (not 1)
		yPxRange = self.rSize.y-1
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
		pts = self.corners
		xmin = min([pt.x for pt in pts])
		xmax = max([pt.x for pt in pts])
		ymin = min([pt.y for pt in pts])
		ymax = max([pt.y for pt in pts])
		return BBOX(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)

	@property
	def bboxPx(self):
		return BBOX(xmin=0, ymin=0, xmax=self.rSize.x, ymax=self.rSize.y)

	@property
	def center(self):
		'''(x,y) geo coordinates of image center'''
		return xy(self.corners[0].x + self.geoSize.x/2, self.corners[0].y - self.geoSize.y/2)

	@property
	def geoSize(self):
		'''raster dimensions (width, height) in map units'''
		return xy(self.rSize.x * abs(self.pxSize.x), self.rSize.y * abs(self.pxSize.y))

	@property
	def orthoGeoSize(self):
		'''ortho geo size when affine transfo applied a rotation'''
		pxWidth = math.sqrt(self.pxSize.x**2 + self.rotation.x**2)
		pxHeight = math.sqrt(self.pxSize.y**2 + self.rotation.y**2)
		return xy(self.rSize.x*pxWidth, self.rSize.y*pxHeight)

	@property
	def orthoPxSize(self):
		'''ortho pixels size when affine transfo applied a rotation'''
		pxWidth = math.sqrt(self.pxSize.x**2 + self.rotation.x**2)
		pxHeight = math.sqrt(self.pxSize.y**2 + self.rotation.y**2)
		return xy(pxWidth, pxHeight)


	def geoFromPx(self, xPx, yPx, reverseY=False):
		"""
		Affine transformation (cf. ESRI WorldFile spec.)
		Return geo coords of the center of an given pixel
		xPx = the column number of the pixel in the image counting from left
		yPx = the row number of the pixel in the image counting from top
		use reverseY option is yPx is counting from bottom instead of top
		Number of pixels is range from 0 (not 1)
		"""
		if reverseY:#the users given y pixel in the image counting from bottom
			yPxRange = self.rSize.y - 1
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
			yPxRange = self.rSize.y - 1#number of pixels is range from 0 (not 1)
			yPx = yPxRange - yPx
		#offset the result of 1/2 px to get the good value
		xPx += 0.5
		yPx += 0.5
		#round to floor
		if round2Floor:
			xPx, yPx = math.floor(xPx), math.floor(yPx)
		return xy(xPx, yPx)

	#Alias
	def pxToGeo(self, xPx, yPx, reverseY=False):
		return self.geoFromPx(xPx, yPx, reverseY)
	def geoToPx(self, x, y, reverseY=False, round2Floor=False):
		return self.pxFromGeo(x, y, reverseY, round2Floor)

	############################################
	# Subbox handlers
	############################################

	def setSubBoxGeo(self, subBoxGeo):
		'''set a subbox in geographic coordinate space
		if needed, coords will be adjusted to avoid being outside raster size'''
		if self.hasRotation:
			raise IOError("A subbox cannot be define if the raster has rotation parameter")
		#Before set the property, ensure that the desired subbox overlap the raster extent
		if not self.bbox.overlap(subBoxGeo):
			raise OverlapError()
		elif self.bbox.isWithin(subBoxGeo):
			#Ignore because subbox is greater than raster extent
			return
		else:
			#convert the subbox in pixel coordinate space
			xminPx, ymaxPx = self.pxFromGeo(subBoxGeo.xmin, subBoxGeo.ymin, round2Floor=True)#y pixels counting from top
			xmaxPx, yminPx = self.pxFromGeo(subBoxGeo.xmax, subBoxGeo.ymax, round2Floor=True)#idem
			subBoxPx = BBOX(xmin=xminPx, ymin=yminPx, xmax=xmaxPx, ymax=ymaxPx)#xmax and ymax include
			#set the subbox
			self.setSubBoxPx(subBoxPx)


	def setSubBoxPx(self, subBoxPx):
		if not self.bboxPx.overlap(subBoxPx):
			raise OverlapError()
		xminPx, xmaxPx = subBoxPx.xmin, subBoxPx.xmax
		yminPx, ymaxPx = subBoxPx.ymin, subBoxPx.ymax
		#adjust against raster size if needed
		#we count pixel number from 0 but size represents total number of pixel (counting from 1), so we must use size-1
		sizex, sizey = self.rSize
		if xminPx < 0: xminPx = 0
		if xmaxPx > sizex: xmaxPx = sizex - 1
		if yminPx < 0: yminPx = 0
		if ymaxPx > sizey: ymaxPx = sizey - 1
		#get the adjusted geo coords at pixels center
		xmin, ymin = self.geoFromPx(xminPx, ymaxPx)
		xmax, ymax = self.geoFromPx(xmaxPx, yminPx)
		#set the subbox
		self.subBoxGeo = BBOX(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)


	def applySubBox(self):
		if self.subBoxGeo is not None:
			self.rSize = self.subBoxPxSize
			self.origin = self.subBoxGeoOrigin
			self.subBoxGeo = None

	@property
	def subBoxPx(self):
		'''return the subbox as bbox object in pixels coordinates space'''
		if self.subBoxGeo is None:
			return None
		xmin, ymax = self.pxFromGeo(self.subBoxGeo.xmin, self.subBoxGeo.ymin, round2Floor=True)#y pixels counting from top
		xmax, ymin = self.pxFromGeo(self.subBoxGeo.xmax, self.subBoxGeo.ymax, round2Floor=True)
		return BBOX(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)#xmax and ymax include

	@property
	def subBoxPxSize(self):
		'''dimension of the subbox in pixels'''
		if self.subBoxGeo is None:
			return None
		bbpx = self.subBoxPx
		w, h = bbpx.xmax - bbpx.xmin, bbpx.ymax - bbpx.ymin
		return xy(w+1, h+1)

	@property
	def subBoxGeoSize(self):
		'''dimension of the subbox in map units'''
		if self.subBoxGeo is None:
			return None
		sizex, sizey = self.subBoxPxSize
		return xy(sizex * abs(self.pxSize.x), sizey * abs(self.pxSize.y))

	@property
	def subBoxPxOrigin(self):
		'''pixel coordinate of subbox origin'''
		if self.subBoxGeo is None:
			return None
		return xy(self.subBoxPx.xmin, self.subBoxPx.ymin)

	@property
	def subBoxGeoOrigin(self):
		'''geo coordinate of subbox origin, adjusted at pixel center'''
		if self.subBoxGeo is None:
			return None
		return xy(self.subBoxGeo.xmin, self.subBoxGeo.ymax)

	####

	def __repr__(self):
		'''Brute force print...'''
		print(' has srs %s' %self.hasCRS)
		if self.crs is not None:
			print(str(self.crs))
		print(' origin geo %s' %self.origin)
		print(' pixel size %s' %self.pxSize)
		print(' rotation %s' %self.rotation)
		print(' bbox %s' %self.bbox)
		print(' geoSize %s' %self.geoSize)
		#print('	orthoGeoSize %s' %self.orthoGeoSize)
		#print('	orthoPxSize %s' %self.orthoPxSize)
		#print('	corners %s' %([p.xy for p in self.corners],))
		#print('	center %s' %self.center)
		if self.subBoxGeo is not None:
			print(' subbox origin (geo space) %s' %self.subBoxGeoOrigin)
			print(' subbox origin (px space) %s' %self.subBoxPxOrigin)
			print(' subbox (geo space) %s' %self.subBoxGeo)
			print(' subbox (px space) %s' %self.subBoxPx)
			print(' sub geoSize %s' %self.subBoxGeoSize)
			print(' sub pxSize %s' %self.subBoxPxSize)



class GeoRaster():
	'''A class to represent a georaster file'''


	def __init__(self, path, subBoxGeo=None, useGDAL=False):
		'''
		subBoxGeo : a BBOX object in CRS coordinate space
		useGDAL : use GDAL (if available) for extract raster informations
		'''
		self.path = path
		self.wfPath = self._getWfPath()

		self.format = None #image file format (jpeg, tiff, png ...)
		self.size = None #raster dimension (width, height) in pixel
		self.depth = None #8, 16, 32
		self.dtype = None #int, uint, float
		self.nbBands = None #number of bands
		self.noData = None

		self.georef = None

		if not useGDAL or not HAS_GDAL:

			self.format = getImgFormat(path)
			if self.format not in ['TIFF', 'BMP', 'PNG', 'JPEG', 'JPEG2000']:
				raise IOError("Unsupported format")

			if self.isTiff:
				self._fromTIFF()
				if not self.isGeoref and self.hasWorldFile:
					self.georef = GeoRef.fromWorldFile(self.wfPath, self.size)
			else:
				# Try to read file header
				w, h = getImgDim(self.path)
				if w is None or h is None:
					raise IOError("Unable to read raster size")
				else:
					self.size = xy(w, h)
				#georef
				if self.hasWorldFile:
					self.georef = GeoRef.fromWorldFile(self.wfPath, self.size)
				#TODO add function to extract dtype, nBands & depth from jpg, png, bmp or jpeg2000

		else:
			self._fromGDAL()

		if not self.isGeoref:
			raise IOError("Unable to read georef infos from worldfile or geotiff tags")

		if subBoxGeo is not None:
			self.georef.setSubBoxGeo(subBoxGeo)


	#GeoGef delegation by composition instead of inheritance
	#this special method is called whenever the requested attribute or method is not found in the object
	def __getattr__(self, attr):
		return getattr(self.georef, attr)


	############################################
	# Initialization Helpers
	############################################

	def _getWfPath(self):
		'''Try to find a worlfile path for this raster'''
		ext = self.path[-3:].lower()
		extTest = []
		extTest.append(ext[0] + ext[2] +'w')# tfx, jgw, pgw ...
		extTest.append(extTest[0]+'x')# tfwx
		extTest.append(ext+'w')# tifw
		extTest.append('wld')#*.wld
		extTest.extend( [ext.upper() for ext in extTest] )
		for wfExt in extTest:
			pathTest = self.path[0:len(self.path)-3] + wfExt
			if os.path.isfile(pathTest):
				return pathTest
		return None

	def _fromTIFF(self):
		'''Use Tyf to extract raster infos from geotiff tags'''
		if not self.isTiff or not self.fileExists:
			return
		tif = Tyf.open(self.path)[0]
		self.size = xy(tif['ImageWidth'], tif['ImageLength'])
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
		#Get Georef
		self.georef = GeoRef.fromTyf(tif)


	def _fromGDAL(self):
		'''Use GDAL to extract raster infos and init'''
		if self.path is None or not self.fileExists:
			raise IOError("Cannot find file on disk")
		ds = gdal.Open(self.path, gdal.GA_ReadOnly)
		self.size = xy(ds.RasterXSize, ds.RasterYSize)
		self.format = ds.GetDriver().ShortName
		if self.format in ['JP2OpenJPEG', 'JP2ECW', 'JP2KAK', 'JP2MrSID'] :
			self.format = 'JPEG2000'
		self.nbBands = ds.RasterCount
		b1 = ds.GetRasterBand(1) #first band (band index does not count from 0)
		self.noData = b1.GetNoDataValue()
		ddtype = gdal.GetDataTypeName(b1.DataType)#Byte, UInt16, Int16, UInt32, Int32, Float32, Float64
		if ddtype == "Byte":
			self.dtype = 'uint'
			self.depth = 8
		else:
			self.dtype = ddtype[0:len(ddtype)-2].lower()
			self.depth = int(ddtype[-2:])
		#Get Georef
		self.georef = GeoRef.fromGDAL(ds)
		#Close (gdal has no garbage collector)
		ds, b1 = None, None

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
		if self.format in ['TIFF', 'GTiff']:
			return True
		else:
			return False
	@property
	def hasWorldFile(self):
		return self.wfPath is not None
	@property
	def isGeoref(self):
		'''Flag if georef parameters have been extracted'''
		if self.origin is not None and self.pxSize is not None and self.rotation is not None:
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


	def __repr__(self):
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
		print('* Georef & Geometry')
		print(' is georef %s' %self.isGeoref)
		self.georef.__repr__()
		return "------------"

	#######################################
	# Methods
	#######################################

	def toGDAL(self):
		'''Get GDAL dataset'''
		return gdal.Open(self.path, gdal.GA_ReadOnly)

	def readAsNpArray(self, subset=True, IFACE='AUTO'):
		'''Read raster pixels values as Numpy Array'''

		if subset and self.subBoxGeo is not None:
			#georef = GeoRef(self.size, self.pxSize, self.subBoxGeoOrigin, rot=self.rotation, pxCenter=True)
			img = NpImage(self.path, subBoxPx=self.subBoxPx, noData=self.noData, georef=self.georef, adjustGeoref=True, IFACE=IFACE)
		else:
			img = NpImage(self.path, noData=self.noData, georef=self.georef, IFACE=IFACE)
		return img




class GeoRaster_bpy(GeoRaster):

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
				img = self.readAsNpArray(subset=True, IFACE='AUTO')#TODO iface setting
			else:
				img = self.readAsNpArray(IFACE='AUTO')

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


	def exportAsMesh(self, dx=0, dy=0, step=1, subset=False):
		if subset and self.subBoxGeo is None:
			subset = False

		img = self.readAsNpArray(subset=subset, IFACE='AUTO')
		#TODO raise error if multiband
		data = img.data
		x0, y0 = self.origin
		x0 -= dx
		y0 -= dy

		#Avoid using bmesh because it's very slow with large mesh
		#use from_pydata instead
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




#######################

class NpImage():
	'''Represent an image as Numpy array'''

	def _getIFACE(self, request):
		if request == 'AUTO':
			if HAS_GDAL:
				return 'GDAL'
			elif HAS_PIL:
				return 'PIL'
			elif HAS_IMGIO:
				return 'IMGIO'
		elif request == 'GDAL'and HAS_GDAL:
			return 'GDAL'
		elif request == 'PIL'and HAS_PIL:
			return 'PIL'
		elif request == 'IMGIO' and HAS_IMGIO:
			return 'IMGIO'
		else:
			raise ImportError(str(request) + " interface unavailable")

	#GeoGef delegation by composition instead of inheritance
	#this special method is called whenever the requested attribute or method is not found in the object
	def __getattr__(self, attr):
		if self.isGeoref:
			return getattr(self.georef, attr)
		else:#TODO raise specific msg if request for a georef attribute and not self.isgeoref
			raise AttributeError(str(type(self)) + 'object has no attribute' + str(attr))


	def __init__(self, data, subBoxPx=None, noData=None, georef=None, adjustGeoref=False, IFACE='AUTO'):
		'''
		init from file path, bytes data, Numpy array, NpImage, PIL Image or GDAL dataset
		subBoxPx : a BBOX object in pixel coordinates space used as data filter (will by applyed) (y counting from top)
		noData : the value used to represent nodata, will be used to define a numpy mask
		georef : a Georef object used to set georeferencing informations, optional
		adjustGeoref: determine if the submited georef must be adjusted against the subbox or if its already correct
		IFACE : string value in [AUTO, IMGIO, PIL, GDAL] used to define the imaging engine

		Notes :
		* With GDAL the subbox filter can be applyed at reading level whereas with others imaging
		library, all the data must be extracted before we can extract the subset (using numpy slice).
		In this case, the dataset must fit entirely in memory otherwise it will raise an overflow error
		* If no georef was submited and when the class is init using gdal support or from another npImage instance,
		existing georef of input data will be automatically extracted and adjusted against the subbox
		'''
		self.IFACE = self._getIFACE(IFACE)

		self.data = None
		self.subBoxPx = subBoxPx
		self.noData = noData

		self.georef = georef
		if self.subBoxPx is not None and self.georef is not None:
			if adjustGeoref:
				self.georef.setSubBoxPx(subBoxPx)
				self.georef.applySubBox()

		#init from another NpImage instance
		if isinstance(data, NpImage):
			self.data = self._applySubBox(data.data)
			if data.isGeoref and not self.isGeoref:
				self.georef = data.georef
				#adjust georef against subbox
				if self.subBoxPx is not None:
					self.georef.setSubBoxPx(subBoxPx)
					self.georef.applySubBox()

		#init from numpy array
		if isinstance(data, np.ndarray):
			self.data = self._applySubBox(data)

		#init from bytes data (BLOB)
		if isinstance(data, bytes):
			self.data = self._npFromBLOB(data)

		#init from file path
		if isinstance(data, str):
			if os.path.exists(data):
				self.data = self._npFromPath(data)
			else:
				raise ValueError('Unable to load image data')

		#init from GDAL dataset instance
		if HAS_GDAL:
			if isinstance(data, gdal.Dataset):
				self.data = self._npFromGDAL(data)

		#init from PIL Image instance
		if HAS_PIL:
			if Image.isImageType(data):
				self.data = self._npFromPIL(data)

		if self.data is None:
			raise ValueError('Unable to load image data')

		#Mask nodata value to avoid bias when computing min or max statistics
		if self.noData is not None:
			self.data = np.ma.masked_array(self.data, self.data == self.noData)

	@property
	def size(self):
		return xy(self.data.shape[1], self.data.shape[0])

	@property
	def isGeoref(self):
		'''Flag if georef parameters have been extracted'''
		if self.georef is not None:
			return True
		else:
			return False

	@property
	def nbBands(self):
		if len(self.data.shape) == 2:
			return 1
		elif len(self.data.shape) == 3:
			return self.data.shape[2]

	@property
	def hasAlpha(self):
		return self.nbBands == 4

	@property
	def isOneBand(self):
		return self.nbBands == 1

	@property
	def dtype(self):
		'''return string ['int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'float32', 'float64']'''
		return self.data.dtype

	@property
	def isFloat(self):
		if self.dtype in ['float16', 'float32', 'float64']:
			return True
		else:
			return False

	def getMin(self, bandIdx=0):
		if self.nbBands == 1:
			return self.data.min()
		else:
			return self.data[:,:,bandIdx].min()

	def getMax(self, bandIdx=0):
		if self.nbBands == 1:
			return self.data.max()
		else:
			return self.data[:,:,bandIdx].max()

	@classmethod
	def new(cls, w, h, bkgColor=(255,255,255,255), noData=None, georef=None, IFACE='AUTO'):
		r, g, b, a = bkgColor
		data = np.empty((h, w, 4), np.uint8)
		data[:,:,0] = r
		data[:,:,1] = g
		data[:,:,2] = b
		data[:,:,3] = a
		return cls(data, noData=noData, georef=georef, IFACE=IFACE)

	def _applySubBox(self, data):
		'''Use numpy slice to extract subset of data'''
		if self.subBoxPx is not None:
			x1, x2 = self.subBoxPx.xmin, self.subBoxPx.xmax+1
			y1, y2 = self.subBoxPx.ymin, self.subBoxPx.ymax+1
			if len(data.shape) == 2: #one band
				data = data[y1:y2, x1:x2]
			else:
				data = data[y1:y2, x1:x2, :]
			self.subBoxPx = None
		return data

	def _npFromPath(self, path):
		'''Get Numpy array from a file path'''
		if self.IFACE == 'PIL':
			img = Image.open(path)
			return self._npFromPIL(img)
		elif self.IFACE == 'IMGIO':
			return self._npFromImgIO(path)
		elif self.IFACE == 'GDAL':
			ds = gdal.Open(path)
			return self._npFromGDAL(ds)

	def _npFromBLOB(self, data):
		'''Get Numpy array from Bytes data'''

		if self.IFACE == 'PIL':
			#convert bytes object to bytesio (stream buffer) and open it with PIL
			img = Image.open(io.BytesIO(data))
			data = self._npFromPIL(img)

		elif self.IFACE == 'IMGIO':
			img = io.BytesIO(data)
			data = self._npFromImgIO(img)

		elif self.IFACE == 'GDAL':
			#Use a virtual memory file to create gdal dataset from buffer
			#build a random name to make the function thread safe
			vsipath = '/vsimem/' + ''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for i in range(5))
			gdal.FileFromMemBuffer(vsipath, data)
			ds = gdal.Open(vsipath)
			data = self._npFromGDAL(ds)
			ds = None
			gdal.Unlink(vsipath)

		return data

	def _npFromImgIO(self, img):
		'''Use ImageIO to extract numpy array from image path or bytesIO'''
		data = imageio.imread(img)
		return self._applySubBox(data)

	def _npFromPIL(self, img):
		'''Get Numpy array from PIL Image instance'''
		if img.mode == 'P': #palette (indexed color)
			img = img.convert('RGBA')
		data = np.asarray(img)
		data.setflags(write=True) #PIL return a non writable array
		return self._applySubBox(data)

	def _npFromGDAL(self, ds):
		'''Get Numpy array from GDAL dataset instance'''
		if self.subBoxPx is not None:
			startx, starty = self.subBoxPx.xmin, self.subBoxPx.ymin
			width = (self.subBoxPx.xmax - self.subBoxPx.xmin) + 1
			height = (self.subBoxPx.ymax - self.subBoxPx.ymin) + 1
			data = ds.ReadAsArray(startx, starty, width, height)
		else:
			data = ds.ReadAsArray()
		if len(data.shape) == 3: #multiband
			data = np.rollaxis(data, 0, 3) # because first axis is band index
		else: #one band raster or indexed color (= palette = pseudo color table (pct))
			ctable = ds.GetRasterBand(1).GetColorTable()
			if ctable is not None:
				#Swap index values to their corresponding color (rgba)
				nbColors = ctable.GetCount()
				keys = np.array( [i for i in range(nbColors)] )
				values = np.array( [ctable.GetColorEntry(i) for i in range(nbColors)] )
				sortIdx = np.argsort(keys)
				idx = np.searchsorted(keys, data, sorter=sortIdx)
				data = values[sortIdx][idx]

		#Try to extract georef
		if not self.isGeoref:
			self.georef = GeoRef.fromGDAL(ds)
			#adjust georef against subbox
			if self.subBoxPx is not None and self.georef is not None:
				self.georef.applySubBox()

		return data



	def toBLOB(self, ext='PNG'):
		'''Get bytes raw data'''
		if ext == 'JPG':
			ext = 'JPEG'

		if self.IFACE == 'PIL':
			b = io.BytesIO()
			img = Image.fromarray(self.data)
			img.save(b, format=ext)
			data = b.getvalue() #convert bytesio to bytes

		elif self.IFACE == 'IMGIO':
			if ext == 'JPEG' and self.hasAlpha:
				self.removeAlpha()
			data = imageio.imwrite(imageio.RETURN_BYTES, self.data, format=ext)

		elif self.IFACE == 'GDAL':
			mem = self.toGDAL()
			#build a random name to make the function thread safe
			name = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for i in range(5))
			vsiname = '/vsimem/' + name + '.png'
			out = gdal.GetDriverByName(ext).CreateCopy(vsiname, mem)
			# Read /vsimem/output.png
			f = gdal.VSIFOpenL(vsiname, 'rb')
			gdal.VSIFSeekL(f, 0, 2) # seek to end
			size = gdal.VSIFTellL(f)
			gdal.VSIFSeekL(f, 0, 0) # seek to beginning
			data = gdal.VSIFReadL(1, size, f)
			gdal.VSIFCloseL(f)
			# Cleanup
			gdal.Unlink(vsiname)
			mem = None

		return data



	def toPIL(self):
		'''Get PIL Image instance'''
		return Image.fromarray(self.data)


	def toGDAL(self):
		'''Get GDAL memory driver dataset'''
		w, h = self.size
		n = self.nbBands
		dtype = str(self.dtype)
		if dtype == 'uint8': dtype = 'byte'
		dtype = gdal.GetDataTypeByName(dtype)
		mem = gdal.GetDriverByName('MEM').Create('', w, h, n, dtype)
		#writearray is available only at band level
		if self.isOneBand:
			mem.GetRasterBand(1).WriteArray(self.data)
		else:
			for bandIdx in range(n):
				bandArray = self.data[:,:,bandIdx]
				mem.GetRasterBand(bandIdx+1).WriteArray(bandArray)
		#write georef
		if self.isGeoref:
			mem.SetGeoTransform(self.georef.toGDAL())
			if self.georef.crs is not None:
				mem.SetProjection(self.georef.crs.getOgrSpatialRef().ExportToWkt())
		return mem


	def removeAlpha(self):
		if self.hasAlpha:
			self.data = self.data[:, :, 0:3]

	def addAlpha(self, opacity=255):
		if self.nbBands == 3:
			w, h = self.size
			alpha = np.empty((h,w), dtype=self.dtype)
			alpha.fill(opacity)
			alpha = np.expand_dims(alpha, axis=2)
			self.data = np.append(self.data, alpha, axis=2)


	def save(self, path):
		'''
		save the numpy array to a new image file
		output format is defined by path extension
		'''

		imgFormat = path[-3:]

		if self.IFACE == 'PIL':
			self.toPIL().save(path)
		elif self.IFACE == 'IMGIO':
			if imgFormat == 'jpg' and self.hasAlpha:
				self.removeAlpha()
			imageio.imwrite(path, self.data)#float32 support ok
		elif self.IFACE == 'GDAL':
			if imgFormat == 'png':
				driver = 'PNG'
			elif imgFormat == 'jpg':
				driver = 'JPEG'
			elif imgFormat == 'tif':
				driver = 'Gtiff'
			else:
				raise ValueError('Cannot write to '+ imgFormat + ' image format')
			#Some format like jpg or png has no create method implemented
			#because we can't write data at random with these formats
			#so we must use an intermediate memory driver, write data to it
			#and then write the output file with the createcopy method
			mem = self.toGDAL()
			out = gdal.GetDriverByName(driver).CreateCopy(path, mem)
			mem = out = None

		if self.isGeoref:
			self.georef.toWorldFile(os.path.splitext(path)[0] + '.wld')


	def paste(self, data, x, y):

		img = NpImage(data)
		data = img.data
		w, h = img.size

		if img.isOneBand and self.isOneBand:
			self.data[y:y+h, x:x+w] = data
		elif (not img.isOneBand and self.isOneBand) or (img.isOneBand and not self.isOneBand):
			raise ValueError('Paste error, cannot mix one band with multiband')

		if self.hasAlpha:
			n = img.nbBands
			self.data[y:y+h, x:x+w, 0:n] = data
		else:
			n = self.nbBands
			self.data[y:y+h, x:x+w, :] = data[:, :, 0:n]

	def cast2float(self):
		if not self.isFloat:
			self.data = self.data.astype('float32')

	def fillNodata(self):
		#if not self.noData in self.data:
		if not np.ma.is_masked(self.data):
			#do not process it if its not necessary
			return
		if self.IFACE == 'GDAL':
			# gdal.FillNodata need a band object to apply on
			# so we create a memory datasource (1 band, float)
			height, width = self.data.shape
			ds = gdal.GetDriverByName('MEM').Create('', width, height, 1, gdal.GetDataTypeByName('float32'))
			b = ds.GetRasterBand(1)
			b.SetNoDataValue(self.noData)
			self.data =  np.ma.filled(self.data, self.noData)# Fill mask with nodata value
			b.WriteArray(self.data)
			gdal.FillNodata(targetBand=b, maskBand=None, maxSearchDist=max(self.size.xy), smoothingIterations=0)
			self.data = b.ReadAsArray()
			ds, b = None, None
		else: #Call the inpainting function
			# Cast to float
			self.cast2float()
			# Fill mask with NaN (warning NaN is a special value for float arrays only)
			self.data =  np.ma.filled(self.data, np.NaN)
			# Inpainting
			self.data = replace_nans(self.data, max_iter=5, tolerance=0.5, kernel_size=2, method='localmean')

	def __repr__(self):
		'''Brute force print...'''
		print('* Data infos :')
		print(' size %s' %self.size)
		print(' dtype %s' %self.dtype)
		print(' number of bands %i' %self.nbBands)
		print(' nodata value %s' %self.noData)
		#
		print('* Statistics')
		print(' min max %s' %((self.getMin(), self.getMax()), ))
		#
		if self.isGeoref:
			print('* Georef & Geometry')
			self.georef.__repr__()
		return "------------"

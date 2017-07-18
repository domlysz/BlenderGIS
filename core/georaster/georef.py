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

import math

from ..proj import SRS
from ..utils import XY as xy, BBOX
from ..errors import OverlapError


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
		try:
			geotags = tif['GeoKeyDirectoryTag']
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
		xPxRange = self.rSize.x - 1
		yPxRange = self.rSize.y - 1
		#pixel center
		pt1 = self.geoFromPx(0, 0, pxCenter=True)#upperLeft
		pt2 = self.geoFromPx(xPxRange, 0, pxCenter=True)#upperRight
		pt3 = self.geoFromPx(xPxRange, yPxRange, pxCenter=True)#bottomRight
		pt4 = self.geoFromPx(0, yPxRange, pxCenter=True)#bottomLeft
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


	def geoFromPx(self, xPx, yPx, reverseY=False, pxCenter=True):
		"""
		Affine transformation (cf. ESRI WorldFile spec.)
		Return geo coords of the center of an given pixel
		xPx = the column number of the pixel in the image counting from left
		yPx = the row number of the pixel in the image counting from top
		use reverseY option is yPx is counting from bottom instead of top
		Number of pixels is range from 0 (not 1)
		"""

		if pxCenter:
			#force pixel center, in this case we need to cast the inputs to floor integer
			xPx, yPx = math.floor(xPx), math.floor(yPx)
			ox, oy = self.origin.x, self.origin.y
		else:
			#normal behaviour, coord at pixel's top left corner
			ox = self.origin.x - abs(self.pxSize.x/2)
			oy = self.origin.y + abs(self.pxSize.y/2)

		if reverseY:#the users given y pixel in the image counting from bottom
			yPxRange = self.rSize.y - 1
			yPx = yPxRange - yPx

		x = self.pxSize.x * xPx + self.rotation.y * yPx + ox
		y = self.pxSize.y * yPx + self.rotation.x * xPx + oy

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
		offx = self.origin.x - abs(self.pxSize.x/2)
		offy = self.origin.y + abs(self.pxSize.y/2)
		# transfo
		xPx  = (pxSizey*x - rotx*y + rotx*offy - pxSizey*offx) / (pxSizex*pxSizey - rotx*roty)
		yPx = (-roty*x + pxSizex*y + roty*offx - pxSizex*offy) / (pxSizex*pxSizey - rotx*roty)
		if reverseY:#the users want y pixel position counting from bottom
			yPxRange = self.rSize.y - 1
			yPx = yPxRange - yPx
			yPx += 1 #adjust because the coord start at pixel's top left coord
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
		if xmaxPx >= sizex: xmaxPx = sizex - 1
		if yminPx < 0: yminPx = 0
		if ymaxPx >= sizey: ymaxPx = sizey - 1
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
		s = [
		' spatial ref system {}'.format(self.crs),
		' origin geo {}'.format(self.origin),
		' pixel size {}'.format(self.pxSize),
		' rotation {}'.format(self.rotation),
		' bounding box {}'.format(self.bbox),
		' geoSize {}'.format(self.geoSize)
		]

		if self.subBoxGeo is not None:
			s.extend([
			' subbox origin (geo space) {}'.format(self.subBoxGeoOrigin),
			' subbox origin (px space) {}'.format(self.subBoxPxOrigin),
			' subbox (geo space) {}'.format(self.subBoxGeo),
			' subbox (px space) {}'.format(self.subBoxPx),
			' sub geoSize {}'.format(self.subBoxGeoSize),
			' sub pxSize {}'.format(self.subBoxPxSize),
			])

		return '\n'.join(s)

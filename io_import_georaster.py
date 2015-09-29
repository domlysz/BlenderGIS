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

bl_info = {
	'name': 'Import raster georeferenced with world file',
	'author': 'domLysz',
	'license': 'GPL',
	'deps': 'numpy, gdal',
	'version': (2, 0),
	'blender': (2, 7, 0),#min version = 2.67
	'location': 'File > Import > Georeferenced raster',
	'description': 'Import raster georeferenced with world file',
	'warning': '',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': '',
	'link': '',
	'support': 'COMMUNITY',
	'category': 'Import-Export',
	}

import bpy
import bmesh
import os
import math
import mathutils
import numpy as np#Ship with Blender since 2.70

try:
	from osgeo import gdal
	GDAL_PY = True
except:
	GDAL_PY = False

from shutil import which
if which('gdal_translate'):
	GDAL_BIN = True
else:
	GDAL_BIN = False



#CLASSES

class xy(object):
	def __init__(self, x, y):
		'''
		You can use the constructor in many ways:
		xy(0, 1) - passing two arguments
		xy(x=0, y=1) - passing keywords arguments
		xy(**{'x': 0, 'y': 1}) - unpacking a dictionary
		xy(*[0, 1]) - unpacking a list or a tuple (or a generic iterable)
		'''
		self.data=[x, y]
	def __str__(self):
		return "(%s, %s)"%(self.x,self.y)
	def __getitem__(self,item):
		return self.data[item]
	def __setitem__(self, idx, value):
		self.data[idx] = value
	def __iter__(self):
		return iter(self.data)
	@property
	def x(self):
		return self.data[0]
	@property
	def y(self):
		return self.data[1]
	@property
	def xy(self):
		return self.data

class ellps():
	"""ellipsoid"""
	def __init__(self, a, b):
		self.a =  a#equatorial radius in meters
		self.b =  b#polar radius in meters
		self.f = (self.a-self.b)/self.a#inverse flat
		self.perimeter = (2*math.pi*self.a)#perimeter at equator

ellpsGRS80 = ellps(6378137, 6356752.314245)

class bbox():
	global ellpsGRS80
	def __init__(self, xmin, xmax, ymin, ymax):
		self.xmin=xmin
		self.xmax=xmax
		self.ymin=ymin
		self.ymax=ymax
	def __str__(self):
		return "xmin "+str(self.xmin)+" xmax "+str(self.xmax)+" ymin "+str(self.ymin)+" ymax "+str(self.ymax)
	def __eq__(self, bb):
		if self.xmin == bb.xmin and self.xmax == bb.xmax and self.ymin == bb.ymin and self.ymax == bb.ymax:
			return True
	def degrees2meters(self):
		k = ellpsGRS80.perimeter/360
		return bbox(self.xmin * k, self.xmax * k, self.ymin * k, self.ymax * k)
	def meters2degrees(self):
		k = ellpsGRS80.perimeter/360
		return bbox(self.xmin / k, self.xmax / k, self.ymin / k, self.ymax / k)

class WorldFile(object):
	"""Handle ESRI WorldFile"""
	global ellpsGRS80
	def __init__ (self, wfData, size):
		"""
		wfData can be an image path, in this case the script search for worldfile path and read data from it
		wfData can also be a list of worldfile parameters: (pxSizeX, rotx, roty, pxSizeY, topLeftX, topLeftY)
		"""
		self._rasterSize = size #raster dimension (width, height) in pixel
		self._pixelSize = False #dimension of a pixel in map units (x scale, y scale)
		#y scale is negative because image origin is upper-left whereas map origin is lower-left
		self._rotation = False #rotation terms (x rot, y rot)
		self._corners = False #(x,y) geo coordinates of image corners (upper left, upper right, bottom right, bottom left)
		self._center = False #(x,y) geo coordinates of image center
		self._geoSize = False #raster dimensions (width, height) in map units
		self._bbox = False #(xmin, xmax, ymin, ymax)
		self._wfPath = False
		self.__coorInit = False #geo coordinate of the center of the upper left pixel
		#
		if isinstance(wfData, list) or isinstance(wfData, tuple):
			self._pixelSize = xy(wfData[0], wfData[3])
			self._rotation = xy(wfData[1], wfData[2])
			self.__coorInit = xy(wfData[4], wfData[5])#upper left pixel CENTER
			self.updateProps()
		else: #isinstance(wfData, str)
			self._success = self.__readWF(wfData)
			if self._success:
				self.updateProps()

	def updateProps(self):
		self._corners = self.__calculerCorners()
		self._geoSize = xy(self._rasterSize.x * abs(self._pixelSize.x), self._rasterSize.y * abs(self._pixelSize.y))
		self._center = xy(self._corners[0].x+self._geoSize.x/2, self._corners[0].y-self._geoSize.y/2)
		self._bbox = self.__calcBbox()
		if self._rotation.xy != [0,0]:
			pxWidth = math.sqrt(self._pixelSize.x**2 + self._rotation.x**2)
			pxHeight = math.sqrt(self._pixelSize.y**2 + self._rotation.y**2)
			self._orthoPxSize = xy(pxWidth, pxHeight)
			self._orthoGeoSize = xy(self._rasterSize.x*pxWidth, self._rasterSize.y*pxHeight)

	def __str__(self):
		return "Raster size : "+str(self._rasterSize)+"\nPixel size : "+str(self._pixelSize)\
				+"\nRotation : "+str(self._rotation)+"\nBounding box : "+str(self._bbox)\
				+"\nOrigin pixel center : "+str(self.__coorInit)\
				+"\nGeographic size : "+str(self._geoSize)

	@property
	def success(self):
		return self._success
	@property
	def rasterSize(self):
		return self._rasterSize
	@property
	def pixelSize(self):
		return self._pixelSize
	@property
	def rotation(self):
		return self._rotation
	@property
	def corners(self):
		return self._corners
	@property
	def center(self):
		return self._center
	@property
	def geoSize(self):
		return self._geoSize
	@property
	def bbox(self):
		return self._bbox
	@property
	def wfPath(self):
		return self._wfPath


	def __calculerCorners(self):
		"""
		return (x,y) geo coordinates of image corners (pt1, pt2, pt3, pt4) <--> (upper left, upper right, bottom right, bottom left)
		The coords aren't located at the pixel center but at the upper left for pt1, upper right for pt2 ...
		"""
		xPxRange = self._rasterSize.x-1#number of pixels is range from 0 (not 1)
		yPxRange = self._rasterSize.y-1
		#pixel center
		pt1 = self.geoFromPx(0, yPxRange, True)#upperLeft
		pt2 = self.geoFromPx(xPxRange, yPxRange, True)#upperRight
		pt3 = self.geoFromPx(xPxRange, 0, True)#bottomRight
		pt4 = self.geoFromPx(0, 0, True)#bottomLeft
		#pixel center offset
		xOffset = abs(self._pixelSize.x/2)
		yOffset = abs(self._pixelSize.y/2)
		pt1 = xy(pt1.x - xOffset, pt1.y + yOffset)
		pt2 = xy(pt2.x + xOffset, pt2.y + yOffset)
		pt3 = xy(pt3.x + xOffset, pt3.y - yOffset)
		pt4 = xy(pt4.x - xOffset, pt4.y - yOffset)
		return (pt1, pt2, pt3, pt4)

	def geoFromPx(self, xPx, yPx, reverseY=False):
		"""
		Affine transformation (cf. ESRI WorldFile spec.)
		Return geo coords of the center of an given pixel
		xPx = the column number of the pixel in the image counting from left
		yPx = the row number of the pixel in the image counting from top
		Number of pixels is range from 0 (not 1)
		"""
		if reverseY:#the users given y pixel in the image counting from bottom
			yPxRange = self._rasterSize.y-1
			yPx = yPxRange-yPx
		#
		a=self._pixelSize.x
		e=self._pixelSize.y
		b=self._rotation.x
		d=self._rotation.y
		c=self.__coorInit.x
		f=self.__coorInit.y
		#
		x = a*xPx + d*yPx + c
		y = e*yPx + b*xPx + f
		return xy(x, y)

	def pxFromGeo(self, x, y, reverseY=False, round2Floor=False):
		"""
		Affine transformation (cf. ESRI WorldFile spec.)
		Return pixel position of given geographic coords
		Pixels position is range from 0 (not 1)
		"""
		a=self._pixelSize.x
		e=self._pixelSize.y
		b=self._rotation.x
		d=self._rotation.y
		c=self.__coorInit.x
		f=self.__coorInit.y
		xPx  = (e*x - b*y + b*f - e*c) / (a*e - d*b)
		yPx = (-d*x + a*y + d*c - a*f) / (a*e - d*b)
		if reverseY:#the users want y pixel position counting from bottom
			yPxRange=self._rasterSize.y-1#number of pixels is range from 0 (not 1)
			yPx = yPxRange-yPx
		#seems we need to offset the result of 1/2 px to get the good value
		xPx+=0.5
		yPx+=0.5
		#round to floor
		if round2Floor:
			xPx, yPx = math.floor(xPx), math.floor(yPx)
		return xy(xPx, yPx)

	def __readWF(self, fic):
		wfPathTest = []
		wfPathTest.append(fic[0:(len(fic)-3)] + fic[-3] + fic[-1] +'w')#tif --> tfw, jpg --> jgw, bmp --> bpw, png --> pgw ...
		wfPathTest.append(wfPathTest[0]+'x')#tif --> tfwx, jpg --> jgwx, bmp --> bpwx, png --> pgwx ...
		wfPathTest.append(fic+'w')#tif --> tifw, jpg --> jpgw, bmp --> bmpw, png --> pngw ...
		wfPathTest.append(fic[0:(len(fic)-3)] + 'wld')#*.wld
		for path in wfPathTest:
			if os.path.isfile(path):
				self._wfPath = path
				break
		if not self._wfPath:
			return False
		try:
			objFic = open(self._wfPath,'r')
			wfParams = objFic.readlines()
			objFic.close
			self._pixelSize = xy(float(wfParams[0].replace(',','.')),float(wfParams[3].replace(',','.')))
			self._rotation = xy(float(wfParams[1].replace(',','.')),float(wfParams[2].replace(',','.')))
			self.__coorInit = xy(float(wfParams[4].replace(',','.')),float(wfParams[5].replace(',','.')))#upper left pixel CENTER
		except:
			return False
		return True

	def __calcBbox(self):
		"""
		Return xmin, xmax, ymin, ymax
		"""
		xmin = min([pt.x for pt in self.corners])
		xmax = max([pt.x for pt in self.corners])
		ymin = min([pt.y for pt in self.corners])
		ymax = max([pt.y for pt in self.corners])
		return bbox(xmin, xmax, ymin, ymax)
	
	def degrees2meters(self):
		"""
		Convert decimal degrees to meters
		Correct at equator only but it's the way that equirectangular proj works, we all know these horizontal distortions...
		"""
		k = ellpsGRS80.perimeter/360
		self._pixelSize = xy(*[v*k for v in self._pixelSize])
		self.__coorInit = xy(*[v*k for v in self.__coorInit])
		self.updateProps()

class Stats():
	def __init__(self):
		self.rmin, self.rmax = None, None#true raster pixel value
		self.bmin, self.bmax = None, None#Blender pixel intensity value (from 0.0 to 1.0)
		self.rdelta, self.bdelta = None, None
	def setRval(self, rValues):
		self.rmin, self.rmax = rValues
		self.rdelta = self.rmax - self.rmin
	def setBval(self, bValues):
		self.bmin, self.bmax = bValues
		self.bdelta = self.bmax - self.bmin
	def calcBval(self, depth):
		self.bmin, self.bmax = (self.fromBitDepth(self.rmin, depth), self.fromBitDepth(self.rmax, depth))
		self.bdelta = self.bmax - self.bmin
	def calcRval(self, depth):
		self.rmin, self.rmax = (self.toBitDepth(self.bmin, depth), self.toBitDepth(self.bmax, depth))
		self.rdelta = self.rmax - self.rmin
	def __str__(self):
		txt="Raster (min, max, delta) = "+str((self.rmin, self.rmax, self.rdelta))+'\n'
		txt+="Blender (min, max, delta) = "+str((self.bmin, self.bmax, self.bdelta))
		return txt
	def toBitDepth(self, val, depth):
		"""
		Convert Blender pixel intensity value (from 0.0 to 1.0) in true pixel value in initial image bit depth range
		"""
		return val * (2**depth - 1) 
	def fromBitDepth(self, val, depth):
		"""
		Convert true pixel value in initial image bit depth range to Blender pixel intensity value (from 0.0 to 1.0)
		"""
		return val / (2**depth - 1)

def scale(inVal, low, high, mn, mx):
	#Scale/normalize data : linear stretch from lowest value to highest value
	#outVal = (inVal - min) * (hight - low) / (max - min)] + low
	return (inVal - mn) * (high - low) / (mx - mn) + low


class Raster():

	def __init__(self, path, angCoords=False, wf=False, pack=False):
		self.path = path#filepath
		self.angCoords = angCoords
		self.wf = wf#pxsize, bbox ..
		self.size = None
		#get bpy image
		try:
			self.img = bpy.data.images.load(self.path)
			self.size = xy(self.img.size[0], self.img.size[1])
		except:
			raise IOError("Unable to read raster")
		#read world file
		if not self.wf:
			self.wf=WorldFile(self.path, self.size)
			if not self.wf.success:
				raise IOError("Unable to read worlfile")
		if self.angCoords:
			self.wf.degrees2meters()
		#print(self.wf)
		#Pack image
		if pack:
			self.img.pack()

class DEM(Raster):

	def __init__(self, path, dType, angCoords=False, scaleBounds=False, wf=False, pack=False):
		#Init super class
		Raster.__init__(self, path, angCoords=angCoords, wf=wf, pack=pack)
		#Set image color space
		self.img.colorspace_settings.name = 'Non-Color'#Only Linear, Non Color and Raw get good values...
		self.scaleBounds = scaleBounds
		#bit depth
		signe, depth = dType.split(';')
		self.depth = int(depth)
		if signe == 'u':
			self.unsigned = True
		else:
			self.unsigned = False
		#
		self.noData = None
		self.wholeStats = None
		self.subStats = None

	def getStats(self, subBox=False):
		pixels = self.img.pixels[:]#[r,g,b,a,r,g,b,a,r,g,b,a, .... ] counting from bottom to up and left to right
		nbBands = self.img.channels
		#Get Numpy array
		a=np.array(pixels)#[r,g,b,a,r,g,b,a,r,g,b,a, .... ]
		a=a.reshape(len(a)/nbBands,nbBands)#[[r,g,b,a],[r,g,b,a],[r,g,b,a],[r,g,b,a]...]
		a=a.reshape(self.size.y, self.size.x, nbBands)#In numpy fist dimension is lines (y) and second dimension is cols (x)
		a=np.flipud(a)#now origine is topleft
		a=a.swapaxes(0,1)#now first axis is x, second y
		band1 = a[:,:,0]
		if not self.unsigned:
			#with signed data, positive value are coded from 0 to 2**depth/2 (0.0 to 0.5 in Blender)
			#negative values are coded from 2**depth/2 to 2**depth (0.5 to 1.0 in Blender)
			band1 = np.where(band1<0.5, band1, 0)#filter negative values
		#
		self.wholeStats=Stats()
		self.wholeStats.setBval( (band1.min(), band1.max()) )
		if not self.scaleBounds:
			self.wholeStats.calcRval(self.depth)
		else:
			#with scaled data the only way to retreive elevation values is by user input
			#because only the user know what bounds (min/max) are used to scale the data to raster range capacity (bit depth)
			self.wholeStats.setRval(self.scaleBounds)
		print("Whole DEM statistics :\n"+str(self.wholeStats))
		#
		if subBox:#subset matrix
			subBoxPx = getSubBoxPx(self.wf, subBox, reverseY=False)
			subSet = band1[subBoxPx.xmin:subBoxPx.xmax+1, subBoxPx.ymin:subBoxPx.ymax+1]#topleft to bottomright
			#
			self.subStats = Stats()
			self.subStats.setBval( (subSet.min(), subSet.max()) )
			if not self.scaleBounds:
				self.subStats.calcRval(self.depth)
			else:
				#with scaled data, min and max raster capacity value (0 and 2^depth) aren't necessary affected
				#so we can't just considere altmin<-->0 and altmax<-->2^depth, it's not necessaray true
				#we need to know real min and max value affected in the scaled raster
				#Linear stretch from Blender value (range 0.0 to 1.0) to raster values (range from "scale bounds")
				altMin, altMax = self.scaleBounds
				rmin = scale(self.subStats.bmin, altMin, altMax, self.wholeStats.bmin, self.wholeStats.bmax)
				rmax = scale(self.subStats.bmax, altMin, altMax,  self.wholeStats.bmin, self.wholeStats.bmax)
				self.subStats.setRval( (rmin, rmax) )	
			print("Mesh zonal statistics :\n"+ str(self.subStats))


#------------------------------------------------------------------------

class DEM_GDAL():
	def __init__(self, path, angCoords=False, scale=False):
		self.path=path
		self.dsIn = gdal.Open(self.path, gdal.GA_ReadOnly)
		self.size = xy(self.dsIn.RasterXSize, self.dsIn.RasterYSize)
		self.wf = self.getWorldFile(self.dsIn)
		self.nbBand = self.dsIn.RasterCount
		self.band1 = self.dsIn.GetRasterBand(1)
		self.noData = self.band1.GetNoDataValue()
		self.dType, self.unsigned, self.depth = self.getDtype(self.band1)
		self.proj = self.dsIn.GetProjection()
		self.angCoords = angCoords
		#self.altMin, self.altMax = self.getStats(self.band1)
		self.scale = scale
		print(self.dType)

	def __del__(self):
		self.band1 = None
		self.dsIn = None

	def getDtype(self, band):
		dType = gdal.GetDataTypeName(band.DataType)#Byte, UInt16, Int16, UInt32, Int32, Float32, Float64
		if dType is "Byte":
			unsigned = True
			depth = 8
		else:
			depth = int(dType[-2:])
			if dType[0] is 'U':
				unsigned = True
			else:
				unsigned = False
		return dType, unsigned, depth

	def getWorldFile(self, ds):
		"""Compute world file"""
		topleftx, pxsizex, rotx, toplefty, roty, pxsizey = ds.GetGeoTransform()
		topleftx += abs(pxsizex/2)#because top left coord is from exact top left pixel corner, we need to adjust it at pixel center
		toplefty -= abs(pxsizey/2)
		wfData = (pxsizex, rotx, roty, pxsizey, topleftx, toplefty)#order like wf text
		return WorldFile(wfData, self.size)

	def getSubGeoTrans(self, wf, subBoxPx):
		x, y = wf.geoFromPx(subBoxPx.xmin, subBoxPx.ymin, reverseY=False)#top left pixel center
		pxsizex, pxsizey = wf.pixelSize
		rotx, roty = wf.rotation
		x -= abs(pxsizex/2)
		y += abs(pxsizey/2)
		geoTrans = (x, pxsizex, rotx, y, roty, pxsizey)
		return geoTrans

	def getStats(self, band):
		altMin = band.GetMinimum()
		altMax = band.GetMaximum()
		if altMin is None or altMax is None:
			altMin, altMax = band.ComputeRasterMinMax()
		return altMin, altMax

	def getSubStats(self, outBand, startx, starty, width, height):
		blockSize=64
		amin, amax = (None, None)
		blkIdx=0
		#Loop over blocks
		for i in range(starty, height, blockSize):
			if i + blockSize < height:
				yBlockSize = blockSize
			else:
				yBlockSize = height - i
			for j in range(startx, width, blockSize):
				if j + blockSize < width:
					xBlockSize = blockSize
				else:
					xBlockSize = width - j
				data = self.band1.ReadAsArray(j, i, xBlockSize, yBlockSize).astype(self.dType)#np dataType : int8, int16, uint16, int32, uint32, float32....
				blkIdx+=1
				data = np.where(data==self.noData, 0, data)#filter noData
				data = np.where(data>0, data, 0)#filter positive values
				dataMin, dataMax = (data.min(), data.max())
				if blkIdx == 1:
					amin, amax = dataMin, dataMax
				else:
					if amin > dataMin: amin = dataMin
					if amax > dataMax: amax = dataMax
		data = None
		return amin, amax

	def clip(self, subBox):
		#Check overlap
		if self.angCoords : subBox = subBox.meters2degrees()
		if not overlap(self.wf.bbox, subBox):
			raise OverlapError()
		#overlay extent (in pixels)
		subBoxPx = getSubBoxPx(self.wf, subBox, reverseY=False)
		dx = subBoxPx.xmax - subBoxPx.xmin
		dy = subBoxPx.ymax - subBoxPx.ymin
		if subBoxPx.xmin + dx < self.size.x : dx+=1
		if subBoxPx.ymin + dy < self.size.y : dy+=1
		#Output path
		folder, fileName = os.path.split(self.path)
		baseName, inExt = os.path.splitext(fileName)
		outExt = '.tif'
		tmpDir = bpy.context.user_preferences.filepaths.temporary_directory
		if tmpDir[-1] != os.sep:
			tmpDir += os.sep
		outFile = tmpDir + baseName + "_clip" + outExt
		#Create empty output raster
		dsOut = self.getOutDS(outFile, dx, dy)
		#Assign georef infos
		dsOut.SetGeoTransform(self.getSubGeoTrans(self.wf, subBoxPx))
		dsOut.SetProjection(self.proj)
		#Write data
		outBand = dsOut.GetRasterBand(1)
		startx, starty = subBoxPx.xmin, subBoxPx.ymin
		width = startx + dx
		height = starty + dy
		if self.scale:
			amin, amax = self.getSubStats(outBand, startx, starty, width, height)
			scaleBounds =(amin, amax)
		else:
			scaleBounds = False
		self.writeSubRaster(outBand, startx, starty, width, height, scaleBounds=scaleBounds)
		#Close
		outBand = None
		dsOut = None
		#Load in Blender, pack and delete source files
		outDEM = DEM(outFile, 'u;16', pack=True, angCoords=self.angCoords, scaleBounds=scaleBounds)
		#Delete intermediate files
		os.remove(outFile)
		os.remove(outDEM.wf.wfPath)
		if os.path.isfile(outFile+".aux.xml"):
			os.remove(outFile+".aux.xml")
		return outDEM

	def writeSubRaster(self, outBand, startx, starty, width, height, scaleBounds=False):
		blockSize=64
		#Loop over blocks
		for i in range(starty, height, blockSize):
			if i + blockSize < height:
				yBlockSize = blockSize
			else:
				yBlockSize = height - i
			for j in range(startx, width, blockSize):
				if j + blockSize < width:
					xBlockSize = blockSize
				else:
					xBlockSize = width - j
				data = self.band1.ReadAsArray(j, i, xBlockSize, yBlockSize).astype(self.dType)#np dataType : int8, int16, uint16, int32, uint32, float32....
				data = np.where(data==self.noData, 0, data)# or set to np.NaN ???
				data = np.where(data>0, data, 0)#filter positive values, seems not necessary because writing dsOut automatically cast values to uint16 & clip neg values
				#data = np.where(data<0, data, 0)#filter negative values
				#data = np.negative(data)#or data = np.absolute(data)
				if scaleBounds:
					#Scale/normalize data : linear stretch from lowest value to highest value
					data = data.astype(np.float32)#promote data type before perform calculation
					low, high = (0, 2**self.depth-1)
					subMin, subMax = scaleBounds
					data = scale(data, low, high, subMin, subMax)
				#
				data = data.astype(np.uint16)#seems not necessary because dsOut == Uint16
				#WRITE BLOCK
				outBand.WriteArray(data, j-startx, i-starty)
		data = None

	def getOutDS(self, outFile, dx, dy):
		#Output datasource
		if os.path.isfile(outFile):
				os.remove(outFile)
		driver = gdal.GetDriverByName("GTiff")
		outputNbBand = 1
		outputType = gdal.GDT_UInt16#GDT_Byte, GDT_UInt16, GDT_Int16, GDT_UInt32, GDT_Int32
		dsOut = driver.Create(outFile, dx, dy, outputNbBand, outputType, ['TFW=YES', 'COMPRESS=LZW', 'BIGTIFF=IF_NEEDED'])
		return dsOut


class OverlapError(Exception):
	def __init__(self):
		pass
	def __str__(self):
		return "Non overlap data"


def gdalProcess(filePath, bb, scale=False, angCoords=False):
	if angCoords:
		bb = bb.meters2degrees()
	xmin, ymax, xmax, ymin = bb.xmin, bb.ymax, bb.xmax, bb.ymin
	#Seems GDAL -projwin perform a litle too short clip
	#workaround --> majore bbox by 5%
	majx, majy = (5*(xmax-xmin)/100, 5*(ymax-ymin)/100)
	xmin -= majx
	xmax += majx
	ymin -= majy
	ymax += majy
	#
	folder, fileName = os.path.split(filePath)
	baseName, inExt = os.path.splitext(fileName)
	outExt = '.tif'
	tmpDir = bpy.context.user_preferences.filepaths.temporary_directory
	if tmpDir[-1] != os.sep:
		tmpDir+=os.sep
	#Clip DEM & force it to unsigned 16 bit & assign nodata to 0
	extent=' '.join(map(str,(xmin, ymax, xmax, ymin)))
	outClipPath = tmpDir+baseName+"_clip"+outExt
	cmd='gdal_translate -co tfw=yes -ot UInt16 -a_nodata 0 -projwin '+extent+' -of GTiff "'+filePath+'" "'+outClipPath+'"'
	os.system(cmd)
	if not os.path.exists(outClipPath):
		return False
	#Calculate & parse stats
	os.system('gdalinfo -stats "'+outClipPath+'"')
	metadata = outClipPath+".aux.xml"
	from xml.dom import minidom
	xmldoc = minidom.parse(metadata)
	itemlist = xmldoc.getElementsByTagName('MDI')
	dico={}
	for s in itemlist :
		att = s.attributes['key'].value
		dico[att] = s.firstChild.data
	stats = (float(dico["STATISTICS_MINIMUM"]), float(dico["STATISTICS_MAXIMUM"]))
	#Scale image
	if scale:
		scale = ' '.join(map(str,stats))+" 0 "+str(2**16)#16 bit max value = 2**16 = 65535
		outScalePath = tmpDir+baseName+"_scale"+outExt
		cmd='gdal_translate -co tfw=yes -scale '+scale+' -of GTiff "'+outClipPath+'" "'+outScalePath+'"'
		os.system(cmd)
		if not os.path.exists(outScalePath):
			return False
		outFile = outScalePath
		scaleBounds = stats
	else:
		outFile = outClipPath
		scaleBounds = False
	#Load in Blender, pack and delete source files
	outDEM = DEM(outFile, 'u;16', pack=True, angCoords=angCoords, scaleBounds=scaleBounds)
	os.remove(outClipPath)
	os.remove(metadata)
	os.remove(WorldFile(outClipPath, xy(0,0)).wfPath)
	if scale:
		os.remove(outScalePath)
		os.remove(WorldFile(outScalePath, xy(0,0)).wfPath)
	#
	return outDEM


#------------------------------------------------------------------------

def placeObj(mesh, objName):
	bpy.ops.object.select_all(action='DESELECT')
	#create an object with that mesh
	obj = bpy.data.objects.new(objName, mesh)
	# Link object to scene
	bpy.context.scene.objects.link(obj)
	bpy.context.scene.objects.active = obj
	obj.select = True
	#bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
	return obj

def update3dViews(nbLines, scaleSize):
	targetDst=nbLines*scaleSize
	areas = bpy.context.screen.areas
	for area in areas:
		if area.type == 'VIEW_3D':
			space=area.spaces.active
			if space.grid_lines*space.grid_scale < targetDst:
				space.grid_lines=nbLines
				space.grid_scale=scaleSize
				space.clip_end=targetDst*10#10x more than necessary

def addTexture(mat, img, uvLay):
	engine = bpy.context.scene.render.engine
	mat.use_nodes = True
	node_tree = mat.node_tree
	node_tree.nodes.clear()
	#
	#CYCLES
	bpy.context.scene.render.engine = 'CYCLES' #force Cycles render
	# create image texture node
	textureNode = node_tree.nodes.new('ShaderNodeTexImage')
	textureNode.image = img
	textureNode.show_texture = True
	textureNode.location = (-200, 200)
	# Create BSDF diffuse node
	diffuseNode = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
	diffuseNode.location = (0, 200)
	# Create output node
	outputNode = node_tree.nodes.new('ShaderNodeOutputMaterial')
	outputNode.location = (200, 200)
	# Connect the nodes
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

def getBBox(obj):
	boundPts = obj.bound_box
	xmin=min([pt[0] for pt in boundPts])
	xmax=max([pt[0] for pt in boundPts])
	ymin=min([pt[1] for pt in boundPts])
	ymax=max([pt[1] for pt in boundPts])
	return bbox(xmin, xmax, ymin, ymax)

def getSubBoxPx(wf, subBox, reverseY=False):
	xmin, ymax = wf.pxFromGeo(subBox.xmin, subBox.ymin, round2Floor=True)#y pixels counting from top
	xmax, ymin = wf.pxFromGeo(subBox.xmax, subBox.ymax, round2Floor=True)#idem
	if reverseY:#y pixels counting from bottom
		ymin, ymax = ymax, ymin
	sizex, sizey = wf.rasterSize
	if xmin < 0: xmin = 0
	if xmax > sizex: xmax = sizex
	if ymin < 0: ymin = 0
	if ymax > sizey: ymax = sizey
	return bbox(xmin, xmax, ymin, ymax)#xmax et ymax inclus

def overlap(bb1, bb2):
	def test_overlap(a_min, a_max, b_min, b_max):
		return not ((a_min > b_max) or (b_min > a_max))
	return test_overlap(bb1.xmin, bb1.xmax, bb2.xmin, bb2.xmax) and test_overlap(bb1.ymin, bb1.ymax, bb2.ymin, bb2.ymax)

def geoRastUVmap(obj, mesh, uvTxtLayer, img, wf, dx, dy):
	uvTxtLayer.active = True
	# Assign image texture for every face
	for idx, pg in enumerate(mesh.polygons):
		uvTxtLayer.data[idx].image = img
	#Get UV loop layer
	uvLoopLayer = mesh.uv_layers.active
	#Assign uv coords
	loc = obj.location
	for pg in mesh.polygons:
		for i in pg.loop_indices:
			vertIdx = mesh.loops[i].vertex_index
			pt = list(mesh.vertices[vertIdx].co)
			pt = (pt[0] + loc.x + dx, pt[1] + loc.y + dy)#adjust coords against object location and shift values to retrieve original point coords
			#Compute UV coords --> pourcent from image origin (bottom left)
			dx_px, dy_px = wf.pxFromGeo(pt[0], pt[1], reverseY=True, round2Floor=False)
			u = dx_px / wf.rasterSize[0]
			v = dy_px / wf.rasterSize[1]
			#make sure uv coords are inside texture pixels (ie < rasterSize)
			eps=0.00001
			if u == 1: u = u - eps
			if v == 1: v = v - eps
			#Assign coords
			uvLoop = uvLoopLayer.data[i]
			uvLoop.uv = [u,v]

def setDisplacer(obj, rast, uvTxtLayer, mid=0):
	#Config displacer	
	if rast.wholeStats.rdelta == 0 or rast.subStats.rdelta == 0:
		return False
	displacer = obj.modifiers.new('DEM', type='DISPLACE')
	demTex = bpy.data.textures.new('demText', type = 'IMAGE')
	demTex.image = rast.img
	demTex.use_interpolation = False
	demTex.extension = 'CLIP'
	displacer.texture = demTex
	displacer.texture_coords = 'UV'
	displacer.uv_layer = uvTxtLayer.name
	displacer.mid_level = mid #Texture values below this value will result in negative displacement
	#Setting the displacement strength :
	#displacement = (texture value - Midlevel) * Strength <--> Strength = displacement / texture value (because mid=0)
	displacer.strength = rast.wholeStats.rdelta / rast.wholeStats.bdelta
	#If DEM non scaled then
	#	*displacement = alt max - alt min = delta Z
	#	*texture value = delta Z / (2^depth-1) #in Blender pixel values are normalized between 0.0 and 1.0
	#Strength = displacement / texture value = delta Z / (delta Z / (2^depth-1)) 
	#--> Strength = 2^depth-1
	#displacer.strength = 2**rast.depth-1
	bpy.ops.object.shade_smooth()
	return displacer

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

	# List of operator properties, the attributes will be assigned
	# to the class instance from the operator settings before calling.
	importMode = EnumProperty(
			name="Mode",
			description="Select import mode",
			items=[ ('plan', 'On plane', "Place raster texture on new plane mesh"),
			('bkg', 'As background', "Place raster as background image"),
			('mesh', 'On mesh', "UV map raster on an existing mesh"),
			('DEM', 'As DEM', "Use DEM raster GRID to wrap an existing mesh"),
			('DEM_GDAL', 'As DEM (GDAL)', "Use DEM raster GRID to wrap an existing mesh")]
			)
	#Use previous object translation
	useGeoref = BoolProperty(
			name="Consider georeferencing",
			description="Adjust position next to previous import",
			default=True
			)
	#
	objectsLst = EnumProperty(attr="obj_list", name="Objects", description="Choose object to edit", items=listObjects)
	#
	#Adjust 3d view (grid size and clip distance)
	adjust3dView = BoolProperty(
			name="Adjust 3d view",
			description="Adjust grid floor and clip distances",
			default=True
			)
	#Subdivise (as DEM option)
	subdivision = EnumProperty(
			name="Subdivision",
			description="How to subdivise the plane (dispacer needs vertex to work with)",
			items=[ ('subsurf', 'Subsurf', "Add a subsurf modifier"),
			('mesh', 'Mesh', "Edit the mesh to subdivise the plane according to the number of DEM pixels which overlay the plane"),
			('none', 'None', "No subdivision")]
			)
	#Scale DEM
	scale = BoolProperty(
			name="Scale",
			description="Scale the DEM according to bit depth",
			default=False
			)
	#Scaled DEM bounds
	scale_altMin = IntProperty(
			name="DEM min value",
			default=0
			)
	scale_altMax = IntProperty(

			name="DEM max value",
			default=0
			)
	#Is DEM scaled ?
	isScaled = BoolProperty(
			name="Is scaled",
			description="Is DEM scaled?",
			default=False
			)
	#DEM bit detph
	imgBitDepth = EnumProperty(
			name="Image depth",
			description="Select image bit depth",
			items=[ ('u;16', '16 bits unsigned', "Unsigned 16 bits integer values"),
			('s;16', '16 bits signed', "Signed 16 bits integer values"),
			('u;8', '8 bits', "Byte integer value")]
			)
	#Decimal degrees to meters
	angCoords = BoolProperty(
			name="Angular coords",
			description="Will convert decimal degrees coordinates to meters",
			default=False
			)
	#GDAL mode (python binding or binary)
	gdalMode = EnumProperty(
			name="GDAL mode",
			description="Select how to use GDAL",
			items=[ ('PYTHON', 'Python', "Use GDAL Python binding"),
			('BINARY', 'Binary', "Use GDAL executables")]
			)

	def draw(self, context):
		#Function used by blender to draw the panel.
		layout = self.layout
		layout.prop(self, 'importMode')
		scn = bpy.context.scene
		if "Georef X" in scn and "Georef Y" in scn:
			isGeoref = True
		else:
			isGeoref = False
		#
		if self.importMode == 'plan':
			if isGeoref:
				layout.prop(self, 'useGeoref')
			else:
				self.useGeoref = False
			layout.prop(self, 'angCoords')
			layout.prop(self, 'adjust3dView')
		#
		if self.importMode == 'bkg':
			if isGeoref:
				layout.prop(self, 'useGeoref')
			else:
				self.useGeoref = False
			layout.prop(self, 'angCoords')
			self.adjust3dView = False
		#
		if self.importMode == 'mesh':
			if isGeoref and len(self.objectsLst) > 0:
				self.useGeoref = True
				layout.prop(self, 'objectsLst')
				layout.prop(self, 'angCoords')
				self.adjust3dView = False
			else:
				self.useGeoref = False
				layout.label("There isn't georef mesh to UVmap on")
		#
		if self.importMode == 'DEM':
			if isGeoref and len(self.objectsLst) > 0:
				self.useGeoref = True
				layout.prop(self, 'objectsLst')
				layout.prop(self, 'subdivision')
				layout.prop(self, 'imgBitDepth')
				if self.imgBitDepth.split(';')[0] == 's':#signed data
					layout.label("Warning, negatives values will be set to 0")
				layout.prop(self, 'isScaled')
				if self.isScaled:
					layout.prop(self, 'scale_altMin')
					layout.prop(self, 'scale_altMax')
				layout.prop(self, 'angCoords')
				self.scale = False
				self.adjust3dView = False
			else:
				self.useGeoref = False
				layout.label("There isn't georef mesh to apply DEM on")
		#
		global GDAL_PY
		global GDAL_BIN
		if self.importMode == 'DEM_GDAL':
			if isGeoref and len(self.objectsLst) > 0:
				layout.prop(self, 'gdalMode')
				if self.gdalMode == "PYTHON" and not GDAL_PY:
					layout.label("GDAL Python binding isn't installed")
				elif self.gdalMode == "BINARY" and not GDAL_BIN:
					layout.label("GDAL binary executables aren't installed")
				else:
					self.useGeoref = True
					layout.prop(self, 'objectsLst')
					self.adjust3dView = False
					layout.prop(self, 'subdivision')
					self.isScaled = False
					layout.prop(self, 'scale')
					layout.prop(self, 'angCoords')
			else:
				self.useGeoref = False
				layout.label("There isn't georef mesh to apply DEM on")


	def err(self, msg):
		self.report({'ERROR'}, msg)
		print(msg)
		return {'FINISHED'}

	def execute(self, context):
		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass
		#Get scene
		scn = bpy.context.scene
		#Path
		filePath = self.filepath
		name=os.path.basename(filePath)[:-4]
		#Check GDAL installation
		global GDAL_PY
		global GDAL_BIN
		if self.importMode == 'DEM_GDAL':
			if self.gdalMode == "PYTHON" and not GDAL_PY:
				return self.err("GDAL Python binding isn't installed")
			if self.gdalMode == "BINARY" and not GDAL_BIN:
				return self.err("GDAL binaries executables aren't installed")
		#Get bbox of reference plane
		if self.importMode in ['mesh', 'DEM', 'DEM_GDAL']:#on mesh or as DEM
			if not self.useGeoref:
				return self.err("There isn't georef mesh to UVmap on")
			else:
				dx = scn["Georef X"]
				dy = scn["Georef Y"]
			obj = scn.objects[int(self.objectsLst)]
			obj.select = True
			scn.objects.active = obj
			bpy.ops.object.transform_apply(rotation=True, scale=True)
			bb = getBBox(obj)
			loc = obj.location
			projBBox = bbox(bb.xmin+dx+loc.x, bb.xmax+dx+loc.x, bb.ymin+dy+loc.y, bb.ymax+dy+loc.y)
		#Get scale bounds values
		if self.isScaled:
			scaleBounds = (self.scale_altMin, self.scale_altMax)
		else:
			scaleBounds = False

		######################################
		if self.importMode == 'plan':#on plane
			#Load raster
			try:
				rast = Raster(filePath, self.angCoords)
			except IOError as e:
				return self.err(str(e))
			img, wf = rast.img, rast.wf
			#Get georef data
			if self.useGeoref:
				dx, dy = scn["Georef X"], scn["Georef Y"]
			else:#Add custom properties define x & y translation to retrieve georeferenced model
				dx, dy = wf.center.x, wf.center.y
				scn["Georef X"], scn["Georef Y"] = dx, dy
			#create mesh
			bm = bmesh.new()
			pts = [(pt.x-dx, pt.y-dy) for pt in wf.corners]#shift coords
			z = 0
			pts = [bm.verts.new((pt[0], pt[1], z)) for pt in pts]#upper left to botton left (clockwise)
			pts.reverse()#bottom left to upper left (anticlockwise --> face up)
			bm.faces.new(pts)
			#Create mesh from bmesh
			mesh = bpy.data.meshes.new(name)
			bm.to_mesh(mesh)
			bm.free()
			#place obj
			obj = placeObj(mesh, name)
			#UV mapping
			uvTxtLayer = mesh.uv_textures.new('rastUVmap')# Add UV map texture layer
			geoRastUVmap(obj, mesh, uvTxtLayer, img, wf, dx, dy)
			# Create material
			mat = bpy.data.materials.new('rastMat')
			# Add material to current object
			obj.data.materials.append(mat)
			# Add texture to material
			addTexture(mat, img, uvTxtLayer)

		######################################
		if self.importMode == 'bkg':#background
			#Load raster
			try:
				rast = Raster(filePath, self.angCoords)
			except IOError as e:
				return self.err(str(e))
			img, wf = rast.img, rast.wf
			#Check pixel size and rotation
			if wf.rotation.xy != [0,0]:
				return self.err("Cannot rotate background image")
			if abs(round(wf.pixelSize.x, 3)) != abs(round(wf.pixelSize.y, 3)):
				return self.err("Background image needs equal pixel size in map units in both x ans y axis")
			#
			trueSizeX = wf.geoSize.x
			trueSizeY = wf.geoSize.y
			ratio = img.size[0] / img.size[1]
			if self.useGeoref:
				dx, dy = scn["Georef X"], scn["Georef Y"]
				shiftCenter = (wf.center.x - dx, wf.center.y - dy)
			else:
				dx, dy = wf.center.x, wf.center.y
				scn["Georef X"], scn["Georef Y"] = dx, dy
			areas = bpy.context.screen.areas
			for area in areas:
				if area.type == 'VIEW_3D':
					space = area.spaces.active
					space.show_background_images=True
					bckImg = space.background_images.new()
					bckImg.image = img
					bckImg.view_axis = 'TOP'
					bckImg.opacity = 1
					bckImg.size = trueSizeX/2#at size = 1, width = 2 blender units
					if self.useGeoref:
						bckImg.offset_x = shiftCenter[0]
						bckImg.offset_y = shiftCenter[1]*ratio

		######################################
		if self.importMode == 'mesh':
			#Load raster
			try:
				rast = Raster(filePath, self.angCoords)
			except IOError as e:
				return self.err(str(e))
			img, wf = rast.img, rast.wf
			# Check data overlap
			if not overlap(wf.bbox, projBBox):
				return self.err("Non overlap data")
			# Add UV map texture layer
			mesh = obj.data
			uvTxtLayer = mesh.uv_textures.new('rastUVmap')
			# UV mapping
			geoRastUVmap(obj, mesh, uvTxtLayer, img, wf, dx, dy)
			# Add material and texture
			mat = bpy.data.materials.new('rastMat')
			obj.data.materials.append(mat)
			addTexture(mat, img, uvTxtLayer)

		######################################
		if self.importMode in ['DEM','DEM_GDAL']:
			#Load raster
			if self.importMode == 'DEM':
				try:
					rast = DEM(filePath, self.imgBitDepth, self.angCoords, scaleBounds)
				except IOError as e:
					return self.err(str(e))
			elif self.importMode == 'DEM_GDAL':
				if self.gdalMode == 'PYTHON':
					try:
						ds = DEM_GDAL(filePath, self.angCoords, scale=self.scale)
						rast = ds.clip(projBBox)
						del ds
					except OverlapError as e:
						return self.err(str(e))
				elif self.gdalMode == 'BINARY':
					rast = gdalProcess(filePath, projBBox, angCoords=self.angCoords, scale=self.scale)
					if not rast:
						return self.err("GDAL Fails")
			#--------------------------
			img, wf = rast.img, rast.wf
			#Check data overlap
			if not overlap(wf.bbox, projBBox):
				return self.err("Non overlap data")
			#Compute stats
			rast.getStats(subBox=projBBox)
			# Add UV map texture layer
			mesh = obj.data
			previousUVmap = mesh.uv_textures.active
			uvTxtLayer = mesh.uv_textures.new('demUVmap')
			#UV mapping
			geoRastUVmap(obj, mesh, uvTxtLayer, img, wf, dx, dy)
			#Add material and texture
			if not previousUVmap:
				mat = bpy.data.materials.new('rastMat')
				obj.data.materials.append(mat)
				addTexture(mat, img, uvTxtLayer)
			else:
				previousUVmap.active = True
			#Make subdivision
			if self.subdivision == 'mesh':#Mesh cut
				#if len(mesh.polygons) == 1: #controler que le mesh n'a qu'une face
				nbCuts = int(max(tuple(img.size)))#Estimate better subdivise cuts number
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
			dsp = setDisplacer(obj, rast, uvTxtLayer)
			if not dsp :
				return self.err("Alt min == alt max, unable to config displacer")

		######################################
		#Adjust 3d view
		if self.adjust3dView:
			bb = getBBox(obj)
			dstMax = round(max(abs(bb.xmax), abs(bb.xmin), abs(bb.ymax), abs(bb.ymin)))*2
			nbDigit = len(str(dstMax))
			scale = 10**(nbDigit-2)#1 digits --> 0.1m, 2 --> 1m, 3 --> 10m, 4 --> 100m, , 5 --> 1000m
			nbLines = round(dstMax/scale)
			update3dViews(nbLines, scale)


		# forced view mode with textures
		areas = bpy.context.screen.areas
		for area in areas:
			if area.type == 'VIEW_3D':
				area.spaces.active.show_textured_solid = True
				if scn.render.engine == 'CYCLES':
					area.spaces.active.viewport_shade = 'TEXTURED'
				elif scn.render.engine == 'BLENDER_RENDER':
					area.spaces.active.viewport_shade = 'SOLID'


		return {'FINISHED'}


# Register in File > Import menu
def menu_func_import(self, context):
	self.layout.operator(IMPORT_GEORAST.bl_idname, text="Georeferenced raster")

def register():
	bpy.utils.register_class(IMPORT_GEORAST)
	bpy.types.INFO_MT_file_import.append(menu_func_import)

def unregister():
	bpy.utils.unregister_class(IMPORT_GEORAST)
	bpy.types.INFO_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
	register()

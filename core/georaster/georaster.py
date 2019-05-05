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

import logging
log = logging.getLogger(__name__)

from ..lib import Tyf #geotags reader

from .georef import GeoRef
from .npimg import NpImage
from .img_utils import getImgFormat, getImgDim

from ..utils import XY as xy
from ..errors import OverlapError
from ..checkdeps import HAS_GDAL

if HAS_GDAL:
	from osgeo import gdal


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
				raise IOError("Unsupported format {}".format(self.format))

			if self.isTiff:
				self._fromTIFF()
				if not self.isGeoref and self.hasWorldFile:
					self.georef = GeoRef.fromWorldFile(self.wfPath, self.size)
				else:
					pass
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
		#Warning : Tyf object does not support k in dict test syntax nor get() method, use try block instead
		self.size = xy(tif['ImageWidth'], tif['ImageLength'])
		self.nbBands = tif['SamplesPerPixel']
		self.depth = tif['BitsPerSample']
		if self.nbBands > 1:
			self.depth = self.depth[0]
		sampleFormatMap = {1:'uint', 2:'int', 3:'float', None:'uint', 6:'complex'}
		try:
			self.dtype = sampleFormatMap[tif['SampleFormat']]
		except KeyError:
			self.dtype = 'uint'
		try:
			self.noData = float(tif['GDAL_NODATA'])
		except KeyError:
			self.noData = None
		#Get Georef
		try:
			self.georef = GeoRef.fromTyf(tif)
		except Exception as e:
			log.warning('Cannot extract georefencing informations from tif tags')#, exc_info=True)
			pass


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
		if self.georef is not None:
			if self.origin is not None and self.pxSize is not None and self.rotation is not None:
				return True
			else:
				return False
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
		return '\n'.join([
		'* Paths infos :',
		' path {}'.format(self.path),
		' worldfile {}'.format(self.wfPath),
		' format {}'.format(self.format),
		"* Data infos :",
		" size {}".format(self.size),
		" bit depth {}".format(self.depth),
		" data type {}".format(self.dtype),
		" number of bands {}".format(self.nbBands),
		" nodata value {}".format(self.noData),
		"* Georef & Geometry : \n{}".format(self.georef)
		])

	#######################################
	# Methods
	#######################################

	def toGDAL(self):
		'''Get GDAL dataset'''
		return gdal.Open(self.path, gdal.GA_ReadOnly)

	def readAsNpArray(self, subset=True):
		'''Read raster pixels values as Numpy Array'''

		if subset and self.subBoxGeo is not None:
			#georef = GeoRef(self.size, self.pxSize, self.subBoxGeoOrigin, rot=self.rotation, pxCenter=True)
			img = NpImage(self.path, subBoxPx=self.subBoxPx, noData=self.noData, georef=self.georef, adjustGeoref=True)
		else:
			img = NpImage(self.path, noData=self.noData, georef=self.georef)
		return img

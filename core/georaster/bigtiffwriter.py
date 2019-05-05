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
from .npimg import NpImage


from ..checkdeps import HAS_GDAL, HAS_PIL, HAS_IMGIO

if HAS_GDAL:
	from osgeo import gdal


class BigTiffWriter():
	'''
	This class is designed to write a bigtif with jpeg compression
	writing a large tiff file without trigger a memory overflow is possible with the help of GDAL library
	jpeg compression allows to maintain a reasonable file size
	transparency or nodata are stored in an internal tiff mask because it's not possible to have an alpha channel when using jpg compression
	'''


	def __del__(self):
		# properly close gdal dataset
		self.ds = None


	def __init__(self, path, w, h, georef, geoTiffOptions={'TFW':'YES', 'TILED':'YES', 'BIGTIFF':'YES', 'COMPRESS':'JPEG', 'JPEG_QUALITY':80, 'PHOTOMETRIC':'YCBCR'}):
		'''
		path = fule system path for the ouput tiff
		w, h = width and height in pixels
		georef : a Georef object used to set georeferencing informations, optional
		geoTiffOptions : GDAL create option for tiff format
		'''

		if not HAS_GDAL:
			raise ImportError("GDAL interface unavailable")


		#control path validity

		self.w = w
		self.h = h
		self.size = (w, h)

		self.path = path
		self.georef = georef

		if geoTiffOptions.get('COMPRESS', None) == 'JPEG':
			#JPEG in tiff cannot have an alpha band, workaround is to use internal tiff mask
			self.useMask = True
			gdal.SetConfigOption('GDAL_TIFF_INTERNAL_MASK', 'YES')
			n = 3 #RGB
		else:
			self.useMask = False
			n = 4 #RGBA
		self.nbBands = n

		options = [str(k) + '=' + str(v) for k, v in geoTiffOptions.items()]

		driver = gdal.GetDriverByName("GTiff")
		gdtype = gdal.GDT_Byte #GDT_UInt16, GDT_Int16, GDT_UInt32, GDT_Int32
		self.dtype = 'uint8'

		self.ds = driver.Create(path, w, h, n, gdtype, options)
		if self.useMask:
			self.ds.CreateMaskBand(gdal.GMF_PER_DATASET)#The mask band is shared between all bands on the dataset
			self.mask = self.ds.GetRasterBand(1).GetMaskBand()
			self.mask.Fill(255)
		elif n == 4:
			self.ds.GetRasterBand(4).Fill(255)

		#Write georef infos
		self.ds.SetGeoTransform(self.georef.toGDAL())
		if self.georef.crs is not None:
			self.ds.SetProjection(self.georef.crs.getOgrSpatialRef().ExportToWkt())
		#self.georef.toWorldFile(os.path.splitext(path)[0] + '.tfw')


	def paste(self, data, x, y):
		'''data = numpy array or NpImg'''
		img = NpImage(data)
		data = img.data
		#Write RGB
		for bandIdx in range(3): #writearray is available only at band level
			bandArray = data[:,:,bandIdx]
			self.ds.GetRasterBand(bandIdx+1).WriteArray(bandArray, x, y)
		#Process alpha
		hasAlpha = data.shape[2] == 4
		if hasAlpha:
			alpha = data[:,:,3]
			if self.useMask:
				self.mask.WriteArray(alpha, x, y)
			else:
				self.ds.GetRasterBand(4).WriteArray(alpha, x, y)
		else:
			pass # replaced by fill method
			'''
			#make alpha band or internal mask fully opaque
			h, w = data.shape[0], data.shape[1]
			alpha = np.full((h, w), 255, np.uint8)
			if self.useMask:
				self.mask.WriteArray(alpha, x, y)
			else:
				self.ds.GetRasterBand(4).WriteArray(alpha, x, y)
			'''



	def __repr__(self):
		return '\n'.join([
		"* Data infos :",
		" size {}".format(self.size),
		" type {}".format(self.dtype),
		" number of bands {}".format(self.nbBands),
		"* Georef & Geometry : \n{}".format(self.georef)
		])

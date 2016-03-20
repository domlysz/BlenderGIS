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

class ellps():
	"""ellipsoid"""
	def __init__(self, a, b):
		self.a =  a#equatorial radius in meters
		self.b =  b#polar radius in meters
		self.f = (self.a-self.b)/self.a#inverse flat
		self.perimeter = (2*math.pi*self.a)#perimeter at equator

GRS80 = ellps(6378137, 6356752.314245)

class xy(object):
	'''A class to represent 2-tuple value'''
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

class bbox():
	'''A class to represent a bounding box'''
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
		k = GRS80.perimeter/360
		return bbox(self.xmin * k, self.xmax * k, self.ymin * k, self.ymax * k)
	def meters2degrees(self):
		k = GRS80.perimeter/360
		return bbox(self.xmin / k, self.xmax / k, self.ymin / k, self.ymax / k)

def overlap(bb1, bb2):
	'''Test if 2 bbox objects have intersection areas'''
	def test_overlap(a_min, a_max, b_min, b_max):
		return not ((a_min > b_max) or (b_min > a_max))
	return test_overlap(bb1.xmin, bb1.xmax, bb2.xmin, bb2.xmax) and test_overlap(bb1.ymin, bb1.ymax, bb2.ymin, bb2.ymax)

class OverlapError(Exception):
	'''A class to raise an overlap error'''
	def __init__(self):
		pass
	def __str__(self):
		return "Non overlap data"

def scale(inVal, low, high, mn, mx):
	'''Scale/normalize data (linear stretch from lowest value to highest value)'''
	#outVal = (inVal - min) * (hight - low) / (max - min)] + low
	return (inVal - mn) * (high - low) / (mx - mn) + low

########################################

import struct


def getImgFormat(filepath):
	"""
	Read header of an image file and try to determine it's format
	no requirements, support JPEG, JPEG2000, PNG, GIF, BMP, TIFF, EXR
	"""
	format = None
	with open(filepath, 'rb') as fhandle:
		head = fhandle.read(32)
		# handle GIFs
		if head[:6] in (b'GIF87a', b'GIF89a'):
			format = 'GIF'
		# handle PNG
		elif head.startswith(b'\211PNG\r\n\032\n'):
			format = 'PNG'
		# handle JPEGs
		elif head[6:10] in (b'JFIF', b'Exif'):
			format = 'JPEG'
		# handle JPEG2000s
		elif head.startswith(b'\x00\x00\x00\x0cjP  \r\n\x87\n'):
			format = 'JPEG2000'
		# handle BMP
		elif head.startswith(b'BM'):
			format = 'BMP'
		# handle TIFF
		elif head[:2] in (b'MM', b'II'):
			format = 'TIFF'
		# handle EXR
		elif head.startswith(b'\x76\x2f\x31\x01'):
			format = 'EXR'
	return format



def getImgDim(filepath):
	"""
	Return (width, height) for a given img file content
	no requirements, support JPEG, JPEG2000, PNG, GIF, BMP
	"""
	width, height = None, None
	
	with open(filepath, 'rb') as fhandle:
		head = fhandle.read(32)	
		# handle GIFs
		if head[:6] in (b'GIF87a', b'GIF89a'):
			try:
				width, height = struct.unpack("<hh", head[6:10])
			except struct.error:
				raise ValueError("Invalid GIF file")
		# handle PNG
		elif head.startswith(b'\211PNG\r\n\032\n'):
			try:
				width, height = struct.unpack(">LL", head[16:24])
			except struct.error:
				# Maybe this is for an older PNG version.
				try:
					width, height = struct.unpack(">LL", head[8:16])
				except struct.error:
					raise ValueError("Invalid PNG file")
		# handle JPEGs
		elif head[6:10] in (b'JFIF', b'Exif'):
			try:
				fhandle.seek(0) # Read 0xff next
				size = 2
				ftype = 0
				while not 0xc0 <= ftype <= 0xcf:
					fhandle.seek(size, 1)
					byte = fhandle.read(1)
					while ord(byte) == 0xff:
						byte = fhandle.read(1)
					ftype = ord(byte)
					size = struct.unpack('>H', fhandle.read(2))[0] - 2
				# We are at a SOFn block
				fhandle.seek(1, 1)  # Skip `precision' byte.
				height, width = struct.unpack('>HH', fhandle.read(4))
			except struct.error:
				raise ValueError("Invalid JPEG file")
		# handle JPEG2000s
		elif head.startswith(b'\x00\x00\x00\x0cjP  \r\n\x87\n'):
			fhandle.seek(48)
			try:
				height, width = struct.unpack('>LL', fhandle.read(8))
			except struct.error:
				raise ValueError("Invalid JPEG2000 file")
		# handle BMP
		elif head.startswith(b'BM'):
			imgtype = 'BMP'
			try:
				width, height = struct.unpack("<LL", head[18:26])
			except struct.error:
				raise ValueError("Invalid BMP file")

	return width, height


########################################
# Inpainting function
# http://astrolitterbox.blogspot.fr/2012/03/healing-holes-in-arrays-in-python.html
# https://github.com/gasagna/openpiv-python/blob/master/openpiv/src/lib.pyx


import numpy as np

DTYPEf = np.float64
DTYPEi = np.int32


def replace_nans(array, max_iter, tolerance, kernel_size=1, method='localmean'):
	"""
	Replace NaN elements in an array using an iterative image inpainting algorithm.
	The algorithm is the following:
	1) For each element in the input array, replace it by a weighted average
	of the neighbouring elements which are not NaN themselves. The weights depends
	of the method type. If ``method=localmean`` weight are equal to 1/( (2*kernel_size+1)**2 -1 )
	2) Several iterations are needed if there are adjacent NaN elements.
	If this is the case, information is "spread" from the edges of the missing
	regions iteratively, until the variation is below a certain threshold.
	
	Parameters
	----------
	array : 2d np.ndarray
	an array containing NaN elements that have to be replaced
	
	max_iter : int
	the number of iterations
	
	kernel_size : int
	the size of the kernel, default is 1
	
	method : str
	the method used to replace invalid values. Valid options are 'localmean', 'idw'.
	
	Returns
	-------
	filled : 2d np.ndarray
	a copy of the input array, where NaN elements have been replaced.
	"""
	
	filled = np.empty( [array.shape[0], array.shape[1]], dtype=DTYPEf)
	kernel = np.empty( (2*kernel_size+1, 2*kernel_size+1), dtype=DTYPEf )
	
	# indices where array is NaN
	inans, jnans = np.nonzero( np.isnan(array) )
	
	# number of NaN elements
	n_nans = len(inans)
	
	# arrays which contain replaced values to check for convergence
	replaced_new = np.zeros( n_nans, dtype=DTYPEf)
	replaced_old = np.zeros( n_nans, dtype=DTYPEf)
	
	# depending on kernel type, fill kernel array
	if method == 'localmean':
		# weight are equal to 1/( (2*kernel_size+1)**2 -1 )
		for i in range(2*kernel_size+1):
			for j in range(2*kernel_size+1):
				kernel[i,j] = 1
		#print(kernel, 'kernel')
	elif method == 'idw':
		kernel = np.array([[0, 0.5, 0.5, 0.5,0],
				  [0.5,0.75,0.75,0.75,0.5], 
				  [0.5,0.75,1,0.75,0.5],
				  [0.5,0.75,0.75,0.5,1],
				  [0, 0.5, 0.5 ,0.5 ,0]])
		#print(kernel, 'kernel')
	else:
		raise ValueError("method not valid. Should be one of 'localmean', 'idw'.")
	
	# fill new array with input elements
	for i in range(array.shape[0]):
		for j in range(array.shape[1]):
			filled[i,j] = array[i,j]

	# make several passes
	# until we reach convergence
	for it in range(max_iter):
		#print('Fill NaN iteration', it)
		# for each NaN element
		for k in range(n_nans):
			i = inans[k]
			j = jnans[k]
			
			# initialize to zero
			filled[i,j] = 0.0
			n = 0
			
			# loop over the kernel
			for I in range(2*kernel_size+1):
				for J in range(2*kernel_size+1):
				   
					# if we are not out of the boundaries
					if i+I-kernel_size < array.shape[0] and i+I-kernel_size >= 0:
						if j+J-kernel_size < array.shape[1] and j+J-kernel_size >= 0:
							
							# if the neighbour element is not NaN itself.
							if filled[i+I-kernel_size, j+J-kernel_size] == filled[i+I-kernel_size, j+J-kernel_size] :
								
								# do not sum itself
								if I-kernel_size != 0 and J-kernel_size != 0:
									
									# convolve kernel with original array
									filled[i,j] = filled[i,j] + filled[i+I-kernel_size, j+J-kernel_size]*kernel[I, J]
									n = n + 1*kernel[I,J]
			# divide value by effective number of added elements
			if n != 0:
				filled[i,j] = filled[i,j] / n
				replaced_new[k] = filled[i,j]
			else:
				filled[i,j] = np.nan
				
		# check if mean square difference between values of replaced
		# elements is below a certain tolerance
		#print('tolerance', np.mean( (replaced_new-replaced_old)**2 ))
		if np.mean( (replaced_new-replaced_old)**2 ) < tolerance:
			break
		else:
			for l in range(n_nans):
				replaced_old[l] = replaced_new[l]
	
	return filled


def sincinterp(image, x,  y, kernel_size=3 ):
	"""
	Re-sample an image at intermediate positions between pixels.
	This function uses a cardinal interpolation formula which limits
	the loss of information in the resampling process. It uses a limited
	number of neighbouring pixels.
	
	The new image :math:`im^+` at fractional locations :math:`x` and :math:`y` is computed as:
	.. math::
	im^+(x,y) = \sum_{i=-\mathtt{kernel\_size}}^{i=\mathtt{kernel\_size}} \sum_{j=-\mathtt{kernel\_size}}^{j=\mathtt{kernel\_size}} \mathtt{image}(i,j) sin[\pi(i-\mathtt{x})] sin[\pi(j-\mathtt{y})] / \pi(i-\mathtt{x}) / \pi(j-\mathtt{y})
	
	Parameters
	----------
	image : np.ndarray, dtype np.int32
	the image array.
	
	x : two dimensions np.ndarray of floats
	an array containing fractional pixel row
	positions at which to interpolate the image
	
	y : two dimensions np.ndarray of floats
	an array containing fractional pixel column
	positions at which to interpolate the image
	
	kernel_size : int
	interpolation is performed over a ``(2*kernel_size+1)*(2*kernel_size+1)``
	submatrix in the neighbourhood of each interpolation point.
	
	Returns
	-------
	im : np.ndarray, dtype np.float64
	the interpolated value of ``image`` at the points specified by ``x`` and ``y``
	"""
   
	# the output array
	r = np.zeros( [x.shape[0], x.shape[1]], dtype=DTYPEf)
	 
	# fast pi
	pi = 3.1419
	
	# for each point of the output array
	for I in range(x.shape[0]):
		for J in range(x.shape[1]):
			
			#loop over all neighbouring grid points
			for i in range( int(x[I,J])-kernel_size, int(x[I,J])+kernel_size+1 ):
				for j in range( int(y[I,J])-kernel_size, int(y[I,J])+kernel_size+1 ):
					# check that we are in the boundaries
					if i >= 0 and i <= image.shape[0] and j >= 0 and j <= image.shape[1]:
						if (i-x[I,J]) == 0.0 and (j-y[I,J]) == 0.0:
							r[I,J] = r[I,J] + image[i,j]
						elif (i-x[I,J]) == 0.0:
							r[I,J] = r[I,J] + image[i,j] * np.sin( pi*(j-y[I,J]) )/( pi*(j-y[I,J]) )
						elif (j-y[I,J]) == 0.0:
							r[I,J] = r[I,J] + image[i,j] * np.sin( pi*(i-x[I,J]) )/( pi*(i-x[I,J]) )
						else:
							r[I,J] = r[I,J] + image[i,j] * np.sin( pi*(i-x[I,J]) )*np.sin( pi*(j-y[I,J]) )/( pi*pi*(i-x[I,J])*(j-y[I,J]))
	return r


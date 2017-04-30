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
from mathutils import Vector
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_vector_3d


class XY(object):
	'''A class to represent 2-tuple value'''
	def __init__(self, x, y, z=None):
		'''
		You can use the constructor in many ways:
		XY(0, 1) - passing two arguments
		XY(x=0, y=1) - passing keywords arguments
		XY(**{'x': 0, 'y': 1}) - unpacking a dictionary
		XY(*[0, 1]) - unpacking a list or a tuple (or a generic iterable)
		'''
		if z is None:
			self.data=[x, y]
		else:
			self.data=[x, y, z]
	def __str__(self):
		if self.z is not None:
			return "(%s, %s, %s)"%(self.x, self.y, self.z)
		else:
			return "(%s, %s)"%(self.x,self.y)
	def __repr__(self):
		return self.__str__()
	def __getitem__(self,item):
		return self.data[item]
	def __setitem__(self, idx, value):
		self.data[idx] = value
	def __iter__(self):
		return iter(self.data)
	def __len__(self):
		return len(self.data)
	@property
	def x(self):
		return self.data[0]
	@property
	def y(self):
		return self.data[1]
	@property
	def z(self):
		try:
			return self.data[2]
		except:
			return None
	@property
	def xy(self):
		return self.data[:2]
	@property
	def xyz(self):
		return self.data


class BBOX(dict):
	'''A class to represent a bounding box'''

	def __init__(self, *args, **kwargs):
		'''
		Three ways for init a BBOX class:
		- from a list of values ordered from bottom left to upper right
			>> BBOX(xmin, ymin, xmax, ymax) or BBOX(xmin, ymin, zmin, xmax, ymax, zmax)
		- from a tuple contained a list of values ordered from bottom left to upper right
			>> BBOX( (xmin, ymin, xmax, ymax) ) or BBOX( (xmin, ymin, zmin, xmax, ymax, zmax) )
		- from keyword arguments with no particular order
			>> BBOX(xmin=, ymin=, xmax=, ymax=) or BBOX(xmin=, ymin=, zmin=, xmax=, ymax=, zmax=)
		'''
		if args:
			if len(args) == 1: #maybee we pass directly a tuple
				args = args[0]
			if len(args) == 4:
				self.xmin, self.ymin, self.xmax, self.ymax = args
			elif len(args) == 6:
				self.xmin, self.ymin, self.zmin, self.xmax, self.ymax, self.zmax = args
			else:
				raise ValueError('BBOX() initialization expects 4 or 6 arguments, got %g' % len(args))
		elif kwargs:
			if not all( [kw in kwargs for kw in ['xmin', 'ymin', 'xmax', 'ymax']] ):
				raise ValueError('invalid keyword arguments')
			self.xmin, self.xmax = kwargs['xmin'], kwargs['xmax']
			self.ymin, self.ymax = kwargs['ymin'], kwargs['ymax']
			if 'zmin' in kwargs and 'zmax' in kwargs:
				self.zmin, self.zmax = kwargs['zmin'], kwargs['zmax']

	def __str__(self):
		if self.hasZ:
			return 'xmin:%g, ymin:%g, zmin:%g, xmax:%g, ymax:%g, zmax:%g' % tuple(self)
		else:
			return 'xmin:%g, ymin:%g, xmax:%g, ymax:%g' % tuple(self)

	def __getitem__(self, attr):
		'''access attributes like a dictionnary'''
		return getattr(self, attr)

	def __setitem__(self, key, value):
		'''set attributes like a dictionnary'''
		setattr(self, key, value)

	def __iter__(self):
		'''iterate overs values in bottom left to upper right order
		allows support of unpacking and conversion to tuple or list'''
		if self.hasZ:
			return iter([self.xmin, self.ymin, self.zmin, self.xmax, self.ymax, self.ymax])
		else:
			return iter([self.xmin, self.ymin, self.xmax, self.ymax])

	def keys(self):
		'''override dict keys() method'''
		return self.__dict__.keys()

	def items(self):
		'''override dict keys() method'''
		return self.__dict__.items()

	def values(self):
		'''override dict keys() method'''
		return self.__dict__.values()


	@classmethod
	def fromObj(cls, obj, applyTransform = True):
		'''Create a 3D BBOX from Blender object'''
		if applyTransform:
			boundPts = [obj.matrix_world * Vector(corner) for corner in obj.bound_box]
		else:
			boundPts = obj.bound_box
		xmin = min([pt[0] for pt in boundPts])
		xmax = max([pt[0] for pt in boundPts])
		ymin = min([pt[1] for pt in boundPts])
		ymax = max([pt[1] for pt in boundPts])
		zmin = min([pt[2] for pt in boundPts])
		zmax = max([pt[2] for pt in boundPts])
		return cls(xmin=xmin, ymin=ymin, zmin=zmin, xmax=xmax, ymax=ymax, zmax=zmax)

	@classmethod
	def fromScn(cls, scn):
		'''Create a 3D BBOX from Blender Scene
		union of bounding box of all objects containing in the scene'''
		scn = bpy.context.scene
		objs = scn.objects
		if len(objs) == 0:
			scnBbox = cls(0,0,0,0,0,0)
		else:
			scnBbox = BBOX.fromObj(objs[0])
		for obj in objs:
			bbox = BBOX.fromObj(obj)
			scnBbox += bbox
		return scnBbox

	@classmethod
	def fromBmesh(cls, bm):
		'''Create a 3D bounding box from a bmesh object'''
		xmin = min([pt.co.x for pt in bm.verts])
		xmax = max([pt.co.x for pt in bm.verts])
		ymin = min([pt.co.y for pt in bm.verts])
		ymax = max([pt.co.y for pt in bm.verts])
		zmin = min([pt.co.z for pt in bm.verts])
		zmax = max([pt.co.z for pt in bm.verts])
		#
		return cls(xmin=xmin, ymin=ymin, zmin=zmin, xmax=xmax, ymax=ymax, zmax=zmax)

	@classmethod
	def fromTopView(cls, context):
		'''Create a 2D BBOX from Blender 3dview if the view is top left ortho else return None'''
		scn = context.scene
		area = context.area
		if area.type != 'VIEW_3D':
			return None
		reg = context.region
		reg3d = context.region_data
		if reg3d.view_perspective != 'ORTHO' or tuple(reg3d.view_matrix.to_euler()) != (0,0,0):
			print("View3d must be in top ortho")
			return None
		#
		w, h = area.width, area.height
		coords = (w, h)
		vec = region_2d_to_vector_3d(reg, reg3d, coords)
		loc_ne = region_2d_to_location_3d(reg, reg3d, coords, vec)
		xmax, ymax = loc_ne.x, loc_ne.y
		#
		coords = (0, 0)
		vec = region_2d_to_vector_3d(reg, reg3d, coords)
		loc_sw = region_2d_to_location_3d(reg, reg3d, coords, vec)
		xmin, ymin = loc_sw.x, loc_sw.y
		#
		return cls(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)

	@classmethod
	def fromXYZ(cls, lst):
		'''Create a BBOX from a flat list of values ordered following XYZ axis
		--> (xmin, xmax, ymin, ymax) or (xmin, xmax, ymin, ymax, zmin, zmax)'''
		if len(lst) == 4:
			xmin, xmax, ymin, ymax = lst
			return cls(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
		elif len(lst) == 6:
			xmin, xmax, ymin, ymax, zmin, zmax = lst
			return cls(xmin=xmin, ymin=ymin, zmin=zmin, xmax=xmax, ymax=ymax, zmax=zmax)

	def toXYZ(self):
		'''Export to simple tuple of values ordered following XYZ axis'''
		if self.hasZ:
			return (self.xmin, self.xmax, self.ymin, self.ymax, self.zmin, self.zmax)
		else:
			return (self.xmin, self.xmax, self.ymin, self.ymax)

	@classmethod
	def fromLatlon(cls, lst):
		'''Create a 2D BBOX from a list of values ordered as latlon format (latmin, lonmin, latmax, lonmax) <--> (min, xmin, ymax, xmax)'''
		ymin, xmin, ymax, xmax = lst
		return cls(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)

	def toLatlon(self):
		'''Export to simple tuple of values ordered as latlon format in 2D'''
		return (self.ymin, self.xmin, self.ymax, self.xmax)

	@property
	def hasZ(self):
		'''Check if this bbox is in 3D'''
		if hasattr(self, 'zmin') and hasattr(self, 'zmax'):
			return True
		else:
			return False

	def to2D(self):
		'''Cast 3d bbox to 2d >> discard zmin and zmax values'''
		return BBOX(self.xmin, self.ymin, self.xmax, self.ymax)

	def toGeo(self, geoscn):
		'''Convert the BBOX into Spatial Ref System space defined in Scene'''
		if geoscn.isBroken or not geoscn.isGeoref:
			print('Warning : cannot convert bbox, invalid georef ')
			return None
		xmax = geoscn.crsx + (self.xmax * geoscn.scale)
		ymax = geoscn.crsy + (self.ymax * geoscn.scale)
		xmin = geoscn.crsx + (self.xmin * geoscn.scale)
		ymin = geoscn.crsy + (self.ymin * geoscn.scale)
		if self.hasZ:
			return BBOX(xmin, ymin, self.zmin, xmax, ymax, self.zmax)
		else:
			return BBOX(xmin, ymin, xmax, ymax)

	def __eq__(self, bb):
		'''Test if 2 bbox are equals'''
		if self.xmin == bb.xmin and self.xmax == bb.xmax and self.ymin == bb.ymin and self.ymax == bb.ymax:
			if self.hasZ and bb.hasZ:
					if self.zmin == bb.zmin and self.zmax == bb.zmax:
						return True
			else:
				return True

	def overlap(self, bb):
		'''Test if 2 bbox objects have intersection areas (in 2D only)'''
		def test_overlap(a_min, a_max, b_min, b_max):
			return not ((a_min > b_max) or (b_min > a_max))
		return test_overlap(self.xmin, self.xmax, bb.xmin, bb.xmax) and test_overlap(self.ymin, self.ymax, bb.ymin, bb.ymax)

	def isWithin(self, bb):
		'''Test if this bbox is within another bbox'''
		if bb.xmin <= self.xmin and bb.xmax >= self.xmax and bb.ymin <= self.ymin and bb.ymax >= self.ymax:
			return True
		else:
			return False

	def contains(self, bb):
		'''Test if this bbox contains another bbox'''
		if bb.xmin > self.xmin and bb.xmax < self.xmax and bb.ymin > self.ymin and bb.ymax < self.ymax:
			return True
		else:
			return False

	def __add__(self, bb):
		'''Use '+' operator to perform the union of 2 bbox'''
		xmax = max(self.xmax, bb.xmax)
		xmin = min(self.xmin, bb.xmin)
		ymax = max(self.ymax, bb.ymax)
		ymin = min(self.ymin, bb.ymin)
		if self.hasZ and bb.hasZ:
			zmax = max(self.zmax, bb.zmax)
			zmin = min(self.zmin, bb.zmin)
			return BBOX(xmin, ymin, zmin, xmax, ymax, zmax)
		else:
			return BBOX(xmin, ymin, xmax, ymax)

	def shift(self, dx, dy):
		'''translate the bbox in 2D'''
		self.xmin += dx
		self.xmax += dx
		self.ymin += dy
		self.ymax += dy

	@property
	def center(self):
		x = (self.xmin + self.xmax) / 2
		y = (self.ymin + self.ymax) / 2
		if self.hasZ:
			z = (self.zmin + self.zmax) / 2
			return XY(x,y,z)
		else:
			return XY(x,y)

	@property
	def dimensions(self):
		dx = self.xmax - self.xmin
		dy = self.ymax - self.ymin
		if self.hasZ:
			dz = self.zmax - self.zmin
			return XY(dx,dy,dz)
		else:
			return XY(dx,dy)

	################
	## 2D properties

	@property
	def corners(self):
		'''Get the list of corners coords, starting from upperleft and ordered clockwise'''
		return [ self.ul, self.ur, self.br, self.bl ]

	@property
	def ul(self):
		'''upper left corner'''
		return XY(self.xmin, self.ymax)
	@property
	def ur(self):
		'''upper right corner'''
		return XY(self.xmax, self.ymax)
	@property
	def bl(self):
		'''bottom left corner'''
		return XY(self.xmin, self.ymin)
	@property
	def br(self):
		'''bottom right corner'''
		return XY(self.xmax, self.ymin)

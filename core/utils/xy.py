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
		except IndexError:
			return None
	@property
	def xy(self):
		return self.data[:2]
	@property
	def xyz(self):
		return self.data

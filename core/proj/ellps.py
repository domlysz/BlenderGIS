import math


class Ellps():
	"""ellipsoid"""
	def __init__(self, a, b):
		self.a =  a#equatorial radius in meters
		self.b =  b#polar radius in meters
		self.f = (self.a-self.b)/self.a#inverse flat
		self.perimeter = (2*math.pi*self.a)#perimeter at equator

GRS80 = Ellps(6378137, 6356752.314245)

def dd2meters(dst):
	"""
	Basic function to approximaly convert a short distance in decimal degrees to meters
	Only true at equator and along horizontal axis
	"""
	k = GRS80.perimeter/360
	return dst * k

def meters2dd(dst):
	k = GRS80.perimeter/360
	return dst / k

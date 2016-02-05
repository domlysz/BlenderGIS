# -*- coding:utf-8 -*-

from mathutils import Vector


#bbox functions
#########################################

def getBBox(obj, applyTransform = True):
	if applyTransform:
		boundPts = [obj.matrix_world * Vector(corner) for corner in obj.bound_box]
	else:
		boundPts = obj.bound_box
	bbox={}
	bbox['xmin']=min([pt[0] for pt in boundPts])
	bbox['xmax']=max([pt[0] for pt in boundPts])
	bbox['ymin']=min([pt[1] for pt in boundPts])
	bbox['ymax']=max([pt[1] for pt in boundPts])
	bbox['zmin']=min([pt[2] for pt in boundPts])
	bbox['zmax']=max([pt[2] for pt in boundPts])
	return bbox


#Scale/normalize function : linear stretch from lowest value to highest value
#########################################
def scale(inVal, inMin, inMax, outMin, outMax):
	return (inVal - inMin) * (outMax - outMin) / (inMax - inMin) + outMin

	
	
def linearInterpo(x1, x2, y1, y2, x):
	#Linear interpolation = y1 + slope * tx
	dx = x2 - x1
	dy = y2-y1
	slope = dy/dx
	tx = x - x1 #position from x1 (target x)
	return y1 + slope * tx
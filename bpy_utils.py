
'''Blender Python Utilities (bpu)'''

import bpy
from mathutils import Vector
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_vector_3d

from .core import BBOX

def adjust3Dview(context, bbox, zoomToSelect=True):

	# grid size and clip distance
	dstMax = round(max(abs(bbox.xmax), abs(bbox.xmin), abs(bbox.ymax), abs(bbox.ymin)))*2
	nbDigit = len(str(dstMax))
	scale = 10**(nbDigit-2)#1 digits --> 0.1m, 2 --> 1m, 3 --> 10m, 4 --> 100m, , 5 --> 1000m
	nbLines = round(dstMax/scale)
	targetDst = nbLines*scale
	# set each 3d view
	areas = context.screen.areas
	for area in areas:
		if area.type == 'VIEW_3D':
			space = area.spaces.active
			#Adjust floor grid and clip distance if the new obj is largest than actual settings
			if space.grid_lines*space.grid_scale < targetDst:
				space.grid_lines = nbLines
				space.grid_scale = scale
				space.clip_end = targetDst*10 #10x more than necessary
			if zoomToSelect:
				overrideContext = context.copy()
				overrideContext['area'] = area
				overrideContext['region'] = area.regions[-1]
				bpy.ops.view3d.view_selected(overrideContext)


def showTextures(context):
	'''Force view mode with textures'''
	scn = context.scene
	for area in context.screen.areas:
		if area.type == 'VIEW_3D':
			space = area.spaces.active
			space.show_textured_solid = True
			if scn.render.engine == 'CYCLES':
				area.spaces.active.viewport_shade = 'TEXTURED'
			elif scn.render.engine == 'BLENDER_RENDER':
				area.spaces.active.viewport_shade = 'SOLID'


class getBBOX():

	@staticmethod
	def fromObj(obj, applyTransform = True):
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
		return BBOX(xmin=xmin, ymin=ymin, zmin=zmin, xmax=xmax, ymax=ymax, zmax=zmax)

	@classmethod
	def fromScn(cls, scn):
		'''Create a 3D BBOX from Blender Scene
		union of bounding box of all objects containing in the scene'''
		objs = scn.objects
		if len(objs) == 0:
			scnBbox = BBOX(0,0,0,0,0,0)
		else:
			scnBbox = cls.fromObj(objs[0])
		for obj in objs:
			bbox = cls.fromObj(obj)
			scnBbox += bbox
		return scnBbox

	@staticmethod
	def fromBmesh(bm):
		'''Create a 3D bounding box from a bmesh object'''
		xmin = min([pt.co.x for pt in bm.verts])
		xmax = max([pt.co.x for pt in bm.verts])
		ymin = min([pt.co.y for pt in bm.verts])
		ymax = max([pt.co.y for pt in bm.verts])
		zmin = min([pt.co.z for pt in bm.verts])
		zmax = max([pt.co.z for pt in bm.verts])
		#
		return BBOX(xmin=xmin, ymin=ymin, zmin=zmin, xmax=xmax, ymax=ymax, zmax=zmax)

	@staticmethod
	def fromTopView(context):
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
		return BBOX(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)

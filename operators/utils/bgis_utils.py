
import bpy
from mathutils import Vector
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_vector_3d

from ...core import BBOX


def placeObj(mesh, objName):
	'''Build and add a new object from a given mesh'''
	bpy.ops.object.select_all(action='DESELECT')
	#create an object with that mesh
	obj = bpy.data.objects.new(objName, mesh)
	# Link object to scene
	bpy.context.scene.objects.link(obj)
	bpy.context.scene.objects.active = obj
	obj.select = True
	#bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
	return obj


def adjust3Dview(context, bbox, zoomToSelect=True):
	'''adjust all 3d views floor grid and clip distance to match the submited bbox'''
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
				dst = targetDst*10 #10x more than necessary
				if dst > 10000000:
					dst = 10000000 #too large clip distance broke the 3d view
				space.clip_end = dst
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


def addTexture(mat, img, uvLay, name='texture'):
	'''Set a new image texture to a given material and following a given uv map'''
	engine = bpy.context.scene.render.engine
	mat.use_nodes = True
	node_tree = mat.node_tree
	node_tree.nodes.clear()
	#
	#CYCLES
	bpy.context.scene.render.engine = 'CYCLES' #force Cycles render
	# create uv map node
	uvMapNode = node_tree.nodes.new('ShaderNodeUVMap')
	uvMapNode.uv_map = uvLay.name
	uvMapNode.location = (-400, 200)
	# create image texture node
	textureNode = node_tree.nodes.new('ShaderNodeTexImage')
	textureNode.image = img
	textureNode.extension = 'CLIP'
	textureNode.show_texture = True
	textureNode.location = (-200, 200)
	# Create BSDF diffuse node
	diffuseNode = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
	diffuseNode.location = (0, 200)
	# Create output node
	outputNode = node_tree.nodes.new('ShaderNodeOutputMaterial')
	outputNode.location = (200, 200)
	# Connect the nodes
	node_tree.links.new(uvMapNode.outputs['UV'] , textureNode.inputs['Vector'])
	node_tree.links.new(textureNode.outputs['Color'] , diffuseNode.inputs['Color'])
	node_tree.links.new(diffuseNode.outputs['BSDF'] , outputNode.inputs['Surface'])
	#
	#BLENDER_RENDER
	bpy.context.scene.render.engine = 'BLENDER_RENDER'
	# Create image texture from image
	imgTex = bpy.data.textures.new(name, type = 'IMAGE')
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


class getBBOX():

	'''Utilities to build BBOX object from various Blender context'''

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

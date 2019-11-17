# -*- coding:utf-8 -*-
#import DelaunayVoronoi
import bpy
import time
from .utils import computeVoronoiDiagram, computeDelaunayTriangulation

try:
	from mathutils.geometry import delaunay_2d_cdt
except ImportError:
	NATIVE = False
else:
	NATIVE = True

import logging
log = logging.getLogger(__name__)

class Point:
	def __init__(self, x, y, z):
		self.x, self.y, self.z = x, y, z

def unique(L):
	"""Return a list of unhashable elements in s, but without duplicates.
	[[1, 2], [2, 3], [1, 2]] >>> [[1, 2], [2, 3]]"""
	#For unhashable objects, you can sort the sequence and then scan from the end of the list, deleting duplicates as you go
	nDupli=0
	nZcolinear=0
	L.sort()#sort() brings the equal elements together; then duplicates are easy to weed out in a single pass.
	last = L[-1]
	for i in range(len(L)-2, -1, -1):
		if last[:2] == L[i][:2]:#XY coordinates compararison
			if last[2] == L[i][2]:#Z coordinates compararison
				nDupli+=1#duplicates vertices
			else:#Z colinear
				nZcolinear+=1
			del L[i]
		else:
			last = L[i]
	return (nDupli, nZcolinear)#list data type is mutable, input list will automatically update and doesn't need to be returned

def checkEqual(lst):
	return lst[1:] == lst[:-1]


class OBJECT_OT_tesselation_delaunay(bpy.types.Operator):
	bl_idname = "tesselation.delaunay" #name used to refer to this operator (button)
	bl_label = "Triangulation" #operator's label
	bl_description = "Terrain points cloud Delaunay triangulation in 2.5D" #tooltip
	bl_options = {"UNDO"}

	def execute(self, context):
		w = context.window
		w.cursor_set('WAIT')
		t0 = time.clock()
		#Get selected obj
		objs = context.selected_objects
		if len(objs) == 0 or len(objs) > 1:
			self.report({'INFO'}, "Selection is empty or too much object selected")
			return {'CANCELLED'}
		obj = objs[0]
		if obj.type != 'MESH':
			self.report({'INFO'}, "Selection isn't a mesh")
			return {'CANCELLED'}
		#Get points coodinates
		#bpy.ops.object.transform_apply(rotation=True, scale=True)
		r = obj.rotation_euler
		s = obj.scale
		mesh = obj.data

		if NATIVE:
			'''
			Use native Delaunay triangulation function : delaunay_2d_cdt(verts, edges, faces, output_type, epsilon) >> [verts, edges, faces, orig_verts, orig_edges, orig_faces]
			The three returned orig lists give, for each of verts, edges, and faces, the list of input element indices corresponding to the positionally same output element. For edges, the orig indices start with the input edges and then continue with the edges implied by each of the faces (n of them for an n-gon).
			Output type :
			# 0 => triangles with convex hull.
			# 1 => triangles inside constraints.
			# 2 => the input constraints, intersected.
			# 3 => like 2 but with extra edges to make valid BMesh faces.
			'''
			log.info("Triangulate {} points...".format(len(mesh.vertices)))
			verts, edges, faces, overts, oedges, ofaces  = delaunay_2d_cdt([v.co.to_2d() for v in mesh.vertices], [], [], 0, 0.1)
			verts = [ (v.x, v.y, mesh.vertices[overts[i][0]].co.z) for i, v in enumerate(verts)] #retrieve z values
			log.info("Getting {} triangles".format(len(faces)))
			log.info("Create mesh...")
			tinMesh = bpy.data.meshes.new("TIN")
			tinMesh.from_pydata(verts, edges, faces)
			tinMesh.update()
		else:
			vertsPts = [vertex.co for vertex in mesh.vertices]
			#Remove duplicate
			verts = [[vert.x, vert.y, vert.z] for vert in vertsPts]
			nDupli, nZcolinear = unique(verts)
			nVerts = len(verts)
			log.info("{} duplicates points ignored".format(nDupli))
			log.info("{} z colinear points excluded".format(nZcolinear))
			if nVerts < 3:
				self.report({'ERROR'}, "Not enough points")
				return {'CANCELLED'}
			#Check colinear
			xValues = [pt[0] for pt in verts]
			yValues = [pt[1] for pt in verts]
			if checkEqual(xValues) or checkEqual(yValues):
				self.report({'ERROR'}, "Points are colinear")
				return {'CANCELLED'}
			#Triangulate
			log.info("Triangulate {} points...".format(nVerts))
			vertsPts = [Point(vert[0], vert[1], vert[2]) for vert in verts]
			faces = computeDelaunayTriangulation(vertsPts)
			faces = [tuple(reversed(tri)) for tri in faces]#reverse point order --> if all triangles are specified anticlockwise then all faces up
			log.info("Getting {} triangles".format(len(faces)))
			#Create new mesh structure
			log.info("Create mesh...")
			tinMesh = bpy.data.meshes.new("TIN") #create a new mesh
			tinMesh.from_pydata(verts, [], faces) #Fill the mesh with triangles
			tinMesh.update(calc_edges=True) #Update mesh with new data

		#Create an object with that mesh
		tinObj = bpy.data.objects.new("TIN", tinMesh)
		#Place object
		tinObj.location = obj.location.copy()
		tinObj.rotation_euler = r
		tinObj.scale = s
		#Update scene
		context.scene.collection.objects.link(tinObj) #Link object to scene
		context.view_layer.objects.active = tinObj
		tinObj.select_set(True)
		obj.select_set(False)
		#Report
		t = round(time.clock() - t0, 2)
		msg = "{} triangles created in {} seconds".format(len(faces), t)
		self.report({'INFO'}, msg)
		#log.info(msg) #duplicate log
		return {'FINISHED'}

class OBJECT_OT_tesselation_voronoi(bpy.types.Operator):
	bl_idname = "tesselation.voronoi" #name used to refer to this operator (button)
	bl_label = "Diagram" #operator's label
	bl_description = "Points cloud Voronoi diagram in 2D" #tooltip
	bl_options = {"REGISTER","UNDO"}#need register to draw operator options/redo panel (F6)
	#options
	meshType: bpy.props.EnumProperty(
		items = [("Edges", "Edges", ""), ("Faces", "Faces", "")],#(Key, Label, Description)
		name = "Mesh type",
		description = ""
		)

	"""
	def draw(self, context):
	"""

	def execute(self, context):
		w = context.window
		w.cursor_set('WAIT')
		t0 = time.clock()
		#Get selected obj
		objs = context.selected_objects
		if len(objs) == 0 or len(objs) > 1:
			self.report({'INFO'}, "Selection is empty or too much object selected")
			return {'CANCELLED'}
		obj = objs[0]
		if obj.type != 'MESH':
			self.report({'INFO'}, "Selection isn't a mesh")
			return {'CANCELLED'}
		#Get points coodinates
		r = obj.rotation_euler
		s = obj.scale
		mesh = obj.data
		vertsPts = [vertex.co for vertex in mesh.vertices]
		#Remove duplicate
		verts = [[vert.x, vert.y, vert.z] for vert in vertsPts]
		nDupli, nZcolinear = unique(verts)
		nVerts = len(verts)
		log.info("{} duplicates points ignored".format(nDupli))
		log.info("{} z colinear points excluded".format(nZcolinear))
		if nVerts < 3:
			self.report({'ERROR'}, "Not enough points")
			return {'CANCELLED'}
		#Check colinear
		xValues = [pt[0] for pt in verts]
		yValues = [pt[1] for pt in verts]
		if checkEqual(xValues) or checkEqual(yValues):
			self.report({'ERROR'}, "Points are colinear")
			return {'CANCELLED'}
		#Create diagram
		log.info("Tesselation... ({} points)".format(nVerts))
		xbuff, ybuff = 5, 5 # %
		zPosition = 0
		vertsPts = [Point(vert[0], vert[1], vert[2]) for vert in verts]
		if self.meshType == "Edges":
			pts, edgesIdx = computeVoronoiDiagram(vertsPts, xbuff, ybuff, polygonsOutput=False, formatOutput=True)
		else:
			pts, polyIdx = computeVoronoiDiagram(vertsPts, xbuff, ybuff, polygonsOutput=True, formatOutput=True, closePoly=False)
		#
		pts = [[pt[0], pt[1], zPosition] for pt in pts]
		#Create new mesh structure
		log.info("Create mesh...")
		voronoiDiagram = bpy.data.meshes.new("VoronoiDiagram") #create a new mesh
		if self.meshType == "Edges":
			voronoiDiagram.from_pydata(pts, edgesIdx, []) #Fill the mesh with triangles
		else:
			voronoiDiagram.from_pydata(pts, [], list(polyIdx.values())) #Fill the mesh with triangles
		voronoiDiagram.update(calc_edges=True) #Update mesh with new data
		#create an object with that mesh
		voronoiObj = bpy.data.objects.new("VoronoiDiagram", voronoiDiagram)
		#place object
		voronoiObj.location = obj.location.copy()
		voronoiObj.rotation_euler = r
		voronoiObj.scale = s
		#update scene
		context.scene.collection.objects.link(voronoiObj) #Link object to scene
		context.view_layer.objects.active = voronoiObj
		voronoiObj.select_set(True)
		obj.select_set(False)
		#Report
		t = round(time.clock() - t0, 2)
		if self.meshType == "Edges":
			self.report({'INFO'}, "{} edges created in {} seconds".format(len(edgesIdx), t))
		else:
			self.report({'INFO'}, "{} polygons created in {} seconds".format(len(polyIdx), t))
		return {'FINISHED'}

classes = [
	OBJECT_OT_tesselation_delaunay,
	OBJECT_OT_tesselation_voronoi
]

def register():
	for cls in classes:
		try:
			bpy.utils.register_class(cls)
		except ValueError as e:
			log.warning('{} is already registered, now unregister and retry... '.format(cls))
			bpy.utils.unregister_class(cls)
			bpy.utils.register_class(cls)

def unregister():
	for cls in classes:
		bpy.utils.unregister_class(cls)

# -*- coding:utf-8 -*-
#import DelaunayVoronoi
import bpy
from .utils import computeVoronoiDiagram, computeDelaunayTriangulation

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


class OBJECT_OT_TriangulateButton(bpy.types.Operator):
	bl_idname = "tesselation.delaunay" #name used to refer to this operator (button)
	bl_label = "Triangulation" #operator's label
	bl_description = "Terrain points cloud Delaunay triangulation in 2.5D" #tooltip
	bl_options = {"UNDO"}

	def execute(self, context):
		#Get selected obj
		objs = bpy.context.selected_objects
		if len(objs) == 0 or len(objs) > 1:
			self.report({'INFO'}, "Selection is empty or too much object selected")
			print("Selection is empty or too much object selected")
			return {'CANCELLED'}
		obj = objs[0]
		if obj.type != 'MESH':
			self.report({'INFO'}, "Selection isn't a mesh")
			print("Selection isn't a mesh")
			return {'CANCELLED'}
		#Get points coodinates
		#bpy.ops.object.transform_apply(rotation=True, scale=True)
		r = obj.rotation_euler
		s = obj.scale
		mesh = obj.data
		vertsPts = [vertex.co for vertex in mesh.vertices]
		#Remove duplicate
		verts= [[vert.x, vert.y, vert.z] for vert in vertsPts]
		nDupli, nZcolinear = unique(verts)
		nVerts = len(verts)
		print(str(nDupli) + " duplicates points ignored")
		print(str(nZcolinear) + " z colinear points excluded")
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
		print("Triangulate " + str(nVerts) + " points...")
		vertsPts= [Point(vert[0], vert[1], vert[2]) for vert in verts]
		triangles = computeDelaunayTriangulation(vertsPts)
		triangles = [tuple(reversed(tri)) for tri in triangles]#reverse point order --> if all triangles are specified anticlockwise then all faces up
		print(str(len(triangles)) + " triangles")
		#Create new mesh structure
		print("Create mesh...")
		tinMesh = bpy.data.meshes.new("TIN") #create a new mesh
		tinMesh.from_pydata(verts, [], triangles) #Fill the mesh with triangles
		tinMesh.update(calc_edges=True) #Update mesh with new data
		#Create an object with that mesh
		tinObj = bpy.data.objects.new("TIN", tinMesh)
		#Place object
		tinObj.location = obj.location.copy()
		tinObj.rotation_euler = r
		tinObj.scale = s
		#Update scene
		bpy.context.scene.objects.link(tinObj) #Link object to scene
		bpy.context.scene.objects.active = tinObj
		tinObj.select = True
		obj.select = False
		#Report
		self.report({'INFO'}, "Mesh created (" + str(len(triangles)) + " triangles)")
		return {'FINISHED'}

class OBJECT_OT_VoronoiButton(bpy.types.Operator):
	bl_idname = "tesselation.voronoi" #name used to refer to this operator (button)
	bl_label = "Diagram" #operator's label
	bl_description = "Points cloud Voronoi diagram in 2D" #tooltip
	bl_options = {"REGISTER","UNDO"}#need register to draw operator options/redo panel (F6)
	#options
	meshType = bpy.props.EnumProperty(
		items = [("Edges", "Edges", ""), ("Faces", "Faces", "")],#(Key, Label, Description)
		name = "Mesh type",
		description = ""
		)

	"""
	def draw(self, context):
	"""

	def execute(self, context):
		#Get selected obj
		objs = bpy.context.selected_objects
		if len(objs) == 0 or len(objs) > 1:
			self.report({'INFO'}, "Selection is empty or too much object selected")
			print("Selection is empty or too much object selected")
			return {'CANCELLED'}
		obj = objs[0]
		if obj.type != 'MESH':
			self.report({'INFO'}, "Selection isn't a mesh")
			print("Selection isn't a mesh")
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
		print(str(nDupli) + " duplicates points ignored")
		print(str(nZcolinear) + " z colinear points excluded")
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
		print("Tesselation... (" + str(nVerts) + " points)")
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
		print("Create mesh...")
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
		bpy.context.scene.objects.link(voronoiObj) #Link object to scene
		bpy.context.scene.objects.active = voronoiObj
		voronoiObj.select = True
		obj.select = False
		#Report
		if self.meshType == "Edges":
			self.report({'INFO'}, "Mesh created ("+str(len(edgesIdx))+" edges)")
		else:
			self.report({'INFO'}, "Mesh created ("+str(len(polyIdx))+" polygons)")
		return {'FINISHED'}

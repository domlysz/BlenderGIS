# -*- coding:utf-8 -*-
import math
import bpy
from bpy.types import Panel, Operator

from .utils import getBBOX

from ..core.maths.interpo import scale


class Analysis_nodes(Operator):
	'''Create material node thee to analysis height, slope and aspect'''
	bl_idname = "analysis.nodes"
	bl_description  = "Create height, slope and aspect material nodes setup for Cycles"
	bl_label = "Terrain analysis"

	def execute(self, context):
		scn = context.scene
		scn.render.engine = 'CYCLES' #force Cycles render
		obj = scn.objects.active
		if obj is None:
			self.report({'ERROR'}, "No active object")
			return {'FINISHED'}
		#######################
		#HEIGHT
		#######################
		# Create material
		heightMatName = 'Height_' + obj.name
		if heightMatName not in [m.name for m in bpy.data.materials]:
			heightMat = bpy.data.materials.new(heightMatName)
		else:#edit existing height material
			heightMat = bpy.data.materials[heightMatName]
		heightMat.use_nodes = True
		heightMat.use_fake_user = True
		node_tree = heightMat.node_tree
		node_tree.nodes.clear()
		# create geometry node (world coordinates)
		geomNode = node_tree.nodes.new('ShaderNodeNewGeometry')
		geomNode.location = (-600, 200)
		# create separate xyz node
		xyzSplitNode = node_tree.nodes.new('ShaderNodeSeparateXYZ')
		xyzSplitNode.location = (-400, 200)
		#
		#Normalize node group
		groupsTree = bpy.data.node_groups
		'''
		#make a purge (for testing)
		for nodeTree in groupsTree:
			name = nodeTree.name
			try:
				groupsTree.remove(nodeTree)
				print(name+' has been deleted')
			except:
				print('cannot delete '+name)
		'''
		if 'Normalize' in [nodeTree.name for nodeTree in groupsTree]:
		   #groupsTree.remove(groupsTree['Normalize'])
			scaleNodesGroupTree = groupsTree['Normalize']
			scaleNodesGroupTree.nodes.clear()
			scaleNodesGroupTree.inputs.clear()
			scaleNodesGroupTree.outputs.clear()
		else:
			scaleNodesGroupTree = groupsTree.new('Normalize', 'ShaderNodeTree') # = bpy.types.node_tree
		scaleNodesGroupName = scaleNodesGroupTree.name #Normalize.001 if normalize already exists
		#  group inputs
		scaleInputsNode = scaleNodesGroupTree.nodes.new('NodeGroupInput')
		scaleInputsNode.location = (-350,0)
		scaleNodesGroupTree.inputs.new('NodeSocketFloat','val')
		scaleNodesGroupTree.inputs.new('NodeSocketFloat','min')
		scaleNodesGroupTree.inputs.new('NodeSocketFloat','max')
		#  group outputs
		scaleOutputsNode = scaleNodesGroupTree.nodes.new('NodeGroupOutput')
		scaleOutputsNode.location = (300,0)
		scaleNodesGroupTree.outputs.new('NodeSocketFloat','val')
		#  create 3 math nodes in a group
		subtractNode1 = scaleNodesGroupTree.nodes.new('ShaderNodeMath')
		subtractNode1.operation = 'SUBTRACT'
		subtractNode1.location = (-100,100)
		subtractNode2 = scaleNodesGroupTree.nodes.new('ShaderNodeMath')
		subtractNode2.operation = 'SUBTRACT'
		subtractNode2.location = (-100,-100)
		divideNode = scaleNodesGroupTree.nodes.new('ShaderNodeMath')
		divideNode.operation = 'DIVIDE'
		divideNode.location = (100,0)
		#  link nodes
		scaleNodesGroupTree.links.new(scaleInputsNode.outputs['val'], subtractNode1.inputs[0])
		scaleNodesGroupTree.links.new(scaleInputsNode.outputs['min'], subtractNode1.inputs[1])
		scaleNodesGroupTree.links.new(scaleInputsNode.outputs['min'], subtractNode2.inputs[1])
		scaleNodesGroupTree.links.new(scaleInputsNode.outputs['max'], subtractNode2.inputs[0])
		scaleNodesGroupTree.links.new(subtractNode1.outputs[0], divideNode.inputs[0])
		scaleNodesGroupTree.links.new(subtractNode2.outputs[0], divideNode.inputs[1])
		scaleNodesGroupTree.links.new(divideNode.outputs[0], scaleOutputsNode.inputs['val'])
		#  finally add the group to main node_tree
		scaleNodeGroup = node_tree.nodes.new('ShaderNodeGroup')
		scaleNodeGroup.node_tree = bpy.data.node_groups[scaleNodesGroupName]#['Normalize']
		scaleNodeGroup.location = (-200, 200)
		#
		# create z bbox value nodes
		bbox = getBBOX.fromObj(obj)
		zmin = node_tree.nodes.new('ShaderNodeValue')
		zmin.label = 'zmin ' + obj.name
		zmin.outputs[0].default_value = bbox['zmin']
		zmin.location = (-400,0)
		zmax = node_tree.nodes.new('ShaderNodeValue')
		zmax.label = 'zmax ' + obj.name
		zmax.outputs[0].default_value = bbox['zmax']
		zmax.location = (-400,-100)
		# create color ramp node
		colorRampNode = node_tree.nodes.new('ShaderNodeValToRGB')
		colorRampNode.location = (0, 200)
		cr = colorRampNode.color_ramp
		cr.elements[0].color = (0,1,0,1)
		cr.elements[1].color = (1,0,0,1)
		# Create BSDF diffuse node
		diffuseNode = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
		diffuseNode.location = (300, 200)
		# Create output node
		outputNode = node_tree.nodes.new('ShaderNodeOutputMaterial')
		outputNode.location = (500, 200)
		# Connect the nodes
		node_tree.links.new(geomNode.outputs['Position'] , xyzSplitNode.inputs['Vector'])
		node_tree.links.new(xyzSplitNode.outputs['Z'] , scaleNodeGroup.inputs['val'])
		node_tree.links.new(zmin.outputs[0] , scaleNodeGroup.inputs['min'])
		node_tree.links.new(zmax.outputs[0] , scaleNodeGroup.inputs['max'])
		node_tree.links.new(scaleNodeGroup.outputs['val'] , colorRampNode.inputs['Fac'])
		node_tree.links.new(colorRampNode.outputs['Color'] , diffuseNode.inputs['Color'])
		node_tree.links.new(diffuseNode.outputs['BSDF'] , outputNode.inputs['Surface'])
		# Deselect nodes
		for node in node_tree.nodes:
			node.select = False
		#select color ramp
		colorRampNode.select = True
		node_tree.nodes.active = colorRampNode

		#######################
		#SLOPE
		#######################
		# Create material
		slopeMatName = 'Slope'
		if slopeMatName not in [m.name for m in bpy.data.materials]:
			slopeMat = bpy.data.materials.new(slopeMatName)
		else:
			slopeMat = bpy.data.materials[slopeMatName]
		slopeMat.use_nodes = True
		slopeMat.use_fake_user = True
		node_tree = slopeMat.node_tree
		node_tree.nodes.clear()
		'''
		# create texture coordinate node (local coordinates)
		texCoordNode = node_tree.nodes.new('ShaderNodeTexCoord')
		texCoordNode.location = (-600, 0)
		'''
		# create geometry node (world coordinates)
		geomNode = node_tree.nodes.new('ShaderNodeNewGeometry')
		geomNode.location = (-600, 0)
		# create separate xyz node
		xyzSplitNode = node_tree.nodes.new('ShaderNodeSeparateXYZ')
		xyzSplitNode.location = (-400, 0)
		#  create arc-cos node
		arcCosNode = node_tree.nodes.new('ShaderNodeMath')
		arcCosNode.operation = 'ARCCOSINE'
		arcCosNode.location = (-200,0)
		#  create math node to convert radians to degrees
		rad2dg = node_tree.nodes.new('ShaderNodeMath')
		rad2dg.operation = 'MULTIPLY'
		rad2dg.location = (0,0)
		rad2dg.label = "Radians to degrees"
		rad2dg.inputs[1].default_value = 180/math.pi
		#  create math node to normalize value
		normalize = node_tree.nodes.new('ShaderNodeMath')
		normalize.operation = 'DIVIDE'
		normalize.location = (200,0)
		normalize.label = "Normalize"
		normalize.inputs[1].default_value = 100
		# create color ramp node
		colorRampNode = node_tree.nodes.new('ShaderNodeValToRGB')
		colorRampNode.location = (400, 0)
		cr = colorRampNode.color_ramp
		cr.elements[0].color = (0,1,0,1)
		cr.elements[1].position = 0.5
		cr.elements[1].color = (1,0,0,1)
		# Create BSDF diffuse node
		diffuseNode = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
		diffuseNode.location = (800, 0)
		# Create output node
		outputNode = node_tree.nodes.new('ShaderNodeOutputMaterial')
		outputNode.location = (1000, 0)
		# Connect the nodes
		#node_tree.links.new(texCoordNode.outputs['Normal'] , xyzSplitNode.inputs['Vector'])
		node_tree.links.new(geomNode.outputs['True Normal'] , xyzSplitNode.inputs['Vector'])
		node_tree.links.new(xyzSplitNode.outputs['Z'] , arcCosNode.inputs[0])
		node_tree.links.new(arcCosNode.outputs[0] , rad2dg.inputs[0])
		node_tree.links.new(rad2dg.outputs[0] , normalize.inputs[0])
		node_tree.links.new(normalize.outputs[0] , colorRampNode.inputs['Fac'])
		node_tree.links.new(colorRampNode.outputs['Color'] , diffuseNode.inputs['Color'])
		node_tree.links.new(diffuseNode.outputs['BSDF'] , outputNode.inputs['Surface'])
		# Deselect nodes
		for node in node_tree.nodes:
			node.select = False
		#select color ramp
		colorRampNode.select = True
		node_tree.nodes.active = colorRampNode

		#######################
		#ASPECT
		#######################
		# Create material
		aspectMatName = 'Aspect'
		if aspectMatName not in [m.name for m in bpy.data.materials]:
			aspectMat = bpy.data.materials.new(aspectMatName)
		else:
			aspectMat = bpy.data.materials[aspectMatName]
		aspectMat.use_nodes = True
		aspectMat.use_fake_user = True
		node_tree = aspectMat.node_tree
		node_tree.nodes.clear()
		# create geometry node (world coordinates)
		geomNode = node_tree.nodes.new('ShaderNodeNewGeometry')
		geomNode.location = (-600, 200)
		# create separate xyz node
		xyzSplitNode = node_tree.nodes.new('ShaderNodeSeparateXYZ')
		xyzSplitNode.location = (-400, 200)
		node_tree.links.new(geomNode.outputs['True Normal'] , xyzSplitNode.inputs['Vector'])
		#  create maths nodes to compute aspect angle = atan(x/y)
		xyDiv = node_tree.nodes.new('ShaderNodeMath')
		xyDiv.operation = 'DIVIDE'
		xyDiv.location = (-200,0)
		node_tree.links.new(xyzSplitNode.outputs['X'] , xyDiv.inputs[0])
		node_tree.links.new(xyzSplitNode.outputs['Y'] , xyDiv.inputs[1])
		atanNode = node_tree.nodes.new('ShaderNodeMath')
		atanNode.operation = 'ARCTANGENT'
		atanNode.label = 'Aspect radians'
		atanNode.location = (0,0)
		node_tree.links.new(xyDiv.outputs[0] , atanNode.inputs[0])
		#  create math node to convert radians to degrees
		rad2dg = node_tree.nodes.new('ShaderNodeMath')
		rad2dg.operation = 'MULTIPLY'
		rad2dg.location = (200,0)
		rad2dg.label = "Aspect degrees"
		rad2dg.inputs[1].default_value = 180/math.pi
		node_tree.links.new(atanNode.outputs[0] , rad2dg.inputs[0])
		# maths nodes --> if y < 0 then aspect = aspect + 180
		yNegMask = node_tree.nodes.new('ShaderNodeMath')
		yNegMask.operation = 'LESS_THAN'
		yNegMask.location = (0,200)
		yNegMask.label = "y negative ?"
		yNegMask.inputs[1].default_value = 0
		node_tree.links.new(xyzSplitNode.outputs['Y'] , yNegMask.inputs[0])
		yNegMutiply = node_tree.nodes.new('ShaderNodeMath')
		yNegMutiply.operation = 'MULTIPLY'
		yNegMutiply.location = (200,200)
		node_tree.links.new(yNegMask.outputs[0] , yNegMutiply.inputs[0])
		yNegMutiply.inputs[1].default_value = 180
		yNegAdd = node_tree.nodes.new('ShaderNodeMath')
		yNegAdd.operation = 'ADD'
		yNegAdd.location = (400,200)
		node_tree.links.new(yNegMutiply.outputs[0] , yNegAdd.inputs[0])
		node_tree.links.new(rad2dg.outputs[0] , yNegAdd.inputs[1])
		# if y > 0 & x < 0 then aspect = aspect + 360
		xNegMask = node_tree.nodes.new('ShaderNodeMath')
		xNegMask.operation = 'LESS_THAN'
		xNegMask.location = (0,600)
		xNegMask.label = "x negative ?"
		xNegMask.inputs[1].default_value = 0
		node_tree.links.new(xyzSplitNode.outputs['X'] , xNegMask.inputs[0])
		yPosMask = node_tree.nodes.new('ShaderNodeMath')
		yPosMask.operation = 'GREATER_THAN'
		yPosMask.location = (0,400)
		yPosMask.label = "y positive ?"
		yPosMask.inputs[1].default_value = 0
		node_tree.links.new(xyzSplitNode.outputs['Y'] , yPosMask.inputs[0])
		mask = node_tree.nodes.new('ShaderNodeMath')
		mask.operation = 'MULTIPLY'
		mask.location = (200,500)
		node_tree.links.new(xNegMask.outputs[0] , mask.inputs[0])
		node_tree.links.new(yPosMask.outputs[0] , mask.inputs[1])
		maskMultiply = node_tree.nodes.new('ShaderNodeMath')
		maskMultiply.operation = 'MULTIPLY'
		maskMultiply.location = (400,500)
		node_tree.links.new(mask.outputs[0] , maskMultiply.inputs[0])
		maskMultiply.inputs[1].default_value = 360
		maskAdd = node_tree.nodes.new('ShaderNodeMath')
		maskAdd.operation = 'ADD'
		maskAdd.location = (600,300)
		node_tree.links.new(maskMultiply.outputs[0] , maskAdd.inputs[0])
		node_tree.links.new(yNegAdd.outputs[0] , maskAdd.inputs[1])
		#  create math node to normalize value
		normalize = node_tree.nodes.new('ShaderNodeMath')
		normalize.operation = 'DIVIDE'
		normalize.location = (800,300)
		normalize.label = "Normalize"
		normalize.inputs[1].default_value = 360
		node_tree.links.new(maskAdd.outputs[0] , normalize.inputs[0])
		# create color ramp node
		colorRampNode = node_tree.nodes.new('ShaderNodeValToRGB')
		colorRampNode.location = (1000, 300)
		cr = colorRampNode.color_ramp
		stops = cr.elements
		cr.elements[0].color = (1,0,0,1)#first stop = red
		stops.remove(stops[1])#remove last stop
		#orange, yellow, green, cyan, blue1, blue2, pink, red
		colors = [(1,0.5,0,1), (1,1,0,1), (0,1,0,1), (0,1,1,1), (0,0.5,1,1), (0,0,1,1), (1,0,1,1), (1,0,0,1)]
		for i, angle in enumerate([22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5]):
			pos = scale(angle, 0, 360, 0, 1)
			stop = stops.new(pos)
			stop.color = colors[i]
		cr.interpolation = 'CONSTANT'
		node_tree.links.new(normalize.outputs[0] , colorRampNode.inputs['Fac'])
		# Create BSDF diffuse node
		diffuseNode = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
		diffuseNode.location = (1300, 300)
		node_tree.links.new(colorRampNode.outputs['Color'] , diffuseNode.inputs['Color'])
		# Flat color diffuse
		diffuseFlat = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
		diffuseFlat.location = (1300, 0)
		diffuseFlat.inputs[0].default_value = (1,1,1,1)
		# flat test
		flatMask = node_tree.nodes.new('ShaderNodeMath')
		flatMask.operation = 'LESS_THAN'
		flatMask.location = (800,-100)
		flatMask.label = "is flat?"
		flatMask.inputs[1].default_value = 0.999
		node_tree.links.new(xyzSplitNode.outputs['Z'] , flatMask.inputs[0])
		# Mix shader
		mixNode = node_tree.nodes.new('ShaderNodeMixShader')
		mixNode.location = (1500, 200)
		node_tree.links.new(diffuseNode.outputs['BSDF'] , mixNode.inputs[2])
		node_tree.links.new(diffuseFlat.outputs['BSDF'] , mixNode.inputs[1])
		node_tree.links.new(flatMask.outputs[0] , mixNode.inputs['Fac'])
		# Create output node
		outputNode = node_tree.nodes.new('ShaderNodeOutputMaterial')
		outputNode.location = (1700, 200)
		node_tree.links.new(mixNode.outputs[0] , outputNode.inputs['Surface'])
		# Deselect nodes
		for node in node_tree.nodes:
			node.select = False
		#select color ramp
		colorRampNode.select = True
		node_tree.nodes.active = colorRampNode


		#######################

		# Add material to current object
		'''
		if heightMat.name not in [m.name for m in obj.data.materials]:
			#add slot & move ui list index
		else:#this name already exist, just move ui list index to select it
			obj.active_material_index = obj.material_slots.find(heightMat.name)
		'''
		#add slot
		obj.data.materials.append(heightMat)
		#move ui list index
		obj.active_material_index = len(obj.material_slots)-1
		#Assignmaterial to faces
		for faces in obj.data.polygons:
			faces.material_index = obj.active_material_index

		return {'FINISHED'}

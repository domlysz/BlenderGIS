# -*- coding: utf-8 -*-

bl_info = {
	"name": "Delaunay Voronoi ",
	"description": "Points cloud Delaunay triangulation in 2.5D (suitable for terrain modelling) or Voronoi diagram in 2D",
	"author": "Domlysz",
	"version": (1, 3),
	"blender": (2, 7, 0),#Python 3.2
	"location": "Mesh Tool Panel",
	"warning": "", # used for warning icon and text in addons panel
	"wiki_url": "",
	"tracker_url": "",
	"category": "Mesh"}

import bpy
from .delaunayVoronoiBlender import ToolsPanelDelaunay

#Registration
#   All panels and operators must be registered with Blender; otherwise they do not show up.
#   Blender modules loaded at startup require register() and unregister() functions.
#   The simplest way to register everything in the file is with a call to bpy.utils.register_module(__name__).

def register():
	bpy.utils.register_module(__name__)

def unregister():
	bpy.utils.unregister_module(__name__)

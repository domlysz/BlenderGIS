# -*- coding:utf-8 -*-

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

bl_info = {
	"name": "Delaunay Voronoi ",
	"description": "Points cloud Delaunay triangulation in 2.5D (suitable for terrain modelling) or Voronoi diagram in 2D",
	"author": "Domlysz",
	'license': 'GPL',
	'deps': '',
	"version": (1, 3),
	"blender": (2, 7, 0),
	"location": "View3D > Tools > GIS",
	"warning": "",
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': '',
	'link': '',
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

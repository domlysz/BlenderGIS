# Derived from https://github.com/hrbaer/Blender-ASCII-Grid-Import

import re
import os
import string
import bpy

from bpy_extras.io_utils import ImportHelper #helper class defines filename and invoke() function which calls the file selector
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator

from ..core.proj import Reproj
from ..geoscene import GeoScene, georefManagerLayout
from ..prefs import PredefCRS

from .utils import bpyGeoRaster as GeoRaster
from .utils import placeObj, adjust3Dview, showTextures, addTexture, getBBOX
from .utils import rasterExtentToMesh, geoRastUVmap, setDisplacer

PKG, SUBPKG = __package__.split('.', maxsplit=1)


class IMPORT_ASCII_GRID(Operator, ImportHelper):
    """Import ESRI ASCII grid file"""
    bl_idname = "importgis.asc_file"  # important since its how bpy.ops.importgis.asc is constructed (allows calling operator from python console or another script)
    #bl_idname rules: must contain one '.' (dot) charactere, no capital letters, no reserved words (like 'import')
    bl_description = 'Import ESRI ASCII grid with world file'
    bl_label = "Import ASCII Grid"
    bl_options = {"UNDO"}

    # ImportHelper class properties
    filter_glob = StringProperty(
        default="*.asc",
        options={'HIDDEN'},
    )

    # List of operator properties, the attributes will be assigned
    # to the class instance from the operator settings before calling.
    importMode = EnumProperty(
        name="Mode",
        description="Select import mode",
        items=[
            ('MESH', 'Mesh', "Create triangulated regular network mesh"),
            ('CLOUD', 'Point cloud', "Create vertex point cloud"),
        ],
    )

    # Step makes point clouds with billions of points possible to read on consumer hardware
    step = IntProperty(
        name = "Step",
        description="Only read every Nth point for massive point clouds",
        default=1,
        min=1
    )

    def draw(self, context):
        #Function used by blender to draw the panel.
        layout = self.layout
        layout.prop(self, 'importMode')
        layout.prop(self, 'step')
        
        #row = layout.row(align=True)
        #split = row.split(percentage=0.35, align=True)
        #split.label('CRS:')
        #split.prop(self, "rastCRS", text='')
        #row.operator("bgis.add_predef_crs", text='', icon='ZOOMIN')
        #scn = bpy.context.scene
        #geoscn = GeoScene(scn)
        #if geoscn.isPartiallyGeoref:
        #	georefManagerLayout(self, context)


    def err(self, msg):
        '''Report error throught a Blender's message box'''
        self.report({'ERROR'}, msg)
        return {'FINISHED'}

    def execute(self, context):
        prefs = bpy.context.user_preferences.addons[PKG].preferences
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except:
            pass
        bpy.ops.object.select_all(action='DESELECT')
        #Get scene and some georef data
        scn = bpy.context.scene
        geoscn = GeoScene(scn)
        if geoscn.isBroken:
            self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
            return {'FINISHED'}
        if geoscn.isGeoref:
            dx, dy = geoscn.getOriginPrj()
        scale = geoscn.scale #TODO
        # if not geoscn.hasCRS:
        # 	try:
        # 		geoscn.crs = self.rastCRS
        # 	except Exception as e:
        # 		self.report({'ERROR'}, str(e))
        # 		return {'FINISHED'}

        #Raster reprojection throught UV mapping
        #build reprojector objects
        # if geoscn.crs != self.rastCRS:
        # 	rprj = True
        # 	rprjToRaster = Reproj(geoscn.crs, self.rastCRS)
        # 	rprjToScene = Reproj(self.rastCRS, geoscn.crs)
        # else:
        rprj = False
        rprjToRaster = None
        rprjToScene = None

        #Path
        filename = self.filepath
        name = os.path.splitext(os.path.basename(filename))[0]

        f = open(filename, 'r')
        meta_re = re.compile('^([^\s]+)\s+([^\s]+)$')  # 'abc  123'
        meta = {}
        for i in range(6):
            line = f.readline()
            m = meta_re.match(line)
            if m:
                meta[m.group(1)] = m.group(2)

        llcorner = (float(meta['xllcorner']), float(meta['yllcorner']))
        if rprj:
            llcorner = rprjToScene.pt(*llcorner)
        if not geoscn.isGeoref:
            geoscn.setOriginPrj(*llcorner)

        # Create mesh
        name = os.path.splitext(os.path.basename(filename))[0]
        me = bpy.data.meshes.new(name)
        ob = bpy.data.objects.new(name, me)
        ob.location = (llcorner[0] - dx, llcorner[1] - dy, 0)
        ob.show_name = True

        # Link object to scene and make active
        scn = bpy.context.scene
        scn.objects.link(ob)
        scn.objects.active = ob
        ob.select = True

        # step allows reduction during import, only taking every Nth point
        step = self.step
        nrows = int(meta['nrows'])
        ncols = int(meta['ncols'])
        nodata = float(meta['nodata_value'])

        index = 0
        vertices = []
        faces = []
        for y in range(nrows - 1, -1, -step):
            coldata = list(map(float, f.readline().split(' ')))
            for i in range(step - 1):
                _ = f.readline()
            for x in range(0, ncols, step):
                # TODO: exclude nodata values (implications for face generation)
                vertices.append((x, y, coldata[x]))

        if self.importMode == 'MESH':
            step_ncols = int(ncols / step)
            for r in range(0, int(nrows / step) - 1):
                for c in range(0, step_ncols - 1):
                    v1 = index
                    v2 = v1 + step_ncols
                    v3 = v2 + 1
                    v4 = v1 + 1
                    faces.append((v1, v2, v3, v4))
                    index += 1
                index += 1

        me.from_pydata(vertices, [], faces)
        me.update()
        f.close()

        if prefs.adjust3Dview:
            bb = getBBOX.fromObj(ob)
            adjust3Dview(context, bb)
            
        return {'FINISHED'}

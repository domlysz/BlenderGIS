# Derived from https://github.com/hrbaer/Blender-ASCII-Grid-Import

import re
import os
import string
import bpy
import math
import string
from pprint import pprint

from bpy_extras.io_utils import ImportHelper #helper class defines filename and invoke() function which calls the file selector
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator

from ..core.proj import Reproj
from ..core.utils import XY
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
        default="*.asc;*.grd",
        options={'HIDDEN'},
    )

    # Raster CRS definition
    def listPredefCRS(self, context):
        return PredefCRS.getEnumItems()
    fileCRS = EnumProperty(
        name = "CRS",
        description = "Choose a Coordinate Reference System",
        items = listPredefCRS,
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
        
        row = layout.row(align=True)
        split = row.split(percentage=0.35, align=True)
        split.label('CRS:')
        split.prop(self, "fileCRS", text='')
        row.operator("bgis.add_predef_crs", text='', icon='ZOOMIN')
        scn = bpy.context.scene
        geoscn = GeoScene(scn)
        if geoscn.isPartiallyGeoref:
        	georefManagerLayout(self, context)


    def err(self, msg):
        '''Report error throught a Blender's message box'''
        self.report({'ERROR'}, msg)
        return {'FINISHED'}

    def read_row0(self, f, ncols):
        """
        Read a row by columns separated by newline.
        """
        return f.readline().split(' ')

    def read_row1(self, f, ncols):
        """ 
        Read a row by columns separated by whitespace (including newlines).
        6x slower than readlines() method.
        """
        buffer = 4096

        row = []
        complete = False
        while not complete:
            chunk = f.read(buffer)
            if not chunk:
                return row  # eof without reaching ncols?
            last = None
            for m in re.finditer('([^\s]+)', chunk):
                last = m
                row.append(m.group(0))
                if len(row) == ncols:
                    # completed a row within this chunk, rewind the position to start at the beginning of the next row
                    f.seek(f.tell() - (buffer - m.end()))
                    complete = True
                    break
            if not complete and last:
                # incomplete row from chunk, revert last value
                f.seek(f.tell() - (buffer - last.start()))
                del row[-1]
        return row

    def read_row2(self, f, ncols):
        """ 
        Read a row by columns separated by whitespace (including newlines).
        2x slower than readlines() method, with potential side effects depending on input.
        """
        buffer = 4096
        
        row = []
        complete = False
        while not complete:
            chunk = f.read(buffer)
            if not chunk:
                return row  # eof without reaching ncols?

            # remove end of string up to last whitespace to avoid partial values
            for i in range(len(chunk) - 1, -1, -1):
                if chunk[i] in string.whitespace:
                    f.seek(f.tell() - (buffer - i))
                    chunk = chunk[:i]
                    break

            # split where we have a complete row
            split_at = ncols - len(row)
            parts = chunk.split()
            row = row + parts[:split_at]
            if len(row) == ncols:
                # rewind the position to the location where we had enough chars to complete the row
                # NOTE: if the file is newline separated with \r\n, and the filestream converted to \n on read or 
                # there was more than one space between values, this seek will break
                f.seek(f.tell() - len(' '.join(parts[split_at:])))
                break
        return row

    def read_row3(self, f, ncols):
        """ 
        Read a row by columns separated by whitespace (including newlines).
        20x slower than readlines() method.
        """
        buffer = 4096
        
        row = []
        while True:
            chunk = f.read(buffer)
            if not chunk:
                return row  # eof without reaching ncols?

            # remove end of string up to last whitespace to avoid partial values
            buffer_trunc = buffer
            for i in range(len(chunk) - 1, -1, -1):
                if chunk[i] in string.whitespace:
                    buffer_trunc = i
                    f.seek(f.tell() - (buffer - i))
                    chunk = chunk[:i]
                    break

            # split where we have a complete row
            i = 0
            buf = []
            for c in chunk:
                i += 1
                if c in string.whitespace:
                    if buf:
                        row.append(''.join(buf))
                        buf = []
                        if len(row) == ncols:
                            f.seek(f.tell() - (buffer_trunc - i))
                            return row
                    # else we haven't started filling the buffer, so keep reading
                else:
                    buf.append(c)
            # we finished the chunk loop with a value, add it to the row
            if buf:
                row.append(''.join(buf))
                if len(row) == ncols:
                    return row

    def read_row4(self, f, ncols):
        """
        Read a row by columns separated by whitespace (including newlines).
        20x slower than readlines() method.
        """
        with open(f.name, 'rb') as bf:
            bf.seek(f.tell())
            row = []
            buffer = b''
            byte = bf.read(1)
            i = 0
            while byte:
                if byte.isspace():
                    if buffer:
                        row.append(buffer)
                        if i == ncols:
                            f.seek(bf.tell())
                            return row
                        buffer = b''
                        i += 1
                else:
                    buffer += byte
                byte = bf.read(1)

    def read_row5(self, f, ncols):
        """
        Read a row by columns separated by whitespace (including newlines).
        20x slower than readlines() method.
        """
        buffer = 4096
        
        with open(f.name, 'rb') as bf:
            bf.seek(f.tell())
            row = []
            while True:
                chunk = bf.read(buffer)
                if not chunk:
                    return row  # eof without reaching ncols?

                # split where we have a complete row
                i = 0
                buf = ''
                for byte in map(chr, chunk):
                    i += 1
                    if byte.isspace():
                        if buf:
                            row.append(buf)
                            buf = ''
                            if len(row) == ncols:
                                f.seek(bf.tell() - (buffer - i))
                                return row
                        # else we haven't started filling the buffer, so keep reading
                    else:
                        buf += byte
                # we finished the chunk loop with a value, rewind the bf position to try again
                if buf:
                    bf.seek(bf.tell() - len(buf))

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
        if not geoscn.hasCRS:
        	try:
        		geoscn.crs = self.fileCRS
        	except Exception as e:
        		self.report({'ERROR'}, str(e))
        		return {'FINISHED'}

        #build reprojector objects
        if geoscn.crs != self.fileCRS:
        	rprj = True
        	rprjToRaster = Reproj(geoscn.crs, self.fileCRS)
        	rprjToScene = Reproj(self.fileCRS, geoscn.crs)
        else:
            rprj = False
            rprjToRaster = None
            rprjToScene = None

        #Path
        filename = self.filepath
        name = os.path.splitext(os.path.basename(filename))[0]
        print('Importing {}...'.format(filename))

        f = open(filename, 'r')
        meta_re = re.compile('^([^\s]+)\s+([^\s]+)$')  # 'abc  123'
        meta = {}
        for i in range(6):
            line = f.readline()
            m = meta_re.match(line)
            if m:
                meta[m.group(1).lower()] = m.group(2)
        print(pprint(meta))

        # step allows reduction during import, only taking every Nth point
        step = self.step
        nrows = int(meta['nrows'])
        ncols = int(meta['ncols'])
        cellsize = float(meta['cellsize'])
        nodata = float(meta['nodata_value'])
        
        # Create mesh
        name = os.path.splitext(os.path.basename(filename))[0]
        me = bpy.data.meshes.new(name)
        ob = bpy.data.objects.new(name, me)
        ob.show_name = True

        # options are lower left cell corner, or lower left cell centre
        reprojection = {}
        offset = XY(0, 0)
        if 'xllcorner' in meta:
            llcorner = XY(float(meta['xllcorner']), float(meta['yllcorner']))
            reprojection['from'] = llcorner
        elif 'xllcenter' in meta:
            centre = XY(float(meta['xllcenter']), float(meta['yllcenter']))
            offset = XY(-cellsize / 2, -cellsize / 2)
            reprojection['from'] = centre

        # now set the correct offset for the mesh
        if rprj:
            reprojection['to'] = XY(*rprjToScene.pt(*reprojection['from']))
            print('{name} reprojected from {from} to {to}'.format(**reprojection, name=name))
        else:
            reprojection['to'] = reprojection['from']

        if not geoscn.isGeoref:
            # use the centre of the imported grid as scene origin (calculate only if grid file specified llcorner)
            centre = (reprojection['from'].x + offset.x + ((ncols / 2) * cellsize), 
                      reprojection['from'].y + offset.y + ((nrows / 2) * cellsize))
            if rprj:
                centre = rprjToScene.pt(*centre)
            geoscn.setOriginPrj(*centre)
            dx, dy = geoscn.getOriginPrj()

        ob.location = (reprojection['to'].x - dx, reprojection['to'].y - dy, 0)

        # Link object to scene and make active
        scn = bpy.context.scene
        scn.objects.link(ob)
        scn.objects.active = ob
        ob.select = True

        index = 0
        vertices = []
        faces = []
        import time
        t0 = time.time()
        read = self.read_row5
        for y in range(nrows - 1, -1, -step):
            # spec doesn't require newline separated rows so make it handle a single line of all values
            coldata = list(map(float, read(f, ncols)))
            for i in range(step - 1):
                _ = read(f, ncols)
                
            for x in range(0, ncols, step):
                # TODO: exclude nodata values (implications for face generation)
                if not (self.importMode == 'CLOUD' and coldata[x] == nodata):
                    pt = (x * cellsize + offset.x, y * cellsize + offset.y)
                    if rprj:
                        # reproject world-space source coordinate, then transform back to target local-space
                        pt = rprjToScene.pt(pt[0] + reprojection['from'].x, pt[1] + reprojection['from'].y)
                        pt = (pt[0] - reprojection['to'].x, pt[1] - reprojection['to'].y)
                    vertices.append(pt + (coldata[x],))
        t1 = time.time()
        print('execution time:', t1 - t0, 'seconds')

        if self.importMode == 'MESH':
            step_ncols = math.ceil(ncols / step)
            for r in range(0, math.ceil(nrows / step) - 1):
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

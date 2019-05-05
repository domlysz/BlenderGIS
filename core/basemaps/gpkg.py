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
import logging
log = logging.getLogger(__name__)

import os
import io
import math
import datetime
import sqlite3


#http://www.geopackage.org/spec/#tiles
#https://github.com/GitHubRGI/geopackage-python/blob/master/Packaging/tiles2gpkg_parallel.py
#https://github.com/Esri/raster2gpkg/blob/master/raster2gpkg.py


#table_name refer to the name of the table witch contains tiles data
#here for simplification, table_name will always be named "gpkg_tiles"

class GeoPackage():

	MAX_DAYS = 90

	def __init__(self, path, tm):
		self.dbPath = path
		self.name = os.path.splitext(os.path.basename(path))[0]

		#Get props from TileMatrix object
		self.auth, self.code = tm.CRS.split(':')
		self.code = int(self.code)
		self.tileSize = tm.tileSize
		self.xmin, self.ymin, self.xmax, self.ymax = tm.globalbbox
		self.resolutions = tm.getResList()

		if not self.isGPKG():
			self.create()
			self.insertMetadata()

			self.insertCRS(self.code, str(self.code), self.auth)
			#self.insertCRS(3857, "Web Mercator")
			#self.insertCRS(4326, "WGS84")

			self.insertTileMatrixSet()


	def isGPKG(self):
		if not os.path.exists(self.dbPath):
			return False
		db = sqlite3.connect(self.dbPath)

		#check application id
		app_id = db.execute("PRAGMA application_id").fetchone()
		if not app_id[0] == 1196437808:
			db.close()
			return False
		#quick check of table schema
		try:
			db.execute('SELECT table_name FROM gpkg_contents LIMIT 1')
			db.execute('SELECT srs_name FROM gpkg_spatial_ref_sys LIMIT 1')
			db.execute('SELECT table_name FROM gpkg_tile_matrix_set LIMIT 1')
			db.execute('SELECT table_name FROM gpkg_tile_matrix LIMIT 1')
			db.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM gpkg_tiles LIMIT 1')
		except Exception as e:
			log.error('Incorrect GPKG schema', exc_info=True)
			db.close()
			return False
		else:
			db.close()
			return True


	def create(self):
		"""Create default geopackage schema on the database."""
		db = sqlite3.connect(self.dbPath) #this attempt will create a new file if not exist
		cursor = db.cursor()

		# Add GeoPackage version 1.0 ("GP10" in ASCII) to the Sqlite header
		cursor.execute("PRAGMA application_id = 1196437808;")

		cursor.execute("""
			CREATE TABLE gpkg_contents (
				table_name TEXT NOT NULL PRIMARY KEY,
				data_type TEXT NOT NULL,
				identifier TEXT UNIQUE,
				description TEXT DEFAULT '',
				last_change DATETIME NOT NULL DEFAULT
				(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
				min_x DOUBLE,
				min_y DOUBLE,
				max_x DOUBLE,
				max_y DOUBLE,
				srs_id INTEGER,
				CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
					REFERENCES gpkg_spatial_ref_sys(srs_id));
		""")

		cursor.execute("""
			CREATE TABLE gpkg_spatial_ref_sys (
				srs_name TEXT NOT NULL,
				srs_id INTEGER NOT NULL PRIMARY KEY,
				organization TEXT NOT NULL,
				organization_coordsys_id INTEGER NOT NULL,
				definition TEXT NOT NULL,
				description TEXT);
		""")

		cursor.execute("""
			CREATE TABLE gpkg_tile_matrix_set (
				table_name TEXT NOT NULL PRIMARY KEY,
				srs_id INTEGER NOT NULL,
				min_x DOUBLE NOT NULL,
				min_y DOUBLE NOT NULL,
				max_x DOUBLE NOT NULL,
				max_y DOUBLE NOT NULL,
				CONSTRAINT fk_gtms_table_name FOREIGN KEY (table_name)
					REFERENCES gpkg_contents(table_name),
				CONSTRAINT fk_gtms_srs FOREIGN KEY (srs_id)
					REFERENCES gpkg_spatial_ref_sys(srs_id));
		""")

		cursor.execute("""
			CREATE TABLE gpkg_tile_matrix (
				table_name TEXT NOT NULL,
				zoom_level INTEGER NOT NULL,
				matrix_width INTEGER NOT NULL,
				matrix_height INTEGER NOT NULL,
				tile_width INTEGER NOT NULL,
				tile_height INTEGER NOT NULL,
				pixel_x_size DOUBLE NOT NULL,
				pixel_y_size DOUBLE NOT NULL,
				CONSTRAINT pk_ttm PRIMARY KEY (table_name, zoom_level),
				CONSTRAINT fk_ttm_table_name FOREIGN KEY (table_name)
					REFERENCES gpkg_contents(table_name));
		""")

		cursor.execute("""
			CREATE TABLE gpkg_tiles (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				zoom_level INTEGER NOT NULL,
				tile_column INTEGER NOT NULL,
				tile_row INTEGER NOT NULL,
				tile_data BLOB NOT NULL,
				last_modified TIMESTAMP DEFAULT (datetime('now','localtime')),
				UNIQUE (zoom_level, tile_column, tile_row));
		""")

		db.close()


	def insertMetadata(self):
		db = sqlite3.connect(self.dbPath)
		query = """INSERT INTO gpkg_contents (
					table_name, data_type,
					identifier, description,
					min_x, min_y, max_x, max_y,
					srs_id)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);"""
		db.execute(query, ("gpkg_tiles", "tiles", self.name, "Created with BlenderGIS", self.xmin, self.ymin, self.xmax, self.ymax, self.code))
		db.commit()
		db.close()


	def insertCRS(self, code, name, auth='EPSG', wkt=''):
		db = sqlite3.connect(self.dbPath)
		db.execute(""" INSERT INTO gpkg_spatial_ref_sys (
					srs_id,
					organization,
					organization_coordsys_id,
					srs_name,
					definition)
				VALUES (?, ?, ?, ?, ?)
			""", (code, auth, code, name, wkt))
		db.commit()
		db.close()


	def insertTileMatrixSet(self):
		db = sqlite3.connect(self.dbPath)

		#Tile matrix set
		query = """INSERT OR REPLACE INTO gpkg_tile_matrix_set (
					table_name, srs_id,
					min_x, min_y, max_x, max_y)
				VALUES (?, ?, ?, ?, ?, ?);"""
		db.execute(query, ('gpkg_tiles', self.code, self.xmin, self.ymin, self.xmax, self.ymax))


		#Tile matrix of each levels
		for level, res in enumerate(self.resolutions):

			w = math.ceil( (self.xmax - self.xmin) / (self.tileSize * res) )
			h = math.ceil( (self.ymax - self.ymin) / (self.tileSize * res) )

			query = """INSERT OR REPLACE INTO gpkg_tile_matrix (
						table_name, zoom_level,
						matrix_width, matrix_height,
						tile_width, tile_height,
						pixel_x_size, pixel_y_size)
					VALUES (?, ?, ?, ?, ?, ?, ?, ?);"""
			db.execute(query, ('gpkg_tiles', level, w, h, self.tileSize, self.tileSize, res, res))


		db.commit()
		db.close()


	def hasTile(self, x, y, z):
		if self.getTile(x ,y, z) is not None:
			return True
		else:
			return False

	def getTile(self, x, y, z):
		'''return tilde_data if tile exists otherwie return None'''
		#connect with detect_types parameter for automatically convert date to Python object
		db = sqlite3.connect(self.dbPath, detect_types=sqlite3.PARSE_DECLTYPES)
		query = 'SELECT tile_data, last_modified FROM gpkg_tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?'
		result = db.execute(query, (z, x, y)).fetchone()
		db.close()
		if result is None:
			return None
		timeDelta = datetime.datetime.now() - result[1]
		if timeDelta.days > self.MAX_DAYS:
			return None
		return result[0]

	def putTile(self, x, y, z, data):
		db = sqlite3.connect(self.dbPath)
		query = """INSERT OR REPLACE INTO gpkg_tiles
		(tile_column, tile_row, zoom_level, tile_data) VALUES (?,?,?,?)"""
		db.execute(query, (x, y, z, data))
		db.commit()
		db.close()


	def listExistingTiles(self, tiles):
		"""
		input : tiles list [(x,y,z)]
		output : tiles list set [(x,y,z)] of existing records in cache db"""

		db = sqlite3.connect(self.dbPath, detect_types=sqlite3.PARSE_DECLTYPES)

		tiles = ['_'.join(map(str, tile)) for tile in tiles]

		query = "SELECT tile_column, tile_row, zoom_level FROM gpkg_tiles " \
				"WHERE julianday() - julianday(last_modified) < " + str(self.MAX_DAYS) + " " \
				"AND tile_column || '_' || tile_row || '_' || zoom_level IN ('" + "','".join(tiles) + "')"

		result = db.execute(query).fetchall()
		db.close()

		return set(result)

	def listMissingTiles(self, tiles):
		existing = self.listExistingTiles(tiles)
		return set(tiles) - existing # difference


	def getTiles(self, tiles):
		"""tiles = list of (x,y,z) tuple
		return list of (x,y,z,data) tuple"""

		db = sqlite3.connect(self.dbPath, detect_types=sqlite3.PARSE_DECLTYPES)

		tiles = ['_'.join(map(str, tile)) for tile in tiles]

		query = "SELECT tile_column, tile_row, zoom_level, tile_data FROM gpkg_tiles " \
				"WHERE julianday() - julianday(last_modified) < " + str(self.MAX_DAYS) + " " \
				"AND tile_column || '_' || tile_row || '_' || zoom_level IN ('" + "','".join(tiles) + "')"

		result = db.execute(query).fetchall()

		db.close()

		return result


	def putTiles(self, tiles):
		"""tiles = list of (x,y,z,data) tuple"""
		db = sqlite3.connect(self.dbPath)
		query = """INSERT OR REPLACE INTO gpkg_tiles
		(tile_column, tile_row, zoom_level, tile_data) VALUES (?,?,?,?)"""
		db.executemany(query, tiles)
		db.commit()
		db.close()

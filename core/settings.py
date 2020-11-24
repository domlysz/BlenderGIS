# -*- coding:utf-8 -*-
import os
import json

from .checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_IMGIO, HAS_PIL

def getAvailableProjEngines():
	engines = ['AUTO', 'BUILTIN']
	#if EPSGIO.ping():
	engines.append('EPSGIO')
	if HAS_GDAL:
		engines.append('GDAL')
	if HAS_PYPROJ:
		engines.append('PYPROJ')
	return engines

def getAvailableImgEngines():
	engines = ['AUTO']
	if HAS_GDAL:
		engines.append('GDAL')
	if HAS_IMGIO:
		engines.append('IMGIO')
	if HAS_PIL:
		engines.append('PIL')
	return engines


class Settings():

	def __init__(self, **kwargs):
		self._proj_engine = kwargs['proj_engine']
		self._img_engine = kwargs['img_engine']
		self.user_agent = kwargs['user_agent']

	@property
	def proj_engine(self):
		return self._proj_engine

	@proj_engine.setter
	def proj_engine(self, engine):
		if engine not in getAvailableProjEngines():
			raise IOError
		else:
			self._proj_engine = engine

	@property
	def img_engine(self):
		return self._img_engine

	@img_engine.setter
	def img_engine(self, engine):
		if engine not in getAvailableImgEngines():
			raise IOError
		else:
			self._img_engine = engine


cfgFile = os.path.join(os.path.dirname(__file__), "settings.json")

with open(cfgFile, 'r') as cfg:
		prefs = json.load(cfg)

settings = Settings(**prefs)

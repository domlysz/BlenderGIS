# -*- coding:utf-8 -*-

import os
import json

from .checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_IMGIO, HAS_PIL
#from .proj import EPSGIO #WARN this one causes circular import because proj.reproj is imported in proj.__init__ and it also import settings.py

cfgFile = os.path.dirname(os.path.abspath(__file__)) + '/settings.json'
#cfgFile = os.path.join(os.path.dirname(__file__), "settings.json")

def getSettings():
	with open(cfgFile, 'r') as cfg:
		prefs = json.load(cfg)
	return prefs

def setSettings(prefs):
	with open(cfgFile, 'w') as cfg:
		json.dump(prefs, cfg, indent='\t')

def getSetting(k):
	prefs = getSettings()
	return prefs.get(k, None)

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

def setImgEngine(engine):
	if engine not in getAvailableImgEngines():
		raise IOError
	else:
		cfg = getSettings()
		cfg['img_engine'] = engine
		setSettings(cfg)

def setProjEngine(engine):
	if engine not in getAvailableProjEngines():
		raise IOError
	else:
		cfg = getSettings()
		cfg['proj_engine'] = engine
		setSettings(cfg)

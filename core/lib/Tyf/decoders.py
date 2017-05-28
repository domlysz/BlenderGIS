# -*- encoding:utf-8 -*-
# Copyright © 2015-2016, THOORENS Bruno - http://bruno.thoorens.free.fr/licences/tyf.html
import datetime

###############
# type decoders

_1 = _3 = _4 = _6 = _8 = _9 = _11 = _12 = lambda value: value[0] if len(value) == 1 else value

_2 = lambda value: value[:-1].decode()

def _5(value):
	result = tuple((float(n)/(1 if d==0 else d)) for n,d in zip(value[0::2], value[1::2]))
	return result[0] if len(result) == 1 else result

_7 = lambda value: value

_10 = _5

#######################
# Tag-specific decoders

#XPTitle XPComment XBAuthor 0x9c9d
_0x9c9b = _0x9c9c = _0x9c9d = _0x9c9e = _0x9c9f = lambda value : "".join(chr(e) for e in value[0::2]).replace("\x00", "")
#UserComment GPSProcessingMethod
def _0x9286(value):
	stamp = value[:8]
	if stamp == b"ASCII\x00\x00\x00": return value[8:].decode("ascii", errors="ignore")
	else: return value[8:]
_0x1b = _0x9286
#GPSLatitudeRef or InteropIndex
def _0x1(value):
	if value in [b"N\x00", b"N"]: return 1
	elif value in [b"S\x00", b"S"]: return -1
	else: return _2(value)
#GPSLatitude or InteropVersion
def _0x2(value):
	if isinstance(value, tuple):
		degrees, minutes, seconds = _5(value)
		return (seconds/60 + minutes)/60 + degrees
	else:
		return _7(value)
#GPSLatitudeRef
_0x3 = lambda value: 1 if value in [b"E\x00", b"E"] else -1
#GPSLongitude
_0x4 = _0x2
#GPSAltitudeRef
_0x5 = lambda value: 1 if value == 0 else -1
# GPSTimeStamp
_0x7 = lambda value: datetime.time(*[int(e) for e in _5(value)])
# GPSDateStamp
_0x1d = lambda value: datetime.datetime.strptime(_2(value), "%Y:%m:%d")
# DateTime DateTimeOriginal DateTimeDigitized
_0x132 = _0x9003 = _0x9004 = lambda value: datetime.datetime.strptime(_2(value), "%Y:%m:%d %H:%M:%S")

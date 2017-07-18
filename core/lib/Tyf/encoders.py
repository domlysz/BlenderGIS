# -*- encoding:utf-8 -*-
# Copyright © 2015-2016, THOORENS Bruno - http://bruno.thoorens.free.fr/licences/tyf.html
from . import reduce
import math, fractions, datetime
###############
# type encoders

cast = lambda value, mini, maxi: int(max(min(value, maxi), mini))

_m_short = 0
_M_short = 2**8
def _1(value):
	if isinstance(value, tuple): return tuple(cast(v, _m_short, _M_short) for v in value)
	else: return (cast(value, _m_short, _M_short), )

def _2(value):
	if not isinstance(value, bytes):
		value = value.encode()
	if len(value) == 0: return b"\x00"
	value += b"\x00" if value[-1] != b"\x00" else ""
	return value

_m_byte = 0
_M_byte = 2**16
def _3(value):
	if isinstance(value, tuple): return tuple(cast(v, _m_byte, _M_byte) for v in value)
	else: return (cast(value, _m_byte, _M_byte), )

_m_long = 0
_M_long = 2**32
def _4(value):
	if isinstance(value, tuple): return tuple(cast(v, _m_long, _M_long) for v in value)
	else: return (cast(value, _m_long, _M_long), )

def _5(value):
	if not isinstance(value, tuple): value = (value, )
	return reduce(tuple.__add__, [(f.numerator, f.denominator) for f in [fractions.Fraction(str(v)).limit_denominator(10000000) for v in value]])

_m_s_short = -_M_short/2
_M_s_short = _M_short/2-1
def _6(value):
	if isinstance(value, tuple): return tuple(cast(v, _m_s_short, _M_s_short) for v in value)
	else: return (cast(value, _m_s_short, _M_s_short), )

def _7(value):
	if not isinstance(value, bytes):
		value = value.encode()
	return value

_m_s_byte = -_M_byte/2
_M_s_byte = _M_byte/2-1
def _8(value):
	if isinstance(value, tuple): return tuple(cast(v, _m_s_byte, _M_s_byte) for v in value)
	else: return (cast(value, _m_s_byte, _M_s_byte), )

_m_s_long = -_M_long/2
_M_s_long = _M_long/2-1
def _9(value):
	if isinstance(value, tuple): return tuple(cast(v, _m_s_long, _M_s_long) for v in value)
	else: return (cast(value, _m_s_long, _M_s_long), )

_10 = _5

def _11(value):
	return (float(value), )

_12 = _11


#######################
# Tag-specific encoders

# XPTitle XPComment XBAuthor
_0x9c9b = _0x9c9c = _0x9c9d_= _0x9c9e = _0x9c9f = lambda value : reduce(tuple.__add__, [(ord(e), 0) for e in value]) + (0, 0)
#UserComment GPSProcessingMethod
_0x9286 = _0x1b = lambda value: b"ASCII\x00\x00\x00" + (value.encode("ascii", errors="replace") if not isinstance(value, bytes) else value)
#GPSLatitudeRef or InteropIndex
def _0x1 (value):
	if isinstance(value, (bytes, str)):
		return _2(value)
	else:
		return b"N\x00" if bool(value >= 0) == True else b"S\x00"
#GPSLatitude or InteropVersion
def _0x2(value):
	if isinstance(value, (int, float)):
		value = abs(value)

		degrees = math.floor(value)
		minutes = (value - degrees) * 60
		seconds = (minutes - math.floor(minutes)) * 60
		minutes = math.floor(minutes)

		if seconds >= (60.-0.0001): seconds = 0.; minutes += 1
		if minutes >= (60.-0.0001): minutes = 0.; degrees += 1

		return _5((degrees, minutes, seconds))
	else:
		return _7(value)

#GPSLongitudeRef
_0x3 = lambda value: b"E\x00" if bool(value >= 0) == True else b"W\x00"
#GPSLongitude
_0x4 = _0x2
#GPSAltitudeRef
_0x5 = lambda value: _3(1 if value < 0 else 0)
#GPSAltitude
_0x6 = lambda value: _5(abs(value))
# GPSTimeStamp
_0x7 = lambda value: _5(tuple(float(e) for e in [value.hour, value.minute, value.second]))
# GPSDateStamp
_0x1d = lambda value: _2(value.strftime("%Y:%m:%d"))
# DateTime DateTimeOriginal DateTimeDigitized
_0x132 = _0x9003 = _0x9004 = lambda value: _2(value.strftime("%Y:%m:%d %H:%M:%S"))
